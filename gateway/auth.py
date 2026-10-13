"""Accounts: email/password sign-in, access tokens and the refresh cookie. GitHub sign-in is in
github_app.py; the tokens themselves in tokens.py.

Signing in returns a short-lived access token, which the client sends as `Authorization: Bearer`
on every API call, and sets the refresh cookie (httpOnly, SameSite=Lax, Path=/auth), which only
/auth/refresh and /auth/logout read. A cross-site page can't add an Authorization header, so the
API routes need no CSRF guard; the two cookie routes also check the Origin.

The access token carries the user's token_version: logout-all, or changing or resetting the
password, bumps it and revokes every refresh token, which signs out every device.

An email sign-up isn't signed in: it gets a "Confirm your email" link (VERIFY_TTL, once), which
signs it in. Until then it can log in but not chat (403 {"error": "email_unverified"}), and its
address is anyone's to take (shared.accounts.unconfirmed).
"""
import re, secrets, uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import select, update

from gateway import limits, tokens
from gateway.errors import Refused
from gateway.tokens import check_secret
from shared import access, config, email
from shared.accounts import take_unconfirmed, unconfirmed
from shared.db import get_db
from shared.models import EmailVerification, PasswordReset, User, as_utc, utcnow

REFRESH_COOKIE = "otto_refresh"
REFRESH_PATH = "/auth"  # the refresh cookie reaches /auth/* only
RESET_TTL = timedelta(hours=1)
VERIFY_TTL = timedelta(hours=24)
MIN_PASSWORD = 8
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("otto: an unknown email still pays for one hash")
router = APIRouter()
# /docs' Authorize dialog offers both: the password form, and a field to paste an access token
# (for GitHub-only accounts, which have no password: take one from POST /auth/refresh)
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False,
                              description="Sign in with your email (as username) and password.")
pasted = HTTPBearer(auto_error=False, description="Paste an access token, e.g. from POST /auth/refresh.")


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
    return token_body(user)


def check_origin(request: Request):
    """The cookie routes' CSRF check, alongside SameSite=Lax and Path=/auth: a browser request
    must come from the frontend or from this server (its /docs page)."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in (*config.CORS_ORIGINS, f"{request.url.scheme}://{request.url.netloc}"):
        raise HTTPException(403, "origin not allowed")


# --- the current user ---------------------------------------------------------------

def user_from_access(token) -> User | None:
    """The user of a valid access token whose version is still the user's."""
    claims = tokens.access_claims(token) if token else None
    if not claims:
        return None
    with get_db() as s:
        user = s.get(User, claims["sub"])
    # a token from before the last logout-all, password change or reset is void
    return user if user is not None and claims.get("ver") == user.token_version else None


def optional_user(token: str | None = Depends(oauth2),
                  credentials: HTTPAuthorizationCredentials | None = Depends(pasted)) -> User | None:
    """The user of the request's Bearer token, or None; routes that work either way depend on this.
    Both schemes read the same Authorization header; they differ only in how /docs asks for it."""
    token = token or (credentials.credentials if credentials else None)
    return user_from_access(token) if token else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "sign in first", headers={"WWW-Authenticate": "Bearer"})
    return user


def verified_user(user: User = Depends(current_user)) -> User:
    """The current user, if their email is confirmed (or they signed up with GitHub): chats need it."""
    if unconfirmed(user):
        raise Refused(403, "email_unverified", f"Confirm your email first: open the link we sent to {user.email}.")
    return user


def me_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "email_verified": user.email_verified, "name": user.name,
            "github_login": user.github_login,
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


def refusal(code) -> Refused:
    """The refusal for a signup that signup_refusal turned down."""
    return (Refused(503, "paused", access.PAUSED) if code == "paused"
            else Refused(403, "invite_only", access.INVITE_ONLY))


@router.post("/auth/signup", status_code=201, dependencies=[Depends(limits.limit("signup"))])
def signup(body: Signup):
    """A new email account, if signups are open to this email (OTTO_SIGNUP_MODE): otherwise 403
    {"error": "invite_only"}, or 503 {"error": "paused"} while OTTO_ACCEPTING is false. It isn't
    signed in: it gets a "Confirm your email" link, which signs it in. An unconfirmed account with
    this email is replaced. 503 {"error": "email_unavailable"} when email isn't set up."""
    held = user_by_email(body.email)
    if held is not None and not unconfirmed(held):
        raise HTTPException(409, "an account with this email already exists")
    if code := access.signup_refusal(email=body.email):
        raise refusal(code)
    if not email.available():
        raise Refused(503, "email_unavailable", "Sign-up by email isn't available right now. Continue with GitHub.")
    user = User(id=uuid.uuid4().hex, email=body.email, name=body.name, password_hash=hash_password(body.password))
    try:
        with get_db() as s:
            take_unconfirmed(s, body.email)
            s.add(user)
    except IntegrityError:
        raise HTTPException(409, "an account with this email already exists") from None
    _email_verify_link(user)  # if it didn't go, "Resend" sends another
    return {"ok": True, "email": user.email}


def _check_password(email, password) -> User:
    user = user_by_email(email)
    if not password_ok(user, password):
        raise HTTPException(401, "wrong email or password")
    if hasher.check_needs_rehash(user.password_hash):
        with get_db() as s:
            s.exec(update(User).where(User.id == user.id).values(password_hash=hash_password(password)))
    return user


@router.post("/auth/login", dependencies=[Depends(limits.limit("login"))])
def login(body: Login, request: Request, response: Response):
    return signed_in(request, response, _check_password(body.email, body.password))


@router.post("/auth/token", dependencies=[Depends(limits.limit("login"))])
def token(request: Request, response: Response, form: OAuth2PasswordRequestForm = Depends()):
    """Login as an OAuth2 password form (username = the email): what /docs' Authorize sends."""
    return signed_in(request, response, _check_password(form.username, form.password))


class EmailStatus(BaseModel):
    email: str = Field(max_length=320)

    _email = field_validator("email")(normal_email)


@router.post("/auth/email-status", dependencies=[Depends(limits.limit("email_status"))])
def email_status(body: EmailStatus):
    """Whether this email has an account, for email-first sign-in: a password next, or a name and
    a password for a new account. password: false for an account made with GitHub that has none
    yet (sign in with GitHub instead). Rate-limited per IP."""
    user = user_by_email(body.email)
    return {"exists": user is not None, "password": user is not None and user.password_hash is not None}


class AccessRequestIn(BaseModel):
    """The invite-only form: a GitHub username or an email (the form's one field may hold either),
    and an optional note."""
    github_login: str | None = Field(default=None, max_length=320)
    email: str | None = Field(default=None, max_length=320)
    note: str = Field(default="", max_length=access.MAX_NOTE)

    @model_validator(mode="after")
    def someone(self):
        login = (self.github_login or "").strip()
        if "@" in login.lstrip("@"):  # an email typed into the GitHub-or-email field
            self.email, login = self.email or login, ""
        self.github_login = access.normal_login(login) if login else None
        self.email = normal_email(self.email) if self.email and self.email.strip() else None
        if not (self.github_login or self.email):
            raise ValueError("give a GitHub username or an email")
        self.note = self.note.strip()
        return self


@router.post("/access-requests", status_code=201, dependencies=[Depends(limits.limit("access_request"))])
def request_access(body: AccessRequestIn):
    """Ask for an account while signups are invite-only. Asking again for the same GitHub login or
    email updates the request; the answer is the same either way."""
    access.request_access(github_login=body.github_login, email=body.email, note=body.note)
    return {"ok": True}


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
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(response: Response, user: User = Depends(current_user)):
    """Sign out every device, this one too: every refresh token is revoked, every access token void."""
    with get_db() as s:
        s.exec(update(User).where(User.id == user.id).values(token_version=User.token_version + 1))
        tokens.revoke_all(user.id, s, reason="logout_all")
    clear_refresh(response)
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
    tokens.revoke_all(user_id, s, reason="password")
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


token_hash = tokens.sha256


@router.post("/auth/forgot")
def forgot(body: Forgot):
    """Email a reset link (it lasts RESET_TTL, one hour). Always the same 200, whether or not the
    email has an account, and even if sending failed, so this can't be used to find out who has
    one. 503 {"error": "email_unavailable"} when email isn't set up in production (the app then
    hides "Forgot password?": GET /health's password_reset)."""
    if not email.available():
        raise Refused(503, "email_unavailable", "Password reset isn't available right now.")
    user = user_by_email(body.email)
    if user is not None:
        _email_password_link(user)
    return {"ok": True}


def _email_password_link(user: User) -> bool:
    """Email the user a link that sets their password (RESET_TTL, once): a reset, or for an account
    made with GitHub, its first one. Whether it went."""
    token = secrets.token_urlsafe(32)
    with get_db() as s:
        s.add(PasswordReset(token_hash=token_hash(token), user_id=user.id, expires_at=utcnow() + RESET_TTL))
    link = f"{config.FRONTEND_URL}/reset-password?token={token}"
    message = email.reset_email(link) if user.password_hash else email.set_password_email(link, user.email)
    try:
        email.send([user.email], *message)
        return True
    except email.EmailError as e:
        print(f"[auth] the password email to user {user.id} didn't go: {e}", flush=True)
        return False


@router.post("/me/password/setup")
def set_up_password(user: User = Depends(current_user)):
    """An account made with GitHub has no password: email it a link that sets one (the reset flow:
    an hour, once), so it can log in with its email and a password too. 5 an hour per user."""
    if user.password_hash is not None:
        raise HTTPException(400, "this account has a password already; change it instead")
    if not user.email:
        raise HTTPException(400, "this account has no email to send the link to")
    if not email.available():
        raise Refused(503, "email_unavailable", "Otto can't send that right now. Try again later.")
    limits.hit("password_setup", f"user:{user.id}")
    if not _email_password_link(user):
        limits.refund("password_setup", f"user:{user.id}")  # it didn't go: they may try again
        raise Refused(502, "email_failed", "That didn't send. Try again in a minute.")
    return {"ok": True, "email": user.email}


@router.post("/auth/reset")
def reset(body: Reset, request: Request, response: Response):
    """Set the password from an emailed link; it also confirms the email (the link proves it's theirs)."""
    now = utcnow()
    with get_db() as s:
        row = s.get(PasswordReset, token_hash(body.token))
        if row is None or row.used_at is not None or as_utc(row.expires_at) <= now:
            raise HTTPException(400, "this reset link is invalid or has expired; ask for a new one")
        # single use, and it uses up the user's other outstanding links too
        s.exec(update(PasswordReset).where(PasswordReset.user_id == row.user_id, PasswordReset.used_at.is_(None))
               .values(used_at=now))
        s.exec(update(User).where(User.id == row.user_id).values(email_verified=True))
        user = _new_password(s, row.user_id, body.password)
    return signed_in(request, response, user)  # and every other device is signed out


# --- confirming the email -----------------------------------------------------------------

def _email_verify_link(user: User) -> bool:
    """Email the user a link that confirms their address (VERIFY_TTL, once). Whether it went."""
    token = secrets.token_urlsafe(32)
    with get_db() as s:
        s.add(EmailVerification(token_hash=token_hash(token), user_id=user.id, email=user.email,
                                expires_at=utcnow() + VERIFY_TTL))
    try:
        email.send([user.email], *email.verify_email(f"{config.FRONTEND_URL}/verify-email?token={token}"))
        return True
    except email.EmailError as e:
        print(f"[auth] the confirmation email to user {user.id} didn't go: {e}", flush=True)
        return False


def _resend(user: User) -> bool:
    """Another confirmation link, at most 3 an hour per address (limits.LIMITS); whether it went."""
    if not email.available():
        raise Refused(503, "email_unavailable", "Otto can't send that right now. Try again later.")
    key = f"email:{user.email}"
    limits.hit("verify_email", key)
    if not _email_verify_link(user):
        limits.refund("verify_email", key)  # it didn't go: they may try again
        return False
    return True


class Verify(BaseModel):
    token: str = Field(max_length=200)


@router.post("/auth/verify")
def verify_email(body: Verify, request: Request, response: Response):
    """Confirm the email from the emailed link, and sign in. The link works once, for the address
    it was sent to."""
    now = utcnow()
    with get_db() as s:
        row = s.get(EmailVerification, token_hash(body.token))
        user = s.get(User, row.user_id) if row is not None else None
        if (row is None or row.used_at is not None or as_utc(row.expires_at) <= now or user is None
                or user.email != row.email):
            raise HTTPException(400, "this confirmation link is invalid or has expired; ask for a new one")
        s.exec(update(EmailVerification)
               .where(EmailVerification.user_id == user.id, EmailVerification.used_at.is_(None)).values(used_at=now))
        user.email_verified = True
        s.add(user)
        s.flush()
        s.refresh(user)
    return signed_in(request, response, user)


class Resend(BaseModel):
    email: str = Field(max_length=320)

    _email = field_validator("email")(normal_email)


@router.post("/auth/verify/resend")
def resend_verification(body: Resend):
    """The sign-in dialog's "Resend": another link for an unconfirmed account with this email.
    Always the same 200 (an unknown or confirmed email gets nothing), so it doesn't tell who has an
    account. 3 an hour per address."""
    user = user_by_email(body.email)
    if unconfirmed(user):
        _resend(user)
    else:
        if not email.available():
            raise Refused(503, "email_unavailable", "Otto can't send that right now. Try again later.")
        limits.hit("verify_email", f"email:{body.email}")
    return {"ok": True}


@router.post("/me/email/verify")
def resend_mine(user: User = Depends(current_user)):
    """The "Confirm your email" screen's "Resend". 3 an hour per address."""
    if not unconfirmed(user):
        raise HTTPException(400, "this email is confirmed already")
    if not _resend(user):
        raise Refused(502, "email_failed", "That didn't send. Try again in a minute.")
    return {"ok": True, "email": user.email}


class EmailChange(BaseModel):
    email: str = Field(max_length=320)

    _email = field_validator("email")(normal_email)


@router.post("/me/email")
def change_email(body: EmailChange, user: User = Depends(current_user)):
    """Change an unconfirmed account's email (a typo at sign-up) and send a link to the new one;
    links to the old one stop working. A confirmed email can't be changed here. 5 an hour per user."""
    if not unconfirmed(user):
        raise HTTPException(400, "this email is confirmed already")
    held = user_by_email(body.email)
    if held is not None and held.id != user.id and not unconfirmed(held):
        raise HTTPException(409, "an account with this email already exists")
    if code := access.signup_refusal(email=body.email):
        raise refusal(code)
    if not email.available():
        raise Refused(503, "email_unavailable", "Otto can't send that right now. Try again later.")
    limits.hit("email_change", f"user:{user.id}")
    now = utcnow()
    try:
        with get_db() as s:
            if body.email != user.email:
                take_unconfirmed(s, body.email)
            row = s.get(User, user.id)
            row.email = body.email
            s.add(row)
            # links sent to the old address prove nothing about the new one
            for model in (EmailVerification, PasswordReset):
                s.exec(update(model).where(model.user_id == user.id, model.used_at.is_(None)).values(used_at=now))
            s.flush()
            s.refresh(row)
    except IntegrityError:
        raise HTTPException(409, "an account with this email already exists") from None
    _email_verify_link(row)
    return me_json(row)
