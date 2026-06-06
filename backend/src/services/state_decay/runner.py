"""
GC runner — iterates registered stores and expires per each store's own policy.

Callable synchronously from the existing scheduler tick (see
docs/STATE_DECAY_GC.md). NOT a daemon and NOT a new background task: it does
one pass and returns. This mirrors the existing opportunistic-GC pattern in
``conversation_manager`` and the synchronous ``GoalScheduler.tick``.

The runner is the only place the retention judgment is interposed between
"these items are past TTL" (the policy decides) and "these items are gone"
(the policy executes). For each store:

    1. policy.enumerate_expirable()  → candidates past TTL, not store-durable
    2. should_keep(item)             → drop the keepers
    3. policy.expire(survivors-to-decay) → store-specific removal/archival
"""

from __future__ import annotations

import logging
from typing import List, Optional

from src.services.state_decay.policy import GcReport, StoreRegistry, default_registry
from src.services.state_decay.judgment import should_keep

logger = logging.getLogger(__name__)


def run_gc(
    registry: Optional[StoreRegistry] = None,
    only: Optional[List[str]] = None,
) -> List[GcReport]:
    """
    Run one GC pass over every registered store (or just those named in
    ``only``). Returns one ``GcReport`` per store. A failure in one store is
    logged and isolated — it never aborts the others.

    Safe to call from a scheduler tick or an admin endpoint. Performs no work
    of its own beyond orchestration; all storage effects live in the policies.
    """
    reg = registry or default_registry
    reports: List[GcReport] = []

    for policy in reg.policies():
        name = policy.name
        if only is not None and name not in only:
            continue
        try:
            candidates = list(policy.enumerate_expirable())
        except Exception:
            logger.exception("GC enumerate failed for store %s", name)
            reports.append(GcReport(store=name, note="enumerate failed"))
            continue

        to_decay = []
        kept = 0
        for item in candidates:
            # The store may already mark some items durable; enumerate_expirable
            # is expected to exclude those, but we re-check defensively.
            if policy.is_durable(item):
                kept += 1
                continue
            if should_keep(item, store=name):
                kept += 1
                continue
            to_decay.append(item)

        try:
            report = policy.expire(to_decay)
        except Exception:
            logger.exception("GC expire failed for store %s", name)
            reports.append(
                GcReport(store=name, considered=len(candidates), note="expire failed")
            )
            continue

        # The policy reports what it expired; fold in what the judge kept and
        # the full candidate count so the caller sees the whole pass.
        report.considered = max(report.considered, len(candidates))
        report.kept = kept
        reports.append(report)
        logger.info(
            "GC %s: considered=%d expired=%d kept=%d dry_run=%s",
            name,
            report.considered,
            report.expired,
            report.kept,
            report.dry_run,
        )

    return reports
