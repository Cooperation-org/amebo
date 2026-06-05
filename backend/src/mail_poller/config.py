"""
Email poller config, from env (no per-user store yet).

IMAP creds and the Step 0 allowlist / trusted domains. Allowlist + trusted
domains are editable without a deploy (env, later DB).
"""

import os
from dataclasses import dataclass, field
from typing import List


def _csv(name: str) -> List[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class PollerConfig:
    imap_host: str = field(default_factory=lambda: os.getenv("MAIL_POLLER_IMAP_HOST", "imap.gmail.com"))
    imap_port: int = field(default_factory=lambda: int(os.getenv("MAIL_POLLER_IMAP_PORT", "993")))
    imap_user: str = field(default_factory=lambda: os.getenv("MAIL_POLLER_IMAP_USER", ""))
    imap_password: str = field(default_factory=lambda: os.getenv("MAIL_POLLER_IMAP_PASSWORD", ""))
    # Step 0
    allowlist: List[str] = field(default_factory=lambda: _csv("MAIL_POLLER_ALLOWLIST"))
    trusted_domains: List[str] = field(default_factory=lambda: _csv("MAIL_POLLER_TRUSTED_DOMAINS"))
    # authserv-ids whose Authentication-Results we trust (our receiver only)
    trusted_authserv: List[str] = field(
        default_factory=lambda: _csv("MAIL_POLLER_TRUSTED_AUTHSERV") or ["google.com"])
    # idempotency seen-set TTL
    seen_ttl_days: int = field(default_factory=lambda: int(os.getenv("MAIL_POLLER_SEEN_TTL_DAYS", "90")))

    def ready(self) -> bool:
        """True if we have enough to poll and enforce Step 0."""
        return bool(self.imap_user and self.imap_password and (self.allowlist or self.trusted_domains))
