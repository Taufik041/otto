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
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import select, update

from gateway.tokens import check_secret
from shared import config
from shared.db import get_db
from shared.models import PasswordReset, User, as_utc, utcnow

COOKIE = "otto_session"
SESSION_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=1)
MIN_PASSWORD = 8
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("otto: an unknown email still pays for one hash")
router = APIRouter()


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


# --- the current user ---------------------------------------------------------------

def user_from_token(token) -> User | None:
    claims = verify(token, "session") if token else None
    if not claims:
        return None
    with get_db() as s:
        user = s.get(User, claims["sub"])
    # a token from before the last password change or reset is void
    return user if user is not None and claims.get("ver", 0) == user.token_version else None


def optional_user(request: Request) -> User | None:
    """The signed-in user, or None; routes that work either way depend on this."""
    return user_from_token(request.cookies.get(COOKIE))


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "sign in first")
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
def signup(body: Signup, response: Response):
    user = User(id=uuid.uuid4().hex, email=body.email, name=body.name, password_hash=hash_password(body.password))
    try:
        with get_db() as s:
            s.add(user)
    except IntegrityError:
        raise HTTPException(409, "an account with this email already exists") from None
    set_login(response, user)
    return me_json(user)


@router.post("/auth/login")
def login(body: Login, response: Response):
    user = user_by_email(body.email)
    if not password_ok(user, body.password):
        raise HTTPException(401, "wrong email or password")
    if hasher.check_needs_rehash(user.password_hash):
        with get_db() as s:
            s.exec(update(User).where(User.id == user.id).values(password_hash=hash_password(body.password)))
    set_login(response, user)
    return me_json(user)


@router.post("/auth/logout")
def logout(response: Response):
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
    """Set the password and bump token_version, signing out every device. Returns the user."""
    s.exec(update(User).where(User.id == user_id)
           .values(password_hash=hash_password(password), token_version=User.token_version + 1))
    return s.get(User, user_id, populate_existing=True)


@router.post("/me/password")
def change_password(body: PasswordChange, response: Response, user: User = Depends(current_user)):
    """Other devices are signed out; this one gets a new cookie."""
    if user.password_hash is None:
        raise HTTPException(400, "this account signs in with GitHub and has no password")
    if not password_ok(user, body.current):
        raise HTTPException(403, "the current password is wrong")
    with get_db() as s:
        user = _new_password(s, user.id, body.new)
    set_login(response, user)
    return {"ok": True}


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
def reset(body: Reset, response: Response):
    now = utcnow()
    with get_db() as s:
        row = s.get(PasswordReset, token_hash(body.token))
        if row is None or row.used_at is not None or as_utc(row.expires_at) <= now:
            raise HTTPException(400, "this reset link is invalid or has expired; ask for a new one")
        # single use, and it uses up the user's other outstanding links too
        s.exec(update(PasswordReset).where(PasswordReset.user_id == row.user_id, PasswordReset.used_at.is_(None))
               .values(used_at=now))
        user = _new_password(s, row.user_id, body.password)
    set_login(response, user)  # and every other device is signed out
    return {"ok": True}
