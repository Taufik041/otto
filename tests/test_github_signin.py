"""GitHub sign-in and account linking through GET /auth/github/start and /auth/github/callback."""
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlmodel import select

from gateway import auth, github_app
from shared import config
from shared.db import get_db
from shared.models import User
from tests.fakes import log_in_as, signup


def start(client, path="/auth/github/start") -> str:
    """Begin a flow; returns the state GitHub would hand back."""
    r = client.get(path, follow_redirects=False)
    assert r.status_code in (302, 307), r.text
    return parse_qs(urlsplit(r.headers["location"]).query)["state"][0]


def callback(client, **params):
    return client.get("/auth/github/callback", params=params, follow_redirects=False)


def nonce_cookies(client) -> list[str]:
    return [c.name for c in client.cookies.jar if c.name.startswith("gh_nonce_")]


def users() -> list[User]:
    with get_db() as s:
        return list(s.exec(select(User).order_by(User.created_at)).all())


def test_start_redirects_to_github_with_a_signed_state(client, fake_github):
    r = client.get("/auth/github/start", follow_redirects=False)

    url = urlsplit(r.headers["location"])
    assert (url.scheme, url.netloc, url.path) == ("https", "github.com", "/login/oauth/authorize")
    q = parse_qs(url.query)
    assert q["client_id"] == ["Iv1.testclient"]
    claims = auth.verify(q["state"][0], "github-state")
    assert claims["flow"] == "signin" and claims["uid"] is None
    header = r.headers["set-cookie"].lower()
    assert header.startswith(github_app.nonce_cookie(claims["nonce"]) + "=")
    assert "httponly" in header and "max-age=600" in header and "path=/auth/github" in header
    assert client.cookies[github_app.nonce_cookie(claims["nonce"])] == claims["nonce"]


def test_sign_in_creates_a_user(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041", name="Taufik Khan", email="taufik@example.com")

    r = callback(client, code="c1", state=start(client))

    assert r.status_code in (302, 307) and r.headers["location"] == "http://localhost:5173"
    me = client.get("/me").json()
    assert (me["name"], me["github_login"], me["avatar_url"]) == (
        "Taufik Khan", "Taufik041", "https://avatars.githubusercontent.com/u/101")
    assert me["email"] is None and me["has_password"] is False  # GitHub's email is never used
    assert [u.github_id for u in users()] == [101]
    assert nonce_cookies(client) == []  # the state is single-use


def test_signing_in_again_finds_the_same_user_and_refreshes_the_profile(client, fake_github):
    fake_github.add_user("c1", gid=101, login="old-login")
    callback(client, code="c1", state=start(client))
    first = client.get("/me").json()["id"]
    client.cookies.clear()

    fake_github.add_user("c2", gid=101, login="Taufik041")
    callback(client, code="c2", state=start(client))

    me = client.get("/me").json()
    assert me["id"] == first and me["github_login"] == "Taufik041"
    assert len(users()) == 1


def test_a_logged_in_user_links_github_to_their_account(client, fake_github):
    me = signup(client, email="taufik@example.com")
    fake_github.add_user("c1", gid=101, login="Taufik041")

    r = callback(client, code="c1", state=start(client))

    assert r.status_code in (302, 307)
    after = client.get("/me").json()
    assert after["id"] == me["id"] and after["github_login"] == "Taufik041" and after["has_password"]
    assert [(u.id, u.github_id) for u in users()] == [(me["id"], 101)]


def test_start_reads_the_login_cookie(client, fake_github):
    me = signup(client)
    claims = auth.verify(start(client), "github-state")
    assert claims["uid"] == me["id"]


def test_a_state_started_signed_out_links_to_whoever_is_signed_in_at_the_callback(client, fake_github):
    """E.g. a prefetch of /start sent without cookies: never make a second account for a signed-in user."""
    state = start(client)  # uid null
    me = signup(client, email="taufik@example.com")
    fake_github.add_user("c1", gid=101, login="Taufik041")

    r = callback(client, code="c1", state=state)

    assert r.status_code in (302, 307)
    assert client.get("/me").json()["id"] == me["id"]
    assert [(u.id, u.github_id) for u in users()] == [(me["id"], 101)]


def test_a_signed_out_state_never_takes_over_github_linked_elsewhere(client, fake_github):
    fake_github.add_user("c0", gid=101, login="Taufik041")
    callback(client, code="c0", state=start(client))  # 101 has an account of its own
    client.cookies.clear()
    state = start(client)
    other = signup(client, email="other@example.com")
    fake_github.add_user("c1", gid=101, login="Taufik041")

    assert callback(client, code="c1", state=state).status_code == 409
    assert client.get("/me").json()["id"] == other["id"] and len(users()) == 2


def test_accounts_are_never_merged_by_email(client, fake_github):
    email_user = signup(client, email="taufik@example.com")
    client.cookies.clear()
    fake_github.add_user("c1", gid=101, login="Taufik041", email="taufik@example.com")

    callback(client, code="c1", state=start(client))

    me = client.get("/me").json()
    assert me["id"] != email_user["id"] and me["email"] is None
    rows = {u.id: u for u in users()}
    assert rows[email_user["id"]].github_id is None
    assert len(rows) == 2


def test_github_already_linked_to_another_account_is_409(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    callback(client, code="c1", state=start(client))  # a GitHub account of its own
    client.cookies.clear()
    other = signup(client, email="other@example.com")
    fake_github.add_user("c2", gid=101, login="Taufik041")

    r = callback(client, code="c2", state=start(client))

    assert r.status_code == 409
    assert {u.id: u.github_id for u in users()}[other["id"]] is None


def test_an_account_linked_to_a_different_github_is_409(client, fake_github):
    fake_github.add_user("c1", gid=101, login="first")
    callback(client, code="c1", state=start(client))
    fake_github.add_user("c2", gid=202, login="second")
    assert callback(client, code="c2", state=start(client)).status_code == 409
    assert client.get("/me").json()["github_login"] == "first"


def expired_state(client):
    nonce = auth.verify(start(client), "github-state")["nonce"]  # sets its nonce cookie
    return auth.sign({"flow": "signin", "uid": None, "nonce": nonce}, "github-state", timedelta(seconds=-1))


@pytest.mark.parametrize("make_state", [
    lambda client: None,                                            # missing
    lambda client: "garbage",
    expired_state,
    lambda client: auth.session_token("someone"),                   # a token for another purpose
    lambda client: start(client) + "x",                             # tampered
])
def test_a_bad_state_is_400(client, fake_github, make_state):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    state = make_state(client)
    r = callback(client, code="c1", **({"state": state} if state else {}))
    assert r.status_code == 400
    assert users() == [] and fake_github.calls == []


def test_a_state_from_another_browser_is_400(client, fake_github):
    """The attacker's own state and code, replayed in the victim's browser, must not link or log in."""
    fake_github.add_user("c1", gid=666, login="attacker")
    attackers_state = start(client)
    client.cookies.clear()
    victim = signup(client, email="victim@example.com")

    r = callback(client, code="c1", state=attackers_state)

    assert r.status_code == 400
    assert {u.id: u.github_id for u in users()}[victim["id"]] is None


def test_a_state_started_by_someone_else_is_400(client, fake_github):
    a = signup(client, email="a@example.com")
    state = start(client)  # started while signed in as A
    log_in_as(client, signup(client, email="b@example.com")["id"])
    fake_github.add_user("c1", gid=101, login="Taufik041")
    assert callback(client, code="c1", state=state).status_code == 400
    assert all(u.github_id is None for u in users()) and a


def test_each_start_keeps_its_own_nonce_so_duplicate_starts_dont_break_sign_in(client, fake_github):
    """Prefetches, double clicks and reloads can hit /start more than once before GitHub answers."""
    first, second = start(client), start(client)
    assert len(nonce_cookies(client)) == 2
    fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_user("c2", gid=101, login="Taufik041")

    assert callback(client, code="c1", state=first).status_code in (302, 307)
    me = client.get("/me").json()["id"]
    client.cookies.delete(auth.COOKIE)  # signed out again, as when second was started
    assert callback(client, code="c2", state=second).status_code in (302, 307)

    assert client.get("/me").json()["id"] == me and len(users()) == 1
    assert nonce_cookies(client) == []


def test_a_used_state_cant_be_used_again(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_user("c2", gid=101, login="Taufik041")
    state = start(client)
    assert callback(client, code="c1", state=state).status_code in (302, 307)
    client.cookies.delete(auth.COOKIE)
    assert callback(client, code="c2", state=state).status_code == 400


def test_a_bad_code_is_400(client, fake_github):
    assert callback(client, code="nope", state=start(client)).status_code == 400
    assert users() == []


def test_github_sign_in_needs_the_oauth_app_configured(client, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_CLIENT_ID", None)
    assert client.get("/auth/github/start", follow_redirects=False).status_code == 503


def test_cancelling_on_github_goes_back_to_the_frontend(client, fake_github):
    r = callback(client, error="access_denied", state=start(client))
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("http://localhost:5173/")
    assert "access_denied" in r.headers["location"]
    assert fake_github.calls == []
