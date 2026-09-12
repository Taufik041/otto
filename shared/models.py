from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ActionKind(str, Enum):
    SHELL_EXEC = "shell.exec"
    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    CODE_SEARCH = "code.search"
    GIT_STATUS = "git.status"
    GIT_DIFF = "git.diff"
    GIT_COMMIT = "git.commit"
    GIT_PUSH = "git.push"
    GIT_OPEN_PR = "git.open_pr"


class Action(BaseModel):
    session_id: str
    action_id: str = Field(default_factory=_uuid)
    kind: ActionKind
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    session_id: str
    action_id: str
    kind: str
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionEvent(BaseModel):
    session_id: str
    seq: int
    ts: datetime = Field(default_factory=_now)
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


def actions_queue(session_id: str) -> str:
    return f"actions.{session_id}"


def results_queue(session_id: str) -> str:
    return f"results.{session_id}"
