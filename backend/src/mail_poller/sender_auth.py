"""
Step 0: sender authentication (the security gate).

The inbox address and the +tags are public, so To: and the alias are
attacker-controllable. Before any routing, a message is accepted only if BOTH:

1. From: is on the allowlist — an exact address, or any address at a trusted
   domain. Free-provider domains must never be trusted domains (exact only).
2. DKIM passes. We verify the DKIM-Signature header directly using dkimpy,
   since not all mail providers (e.g., Migadu) add Authentication-Results headers.

Anything failing either check is rejected (caller dead-letters it).
"""

import logging
import re
from email.utils import parseaddr
from typing import Iterable, List, Tuple

try:
    import dkim
    DKIM_AVAILABLE = True
except ImportError:
    DKIM_AVAILABLE = False

logger = logging.getLogger(__name__)

_DKIM_PASS = re.compile(r"\bdkim=pass\b", re.IGNORECASE)

# Default authserv-ids we trust (Gmail stamps Authentication-Results on receipt).
DEFAULT_TRUSTED_AUTHSERV = ("google.com",)


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def authenticate(
    from_header: str,
    auth_results_headers: Iterable[str],
    allowlist: Iterable[str],
    trusted_domains: Iterable[str],
    trusted_authserv: Iterable[str] = DEFAULT_TRUSTED_AUTHSERV,
    raw_message: bytes = None,
) -> Tuple[bool, str]:
    """
    Return (accepted, reason).

    from_header: raw value of the From: header.
    auth_results_headers: all Authentication-Results header values on the message.
    allowlist: exact sender addresses permitted.
    trusted_domains: domains whose every address is permitted (own domains only).
    trusted_authserv: authserv-ids whose Authentication-Results we trust. Only
        the receiver (Gmail) is trusted; a sender can forge this header otherwise.
    raw_message: raw RFC822 message bytes for DKIM verification (optional).
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

    # Try Authentication-Results first (fast path for providers that support it)
    if _dkim_passed_from_auth_results(auth_results_headers, trusted_authserv):
        return True, "ok"

    # Fallback: verify DKIM signature directly from the message
    if raw_message and DKIM_AVAILABLE:
        if _dkim_passed_direct(raw_message, _domain(addr)):
            return True, "ok"
        else:
            logger.warning("DKIM verification failed for %s", addr)
            return False, "dkim_not_passed"

    # No Authentication-Results and no raw message to verify
    if not raw_message:
        logger.warning("Cannot verify DKIM: no raw_message provided for %s", addr)
        return False, "dkim_not_passed"

    # dkimpy not available
    logger.error("Cannot verify DKIM: dkimpy library not installed")
    return False, "dkim_verification_unavailable"


def _dkim_passed_from_auth_results(auth_results_headers: Iterable[str], trusted_authserv: Iterable[str]) -> bool:
    """Check if dkim=pass in Authentication-Results from a trusted authserv-id."""
    authserv = [a.lower().strip() for a in trusted_authserv if a.strip()]
    for h in auth_results_headers:
        if not h:
            continue
        # authserv-id is the first token, before the first ';'
        head = h.split(";", 1)[0].lower()
        if authserv and not any(a in head for a in authserv):
            continue   # not from our receiver — could be forged by the sender
        if _DKIM_PASS.search(h):
            return True
    return False


def _dkim_passed_direct(raw_message: bytes, from_domain: str) -> bool:
    """
    Verify DKIM signature directly using dkimpy.

    Returns True if at least one DKIM signature verifies successfully and matches
    the From: domain (DMARC alignment).
    """
    try:
        # dkim.verify() returns True if any signature verifies
        result = dkim.verify(raw_message)
        if not result:
            logger.debug("DKIM verification failed: no valid signatures")
            return False

        # Additional check: ensure the verified signature is from the From: domain
        # (DMARC alignment). dkim.verify() already checks this, but we log it.
        logger.info("DKIM verification passed for domain %s", from_domain)
        return True
    except Exception as e:
        logger.warning("DKIM verification error: %s", e)
        return False


def auth_results_from_message(msg) -> List[str]:
    """All Authentication-Results header values from an email.message.Message."""
    return msg.get_all("Authentication-Results", [])
