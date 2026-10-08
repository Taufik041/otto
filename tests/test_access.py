"""Who may make a new account (OTTO_SIGNUP_MODE, OTTO_ACCEPTING), access requests, and the
`python -m scripts.access_requests` CLI."""
import pytest
from sqlmodel import select

from scripts import access_requests as cli
from shared import access, config
from shared.db import get_db
from shared.models import AccessRequest, User
from tests.fakes import PASSWORD, sign_out, signup
from tests.test_github_signin import callback, start, users


def sign_up(client, email="new@example.com"):
    return client.post("/auth/signup", json={"name": "New", "email": email, "password": PASSWORD})


def requests_() -> list[AccessRequest]:
    with get_db() as s:
        return list(s.exec(select(AccessRequest).order_by(AccessRequest.id)).all())


@pytest.fixture
def allowlist(monkeypatch):
    monkeypatch.setattr(config, "SIGNUP_MODE", "allowlist")
    monkeypatch.setattr(config, "ALLOWED_EMAILS", {"friend@example.com"})
    monkeypatch.setattr(config, "ALLOWED_GITHUB", {"friend-gh"})


# --- email signups --------------------------------------------------------------------

def test_open_mode_lets_anyone_sign_up(client):
    assert sign_up(client).status_code == 201


def test_allowlist_mode_refuses_an_unlisted_email(client, allowlist):
    r = sign_up(client, "stranger@example.com")

    assert r.status_code == 403
    assert r.json()["error"] == "invite_only" and r.json()["detail"]
    assert "set-cookie" not in r.headers
    with get_db() as s:
        assert s.exec(select(User)).all() == []


def test_allowlist_mode_lets_a_listed_email_sign_up(client, allowlist):
    assert sign_up(client, "Friend@Example.com").status_code == 201


def test_an_approved_access_request_lets_its_email_sign_up(client, allowlist):
    row = access.request_access(email="later@example.com", note="")
    assert sign_up(client, "later@example.com").status_code == 403
    access.approve(row.id)
    assert sign_up(client, "later@example.com").status_code == 201


def test_closed_mode_refuses_even_a_listed_email(client, allowlist, monkeypatch):
    monkeypatch.setattr(config, "SIGNUP_MODE", "closed")
    r = sign_up(client, "friend@example.com")
    assert r.status_code == 403 and r.json()["error"] == "invite_only"


def test_paused_refuses_new_accounts_in_any_mode(client, monkeypatch):
    monkeypatch.setattr(config, "ACCEPTING", False)
    r = sign_up(client)
    assert r.status_code == 503 and r.json()["error"] == "paused"


@pytest.mark.parametrize("mode", ["allowlist", "closed"])
def test_existing_users_keep_access(client, monkeypatch, mode):
    signup(client, email="old@example.com")
    sign_out(client)
    monkeypatch.setattr(config, "SIGNUP_MODE", mode)
    monkeypatch.setattr(config, "ACCEPTING", False)

    r = client.post("/auth/login", json={"email": "old@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert client.post("/auth/refresh").status_code == 200


# --- GitHub signups ---------------------------------------------------------------------

def test_allowlist_refuses_a_new_unlisted_github_account(client, fake_github, allowlist):
    fake_github.add_user("c1", gid=101, login="stranger")

    r = callback(client, code="c1", state=start(client))

    assert r.status_code in (302, 307)
    assert r.headers["location"] == "http://localhost:5173/auth/callback?error=invite_only"
    assert users() == [] and "otto_refresh" not in client.cookies


def test_allowlist_lets_a_listed_github_login_sign_up(client, fake_github, allowlist):
    fake_github.add_user("c1", gid=101, login="Friend-GH")
    callback(client, code="c1", state=start(client))
    assert [u.github_login for u in users()] == ["Friend-GH"]


def test_an_approved_github_request_lets_it_sign_up(client, fake_github, allowlist):
    access.approve(access.request_access(github_login="@Later-GH", note="hi").id)
    fake_github.add_user("c1", gid=101, login="later-gh")
    callback(client, code="c1", state=start(client))
    assert [u.github_login for u in users()] == ["later-gh"]


def test_paused_refuses_a_new_github_account(client, fake_github, monkeypatch):
    monkeypatch.setattr(config, "ACCEPTING", False)
    fake_github.add_user("c1", gid=101, login="someone")
    r = callback(client, code="c1", state=start(client))
    assert r.headers["location"] == "http://localhost:5173/auth/callback?error=paused"
    assert users() == []


def test_closed_mode_still_signs_in_a_linked_github_account_and_links_new_ones(client, fake_github, monkeypatch):
    fake_github.add_user("c1", gid=101, login="old-gh")
    callback(client, code="c1", state=start(client))
    sign_out(client)
    monkeypatch.setattr(config, "SIGNUP_MODE", "closed")

    callback(client, code="c1", state=start(client))  # signing in again
    assert client.get("/me").json()["github_login"] == "old-gh"

    sign_out(client)
    monkeypatch.setattr(config, "SIGNUP_MODE", "open")
    me = signup(client, email="mail@example.com")
    monkeypatch.setattr(config, "SIGNUP_MODE", "closed")
    fake_github.add_user("c2", gid=202, login="second-gh")
    callback(client, code="c2", state=start(client, "link"))  # linking GitHub to a signed-in account
    got = client.get("/me").json()
    assert (got["id"], got["github_login"]) == (me["id"], "second-gh")


# --- POST /access-requests -------------------------------------------------------------

def test_an_access_request_is_stored_pending(client):
    r = client.post("/access-requests", json={"github_login": "@Someone", "note": "I'd like to try it"})

    assert r.status_code == 201 and r.json() == {"ok": True}
    [row] = requests_()
    assert (row.github_login, row.email, row.note, row.status) == ("someone", None, "I'd like to try it", "pending")


def test_access_requests_are_deduped(client):
    client.post("/access-requests", json={"email": "A@example.com"})
    r = client.post("/access-requests", json={"email": "a@example.com ", "note": "again"})

    assert r.status_code == 201 and r.json() == {"ok": True}  # the same answer: nothing to learn
    [row] = requests_()
    assert (row.email, row.note) == ("a@example.com", "again")


def test_an_approved_request_stays_approved_when_asked_again(client):
    access.approve(access.request_access(email="a@example.com", note="").id)
    client.post("/access-requests", json={"email": "a@example.com"})
    assert [r.status for r in requests_()] == ["approved"]


@pytest.mark.parametrize("body", [
    {}, {"note": "hi"}, {"email": "not-an-email"}, {"github_login": "bad login!"},
    {"github_login": "-dash"}, {"github_login": "a" * 40}, {"email": "a@example.com", "note": "x" * 501},
])
def test_a_bad_access_request_is_422(client, body):
    assert client.post("/access-requests", json=body).status_code == 422
    assert requests_() == []


def test_the_login_field_may_hold_an_email(client):
    """The form has one field, "GitHub username or email": an email in it counts as the email."""
    client.post("/access-requests", json={"github_login": "Me@Example.com"})
    [row] = requests_()
    assert (row.github_login, row.email) == (None, "me@example.com")


# --- the CLI --------------------------------------------------------------------------------

def test_the_cli_lists_pending_requests(capsys):
    access.request_access(github_login="someone", note="please")
    access.approve(access.request_access(email="done@example.com", note="").id)

    cli.main([])
    out = capsys.readouterr().out
    assert "someone" in out and "please" in out and "done@example.com" not in out

    cli.main(["--all"])
    assert "done@example.com" in capsys.readouterr().out


@pytest.mark.parametrize("who", ["1", "someone", "@SomeOne"])
def test_the_cli_approves_by_id_or_login(who, capsys):
    access.request_access(github_login="someone", note="")
    assert cli.main(["approve", who]) == 0
    assert [r.status for r in requests_()] == ["approved"] and requests_()[0].approved_at is not None
    assert "approved" in capsys.readouterr().out


def test_the_cli_approves_by_email_and_refuses_an_unknown_one(capsys):
    access.request_access(email="a@example.com", note="")
    assert cli.main(["approve", "A@example.com"]) == 0
    assert cli.main(["approve", "nobody@example.com"]) == 1
    assert "no access request" in capsys.readouterr().err
