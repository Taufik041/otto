"""A GitHub sign-up's email (GitHub's verified primary one), setting a password on a GitHub-made
account, and what email-first sign-in says about one."""
import pytest

from shared import config
from shared.db import get_db
from shared.models import User
from tests.fakes import PASSWORD, sign_out, signup
from tests.test_auth import reset_link, token_from
from tests.test_github_signin import callback, failed, start, users


def github_sign_up(client, fake_github, code="c1", gid=101, login="Taufik041", **extra) -> dict:
    fake_github.add_user(code, gid=gid, login=login, **extra)
    callback(client, code=code, state=start(client))
    return client.get("/me").json()


def verified(user_id) -> bool:
    with get_db() as s:
        return s.get(User, user_id).email_verified


# --- 1. the new account's email ------------------------------------------------------------

def test_a_github_sign_up_gets_githubs_verified_primary_email(client, fake_github):
    me = github_sign_up(client, fake_github, email="public@example.com",
                        emails=[("Primary@Example.com", True), ("other@example.com", True)])
    assert me["email"] == "primary@example.com" and verified(me["id"])
    assert me["has_password"] is False


def test_an_unverified_primary_is_never_used(client, fake_github):
    me = github_sign_up(client, fake_github, emails=[("primary@example.com", False), ("other@example.com", True)])
    assert me["email"] is None and not verified(me["id"])


def test_without_the_email_list_the_profile_email_is_used(client, fake_github):
    """No email permission on the App: the profile email, which GitHub only allows to be verified."""
    me = github_sign_up(client, fake_github, email="Public@Example.com")
    assert me["email"] == "public@example.com" and verified(me["id"])


def test_without_any_email_the_account_has_none_as_before(client, fake_github):
    me = github_sign_up(client, fake_github)
    assert me["email"] is None and not verified(me["id"])


def test_an_email_sign_up_isnt_marked_verified(client):
    assert not verified(signup(client, confirm=False)["id"])


def test_linking_github_never_changes_the_accounts_email(client, fake_github):
    me = signup(client, email="mine@example.com")
    fake_github.add_user("c1", gid=101, login="Taufik041", emails=[("work@example.com", True)])
    callback(client, code="c1", state=start(client, "link"))
    after = client.get("/me").json()
    assert (after["id"], after["email"], after["github_login"]) == (me["id"], "mine@example.com", "Taufik041")


def test_signing_in_again_doesnt_change_the_email(client, fake_github):
    github_sign_up(client, fake_github, emails=[("first@example.com", True)])
    sign_out(client)
    me = github_sign_up(client, fake_github, code="c2", emails=[("changed@example.com", True)])
    assert me["email"] == "first@example.com"


# --- 4. the allowlist is by GitHub login, as before -----------------------------------------

@pytest.fixture
def allowlist(monkeypatch):
    monkeypatch.setattr(config, "SIGNUP_MODE", "allowlist")
    monkeypatch.setattr(config, "ALLOWED_EMAILS", {"friend@example.com"})
    monkeypatch.setattr(config, "ALLOWED_GITHUB", {"friend-gh"})


def test_an_allowed_github_login_signs_up_whatever_its_email(client, fake_github, allowlist):
    me = github_sign_up(client, fake_github, login="Friend-GH", emails=[("unlisted@example.com", True)])
    assert me["github_login"] == "Friend-GH" and me["email"] == "unlisted@example.com"


def test_an_allowed_email_doesnt_let_an_unlisted_github_login_sign_up(client, fake_github, allowlist):
    fake_github.add_user("c1", gid=101, login="stranger", emails=[("friend@example.com", True)])
    failed(callback(client, code="c1", state=start(client)), "invite_only")
    assert users() == []


# --- 2. setting a password on an account made with GitHub -----------------------------------

def test_set_a_password_emails_a_link_and_then_email_login_works(client, fake_github, capsys):
    me = github_sign_up(client, fake_github, emails=[("taufik@example.com", True)])
    capsys.readouterr()

    r = client.post("/me/password/setup")

    assert r.status_code == 200 and r.json() == {"ok": True, "email": "taufik@example.com"}
    out = capsys.readouterr().out
    assert "Set your Otto password" in out and "taufik@example.com" in out
    token = token_from(next(l for l in out.splitlines() if "reset-password?token=" in l))
    r = client.post("/auth/reset", json={"token": token, "password": "a brand new password"})
    assert r.status_code == 200 and r.json()["user"]["has_password"] is True

    sign_out(client)
    r = client.post("/auth/login", json={"email": "taufik@example.com", "password": "a brand new password"})
    assert r.status_code == 200 and r.json()["user"]["id"] == me["id"]
    sign_out(client)
    assert github_sign_up(client, fake_github, code="c2")["id"] == me["id"]  # GitHub still works too


def test_the_set_password_link_lasts_an_hour_and_works_once(client, fake_github, capsys):
    from datetime import timedelta

    from shared.models import PasswordReset, as_utc, utcnow
    from sqlmodel import select

    github_sign_up(client, fake_github, emails=[("taufik@example.com", True)])
    capsys.readouterr()
    client.post("/me/password/setup")
    token = token_from(reset_link(capsys))
    with get_db() as s:
        [row] = s.exec(select(PasswordReset)).all()
    assert timedelta(minutes=59) < as_utc(row.expires_at) - utcnow() <= timedelta(hours=1)
    assert client.post("/auth/reset", json={"token": token, "password": "a brand new password"}).status_code == 200
    assert client.post("/auth/reset", json={"token": token, "password": "another new password"}).status_code == 400


def test_an_account_with_a_password_changes_it_instead(client, capsys):
    signup(client)
    capsys.readouterr()
    assert client.post("/me/password/setup").status_code == 400
    assert "reset-password" not in capsys.readouterr().out


def test_an_account_without_an_email_cant_set_a_password(client, fake_github, capsys):
    github_sign_up(client, fake_github)
    capsys.readouterr()
    r = client.post("/me/password/setup")
    assert r.status_code == 400 and "email" in r.json()["detail"]
    assert "reset-password" not in capsys.readouterr().out


def test_set_a_password_needs_a_login(client):
    assert client.post("/me/password/setup").status_code == 401


def test_set_a_password_without_email_set_up_is_503(client, fake_github, monkeypatch):
    from shared import email

    github_sign_up(client, fake_github, emails=[("taufik@example.com", True)])
    monkeypatch.setattr(email, "available", lambda: False)
    r = client.post("/me/password/setup")
    assert r.status_code == 503 and r.json()["error"] == "email_unavailable"


def test_forgot_password_on_a_github_made_account_sets_one(client, fake_github, capsys):
    me = github_sign_up(client, fake_github, emails=[("taufik@example.com", True)])
    sign_out(client)
    capsys.readouterr()

    assert client.post("/auth/forgot", json={"email": "Taufik@example.com"}).status_code == 200

    out = capsys.readouterr().out
    assert "Set your Otto password" in out  # it has none to reset
    token = token_from(next(l for l in out.splitlines() if "reset-password?token=" in l))
    assert client.post("/auth/reset", json={"token": token, "password": "a brand new password"}).status_code == 200
    sign_out(client)
    r = client.post("/auth/login", json={"email": "taufik@example.com", "password": "a brand new password"})
    assert r.status_code == 200 and r.json()["user"]["id"] == me["id"]


def test_set_a_password_is_rate_limited(client, fake_github, capsys):
    github_sign_up(client, fake_github, emails=[("taufik@example.com", True)])
    codes = [client.post("/me/password/setup").status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


# --- 3. email-first sign-in -----------------------------------------------------------------

def test_email_status_says_when_an_account_has_no_password(client, fake_github):
    github_sign_up(client, fake_github, emails=[("gh@example.com", True)])
    sign_out(client)
    signup(client, email="pw@example.com")
    sign_out(client)

    status = lambda e: client.post("/auth/email-status", json={"email": e}).json()
    assert status("GH@example.com") == {"exists": True, "password": False}
    assert status("pw@example.com") == {"exists": True, "password": True}
    assert status("nobody@example.com") == {"exists": False, "password": False}


def test_logging_in_to_a_github_made_account_without_a_password_is_401(client, fake_github):
    github_sign_up(client, fake_github, emails=[("gh@example.com", True)])
    sign_out(client)
    assert client.post("/auth/login", json={"email": "gh@example.com", "password": PASSWORD}).status_code == 401
