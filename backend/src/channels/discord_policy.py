"""
Who may make amebo do what, in a Discord server.

Slack gives amebo one flat audience: anyone in the workspace can ask, and the
instance's `allowed_tools` decides the rest. Discord has real roles, so this
module adds the one distinction that matters and no more:

    ASK  — ask questions, get answers. Anyone in the server.
    ACT  — commands that change something outside Discord (creating a task).

Nothing here is Workers-We-See-specific. What *is* specific — the server id,
which role names count as ACT, which GovKit org holds the membership — is data
on the amebo instance row, read fresh on every message:

    instances.config -> {
      "discord": {
        "guild_id": "123…",              # the one server this instance serves
        "govkit_org": "vc",    # whose Membership rows are the identity map
        "act_roles": ["Steward", "Admin"],   # Discord role NAMES that may ACT
        "act_govkit_roles": ["admin", "steward"],  # GovKit roles that may ACT
        "channels": {"allow": [], "deny": []}      # channel names; empty allow = all
      }
    }

Two identity sources, in order: GovKit membership is authoritative (it is the
one home of who a person is), and Discord roles are the fallback for people the
org has not enrolled yet. An unknown speaker can always ASK and never ACT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional

from src.integrations.govkit_directory import GovKitDirectory, Member

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    ASK = "ask"
    ACT = "act"


# Used when an instance has no `act_govkit_roles` of its own. GovKit's own
# vocabulary: admin and steward run the org, member does the work.
DEFAULT_ACT_GOVKIT_ROLES = ("admin", "steward")


@dataclass(frozen=True)
class DiscordConfig:
    """The Discord block of an instance's config, parsed."""

    guild_id: str = ""
    govkit_org: str = ""
    act_roles: List[str] = field(default_factory=list)
    act_govkit_roles: List[str] = field(default_factory=lambda: list(DEFAULT_ACT_GOVKIT_ROLES))
    allow_channels: List[str] = field(default_factory=list)
    deny_channels: List[str] = field(default_factory=list)

    @classmethod
    def from_instance(cls, instance: Optional[Dict]) -> "DiscordConfig":
        block = ((instance or {}).get("config") or {}).get("discord") or {}
        channels = block.get("channels") or {}
        return cls(
            guild_id=str(block.get("guild_id") or ""),
            govkit_org=block.get("govkit_org") or "",
            act_roles=[r.lower() for r in (block.get("act_roles") or [])],
            act_govkit_roles=[
                r.lower() for r in (block.get("act_govkit_roles") or DEFAULT_ACT_GOVKIT_ROLES)
            ],
            allow_channels=[c.lower().lstrip("#") for c in (channels.get("allow") or [])],
            deny_channels=[c.lower().lstrip("#") for c in (channels.get("deny") or [])],
        )

    def channel_allowed(self, channel_name: Optional[str]) -> bool:
        """An empty allow-list means every channel; deny always wins."""
        name = (channel_name or "").lower().lstrip("#")
        if name in self.deny_channels:
            return False
        if self.allow_channels:
            return name in self.allow_channels
        return True


@dataclass(frozen=True)
class Speaker:
    """Who is talking, after both identity sources have been consulted."""

    discord_user_id: str
    display_name: str
    discord_roles: List[str] = field(default_factory=list)
    member: Optional[Member] = None      # GovKit membership, if it knows them

    @property
    def known(self) -> bool:
        return self.member is not None

    @property
    def author_info(self) -> str:
        """Stable identity string for conversation memory."""
        return f"discord:{self.discord_user_id}"


class DiscordPolicy:
    """Decides what a speaker may do. Holds no state beyond its config."""

    def __init__(self, config: DiscordConfig, directory: Optional[GovKitDirectory] = None):
        self.config = config
        if directory is not None:
            self.directory = directory
        else:
            self.directory = GovKitDirectory(org_slug=config.govkit_org)

    def identify(
        self,
        discord_user_id: str,
        display_name: str,
        role_names: Iterable[str],
    ) -> Speaker:
        """Resolve a Discord author into a Speaker, asking GovKit who they are."""
        member = None
        if self.directory.configured:
            member = self.directory.member_by_discord_id(discord_user_id)
        return Speaker(
            discord_user_id=str(discord_user_id),
            display_name=(member.display_name if member and member.display_name else display_name),
            discord_roles=[r.lower() for r in role_names],
            member=member,
        )

    def allows(self, speaker: Speaker, permission: Permission) -> bool:
        if permission is Permission.ASK:
            return True
        if permission is Permission.ACT:
            if speaker.member is not None:
                return speaker.member.role.lower() in self.config.act_govkit_roles
            # Not enrolled in GovKit yet — fall back to the server's own roles.
            return any(r in self.config.act_roles for r in speaker.discord_roles)
        return False

    def denial_message(self, permission: Permission) -> str:
        """What to tell someone who may not do this. Plain, no lecture."""
        if permission is Permission.ACT:
            return (
                "That command is limited to stewards and admins. "
                "Ask me a question instead, or ask a steward to run it."
            )
        return "You don't have access to that here."
