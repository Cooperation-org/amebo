"""
Trust / authorization scoring — the swappable seam (arch §4.3, I10).

Authorization is code below the model: a principal's trust is computed from
transport identity and checked in the tool executor before any tool runs. This
module encapsulates the *scoring* so it can be replaced later without touching
the executor or any tool:

  - `Principal` is transport-agnostic (Slack is only one transport; web, email,
    API, Discord, and future LinkedTrust-claim-backed signals feed the same
    shape). It carries the transport kind, the recognized person (or None), and
    coarse verification flags — never transport-specific fields.
  - `TrustEvaluator` is the seam. The default `TransportTierEvaluator` maps
    transport -> today's T0/T1/T2 tiers. A future evaluator can return a richer
    signal (e.g. a graded score, or one folded from LinkedTrust claims) and the
    gate is unchanged — swap it via `set_trust_evaluator`.

The gate itself (which tool needs which level) lives in the executor; this
module only scores the principal and exposes the access-class -> required-level
policy as data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Protocol


class TrustLevel(IntEnum):
    """Ordered trust. IntEnum so the gate can compare `level >= required`. A
    future scorer may map a continuous score onto (or beyond) these; keep the
    ordering meaningful."""
    T0 = 0        # unknown / unauthenticated — public conversation only
    T1 = 1        # channel-verified (e.g. Slack workspace membership)
    T2 = 2        # authenticated (LinkedTrust OIDC session)
    SERVICE = 3   # amebo acting under an org's own service authority (claws)


@dataclass(frozen=True)
class Principal:
    """A normalized, transport-agnostic view of who is causing an action."""
    transport: str                       # 'slack' | 'web' | 'email' | 'api' | 'system' | ...
    person_id: Optional[int] = None      # recognized person, or None (unknown speaker)
    authenticated: bool = False          # strong auth present (OIDC session) -> T2
    channel_verified: bool = False       # transport-enforced identity (Slack workspace) -> T1
    is_service: bool = False             # amebo's own claw/system actor -> SERVICE


class TrustEvaluator(Protocol):
    def evaluate(self, principal: Principal) -> TrustLevel: ...


class TransportTierEvaluator:
    """Default scorer: transport identity -> tier (arch §4.3).

    Email is ALWAYS T0 even when it maps to a known person — `From:` is
    spoofable and email content is context, never identity. Anything a future
    signal wants to add goes in a replacement evaluator, not here.
    """

    def evaluate(self, principal: Principal) -> TrustLevel:
        if principal.is_service or principal.transport == "system":
            return TrustLevel.SERVICE
        if principal.transport == "email":
            return TrustLevel.T0
        if principal.authenticated and principal.person_id is not None:
            return TrustLevel.T2
        if principal.channel_verified and principal.person_id is not None:
            return TrustLevel.T1
        return TrustLevel.T0


# --- access-class policy (data): what level a tool's class requires -----------
#
# read  : org-scoped read — needs a recognized member (>= T1). T0 has no
#         candidate org anyway (resolution is fail-closed), so this is the second
#         independent denial arch §4.3 calls for.
# write : outbound / external write — >= T1, and still passes the draft gate (I6).
# admin : admin-class op — >= T2 (plus an org-admin role check in the executor).
_ACCESS_CLASS_MIN = {
    "read": TrustLevel.T1,
    "write": TrustLevel.T1,
    "admin": TrustLevel.T2,
}


def required_level(access_class: str) -> TrustLevel:
    try:
        return _ACCESS_CLASS_MIN[access_class]
    except KeyError:
        # Unknown class is treated as the most restrictive — fail closed.
        return TrustLevel.T2


# --- the swappable module seam ------------------------------------------------

_evaluator: TrustEvaluator = TransportTierEvaluator()


def get_trust_evaluator() -> TrustEvaluator:
    return _evaluator


def set_trust_evaluator(evaluator: TrustEvaluator) -> None:
    """Replace the scorer (e.g. a richer LinkedTrust-backed one). The executor
    and tools are unaffected — this is the whole point of the seam."""
    global _evaluator
    _evaluator = evaluator


def evaluate(principal: Principal) -> TrustLevel:
    return _evaluator.evaluate(principal)
