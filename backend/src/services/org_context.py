"""
OrgContext — the per-action org an amebo operation executes under (arch §4.1).

Every tool execution carries one. It is resolved once, before the agent loop,
by OrgResolver (arch §4.2) for inbound messages, or trivially from goal.org_id
for goal dispatch. Executing a tool without one is a fail-closed error (I2).

This module holds only the immutable data objects + the MissingOrgContext error.
Resolution logic lives in org_resolution.py; enforcement lives in the tool
executor (registry.execute_tool).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class MissingOrgContext(RuntimeError):
    """Raised when a tool would execute without a resolved OrgContext (I2)."""


@dataclass(frozen=True)
class Venue:
    """Where an interaction is happening. All optional — a goal dispatch has no
    venue; a Slack message has all four."""
    channel_kind: Optional[str] = None   # 'slack' | 'web' | 'email' | ...
    workspace_ref: Optional[str] = None  # Slack team_id, etc.
    channel_ref: Optional[str] = None    # Slack channel id, etc.
    thread_ref: Optional[str] = None     # source-agnostic thread key


@dataclass(frozen=True)
class OrgContext:
    """The finished context injected into every tool invocation (arch §4.1)."""
    org_id: int
    instance_id: int
    actor_type: str                       # 'user' | 'claw' | 'system'
    actor_person_id: Optional[int] = None
    authority: str = "service"            # 'none' | 'service' (v1) | 'delegated' (reserved)
    venue: Optional[Venue] = None

    def __post_init__(self) -> None:
        if self.actor_type not in ("user", "claw", "system"):
            raise ValueError(f"invalid actor_type {self.actor_type!r}")
        # 'none' = acting under NO credential authority (e.g. the unknown-user
        # read-only path — nothing it does may touch org credentials).
        if self.authority not in ("none", "service", "delegated"):
            raise ValueError(f"invalid authority {self.authority!r}")
