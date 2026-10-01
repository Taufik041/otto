"""Accounts: email/password sign-in and the login cookie. GitHub sign-in is in github_app.py.

The login session is a signed JWT (HS256, AUTH_SECRET) in an httpOnly, SameSite=Lax cookie.
SameSite=Lax plus JSON-only writes (see app.py) keep other sites from acting as the user.
The JWT carries the user's token_version; changing or resetting the password bumps it, which
signs out every other device.
"""
import hashlib, re, secrets, uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import select, update

from gateway import tokens
from gateway.tokens import check_secret
from shared import config
from shared.db import get_db
from shared.models import PasswordReset, User, as_utc, utcnow

COOKIE = "otto_session"
REFRESH_COOKIE = "otto_refresh"
REFRESH_PATH = "/auth"  # the refresh cookie reaches /auth/* only
SESSION_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=1)
MIN_PASSWORD = 8
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("otto: an unknown email still pays for one hash")
router = APIRouter()
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)  # Swagger's "Authorize"


# --- signed tokens ------------------------------------------------------------------

def sign(claims, audience, ttl) -> str:
    """A JWT for one purpose (audience), so a token made for one can't be used as another."""
    check_secret()
    now = utcnow()
    return jwt.encode({**claims, "aud": audience, "iat": now, "exp": now + ttl}, config.AUTH_SECRET,
                      algorithm="HS256")


def verify(token, audience) -> dict | None:
    """The claims of a valid, unexpired token for `audience`, else None."""
    check_secret()
    try:
        return jwt.decode(token or "", config.AUTH_SECRET, algorithms=["HS256"], audience=audience)
    except jwt.InvalidTokenError:
        return None


def session_token(user_id, version=0) -> str:
    return sign({"sub": user_id, "ver": version}, "session", SESSION_TTL)


def set_login(response: Response, user: User):
    response.set_cookie(COOKIE, session_token(user.id, user.token_version),
                        max_age=int(SESSION_TTL.total_seconds()), httponly=True, samesite="lax",
                        secure=config.COOKIE_SECURE, path="/")


def clear_login(response: Response):
    response.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/")


# --- access tokens and the refresh cookie ----------------------------------------------------

def set_refresh(response: Response, token):
    response.set_cookie(REFRESH_COOKIE, token, max_age=int(tokens.refresh_ttl().total_seconds()), httponly=True,
                        samesite="lax", secure=config.COOKIE_SECURE, path=REFRESH_PATH)


def clear_refresh(response: Response):
    response.delete_cookie(REFRESH_COOKIE, httponly=True, samesite="lax", secure=config.COOKIE_SECURE,
                           path=REFRESH_PATH)


def token_body(user: User) -> dict:
    return {"access_token": tokens.access_token(user), "token_type": "bearer",
            "expires_in": int(tokens.access_ttl().total_seconds()), "user": me_json(user)}


def signed_in(request: Request, response: Response, user: User) -> dict:
    """Sign this device in: a new refresh family in the cookie, and an access token in the body."""
    set_refresh(response, tokens.issue_refresh(user.id, request.headers.get("user-agent")))
    set_login(response, user)
    return token_body(user)


def check_origin(request: Request):
    """The cookie routes' CSRF check, alongside SameSite=Lax and Path=/auth: a browser request
    must come from the frontend or from this server (its /docs page)."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in (*config.CORS_ORIGINS, f"{request.url.scheme}://{request.url.netloc}"):
        raise HTTPException(403, "origin not allowed")


# --- the current user ---------------------------------------------------------------

def user_from_token(token) -> User | None:
    claims = verify(token, "session") if token else None
    if not claims:
        return None
    with get_db() as s:
        user = s.get(User, claims["sub"])
    # a token from before the last password change or reset is void
    return user if user is not None and claims.get("ver", 0) == user.token_version else None


def user_from_access(token) -> User | None:
    """The user of a valid access token whose version is still the user's."""
    claims = tokens.access_claims(token) if token else None
    if not claims:
        return None
    with get_db() as s:
        user = s.get(User, claims["sub"])
    return user if user is not None and claims.get("ver") == user.token_version else None


def optional_user(request: Request, token: str | None = Depends(oauth2)) -> User | None:
    """The signed-in user, or None; routes that work either way depend on this."""
    if token:
        return user_from_access(token)
    return user_from_token(request.cookies.get(COOKIE))


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "sign in first", headers={"WWW-Authenticate": "Bearer"})
    return user


def me_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "github_login": user.github_login,
            "avatar_url": user.avatar_url, "default_model": user.default_model,
            "daily_token_limit": user.daily_token_limit, "has_password": user.password_hash is not None,
            "created_at": as_utc(user.created_at)}


# --- passwords ----------------------------------------------------------------------

def hash_password(password) -> str:
    return hasher.hash(password)


def password_ok(user: User | None, password) -> bool:
    """Whether password is the user's. Hashes even without a user, so timing doesn't reveal emails."""
    stored = user.password_hash if user else None
    try:
        return hasher.verify(stored or DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


def normal_email(v) -> str:
    v = v.strip().lower()
    if not EMAIL.fullmatch(v):
        raise ValueError("not an email address")
    return v


def strong_password(v) -> str:
    if len(v) < MIN_PASSWORD:
        raise ValueError(f"use at least {MIN_PASSWORD} characters")
    return v


class Signup(BaseModel):
    name: str = Field(max_length=100)
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)

    @field_validator("name")
    @classmethod
    def named(cls, v):
        if not v.strip():
            raise ValueError("a name is required")
        return v.strip()

    _email = field_validator("email")(normal_email)
    _password = field_validator("password")(strong_password)


class Login(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


def user_by_email(email) -> User | None:
    with get_db() as s:
        return s.exec(select(User).where(User.email == email.strip().lower())).first()


@router.post("/auth/signup", status_code=201)
def signup(body: Signup, request: Request, response: Response):
    user = User(id=uuid.uuid4().hex, email=body.email, name=body.name, password_hash=hash_password(body.password))
    try:
        with get_db() as s:
            s.add(user)
    except IntegrityError:
        raise HTTPException(409, "an account with this email already exists") from None
    return signed_in(request, response, user)


def _check_password(email, password) -> User:
    user = user_by_email(email)
    if not password_ok(user, password):
        raise HTTPException(401, "wrong email or password")
    if hasher.check_needs_rehash(user.password_hash):
        with get_db() as s:
            s.exec(update(User).where(User.id == user.id).values(password_hash=hash_password(password)))
    return user


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    return signed_in(request, response, _check_password(body.email, body.password))


@router.post("/auth/token")
def token(request: Request, response: Response, form: OAuth2PasswordRequestForm = Depends()):
    """Login as an OAuth2 password form (username = the email): what /docs' Authorize sends."""
    return signed_in(request, response, _check_password(form.username, form.password))


def _refused(status, detail) -> JSONResponse:
    """A refusal that also drops the refresh cookie."""
    r = JSONResponse({"detail": detail}, status, headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)
    clear_refresh(r)
    return r


@router.post("/auth/refresh")
def refresh(request: Request, response: Response):
    """A new access token for the refresh cookie, which is swapped for the next one. A cookie that
    was swapped out already signs out the device it was stolen from (its family is revoked)."""
    check_origin(request)
    got = tokens.rotate_refresh(request.cookies.get(REFRESH_COOKIE), request.headers.get("user-agent"))
    if got is None:
        return _refused(401, "sign in again")
    user_id, new = got
    with get_db() as s:
        user = s.get(User, user_id)
    if user is None:
        return _refused(401, "sign in again")
    set_refresh(response, new)
    return token_body(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    """Sign this device out: its refresh token's family is revoked and the cookie dropped. Its
    access token runs out within ACCESS_TOKEN_MINUTES."""
    check_origin(request)
    tokens.revoke_family(request.cookies.get(REFRESH_COOKIE))
    clear_refresh(response)
    clear_login(response)
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(response: Response, user: User = Depends(current_user)):
    """Sign out every device, this one too: every refresh token is revoked, every access token void."""
    with get_db() as s:
        s.exec(update(User).where(User.id == user.id).values(token_version=User.token_version + 1))
        tokens.revoke_all(user.id, s)
    clear_refresh(response)
    clear_login(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return me_json(user)


class MeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    default_model: str | None = None  # a catalog id; null: the server's default

    @field_validator("name")
    @classmethod
    def named(cls, v):
        if v is None or not v.strip():
            raise ValueError("a name is required")
        return v.strip()

    @field_validator("default_model")
    @classmethod
    def available_model(cls, v):
        if v is not None and not config.is_available(v):
            raise ValueError(f"unknown or unavailable model {v!r}; see GET /models")
        return v


@router.patch("/me")
def update_me(body: MeUpdate, user: User = Depends(current_user)):
    """Change only the fields given."""
    with get_db() as s:
        row = s.get(User, user.id)
        for field in body.model_fields_set:
            setattr(row, field, getattr(body, field))
        s.add(row)
    return me_json(row)


class PasswordChange(BaseModel):
    current: str = Field(max_length=1024)
    new: str = Field(max_length=1024)

    _new = field_validator("new")(strong_password)


def _new_password(s, user_id, password) -> User:
    """Set the password, bump token_version and revoke every refresh token, signing out every
    device. Returns the user."""
    s.exec(update(User).where(User.id == user_id)
           .values(password_hash=hash_password(password), token_version=User.token_version + 1))
    tokens.revoke_all(user_id, s)
    return s.get(User, user_id, populate_existing=True)


@router.post("/me/password")
def change_password(body: PasswordChange, request: Request, response: Response, user: User = Depends(current_user)):
    """Other devices are signed out; this one gets new tokens."""
    if user.password_hash is None:
        raise HTTPException(400, "this account signs in with GitHub and has no password")
    if not password_ok(user, body.current):
        raise HTTPException(403, "the current password is wrong")
    with get_db() as s:
        user = _new_password(s, user.id, body.new)
    return signed_in(request, response, user)


# --- forgot / reset password -----------------------------------------------------------

class Forgot(BaseModel):
    email: str = Field(max_length=320)


class Reset(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)

    _password = field_validator("password")(strong_password)


def token_hash(token) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/auth/forgot")
def forgot(body: Forgot):
    """Always 200, so this can't be used to find out who has an account."""
    user = user_by_email(body.email)
    if user is not None:
        token = secrets.token_urlsafe(32)
        with get_db() as s:
            s.add(PasswordReset(token_hash=token_hash(token), user_id=user.id, expires_at=utcnow() + RESET_TTL))
        # no email yet: the link goes to the server console
        print(f"[auth] password reset for {user.email}: {config.FRONTEND_URL}/reset-password?token={token}",
              flush=True)
    return {"ok": True}


@router.post("/auth/reset")
def reset(body: Reset, request: Request, response: Response):
    now = utcnow()
    with get_db() as s:
        row = s.get(PasswordReset, token_hash(body.token))
        if row is None or row.used_at is not None or as_utc(row.expires_at) <= now:
            raise HTTPException(400, "this reset link is invalid or has expired; ask for a new one")
        # single use, and it uses up the user's other outstanding links too
        s.exec(update(PasswordReset).where(PasswordReset.user_id == row.user_id, PasswordReset.used_at.is_(None))
               .values(used_at=now))
        user = _new_password(s, row.user_id, body.password)
    return signed_in(request, response, user)  # and every other device is signed out
