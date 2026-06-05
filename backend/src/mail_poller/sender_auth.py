"""
Step 0: sender authentication (the security gate).

The inbox address and the +tags are public, so To: and the alias are
attacker-controllable. Before any routing, a message is accepted only if BOTH:

1. From: is on the allowlist — an exact address, or any address at a trusted
   domain. Free-provider domains must never be trusted domains (exact only).
2. DKIM passes (read the receiver's Authentication-Results header). This proves
   the mail genuinely came from that account and isn't a spoof of an allowlisted
   address.

Anything failing either check is rejected (caller dead-letters it).
"""

import re
from email.utils import parseaddr
from typing import Iterable, List, Tuple

# Receiver-added Authentication-Results we trust (Gmail stamps this on receipt).
_DKIM_PASS = re.compile(r"\bdkim=pass\b", re.IGNORECASE)


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def authenticate(
    from_header: str,
    auth_results_headers: Iterable[str],
    allowlist: Iterable[str],
    trusted_domains: Iterable[str],
) -> Tuple[bool, str]:
    """
    Return (accepted, reason).

    from_header: raw value of the From: header.
    auth_results_headers: all Authentication-Results header values on the message.
    allowlist: exact sender addresses permitted.
    trusted_domains: domains whose every address is permitted (own domains only).
    """
    _, addr = parseaddr(from_header or "")
    addr = addr.lower().strip()
    if not addr or "@" not in addr:
        return False, "no_from_address"

    allow = {a.lower().strip() for a in allowlist if a.strip()}
    domains = {d.lower().strip().lstrip("@") for d in trusted_domains if d.strip()}

    in_allowlist = addr in allow
    in_trusted_domain = _domain(addr) in domains
    if not (in_allowlist or in_trusted_domain):
        return False, "sender_not_allowlisted"

    if not _dkim_passed(auth_results_headers):
        return False, "dkim_not_passed"

    return True, "ok"


def _dkim_passed(auth_results_headers: Iterable[str]) -> bool:
    return any(_DKIM_PASS.search(h or "") for h in auth_results_headers)


def auth_results_from_message(msg) -> List[str]:
    """All Authentication-Results header values from an email.message.Message."""
    return msg.get_all("Authentication-Results", [])
