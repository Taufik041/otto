from datetime import timedelta

import jwt
import pytest

from gateway import auth
from shared import config
from shared.db import get_db
from shared.models import User, utcnow
from tests.fakes import PASSWORD, signup


def cookie_header(r) -> str:
    [header] = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith(auth.COOKIE)]
    return header


def user_row(user_id) -> User:
    with get_db() as s:
        return s.get(User, user_id)


# --- signup ------------------------------------------------------------------------

def test_signup_logs_in_with_an_httponly_lax_cookie(client):
    r = client.post("/auth/signup", json={"name": " Taufik Khan ", "email": "Taufik@Example.com",
                                          "password": PASSWORD})

    assert r.status_code == 201
    me = r.json()
    assert (me["name"], me["email"], me["has_password"]) == ("Taufik Khan", "taufik@example.com", True)
    assert me["github_login"] is None and me["daily_token_limit"] == 50000
    header = cookie_header(r).lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header
    assert f"max-age={7 * 24 * 3600}" in header
    assert "secure" not in header  # http://localhost in dev
    assert client.get("/me").json() == me


def test_the_password_is_stored_as_argon2_and_never_returned(client):
    me = signup(client)
    assert PASSWORD not in client.get("/me").text and "password_hash" not in me
    assert user_row(me["id"]).password_hash.startswith("$argon2id$")


def test_the_cookie_is_secure_behind_https(client, monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    r = client.post("/auth/signup", json={"name": "a", "email": "a@example.com", "password": PASSWORD})
    assert "secure" in cookie_header(r).lower()


def test_signup_with_an_existing_email_is_409(client):
    signup(client, email="taufik@example.com")
    client.cookies.clear()
    r = client.post("/auth/signup", json={"name": "x", "email": "TAUFIK@example.com", "password": PASSWORD})
    assert r.status_code == 409
    assert auth.COOKIE not in client.cookies


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

def test_login_and_logout(client):
    me = signup(client)
    client.cookies.clear()
    assert client.get("/me").status_code == 401

    r = client.post("/auth/login", json={"email": " TAUFIK@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["id"] == me["id"]
    assert "httponly" in cookie_header(r).lower()
    assert client.get("/me").json()["id"] == me["id"]

    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert "max-age=0" in cookie_header(r).lower()
    assert client.get("/me").status_code == 401


@pytest.mark.parametrize("email,password", [("taufik@example.com", "wrong password"),
                                            ("nobody@example.com", PASSWORD)])
def test_wrong_password_or_unknown_email_is_401(client, email, password):
    signup(client)
    client.cookies.clear()
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert auth.COOKIE not in client.cookies


def test_a_github_only_account_cannot_log_in_with_a_password(client):
    with get_db() as s:
        s.add(User(id="gh1", email="gh@example.com", name="gh", github_id=7))
    assert client.post("/auth/login", json={"email": "gh@example.com", "password": PASSWORD}).status_code == 401


def forged(claims, secret=None):
    return jwt.encode(claims, secret or config.AUTH_SECRET, algorithm="HS256")


def test_bad_cookies_are_401(client):
    me = signup(client)
    now = utcnow()
    for token in ["garbage",
                  forged({"sub": me["id"], "aud": "session", "exp": now + timedelta(days=1)}, "other" * 10),
                  forged({"sub": me["id"], "aud": "session", "exp": now - timedelta(seconds=1)}),
                  forged({"sub": me["id"], "aud": "github-state", "exp": now + timedelta(days=1)}),
                  forged({"sub": "no-such-user", "aud": "session", "exp": now + timedelta(days=1)})]:
        client.cookies.set(auth.COOKIE, token)
        assert client.get("/me").status_code == 401, token


def test_the_login_cookie_lasts_7_days(client):
    signup(client)
    claims = jwt.decode(client.cookies[auth.COOKIE], config.AUTH_SECRET, algorithms=["HS256"],
                        audience="session")
    assert claims["exp"] - claims["iat"] == 7 * 24 * 3600


# --- CSRF: writes must be JSON ------------------------------------------------------

@pytest.mark.parametrize("ctype", ["application/x-www-form-urlencoded", "text/plain", "multipart/form-data", None])
def test_state_changing_requests_must_be_json(client, ctype):
    signup(client)
    headers = {"content-type": ctype} if ctype else {}
    if ctype is None:
        client.headers.pop("content-type")
    r = client.post("/auth/logout", content=b"", headers=headers)
    assert r.status_code == 415
    assert client.get("/me").status_code == 200  # still logged in
    r = client.post("/auth/login", content=b"email=a&password=b", headers=headers)
    assert r.status_code == 415


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
