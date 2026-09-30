"""Accounts: email/password sign-in and the login cookie. GitHub sign-in is in github_app.py.

The login session is a signed JWT (HS256, AUTH_SECRET) in an httpOnly, SameSite=Lax cookie.
SameSite=Lax plus JSON-only writes (see app.py) keep other sites from acting as the user.
"""
import re, uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import select, update

from shared import config
from shared.db import get_db
from shared.models import User, as_utc, utcnow

COOKIE = "otto_session"
SESSION_TTL = timedelta(days=7)
MIN_PASSWORD = 8
MIN_SECRET = 32
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("otto: an unknown email still pays for one hash")
router = APIRouter()


# --- signed tokens ------------------------------------------------------------------

def check_secret():
    if not config.AUTH_SECRET or len(config.AUTH_SECRET) < MIN_SECRET:
        raise RuntimeError(f"set AUTH_SECRET to a random string of at least {MIN_SECRET} characters, "
                           "e.g. python -c 'import secrets; print(secrets.token_urlsafe(48))'")


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


def session_token(user_id) -> str:
    return sign({"sub": user_id}, "session", SESSION_TTL)


def set_login(response: Response, user_id):
    response.set_cookie(COOKIE, session_token(user_id), max_age=int(SESSION_TTL.total_seconds()),
                        httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/")


def clear_login(response: Response):
    response.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/")


# --- the current user ---------------------------------------------------------------

def user_from_token(token) -> User | None:
    claims = verify(token, "session") if token else None
    if not claims:
        return None
    with get_db() as s:
        return s.get(User, claims["sub"])


def optional_user(request: Request) -> User | None:
    return user_from_token(request.cookies.get(COOKIE))


def current_user(request: Request) -> User:
    user = optional_user(request)
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
    set_login(response, user.id)
    return me_json(user)


@router.post("/auth/login")
def login(body: Login, response: Response):
    user = user_by_email(body.email)
    if not password_ok(user, body.password):
        raise HTTPException(401, "wrong email or password")
    if hasher.check_needs_rehash(user.password_hash):
        with get_db() as s:
            s.exec(update(User).where(User.id == user.id).values(password_hash=hash_password(body.password)))
    set_login(response, user.id)
    return me_json(user)


@router.post("/auth/logout")
def logout(response: Response):
    clear_login(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return me_json(user)
