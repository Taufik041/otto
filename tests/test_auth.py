from datetime import timedelta

import pytest
from sqlmodel import select, update

from gateway import auth
from shared import config
from shared.db import get_db
from shared.models import PasswordReset, User, as_utc, utcnow
from tests.fakes import PASSWORD, log_in_as, sign_out, signup


def user_row(user_id) -> User:
    with get_db() as s:
        return s.get(User, user_id)


# --- signup ------------------------------------------------------------------------

def test_signup_returns_the_user_and_signs_in(client):
    r = client.post("/auth/signup", json={"name": " Taufik Khan ", "email": "Taufik@Example.com",
                                          "password": PASSWORD})

    assert r.status_code == 201
    me = r.json()["user"]
    assert (me["name"], me["email"], me["has_password"]) == ("Taufik Khan", "taufik@example.com", True)
    assert me["github_login"] is None and me["daily_token_limit"] == 50000
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert client.get("/me").json() == me


def test_the_password_is_stored_as_argon2_and_never_returned(client):
    me = signup(client)
    assert PASSWORD not in client.get("/me").text and "password_hash" not in me
    assert user_row(me["id"]).password_hash.startswith("$argon2id$")


def test_signup_with_an_existing_email_is_409(client):
    signup(client, email="taufik@example.com")
    sign_out(client)
    r = client.post("/auth/signup", json={"name": "x", "email": "TAUFIK@example.com", "password": PASSWORD})
    assert r.status_code == 409
    assert "set-cookie" not in r.headers


@pytest.mark.parametrize("body", [
    {"name": "a", "email": "a@example.com", "password": "1234567"},       # too short
    {"name": "a", "email": "not-an-email", "password": PASSWORD},
    {"name": "  ", "email": "a@example.com", "password": PASSWORD},
    {"email": "a@example.com", "password": PASSWORD},
])
def test_signup_validation_is_422(client, body):
    assert client.post("/auth/signup", json=body).status_code == 422


def test_a_new_user_gets_the_configured_daily_limit(client, monkeypatch):
    monkeypatch.setattr(config, "DAILY_TOKEN_LIMIT", 1234)
    assert signup(client)["daily_token_limit"] == 1234


# --- login, logout, /me -------------------------------------------------------------

def test_login(client):
    me = signup(client)
    sign_out(client)
    assert client.get("/me").status_code == 401

    r = client.post("/auth/login", json={"email": " TAUFIK@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["id"] == me["id"]
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    assert client.get("/me").json()["id"] == me["id"]


@pytest.mark.parametrize("email,password", [("taufik@example.com", "wrong password"),
                                            ("nobody@example.com", PASSWORD)])
def test_wrong_password_or_unknown_email_is_401(client, email, password):
    signup(client)
    sign_out(client)
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers


def test_a_github_only_account_cannot_log_in_with_a_password(client):
    with get_db() as s:
        s.add(User(id="gh1", email="gh@example.com", name="gh", github_id=7))
    assert client.post("/auth/login", json={"email": "gh@example.com", "password": PASSWORD}).status_code == 401


def test_the_gateway_refuses_to_start_without_a_strong_auth_secret(env, monkeypatch):
    from fastapi.testclient import TestClient
    from gateway import app as gateway_app

    for secret in (None, "short"):
        monkeypatch.setattr(config, "AUTH_SECRET", secret)
        with pytest.raises(RuntimeError, match="AUTH_SECRET"):
            with TestClient(gateway_app.app):
                pass


def test_cors_allows_credentials_for_the_frontend(client):
    r = client.options("/me", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-credentials") == "true"


# --- forgot / reset password ---------------------------------------------------------

def reset_link(capsys) -> str:
    out = capsys.readouterr().out
    [line] = [l for l in out.splitlines() if "reset-password?token=" in l]
    return line


def token_from(line) -> str:
    return line.split("reset-password?token=")[1].split()[0]


def test_forgot_logs_a_reset_link_and_reset_sets_the_password(client, capsys):
    me = signup(client)
    sign_out(client)
    capsys.readouterr()

    r = client.post("/auth/forgot", json={"email": "Taufik@example.com"})

    assert r.status_code == 200
    line = reset_link(capsys)
    assert "http://localhost:5173/reset-password?token=" in line
    token = token_from(line)
    with get_db() as s:
        [row] = s.exec(select(PasswordReset)).all()
    assert token not in row.token_hash and row.user_id == me["id"]  # only a hash is stored
    ttl = as_utc(row.expires_at) - utcnow()
    assert timedelta(minutes=59) < ttl <= timedelta(hours=1)

    r = client.post("/auth/reset", json={"token": token, "password": "a brand new password"})
    assert r.status_code == 200 and r.json()["user"]["id"] == me["id"]  # and signed in
    assert client.post("/auth/login", json={"email": me["email"], "password": PASSWORD}).status_code == 401
    assert client.post("/auth/login", json={"email": me["email"],
                                            "password": "a brand new password"}).status_code == 200


def test_forgot_for_an_unknown_email_is_200_and_sends_nothing(client, capsys):
    capsys.readouterr()
    assert client.post("/auth/forgot", json={"email": "nobody@example.com"}).status_code == 200
    assert "reset-password" not in capsys.readouterr().out


def test_a_reset_token_works_once(client, capsys):
    signup(client)
    client.post("/auth/forgot", json={"email": "taufik@example.com"})
    token = token_from(reset_link(capsys))
    assert client.post("/auth/reset", json={"token": token, "password": "new password 1"}).status_code == 200
    r = client.post("/auth/reset", json={"token": token, "password": "new password 2"})
    assert r.status_code == 400


def test_resetting_uses_up_every_outstanding_token(client, capsys):
    signup(client)
    client.post("/auth/forgot", json={"email": "taufik@example.com"})
    first = token_from(reset_link(capsys))
    client.post("/auth/forgot", json={"email": "taufik@example.com"})
    second = token_from(reset_link(capsys))
    assert client.post("/auth/reset", json={"token": second, "password": "new password 1"}).status_code == 200
    assert client.post("/auth/reset", json={"token": first, "password": "new password 2"}).status_code == 400


def test_an_expired_or_unknown_reset_token_is_400(client, capsys, monkeypatch):
    signup(client)
    monkeypatch.setattr(auth, "RESET_TTL", timedelta(seconds=-1))
    client.post("/auth/forgot", json={"email": "taufik@example.com"})
    token = token_from(reset_link(capsys))
    assert client.post("/auth/reset", json={"token": token, "password": "new password"}).status_code == 400
    assert client.post("/auth/reset", json={"token": "made-up", "password": "new password"}).status_code == 400


def test_reset_needs_a_strong_password(client, capsys):
    signup(client)
    client.post("/auth/forgot", json={"email": "taufik@example.com"})
    token = token_from(reset_link(capsys))
    assert client.post("/auth/reset", json={"token": token, "password": "short"}).status_code == 422
    # the token wasn't used up by the refused request
    assert client.post("/auth/reset", json={"token": token, "password": "long enough"}).status_code == 200


# --- token_version ----------------------------------------------------------------------

def test_a_token_with_a_stale_version_is_401(client):
    me = signup(client)
    with get_db() as s:
        s.exec(update(User).where(User.id == me["id"]).values(token_version=3))
    assert client.get("/me").status_code == 401
    log_in_as(client, me["id"])
    assert client.get("/me").status_code == 200
