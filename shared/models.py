from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

STATUSES = ("pending", "running", "done", "failed", "interrupted")


def utcnow():
    return datetime.now(timezone.utc)


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    repo_url: str | None = None
    task: str
    status: str = "pending"  # one of STATUSES
    model: str
    work_branch: str | None = None  # for later: the branch the session pushes to
    created_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))


class SessionEvent(SQLModel, table=True):
    __tablename__ = "session_events"

    session_id: str = Field(foreign_key="sessions.id", primary_key=True)
    seq: int = Field(primary_key=True)  # per session, starts at 1
    ts: datetime = Field(default_factory=utcnow, sa_type=sa.DateTime(timezone=True))
    type: str
    # JSONB on Postgres, plain JSON elsewhere so tests can run on SQLite
    payload: dict = Field(sa_column=sa.Column(sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False))
