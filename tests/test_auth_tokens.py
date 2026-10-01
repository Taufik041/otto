"""Bearer access tokens and the refresh cookie: sign-in, refresh rotation, logout, signing out everywhere."""
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from shared import config
from shared.db import get_db
from shared.models import RefreshToken, User, utcnow
from tests.conftest import ORIGIN
from tests.fakes import PASSWORD

EMAIL = "taufik@example.com"


@pytest.fixture
def api(env):
    """A client with no default headers: what curl or Swagger sends."""
    from gateway import app as gateway_app

    with TestClient(gateway_app.app) as c:
        yield c


def refresh_header(r) -> str:
    [header] = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("otto_refresh=")]
    return header


def use_refresh(api, token):
    """Make token the client's only refresh cookie."""
    api.cookies.clear()
    api.cookies.set("otto_refresh", token, path="/auth")


def bearer(token) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sign_up(api, email=EMAIL):
    r = api.post("/auth/signup", json={"name": "Taufik", "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r


def check_token_response(r):
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    assert body["user"]["email"] == EMAIL
    claims = jwt.decode(body["access_token"], config.AUTH_SECRET, algorithms=["HS256"])
    assert (claims["sub"], claims["type"]) == (body["user"]["id"], "access")
    header = refresh_header(r).lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/auth" in header
    assert f"max-age={30 * 24 * 3600}" in header and "secure" not in header
    return body


# --- signing in ---------------------------------------------------------------------------

def test_signup_returns_a_bearer_token_and_sets_the_refresh_cookie(api):
    body = check_token_response(sign_up(api))
    assert api.get("/me", headers=bearer(body["access_token"])).json() == body["user"]


def test_login_returns_a_bearer_token_and_sets_the_refresh_cookie(api):
    sign_up(api)
    api.cookies.clear()
    r = api.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    check_token_response(r)


def test_the_oauth2_password_form_works_like_login(api):
    sign_up(api)
    api.cookies.clear()
    r = api.post("/auth/token", data={"username": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = check_token_response(r)
    assert api.get("/me", headers=bearer(body["access_token"])).status_code == 200
    assert api.post("/auth/token", data={"username": EMAIL, "password": "wrong"}).status_code == 401


def test_the_refresh_cookie_is_secure_behind_https(api, monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    assert "secure" in refresh_header(sign_up(api)).lower()


def test_swagger_knows_the_token_url(api):
    schemes = api.get("/openapi.json").json()["components"]["securitySchemes"]
    assert schemes["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/auth/token"


# --- the bearer dependency ------------------------------------------------------------------

def forged(claims, secret=None) -> str:
    return jwt.encode(claims, secret or config.AUTH_SECRET, algorithm="HS256")


def test_protected_routes_need_a_valid_access_token(api):
    uid = sign_up(api).json()["user"]["id"]
    api.cookies.clear()
    now = utcnow()
    good = {"sub": uid, "ver": 0, "type": "access", "jti": "j", "iat": now, "exp": now + timedelta(minutes=5)}
    assert api.get("/me", headers=bearer(forged(good))).status_code == 200
    for headers in [{}, bearer("garbage"), {"Authorization": forged(good)},
                    bearer(forged({**good, "exp": now - timedelta(seconds=1)})),
                    bearer(forged({**good, "type": "refresh"})),
                    bearer(forged({**good, "ver": 1})),
                    bearer(forged({**good, "sub": "nobody"})),
                    bearer(forged(good, "another secret " * 4))]:
        r = api.get("/me", headers=headers)
        assert r.status_code == 401, headers
        assert r.headers["www-authenticate"] == "Bearer"


# --- refresh --------------------------------------------------------------------------------

def test_refresh_rotates_the_cookie_and_returns_a_new_access_token(api):
    sign_up(api)
    old = api.cookies["otto_refresh"]

    r = api.post("/auth/refresh")

    assert r.status_code == 200
    body = check_token_response(r)
    new = api.cookies["otto_refresh"]
    assert new != old
    assert api.get("/me", headers=bearer(body["access_token"])).status_code == 200


def test_a_rotated_refresh_token_fails_and_reusing_it_revokes_the_family(api):
    sign_up(api)
    old = api.cookies["otto_refresh"]
    assert api.post("/auth/refresh").status_code == 200
    new = api.cookies["otto_refresh"]

    use_refresh(api, old)
    r = api.post("/auth/refresh")
    assert r.status_code == 401
    assert "max-age=0" in refresh_header(r).lower()

    use_refresh(api, new)
    assert api.post("/auth/refresh").status_code == 401


def test_refresh_without_a_cookie_or_with_an_expired_one_is_401(api, monkeypatch):
    assert api.post("/auth/refresh").status_code == 401
    monkeypatch.setattr(config, "REFRESH_TOKEN_DAYS", -1)
    sign_up(api)
    assert api.post("/auth/refresh").status_code == 401


def test_refresh_checks_the_origin(api):
    sign_up(api)
    assert api.post("/auth/refresh", headers={"Origin": "http://evil.example"}).status_code == 403
    assert api.post("/auth/refresh", headers={"Origin": ORIGIN}).status_code == 200
    assert api.post("/auth/refresh", headers={"Origin": "http://testserver"}).status_code == 200  # /docs


# --- logout ---------------------------------------------------------------------------------

def test_logout_needs_no_body_clears_the_cookie_and_ends_the_refresh_token(api):
    sign_up(api)
    token = api.cookies["otto_refresh"]

    r = api.post("/auth/logout")

    assert r.status_code == 200
    assert "max-age=0" in refresh_header(r).lower() and "path=/auth" in refresh_header(r).lower()
    use_refresh(api, token)
    assert api.post("/auth/refresh").status_code == 401


def test_logout_without_a_cookie_is_fine(api):
    assert api.post("/auth/logout").status_code == 200


def test_logout_checks_the_origin(api):
    sign_up(api)
    assert api.post("/auth/logout", headers={"Origin": "http://evil.example"}).status_code == 403
    assert api.post("/auth/refresh").status_code == 200  # still signed in


def test_logout_ends_only_this_devices_family(api):
    sign_up(api)
    laptop = api.cookies["otto_refresh"]
    api.cookies.clear()
    api.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    api.post("/auth/logout")
    use_refresh(api, laptop)
    assert api.post("/auth/refresh").status_code == 200


def test_a_post_with_no_body_or_content_type_is_accepted(api):
    access = sign_up(api).json()["access_token"]
    assert api.post("/auth/logout-all", headers=bearer(access)).status_code == 200


# --- signing out everywhere -------------------------------------------------------------------

def test_logout_all_voids_every_access_and_refresh_token(api):
    access = sign_up(api).json()["access_token"]
    laptop = api.cookies["otto_refresh"]
    api.cookies.clear()
    phone = api.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]

    r = api.post("/auth/logout-all", headers=bearer(phone))

    assert r.status_code == 200 and "max-age=0" in refresh_header(r).lower()
    for token in (access, phone):
        assert api.get("/me", headers=bearer(token)).status_code == 401
    use_refresh(api, laptop)
    assert api.post("/auth/refresh").status_code == 401


def test_logout_all_needs_a_token(api):
    assert api.post("/auth/logout-all").status_code == 401


def test_changing_the_password_voids_other_tokens_and_gives_this_device_new_ones(api):
    old = sign_up(api).json()["access_token"]
    other_device = api.cookies["otto_refresh"]

    r = api.post("/me/password", json={"current": PASSWORD, "new": "a whole new password"}, headers=bearer(old))

    assert r.status_code == 200
    body = check_token_response(r)
    assert api.get("/me", headers=bearer(old)).status_code == 401
    assert api.get("/me", headers=bearer(body["access_token"])).status_code == 200
    assert api.post("/auth/refresh").status_code == 200  # this device's new cookie
    use_refresh(api, other_device)
    assert api.post("/auth/refresh").status_code == 401


def test_resetting_the_password_voids_every_token_and_signs_this_device_in(api, capsys):
    old = sign_up(api).json()["access_token"]
    other_device = api.cookies["otto_refresh"]
    api.cookies.clear()
    api.post("/auth/forgot", json={"email": EMAIL})
    line = [l for l in capsys.readouterr().out.splitlines() if "reset-password?token=" in l][0]
    token = line.split("reset-password?token=")[1].split()[0]

    r = api.post("/auth/reset", json={"token": token, "password": "a brand new password"})

    assert r.status_code == 200
    body = check_token_response(r)
    assert api.get("/me", headers=bearer(old)).status_code == 401
    assert api.get("/me", headers=bearer(body["access_token"])).status_code == 200
    use_refresh(api, other_device)
    assert api.post("/auth/refresh").status_code == 401


def test_deleting_the_account_deletes_its_refresh_tokens(api):
    access = sign_up(api).json()["access_token"]
    assert api.delete("/me", headers=bearer(access)).status_code == 200
    with get_db() as s:
        assert s.exec(select(RefreshToken)).all() == [] and s.exec(select(User)).all() == []


# --- the old login cookie is gone ---------------------------------------------------------------

def test_the_old_login_cookie_signs_no_one_in(api):
    from gateway import auth

    uid = sign_up(api).json()["user"]["id"]
    api.cookies.clear()
    api.cookies.set("otto_session", auth.sign({"sub": uid, "ver": 0}, "session", timedelta(days=1)))
    assert api.get("/me").status_code == 401


def test_writes_are_not_refused_for_their_content_type(api):
    sign_up(api)
    api.cookies.set("otto_session", "anything")
    r = api.patch("/me", content=b"name=x", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 401  # not 415: Bearer auth needs no CSRF guard
