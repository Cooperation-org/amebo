"""
Reference integrity — a read-only claw that uses the system to track itself.

Amebo and abra store *name bindings*: rows of the shape

    (scope, name, relationship, target_type, target_ref)

where ``target_ref`` points at an entity that lives in another system of
record — a CRM contact, a Taiga task, a URI. Per docs/ORGS_GOALS_CLAW.md
("Storage Split: Structured vs. Semantic") the binding holds a *pointer*,
not a copy of the external data. Pointers go stale: a CRM contact gets
merged or deleted, a Taiga task is archived, and the binding is left
dangling with nothing on the other end.

This service walks those bindings and, for each external reference, asks the
*owning* system "does this still exist?" — read-only — and classifies the
result:

    OK            — the target resolved; the pointer is live.
    DANGLING      — the owning system answered, and the target is gone.
    UNRESOLVABLE  — the owning system could not be reached / errored, OR no
                    resolver is wired for that reference kind, so we cannot
                    say either way. Never treated as dangling: we do not
                    delete or flag on the strength of a system being down.

It returns a structured :class:`IntegrityReport`. It writes nothing,
anywhere, and sends no outbound message. Acting on a dangling reference
(notifying a human, proposing a fix) is deliberately out of scope and must
route through the existing draft-approval gate later — see
docs/REFERENCE_INTEGRITY_CLAW.md.

Boundaries (mirrors the resolver/pointer rules):
- Reads bindings through a ``BindingReader`` (the existing read-only
  BindingRepo satisfies it in prod; tests inject a fake).
- Resolves each external reference through an injected ``ReferenceResolver``
  keyed by reference *kind* (e.g. "crm_contact", "taiga_task"). Real
  resolvers wrap amebo's existing read-only tool wrappers; tests inject
  fakes. A reference whose kind has no registered resolver is reported
  UNRESOLVABLE, never silently skipped.
- One resolver raising does not abort the run — that single reference is
  UNRESOLVABLE and the walk continues (failure isolation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class RefStatus(str, Enum):
    """How a single external reference resolved."""

    OK = "OK"                      # target exists in its system of record
    DANGLING = "DANGLING"          # system answered; target is gone
    UNRESOLVABLE = "UNRESOLVABLE"  # system unreachable / errored / no resolver


# Resolution outcome a resolver returns. A plain tri-state keeps resolvers
# trivial to implement and to fake: True (exists), False (gone), or None
# (cannot tell — caller maps to UNRESOLVABLE). Raising is also allowed and
# is treated as UNRESOLVABLE with the exception captured.
ResolveOutcome = Optional[bool]


# ---------------------------------------------------------------------------
# Pluggable read-only ports (Protocols — fakes in tests, real wiring in prod)
# ---------------------------------------------------------------------------

@runtime_checkable
class BindingReader(Protocol):
    """
    Read-only port over the binding store. The existing
    ``src.db.repositories.binding_repo.BindingRepo`` already provides this
    method, so it satisfies the protocol with no changes.

    Each returned binding is a mapping with at least:
        id, scope, name, relationship, target_type, target_ref
    """

    def search_bindings_by_name(  # pragma: no cover - structural
        self,
        name: str,
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class ReferenceResolver(Protocol):
    """
    Read-only existence check for one *kind* of external reference.

    ``exists(ref)`` returns:
        True   — the target exists in its system of record.
        False  — the system answered and the target is gone (DANGLING).
        None   — the resolver cannot determine existence (UNRESOLVABLE).

    It MUST NOT write, update, or delete anything, and MUST NOT send any
    outbound message. Raising is permitted and is treated as UNRESOLVABLE
    (failure isolation) — the run continues.
    """

    def exists(self, ref: str) -> ResolveOutcome:  # pragma: no cover - structural
        ...


# ---------------------------------------------------------------------------
# Report shapes
# ---------------------------------------------------------------------------

@dataclass
class ReferenceCheck:
    """The result of checking one binding's external reference."""

    binding_id: Any
    scope: Optional[str]
    name: Optional[str]
    relationship: Optional[str]
    target_type: Optional[str]      # the reference "kind" (crm_contact, ...)
    target_ref: Optional[str]       # the external id / slug / uri
    status: RefStatus
    detail: Optional[str] = None    # human-readable locator / failure reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "scope": self.scope,
            "name": self.name,
            "relationship": self.relationship,
            "target_type": self.target_type,
            "target_ref": self.target_ref,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class IntegrityReport:
    """
    Structured outcome of a reference-integrity pass over a scope.

    ``checks`` holds every external reference examined. ``dangling`` and
    ``unresolvable`` are convenience slices with enough detail (scope, name,
    target_type, target_ref) to locate each problem. Counts are derived so
    the report stays internally consistent.
    """

    scope: Optional[str]
    checks: List[ReferenceCheck] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def ok(self) -> List[ReferenceCheck]:
        return [c for c in self.checks if c.status is RefStatus.OK]

    @property
    def dangling(self) -> List[ReferenceCheck]:
        return [c for c in self.checks if c.status is RefStatus.DANGLING]

    @property
    def unresolvable(self) -> List[ReferenceCheck]:
        return [c for c in self.checks if c.status is RefStatus.UNRESOLVABLE]

    @property
    def counts(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "ok": len(self.ok),
            "dangling": len(self.dangling),
            "unresolvable": len(self.unresolvable),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "counts": self.counts,
            # Full list for the audit surface; the slices below are what a
            # human acts on first.
            "checks": [c.to_dict() for c in self.checks],
            "dangling": [c.to_dict() for c in self.dangling],
            "unresolvable": [c.to_dict() for c in self.unresolvable],
        }


# ---------------------------------------------------------------------------
# Which target_types are external references we resolve
# ---------------------------------------------------------------------------

# A binding's ``target_type`` names the kind of thing ``target_ref`` points
# at. Only *cross-system* kinds are checkable here. ``content`` points at
# amebo's own content rows (not an external system) and ``uri`` is the
# amebo-internal claw pointer convention (e.g. "amebo:claw/<goal_id>") plus
# arbitrary external URLs — neither is resolved by a system-of-record
# existence check in v1, so both are skipped, not flagged. Extend by
# registering a resolver for the kind and adding it here.
DEFAULT_EXTERNAL_TYPES = ("crm_contact", "taiga_task")


class ReferenceIntegrityService:
    """
    Walk name-bindings for a scope, resolve each external reference against
    its system of record (read-only), and return an :class:`IntegrityReport`.

    Construction injects the read-only ports:

        reader     — a BindingReader (prod: BindingRepo; tests: a fake).
        resolvers  — {kind: ReferenceResolver}. A reference whose target_type
                     has no resolver is reported UNRESOLVABLE.
        names      — the binding ``name`` keys to enumerate for the scope.
                     The binding store is name-keyed (search_bindings_by_name),
                     so the caller supplies the names of interest. See the
                     wiring note in docs/REFERENCE_INTEGRITY_CLAW.md for how a
                     scope-wide name list is sourced in prod.
        external_types — override the set of target_types treated as external.
    """

    def __init__(
        self,
        reader: BindingReader,
        resolvers: Dict[str, ReferenceResolver],
        external_types: Optional[tuple] = None,
    ):
        self._reader = reader
        self._resolvers = dict(resolvers)
        self._external_types = tuple(external_types or DEFAULT_EXTERNAL_TYPES)

    # ------------------------------------------------------------------ Run

    def check_scope(
        self,
        scope: Optional[str],
        names: List[str],
    ) -> IntegrityReport:
        """
        Enumerate bindings for ``names`` within ``scope``, classify every
        external reference, and return the report. Pure read path: touches
        no system other than through the injected ports, writes nothing.
        """
        report = IntegrityReport(scope=scope)
        seen: set = set()  # dedupe identical (id, target_ref) bindings

        for name in names:
            try:
                bindings = self._reader.search_bindings_by_name(name, scope=scope) or []
            except Exception as exc:
                # A reader failure for one name should not abort the whole
                # pass. Record nothing for that name (we have no binding to
                # point at) and move on.
                logger.warning(
                    "reference_integrity: reader failed for name %r scope %r: %s",
                    name, scope, exc,
                )
                continue

            for binding in bindings:
                target_type = binding.get("target_type")
                if target_type not in self._external_types:
                    continue  # not a cross-system reference — skip, don't flag
                key = (binding.get("id"), binding.get("target_ref"))
                if key in seen:
                    continue
                seen.add(key)
                report.checks.append(self._check_binding(binding))

        return report

    # -------------------------------------------------------------- Per-ref

    def _check_binding(self, binding: Dict[str, Any]) -> ReferenceCheck:
        target_type = binding.get("target_type")
        target_ref = binding.get("target_ref")
        base = dict(
            binding_id=binding.get("id"),
            scope=binding.get("scope"),
            name=binding.get("name"),
            relationship=binding.get("relationship"),
            target_type=target_type,
            target_ref=target_ref,
        )

        if not target_ref:
            return ReferenceCheck(
                **base, status=RefStatus.UNRESOLVABLE,
                detail="binding has no target_ref",
            )

        resolver = self._resolvers.get(target_type)
        if resolver is None:
            return ReferenceCheck(
                **base, status=RefStatus.UNRESOLVABLE,
                detail=f"no resolver registered for target_type {target_type!r}",
            )

        try:
            outcome = resolver.exists(target_ref)
        except Exception as exc:
            # Failure isolation: one system being down (or a resolver bug)
            # marks this single reference UNRESOLVABLE; the walk continues.
            logger.warning(
                "reference_integrity: resolver for %r raised on %r: %s",
                target_type, target_ref, exc,
            )
            return ReferenceCheck(
                **base, status=RefStatus.UNRESOLVABLE,
                detail=f"resolver error: {exc}",
            )

        if outcome is True:
            return ReferenceCheck(**base, status=RefStatus.OK)
        if outcome is False:
            return ReferenceCheck(
                **base, status=RefStatus.DANGLING,
                detail=f"{target_type} {target_ref!r} not found in system of record",
            )
        # None — resolver could not determine existence.
        return ReferenceCheck(
            **base, status=RefStatus.UNRESOLVABLE,
            detail=f"{target_type} resolver could not determine existence",
        )


# ---------------------------------------------------------------------------
# Claw entry point
# ---------------------------------------------------------------------------

def run_reference_integrity_claw(
    scope: Optional[str],
    names: List[str],
    reader: Optional[BindingReader] = None,
    resolvers: Optional[Dict[str, ReferenceResolver]] = None,
    org_id: Optional[int] = None,
) -> IntegrityReport:
    """
    Claw entry point: run one read-only reference-integrity pass and RETURN
    the report (also logging a one-line summary). Safe to call from a
    scheduler tick.

    This function is the whole claw. It is intentionally NOT wired into the
    GoalScheduler or main.py — see docs/REFERENCE_INTEGRITY_CLAW.md for the
    one-line integration note. It performs NO writes and sends NO outbound
    notification. Telling a human about dangling references is out of scope
    here: that is outbound and must route through the existing
    draft-approval gate later.

    Dependency wiring:
        reader     — defaults to the real read-only BindingRepo (lazy import
                     so this module stays unit-testable without DB deps).
                     ``org_id`` is forwarded to BindingRepo to select the
                     shared abra DB (None) vs. an org-isolated store.
        resolvers  — defaults to the real read-only CLI-backed resolvers.
                     Tests inject fakes for both.
    """
    if reader is None:
        from src.db.repositories.binding_repo import BindingRepo
        reader = BindingRepo(org_id=org_id)
    if resolvers is None:
        from src.services.reference_integrity_adapters import default_resolvers
        resolvers = default_resolvers()

    service = ReferenceIntegrityService(reader=reader, resolvers=resolvers)
    report = service.check_scope(scope=scope, names=names)

    counts = report.counts
    logger.info(
        "reference_integrity claw: scope=%r total=%d ok=%d dangling=%d unresolvable=%d",
        scope, counts["total"], counts["ok"],
        counts["dangling"], counts["unresolvable"],
    )
    if report.dangling:
        for c in report.dangling:
            logger.warning(
                "reference_integrity DANGLING: scope=%r name=%r %s=%r (binding %s)",
                c.scope, c.name, c.target_type, c.target_ref, c.binding_id,
            )
    return report
