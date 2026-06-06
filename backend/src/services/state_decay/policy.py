"""
Per-store GC abstraction.

Each system of record that holds Amebo working-state registers its own
``GcPolicy``. The runner never assumes a single mechanism: it asks each policy
to enumerate its expirable items, asks the retention judge whether to keep
each, and then asks the policy to expire the rest. The "how" (a SQL DELETE, an
abra API call, a no-op archive) lives entirely inside each policy.

Nothing here touches a database. Policies do that in ``stores`` so this module
stays a pure, testable contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable, List, Optional, Protocol, runtime_checkable


@dataclass
class GcReport:
    """
    Outcome of running one store's GC pass. Returned per store so the runner
    (and tests, and any admin endpoint) can see exactly what happened without
    re-querying.

    ``expired`` and ``kept`` count *items the policy considered* — items that
    were not yet candidates (e.g. inside their TTL window) are not counted.

    ``dry_run`` records whether the policy actually removed anything. A store
    whose deletion is destructive and external (the abra scope) defaults to
    dry-run: it lists what it *would* expire and removes nothing.
    """

    store: str
    considered: int = 0
    expired: int = 0
    kept: int = 0
    dry_run: bool = False
    # Opaque identifiers of items the policy would/did expire — useful for
    # dry-run inspection and for tests. Kept small; not a full dump.
    expired_ids: List[Any] = field(default_factory=list)
    note: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "store": self.store,
            "considered": self.considered,
            "expired": self.expired,
            "kept": self.kept,
            "dry_run": self.dry_run,
            "expired_ids": self.expired_ids,
            "note": self.note,
        }


@runtime_checkable
class GcPolicy(Protocol):
    """
    The contract a store implements so the runner can decay it.

    A policy is responsible for THREE things, and nothing else:

      1. ``name`` / ``ttl`` — identity and how long an item lives before it is
         even a candidate for expiry.
      2. ``enumerate_expirable()`` — yield the items that are *past TTL* and
         not already marked durable/kept by the store itself. The runner then
         consults the retention judge on each.
      3. ``expire(items)`` — remove (or archive) the items the runner decided
         should decay, and return a ``GcReport``.

    Keeping enumeration and expiry separate lets the runner interpose the
    retention judgment between "these are old" and "these are gone", and lets
    each store decide what "remove" means for it.
    """

    @property
    def name(self) -> str:
        """Stable store identifier, e.g. ``"threads"`` or ``"abra_working_memory"``."""
        ...

    @property
    def ttl(self) -> timedelta:
        """How long an item lives before it becomes an expiry candidate."""
        ...

    def is_durable(self, item: Any) -> bool:
        """
        True if the store *itself* already marks this item as kept/durable
        (e.g. a thread with ``retained_until > NOW()``). Durable items are
        never enumerated as expirable. This is distinct from the retention
        judge: ``is_durable`` is the store's own persisted decision; the judge
        is Amebo's fresh decision at GC time.
        """
        ...

    def enumerate_expirable(self) -> Iterable[Any]:
        """
        Yield items past TTL and not ``is_durable``. The runner consults the
        retention judge on each; survivors are NOT expired.
        """
        ...

    def expire(self, items: List[Any]) -> GcReport:
        """
        Expire the given items per this store's mechanism. Returns a report.
        A dry-run policy logs/lists but removes nothing and sets
        ``GcReport.dry_run = True``.
        """
        ...


class StoreRegistry:
    """
    Holds one ``GcPolicy`` per store. Each store registers its own policy so no
    single GC mechanism is assumed. The runner iterates whatever is registered.
    """

    def __init__(self) -> None:
        self._policies: dict[str, GcPolicy] = {}

    def register(self, policy: GcPolicy) -> None:
        if not isinstance(policy, GcPolicy):
            raise TypeError(
                f"{policy!r} does not satisfy the GcPolicy protocol"
            )
        name = policy.name
        if name in self._policies:
            raise ValueError(f"A policy named {name!r} is already registered")
        self._policies[name] = policy

    def unregister(self, name: str) -> None:
        self._policies.pop(name, None)

    def get(self, name: str) -> Optional[GcPolicy]:
        return self._policies.get(name)

    def names(self) -> List[str]:
        return list(self._policies.keys())

    def policies(self) -> List[GcPolicy]:
        return list(self._policies.values())

    def clear(self) -> None:
        self._policies.clear()


# Process-wide registry. Stores register themselves into this on import of the
# ``stores`` module; tests build their own registries and pass them to run_gc.
default_registry = StoreRegistry()
