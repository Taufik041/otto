"""GitHub sign-in and account linking: POST /auth/github/url (or GET /auth/github/start), then
/auth/github/callback, which sets the refresh cookie and sends the browser to /auth/callback.
A callback that fails sends the browser to the frontend with ?error=<code>, never JSON."""
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlmodel import select

from gateway import auth, github_app
from shared import config
from shared.db import get_db
from shared.models import User
from tests.fakes import sign_out, signup


def start(client, how="get") -> str:
    """Begin a flow: "get" (GET /auth/github/start), "signin" or "link" (POST /auth/github/url),
    or "install" (POST /github/install-url). Returns the state GitHub would hand back."""
    if how == "get":
        r = client.get("/auth/github/start", follow_redirects=False)
        assert r.status_code in (302, 307), r.text
        url = r.headers["location"]
    else:
        r = (client.post("/github/install-url") if how == "install"
             else client.post("/auth/github/url", json={"mode": how}))
        assert r.status_code == 200, r.text
        url = r.json()["url"]
    return parse_qs(urlsplit(url).query)["state"][0]


def callback(client, **params):
    """Come back from GitHub. A sign-in lands on the frontend's /auth/callback, which then (like
    the frontend) trades the refresh cookie for an access token."""
    r = client.get("/auth/github/callback", params=params, follow_redirects=False)
    if r.status_code in (302, 307) and r.headers["location"] == f"{config.FRONTEND_URL}/auth/callback":
        got = client.post("/auth/refresh")
        assert got.status_code == 200, got.text
        client.headers["Authorization"] = f"Bearer {got.json()['access_token']}"
    return r


def failed(r, code, where="/login", **extra):
    """The callback sent the browser to the frontend's `where` with ?error=code (and extra)."""
    assert r.status_code == 302, r.text
    assert "json" not in r.headers.get("content-type", "")
    url = urlsplit(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == config.FRONTEND_URL + where
    assert parse_qs(url.query) == {"error": [code], **{k: [v] for k, v in extra.items()}}
    assert not any(v.startswith("otto_refresh=") for k, v in r.headers.multi_items() if k == "set-cookie")


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

    assert r.status_code in (302, 307) and r.headers["location"] == "http://localhost:5173/auth/callback"
    header = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("otto_refresh=")][0]
    assert "httponly" in header.lower() and "path=/auth" in header.lower()
    me = client.get("/me").json()
    assert (me["name"], me["github_login"], me["avatar_url"]) == (
        "Taufik Khan", "Taufik041", "https://avatars.githubusercontent.com/u/101")
    assert me["email"] == "taufik@example.com" and me["has_password"] is False  # GitHub's verified email (tests/test_github_email.py)
    assert [u.github_id for u in users()] == [101]
    assert nonce_cookies(client) == []  # the state is single-use


def test_signing_in_again_finds_the_same_user_and_refreshes_the_profile(client, fake_github):
    fake_github.add_user("c1", gid=101, login="old-login")
    callback(client, code="c1", state=start(client))
    first = client.get("/me").json()["id"]
    sign_out(client)

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


def test_the_url_endpoint_sets_the_nonce_cookie_and_link_mode_puts_the_uid_in_the_state(client, fake_github):
    me = signup(client)
    r = client.post("/auth/github/url", json={"mode": "link"})
    claims = auth.verify(parse_qs(urlsplit(r.json()["url"]).query)["state"][0], "github-state")
    assert (claims["flow"], claims["uid"]) == ("signin", me["id"])
    header = r.headers["set-cookie"].lower()
    assert header.startswith(github_app.nonce_cookie(claims["nonce"]) + "=") and "path=/auth/github" in header


def test_signin_mode_needs_no_login_and_has_no_uid(client, fake_github):
    r = client.post("/auth/github/url", json={"mode": "signin"})
    url = urlsplit(r.json()["url"])
    assert (url.netloc, url.path) == ("github.com", "/login/oauth/authorize")
    assert auth.verify(parse_qs(url.query)["state"][0], "github-state")["uid"] is None


def test_link_mode_needs_a_login(client, fake_github):
    assert client.post("/auth/github/url", json={"mode": "link"}).status_code == 401
    assert client.post("/auth/github/url", json={"mode": "other"}).status_code == 422


def test_link_mode_links_by_the_states_uid_without_a_refresh_cookie(client, fake_github):
    me = signup(client)
    state = start(client, "link")
    client.cookies.delete("otto_refresh")
    fake_github.add_user("c1", gid=101, login="Taufik041")

    r = callback(client, code="c1", state=state)

    assert r.headers["location"] == "http://localhost:5173/auth/callback"
    assert client.get("/me").json()["id"] == me["id"]
    assert [(u.id, u.github_id) for u in users()] == [(me["id"], 101)]


def test_a_link_for_a_deleted_account_is_state_invalid(client, fake_github):
    signup(client)
    state = start(client, "link")
    client.delete("/me")
    fake_github.add_user("c1", gid=101, login="Taufik041")
    failed(callback(client, code="c1", state=state), "state_invalid", "/settings/github")
    assert users() == []


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
    sign_out(client)
    state = start(client)
    other = signup(client, email="other@example.com")
    fake_github.add_user("c1", gid=101, login="Taufik041")

    r = callback(client, code="c1", state=state)

    failed(r, "github_already_linked", "/settings/github", login="Taufik041")
    assert client.get("/me").json()["id"] == other["id"] and len(users()) == 2


def test_a_github_email_that_an_account_uses_is_neither_merged_nor_a_second_account(client, fake_github):
    email_user = signup(client, email="taufik@example.com")
    sign_out(client)
    fake_github.add_user("c1", gid=101, login="Taufik041",
                         emails=[("work@example.com", True), ("Taufik@Example.com", True)])

    r = callback(client, code="c1", state=start(client))

    failed(r, "github_email_in_use")
    assert [(u.id, u.github_id) for u in users()] == [(email_user["id"], None)]
    assert "/user/emails" in fake_github.paths("GET")


def test_an_unverified_github_email_doesnt_count(client, fake_github):
    email_user = signup(client, email="taufik@example.com")
    sign_out(client)
    fake_github.add_user("c1", gid=101, login="Taufik041", emails=[("taufik@example.com", False)])

    callback(client, code="c1", state=start(client))

    me = client.get("/me").json()
    assert me["id"] != email_user["id"] and me["email"] is None  # a new account, GitHub's email unused
    assert len(users()) == 2


def test_without_the_email_list_the_public_email_counts(client, fake_github):
    """No email permission on the App: /user's email (GitHub only shows a verified one) still counts."""
    signup(client, email="taufik@example.com")
    sign_out(client)
    fake_github.add_user("c1", gid=101, login="Taufik041", email="taufik@example.com")

    failed(callback(client, code="c1", state=start(client)), "github_email_in_use")
    assert len(users()) == 1


def test_an_email_in_use_never_stops_the_github_account_already_linked(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    callback(client, code="c1", state=start(client))
    me = client.get("/me").json()["id"]
    sign_out(client)
    signup(client, email="taufik@example.com")
    sign_out(client)
    fake_github.add_user("c2", gid=101, login="Taufik041", emails=[("taufik@example.com", True)])

    callback(client, code="c2", state=start(client))

    assert client.get("/me").json()["id"] == me


def test_github_already_linked_to_another_account_goes_back_to_settings(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    callback(client, code="c1", state=start(client))  # a GitHub account of its own
    sign_out(client)
    other = signup(client, email="other@example.com")
    fake_github.add_user("c2", gid=101, login="Taufik041")

    r = callback(client, code="c2", state=start(client, "link"))

    failed(r, "github_already_linked", "/settings/github", login="Taufik041")
    assert {u.id: u.github_id for u in users()}[other["id"]] is None


def test_an_account_linked_to_a_different_github_is_a_mismatch_naming_the_linked_one(client, fake_github, capsys):
    fake_github.add_user("c1", gid=101, login="first")
    callback(client, code="c1", state=start(client))
    fake_github.add_user("c2", gid=202, login="second")
    failed(callback(client, code="c2", state=start(client, "link")), "github_account_mismatch", "/settings/github",
           login="first")
    assert "linked to GitHub first, not second" in capsys.readouterr().out
    assert client.get("/me").json()["github_login"] == "first"


def expired_state(client):
    nonce = auth.verify(start(client), "github-state")["nonce"]  # sets its nonce cookie
    return auth.sign({"flow": "signin", "uid": None, "nonce": nonce}, "github-state", timedelta(seconds=-1))


@pytest.mark.parametrize("make_state", [
    lambda client: None,                                            # missing
    lambda client: "garbage",
    expired_state,
    lambda client: auth.sign({"sub": "someone"}, "session", timedelta(days=1)),  # for another purpose
    lambda client: start(client) + "x",                             # tampered
])
def test_a_bad_state_is_state_invalid(client, fake_github, make_state):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    state = make_state(client)
    r = callback(client, code="c1", **({"state": state} if state else {}))
    failed(r, "state_invalid")
    assert users() == [] and fake_github.calls == []


def test_a_state_from_another_browser_is_state_invalid(client, fake_github):
    """The attacker's own state and code, replayed in the victim's browser, must not link or log in."""
    fake_github.add_user("c1", gid=666, login="attacker")
    attackers_state = start(client)
    client.cookies.clear()  # another browser
    victim = signup(client, email="victim@example.com")

    r = callback(client, code="c1", state=attackers_state)

    failed(r, "state_invalid", "/settings/github")  # the victim is signed in here
    assert {u.id: u.github_id for u in users()}[victim["id"]] is None


def test_a_state_started_by_someone_else_is_state_invalid(client, fake_github):
    a = signup(client, email="a@example.com")
    state = start(client, "link")  # started while signed in as A
    sign_out(client)
    signup(client, email="b@example.com")
    fake_github.add_user("c1", gid=101, login="Taufik041")
    failed(callback(client, code="c1", state=state), "state_invalid", "/settings/github")
    assert all(u.github_id is None for u in users()) and a


def test_each_start_keeps_its_own_nonce_so_duplicate_starts_dont_break_sign_in(client, fake_github):
    """Prefetches, double clicks and reloads can hit /start more than once before GitHub answers."""
    first, second = start(client), start(client)
    assert len(nonce_cookies(client)) == 2
    fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_user("c2", gid=101, login="Taufik041")

    assert callback(client, code="c1", state=first).status_code in (302, 307)
    me = client.get("/me").json()["id"]
    sign_out(client)  # signed out again, as when second was started
    assert callback(client, code="c2", state=second).status_code in (302, 307)

    assert client.get("/me").json()["id"] == me and len(users()) == 1
    assert nonce_cookies(client) == []


def test_a_used_state_cant_be_used_again(client, fake_github):
    fake_github.add_user("c1", gid=101, login="Taufik041")
    fake_github.add_user("c2", gid=101, login="Taufik041")
    state = start(client)
    assert callback(client, code="c1", state=state).status_code in (302, 307)
    sign_out(client)
    failed(callback(client, code="c2", state=state), "state_invalid")


def test_a_bad_code_is_github_unavailable_and_githubs_answer_is_logged(client, fake_github, capsys):
    r = callback(client, code="nope", state=start(client))
    failed(r, "github_unavailable")
    assert users() == []
    out = capsys.readouterr().out
    assert "bad_verification_code" in out and "The code passed is incorrect or expired." in out


@pytest.mark.parametrize("path", ["get", "install"])
def test_wrong_client_credentials_say_so_and_never_log_the_secret(client, fake_github, monkeypatch, capsys, path):
    if path == "install":
        signup(client)
    monkeypatch.setattr(config, "GITHUB_CLIENT_SECRET", "wrong-secret-0123456789")
    fake_github.add_user("c1", gid=101, login="Taufik041")
    extra = {"installation_id": 555, "setup_action": "install"} if path == "install" else {}

    r = callback(client, code="c1", state=start(client, path), **extra)

    failed(r, "github_unavailable", "/login" if path == "get" else "/settings/github")
    out = capsys.readouterr().out
    assert "GitHub rejected Otto's client credentials — check GITHUB_CLIENT_ID/SECRET" in out
    assert "incorrect_client_credentials" in out and "client_secret passed are incorrect" in out
    assert "wrong-secret-0123456789" not in out + r.text


def test_github_sign_in_needs_the_oauth_app_configured(client, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_CLIENT_ID", None)
    assert client.get("/auth/github/start", follow_redirects=False).status_code == 503
    assert client.post("/auth/github/url", json={"mode": "signin"}).status_code == 503


def test_cancelling_on_github_goes_back_to_the_sign_in_dialog(client, fake_github):
    r = callback(client, error="access_denied", state=start(client))
    failed(r, "access_denied")
    assert fake_github.calls == [] and nonce_cookies(client) == []


def test_cancelling_a_link_goes_back_to_settings(client, fake_github):
    signup(client)
    failed(callback(client, error="access_denied", state=start(client, "link")), "access_denied", "/settings/github")


def test_another_error_from_github_is_unknown_and_logged(client, fake_github, capsys):
    failed(callback(client, error="application_suspended", state=start(client)), "unknown")
    assert "application_suspended" in capsys.readouterr().out


def test_github_unreachable_is_github_unavailable(client, fake_github, monkeypatch, capsys):
    import requests

    def down(method, url, **kw):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(github_app, "request", down)
    failed(callback(client, code="c1", state=start(client)), "github_unavailable")
    assert "no route to host" in capsys.readouterr().out


def test_a_bug_is_unknown_with_the_traceback_logged(client, fake_github, monkeypatch, capsys):
    def broken(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(github_app, "_sign_in", broken)
    fake_github.add_user("c1", gid=101, login="Taufik041")
    failed(callback(client, code="c1", state=start(client)), "unknown")
    out = capsys.readouterr().out
    assert "RuntimeError: boom" in out and "Traceback" in out
