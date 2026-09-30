from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from shared import config

STATUSES = ("pending", "provisioning", "queued", "running", "done", "failed", "interrupted", "stopped")
TITLE_LENGTH = 60


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(ts):
    """ts as an aware UTC datetime: SQLite hands back naive ones (they were stored as UTC)."""
    return ts.replace(tzinfo=timezone.utc) if ts is not None and ts.tzinfo is None else ts


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True)  # None: made by the brain CLI
    title: str = ""
    repo: str | None = None  # "owner/name"; None: a plain chat, with no sandbox
    task: str  # the first message
    status: str = "pending"  # one of STATUSES
    model: str
    work_branch: str | None = None  # otto/<id>, set once the session opens a PR
    pr_url: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))

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


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(primary_key=True)
    email: str | None = Field(default=None, unique=True)  # lower-cased; None for GitHub-only accounts
    name: str
    password_hash: str | None = None  # argon2; None: no email/password sign-in
    github_id: int | None = Field(default=None, unique=True, sa_type=sa.BigInteger)
    github_login: str | None = None
    avatar_url: str | None = None
    default_model: str | None = None  # a catalog id; None: the server's default
    daily_token_limit: int = Field(default_factory=lambda: config.DAILY_TOKEN_LIMIT)
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class PasswordReset(SQLModel, table=True):
    __tablename__ = "password_resets"

    token_hash: str = Field(primary_key=True)  # sha256 of the emailed token; the token itself isn't stored
    user_id: str = Field(foreign_key="users.id", index=True)
    expires_at: datetime = Field(sa_type=sa.DateTime(timezone=True))
    used_at: datetime | None = Field(default=None, sa_type=sa.DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class Installation(SQLModel, table=True):
    """A GitHub App installation a user connected to Otto: its repos are theirs to work on."""
    __tablename__ = "installations"

    id: int = Field(primary_key=True, sa_type=sa.BigInteger, sa_column_kwargs={"autoincrement": False})  # GitHub's
    user_id: str = Field(foreign_key="users.id", index=True)
    account_login: str  # the user or organization it is installed on
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
