from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from shared import config

STATUSES = ("pending", "provisioning", "queued", "running", "done", "failed", "interrupted", "stopped",
            "limited")  # limited: stopped at the user's daily token limit; it can go on tomorrow
TITLE_LENGTH = 60


def utcnow():
    return datetime.now(UTC)


def as_utc(ts):
    """ts as an aware UTC datetime: SQLite hands back naive ones (they were stored as UTC)."""
    return ts.replace(tzinfo=UTC) if ts is not None and ts.tzinfo is None else ts


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True)  # None: made by the brain CLI
    title: str = ""
    # where the title came from: "auto" (the first message, until the first turn completes),
    # "generated" (the PR's title or the model's), "user" (renamed: never replaced)
    title_source: str = Field(default="auto", sa_column_kwargs={"server_default": "auto"})
    # the last event the user saw (POST /sessions/{id}/seen): a turn that ended after it wants attention
    last_seen_seq: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    repo: str | None = None  # "owner/name"; None: a plain chat, with no sandbox
    task: str  # the first message
    status: str = "pending"  # one of STATUSES
    model: str
    work_branch: str | None = None  # otto/<id>, set once the session opens a PR
    pr_url: str | None = None
    # the commit Otto pushed last to otto/<id>: CI results for it are the chat's (shared/ci.py)
    head_sha: str | None = Field(default=None, index=True)
    # the first message's id from the client that sent it: posting it again returns this chat
    client_message_id: str | None = None
    # "chat", or "review": a pull request review asked for on GitHub (shared/review.py)
    kind: str = Field(default="chat", sa_column_kwargs={"server_default": "chat"})
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))

    __table_args__ = (sa.Index("ix_sessions_client_message_id", "user_id", "client_message_id", unique=True),)

    @property
    def repo_url(self) -> str | None:
        return f"https://github.com/{self.repo}" if self.repo else None


def make_title(text) -> str:
    """A chat's title: its first message on one line, trimmed to TITLE_LENGTH characters."""
    return " ".join(str(text).split())[:TITLE_LENGTH].rstrip() or "New chat"


class SessionEvent(SQLModel, table=True):
    __tablename__ = "session_events"

    session_id: str = Field(foreign_key="sessions.id", primary_key=True)
    seq: int = Field(primary_key=True)  # per session, starts at 1
    ts: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    type: str
    # JSONB on Postgres, plain JSON elsewhere so tests can run on SQLite
    payload: dict = Field(sa_column=sa.Column(sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False))
    # a user message's id from the client that sent it: posting it again stores nothing
    client_message_id: str | None = None

    __table_args__ = (sa.Index("ix_session_events_client_message_id", "session_id", "client_message_id", unique=True),)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(primary_key=True)
    email: str | None = Field(default=None, unique=True)  # lower-cased; None for GitHub-only accounts
    # proved its owner's: GitHub's verified primary email (an account made by GitHub sign-in), or a
    # confirmation or reset link opened from it. An email sign-up is unconfirmed until then
    email_verified: bool = Field(default=False, sa_column_kwargs={"server_default": sa.false()})
    name: str
    password_hash: str | None = None  # argon2; None: no email/password sign-in
    github_id: int | None = Field(default=None, unique=True, sa_type=sa.BigInteger)
    github_login: str | None = None
    avatar_url: str | None = None
    default_model: str | None = None  # a catalog id; None: the server's default
    daily_token_limit: int = Field(default_factory=lambda: config.DAILY_TOKEN_LIMIT)
    token_version: int = Field(default=0, sa_column_kwargs={"server_default": "0"})  # in login tokens; +1 signs out
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    # deleted (shared.accounts.deactivate): signs nobody in, and holds no email or GitHub login; its
    # data is purged later (purged_at), leaving an anonymous row
    deleted_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    # sha256s of the email and GitHub login it had, for the purge to find its access requests
    purge_keys: list | None = Field(default=None, sa_column=sa.Column(sa.JSON().with_variant(JSONB(), "postgresql")))
    purged_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))


class PasswordReset(SQLModel, table=True):
    __tablename__ = "password_resets"

    token_hash: str = Field(primary_key=True)  # sha256 of the emailed token; the token itself isn't stored
    user_id: str = Field(foreign_key="users.id", index=True)
    expires_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    used_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class EmailVerification(SQLModel, table=True):
    """A "Confirm your email" link, for the address the account had when it was sent: changing
    the email voids it."""
    __tablename__ = "email_verifications"

    token_hash: str = Field(primary_key=True)  # sha256 of the emailed token; the token itself isn't stored
    user_id: str = Field(foreign_key="users.id", index=True)
    email: str
    expires_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    used_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


REVOKED_REASONS = ("rotated", "logout", "reuse", "password", "logout_all", "deleted")


class RefreshToken(SQLModel, table=True):
    """One refresh token. Each sign-in starts a family; /auth/refresh replaces the token with the
    next one in its family. Only a hash of the token is stored."""
    __tablename__ = "refresh_tokens"

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    family_id: str = Field(index=True)
    token_hash: str = Field(unique=True)  # sha256 of the token
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    expires_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    revoked_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    revoked_reason: str | None = None  # one of REVOKED_REASONS
    replaced_by_id: str | None = None  # the token that rotated this one out
    user_agent: str | None = None


class Installation(SQLModel, table=True):
    """A GitHub App installation a user connected to Otto: its repos are theirs to work on."""
    __tablename__ = "installations"

    id: int = Field(primary_key=True, sa_type=sa.BigInteger, sa_column_kwargs={"autoincrement": False})  # GitHub's
    user_id: str = Field(foreign_key="users.id", index=True)
    account_login: str  # the user or organization it is installed on
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class Usage(SQLModel, table=True):
    """One LLM call's tokens."""
    __tablename__ = "usage"
    __table_args__ = (sa.Index("ix_usage_user_id_created_at", "user_id", "created_at"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id")  # None: a session from the brain CLI
    session_id: str | None = Field(default=None, foreign_key="sessions.id", index=True)  # None: since deleted
    provider: str
    model: str  # the session's catalog id, e.g. "openai:gpt-4o-mini"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class ProviderHealth(SQLModel, table=True):
    """A provider (or one catalog model) the brain found unusable: out of credit, a bad key, an
    unknown model. GET /models shows it unavailable; the gateway clears the table when it starts."""
    __tablename__ = "provider_health"

    key: str = Field(primary_key=True)  # a provider ("openrouter") or a catalog model id ("openai:gpt-4.1")
    reason: str  # "quota", "auth" or "model"
    updated_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class WebhookDelivery(SQLModel, table=True):
    """A GitHub webhook delivery taken in (X-GitHub-Delivery): a redelivery of it is a duplicate.
    Pruned after a week."""
    __tablename__ = "webhook_deliveries"

    id: str = Field(primary_key=True)  # GitHub's delivery GUID
    event: str  # X-GitHub-Event
    received_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True), index=True)


REVIEW_STATES = ("claimed", "queued", "posting", "posted", "failed", "limited", "ignored")


class PrReview(SQLModel, table=True):
    """One review Otto was asked for on GitHub: "@<app> review" in a pull request's comment, or a
    pull request opened in a repo with auto-review on. Its key is taken once, so a webhook
    delivered again never reviews (or posts) twice."""
    __tablename__ = "pr_reviews"

    key: str = Field(primary_key=True)  # "comment:<id>", or "auto:<owner/name>#<number>@<head sha>"
    user_id: str = Field(foreign_key="users.id", index=True)  # whose quota and installation it uses
    session_id: str | None = Field(default=None, index=True)  # its chat, once made
    repo: str  # "owner/name"
    number: int
    trigger: str  # "mention" or "auto"
    comment_id: int | None = Field(default=None, sa_type=sa.BigInteger)  # the comment that asked
    state: str = "claimed"  # one of REVIEW_STATES
    review_id: int | None = Field(default=None, sa_type=sa.BigInteger)  # GitHub's, once posted
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class AutoReview(SQLModel, table=True):
    """A repo whose new pull requests Otto reviews by itself (Settings → GitHub), on the quota of
    the user who turned it on. Off: no row."""
    __tablename__ = "auto_reviews"

    repo_key: str = Field(primary_key=True)  # the full name, lower-cased
    full_name: str  # "owner/name", as GitHub spells it
    user_id: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


ACCESS_STATUSES = ("pending", "approved")


class AccessRequest(SQLModel, table=True):
    """Someone asking for an account while signups are invite-only (POST /access-requests). An
    approved one may sign up with that GitHub login or email."""
    __tablename__ = "access_requests"

    id: int | None = Field(default=None, primary_key=True)
    github_login: str | None = Field(default=None, unique=True)  # lower-cased, without the @
    email: str | None = Field(default=None, unique=True)  # lower-cased
    note: str = ""
    status: str = Field(default="pending", sa_column_kwargs={"server_default": "pending"})  # ACCESS_STATUSES
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))  # asked again
    approved_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
