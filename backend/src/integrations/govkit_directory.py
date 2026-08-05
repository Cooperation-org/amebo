"""
GovKit member directory — resolves a chat identity to a person GovKit knows.

BOUNDARIES: amebo does not store who anyone is. For an org whose membership
lives in GovKit, GovKit's Membership row is the one home of both the person
and their external identity map (it already holds `taiga_username` /
`taiga_user_id`; `discord_user_id` is the same idea for chat). amebo asks and
caches the answer for a few minutes — it never writes its own copy.

Talks to GovKit's server-to-server API with a shared bearer secret, the same
channel the invite doorway uses:

    GET {base}/api/v1/orgs/{org}/members/by-discord/{discord_user_id}/

Configure with:

    GOVKIT_BASE_URL=https://govkit.example.org
    GOVKIT_S2S_TOKEN=<the shared secret, matching GovKit's GOVKIT_S2S_TOKEN>

The org is per-caller (an instance's config names its GovKit org slug), so it
is an argument, never an env var.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# A member's role rarely changes and every inbound message would otherwise be a
# round trip. Short enough that a role change lands within a coffee break.
CACHE_TTL_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class Member:
    """A person as GovKit knows them. Read-only here — GovKit owns this row."""

    display_name: str
    role: str                       # GovKit MembershipRole: admin | steward | member
    email: str = ""
    org_slug: str = ""
    taiga_username: str = ""


class GovKitDirectory:
    """Look up members of one GovKit org by their chat identity."""

    def __init__(
        self,
        org_slug: str,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.org_slug = org_slug
        self.base_url = (base_url or os.getenv("GOVKIT_BASE_URL", "")).rstrip("/")
        self.token = token or os.getenv("GOVKIT_S2S_TOKEN", "")
        self._cache: Dict[str, Tuple[float, Optional[Member]]] = {}

    @property
    def configured(self) -> bool:
        """False when this deployment has no GovKit to ask."""
        return bool(self.base_url and self.token and self.org_slug)

    def member_by_discord_id(self, discord_user_id: str) -> Optional[Member]:
        """
        The member whose Membership carries this Discord user id, or None.

        None means "GovKit does not know this person" — which is a normal
        answer for anyone in the server who has not joined the org yet. It is
        also what a GovKit outage returns, so callers must treat None as
        *unknown*, never as *denied by policy*; the policy layer decides what
        an unknown person may do.
        """
        if not self.configured or not discord_user_id:
            return None

        cached = self._cache.get(discord_user_id)
        if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

        member = self._fetch(discord_user_id)
        self._cache[discord_user_id] = (time.time(), member)
        return member

    def _fetch(self, discord_user_id: str) -> Optional[Member]:
        url = (
            f"{self.base_url}/api/v1/orgs/{self.org_slug}"
            f"/members/by-discord/{discord_user_id}/"
        )
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.warning("GovKit directory unreachable (%s): %s", url, exc)
            return None

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning(
                "GovKit directory returned %s for discord user %s",
                resp.status_code, discord_user_id,
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.warning("GovKit directory returned non-JSON for %s", discord_user_id)
            return None

        return Member(
            display_name=data.get("display_name") or data.get("email") or "",
            role=data.get("role") or "member",
            email=data.get("email") or "",
            org_slug=data.get("org_slug") or self.org_slug,
            taiga_username=data.get("taiga_username") or "",
        )
