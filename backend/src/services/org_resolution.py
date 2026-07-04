"""
OrgResolver — per-action target-org resolution (arch §4.2).

Given the instance, the recognized person, the utterance, and the venue, decide
which org an inbound action executes under, by the deterministic precedence
chain (implemented here EXACTLY in order):

    candidates = memberships(person) ∩ orgs_for_instance(instance)
    4. explicit targeting in the utterance   -> resolve + pin to thread
    5. thread pin                            -> resolve
    6. channel default, else workspace default -> resolve
    7. sole membership                       -> resolve
    8. else ask one short line listing candidates (ambiguous)

Recognition (step 2, speaker->person) and venue->instance (step 1) happen before
this, in the channel adapter; this resolver takes the finished instance_id +
person_id. Resolution completes before the agent loop; the loop and every tool
receive the finished OrgContext (built via org_context_for). Fail-closed: an
unresolved action yields no OrgContext, so no org-scoped tool can run (I2).

All DB access is via injected repos so the chain is unit-testable with fakes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.services.org_context import OrgContext, Venue


@dataclass
class Resolution:
    status: str                                   # resolved | ambiguous | not_member | none
    org_id: Optional[int] = None
    should_pin: bool = False
    candidates: List[Dict] = field(default_factory=list)  # [{org_id, name}]
    message: Optional[str] = None                 # one line for ambiguous/not_member/none


def _mention_pos(utterance: str, org_meta: Dict) -> Optional[int]:
    """The earliest character index at which the utterance explicitly names this
    org — its name, slug (hyphens treated as spaces), or any alias — on word
    boundaries, case-insensitive. None if not mentioned. Position lets the
    resolver honor the FIRST org named in the text (arch §4.2), not id order."""
    if not utterance:
        return None
    text = utterance.lower()
    terms = set()
    for raw in [org_meta.get("name"), org_meta.get("slug"), *(org_meta.get("aliases") or [])]:
        if not raw:
            continue
        t = str(raw).lower().strip()
        if not t:
            continue
        terms.add(t)
        if "-" in t:
            terms.add(t.replace("-", " "))
    best = None
    for term in terms:
        m = re.search(r"\b" + re.escape(term) + r"\b", text)
        if m and (best is None or m.start() < best):
            best = m.start()
    return best


def _mentions(utterance: str, org_meta: Dict) -> bool:
    return _mention_pos(utterance, org_meta) is not None


class OrgResolver:

    def __init__(self, *, member_repo=None, instance_repo=None, org_repo=None,
                 routing_repo=None, identity_repo=None):
        # Lazy real defaults so tests can inject fakes without touching the DB.
        if member_repo is None:
            from src.db.repositories.org_member_repo import OrgMemberRepo
            member_repo = OrgMemberRepo()
        if instance_repo is None:
            from src.db.repositories.instance_repo import InstanceRepo
            instance_repo = InstanceRepo()
        if org_repo is None:
            from src.db.repositories.org_repo import OrgRepo
            org_repo = OrgRepo()
        if routing_repo is None:
            from src.db.repositories.org_routing_repo import OrgRoutingRepo
            routing_repo = OrgRoutingRepo()
        if identity_repo is None:
            from src.db.repositories.person_identity_repo import PersonIdentityRepo
            identity_repo = PersonIdentityRepo()
        self._members = member_repo
        self._instances = instance_repo
        self._orgs = org_repo
        self._routing = routing_repo
        self._identity = identity_repo

    # -- recognition (step 2): channel/OIDC identity -> person -----------------

    def recognize(self, venue: Optional[Venue], speaker_external_id: Optional[str]) -> Optional[int]:
        if not venue or not venue.channel_kind or not speaker_external_id:
            return None
        return self._identity.recognize(
            venue.channel_kind, speaker_external_id, venue.workspace_ref or ""
        )

    # -- resolution (steps 3-8) ------------------------------------------------

    def resolve(self, *, instance_id: int, person_id: Optional[int],
                utterance: str, venue: Optional[Venue]) -> Resolution:
        memberships = {m["org_id"] for m in self._members.memberships(person_id)} if person_id else set()
        served = set(self._instances.orgs_for_instance(instance_id))
        candidate_ids = memberships & served

        cand_meta = {m["org_id"]: m for m in self._orgs.metadata(sorted(candidate_ids))}
        thread_ref = venue.thread_ref if venue else None

        # 4. Explicit targeting — the FIRST org named in the utterance wins (by
        #    text position, not id order) and re-pins. A second named candidate
        #    is out of scope for v1 (§12.7): resolve the first; a caller may offer
        #    the rest separately.
        mentioned = sorted(
            (pos, oid) for oid in candidate_ids
            if (pos := _mention_pos(utterance, cand_meta[oid])) is not None
        )
        if mentioned:
            target = mentioned[0][1]
            if thread_ref:
                self._routing.pin_thread(thread_ref, target, person_id)
            return Resolution("resolved", org_id=target, should_pin=True)

        # Naming an org that exists but isn't a usable candidate -> a clear
        # one-liner instead of the generic ask (arch §4.2 step 4), both ways:
        # (a) the instance serves it but the person isn't a member;
        non_member_served = served - memberships
        for m in self._orgs.metadata(sorted(non_member_served)):
            if _mentions(utterance, m):
                return Resolution(
                    "not_member",
                    message=f"You're not a member of {m['name']}, so I can't act for it here.",
                )
        # (b) the person is a member but THIS instance doesn't serve it.
        member_not_served = memberships - served
        for m in self._orgs.metadata(sorted(member_not_served)):
            if _mentions(utterance, m):
                return Resolution(
                    "not_served",
                    message=f"This amebo doesn't serve {m['name']}.",
                )

        # 5. Thread pin (only if still a candidate).
        if thread_ref:
            pinned = self._routing.thread_pin(thread_ref)
            if pinned in candidate_ids:
                return Resolution("resolved", org_id=pinned)

        # 6. Channel default, then workspace default (only if a candidate).
        if venue and venue.workspace_ref and venue.channel_ref:
            cd = self._routing.channel_default(venue.workspace_ref, venue.channel_ref)
            if cd in candidate_ids:
                return Resolution("resolved", org_id=cd)
        if venue and venue.workspace_ref:
            wd = self._routing.workspace_default(venue.workspace_ref)
            if wd in candidate_ids:
                return Resolution("resolved", org_id=wd)

        # 7. Sole membership.
        if len(candidate_ids) == 1:
            return Resolution("resolved", org_id=next(iter(candidate_ids)))

        # 8. Ask, or nothing to act on.
        if not candidate_ids:
            return Resolution(
                "none",
                message="I don't have an org I can act on for you here.",
            )
        names = [cand_meta[o]["name"] for o in sorted(candidate_ids)]
        return Resolution(
            "ambiguous",
            candidates=[{"org_id": o, "name": cand_meta[o]["name"]} for o in sorted(candidate_ids)],
            message="Which org should this go under — " + ", ".join(names) + "?",
        )

    # -- build the finished context --------------------------------------------

    def org_context_for(self, resolution: Resolution, *, instance_id: int,
                        person_id: Optional[int], venue: Optional[Venue],
                        actor_type: str = "user") -> Optional[OrgContext]:
        """The OrgContext for a resolved outcome, else None (fail-closed)."""
        if resolution.status != "resolved" or resolution.org_id is None:
            return None
        return OrgContext(
            org_id=resolution.org_id,
            instance_id=instance_id,
            actor_type=actor_type,
            actor_person_id=person_id,
            venue=venue,
        )

    def for_goal(self, goal: Dict, instance_id: int) -> OrgContext:
        """Goal dispatch resolves trivially from goal.org_id (arch §4.2)."""
        return OrgContext(
            org_id=goal["org_id"],
            instance_id=instance_id,
            actor_type="claw",
            actor_person_id=None,
        )
