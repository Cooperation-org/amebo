"""
Value types for the coding-agent orchestration layer.

These mirror the `coding_sessions` / `coding_jobs` rows (migration 013) and the
small set of model identifiers the router chooses between.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SessionStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class Model(str, Enum):
    """
    Claude tiers the router dispatches between. Values are the exact model IDs.
    A non-Claude provider would be orchestrated outside the Agent SDK.
    """
    OPUS = "claude-opus-4-8"
    SONNET = "claude-sonnet-4-6"
    HAIKU = "claude-haiku-4-5-20251001"


@dataclass
class CodingSession:
    id: str
    thread_id: int
    model: str
    status: str
    instance_id: Optional[int] = None
    sdk_session_id: Optional[str] = None
    repo_url: Optional[str] = None
    worktree_path: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "CodingSession":
        return cls(
            id=str(row["id"]),
            thread_id=row["thread_id"],
            model=row["model"],
            status=row["status"],
            instance_id=row.get("instance_id"),
            sdk_session_id=row.get("sdk_session_id"),
            repo_url=row.get("repo_url"),
            worktree_path=row.get("worktree_path"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@dataclass
class CodingJob:
    id: str
    session_id: str
    seq: int
    prompt: str
    status: str
    payload: Dict[str, Any]
    result: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "CodingJob":
        return cls(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            seq=row["seq"],
            prompt=row["prompt"],
            status=row["status"],
            payload=row.get("payload") or {},
            result=row.get("result"),
            error=row.get("error"),
            attempts=row.get("attempts", 0),
        )
