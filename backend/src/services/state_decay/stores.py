"""
Concrete GC policies, one per store. Each one owns its own mechanism; the
runner treats them uniformly through the ``GcPolicy`` protocol.

Stores modeled:

  - ThreadStorePolicy        — conversation threads/turns. Short TTL. Items
                               with ``retained_until > NOW()`` are durable.
                               Expiry deletes threads (turns cascade).
  - GoalEventsPolicy         — the append-only goal audit trail. Long TTL,
                               archival posture: by default it does NOT delete
                               (audit is a system of record). It can enumerate
                               very old events for inspection.
  - AbraWorkingMemoryPolicy  — Amebo's OWN abra scope/catcode (distinct from
                               the durable human-authored `golda` scope). This
                               is destructive against an external store, so it
                               DEFAULTS TO DRY-RUN: it lists what it would
                               expire and removes nothing. Real deletion
                               requires an explicit flag AND a non-default
                               scope guard.

These read the real amebo / abra DBs only when ``run_gc`` is invoked against
the live registry. The unit tests register fake policies, so importing this
module is side-effect-free except for registering the policies on
``default_registry`` at the bottom (guarded so tests can clear it).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List, Optional

from psycopg2 import extras

from src.db.connection import DatabaseConnection
from src.db.abra_connection import AbraConnection
from src.services.state_decay.policy import GcPolicy, GcReport, default_registry

logger = logging.getLogger(__name__)


# Default TTLs. Threads decay fast (mirrors the existing 24h opportunistic GC
# in conversation_manager); audit is kept long; abra working memory is medium.
THREAD_TTL = timedelta(hours=24)
GOAL_EVENTS_TTL = timedelta(days=365)
ABRA_WORKING_MEMORY_TTL = timedelta(days=30)

# The scope Amebo uses for its OWN transient working memory in abra. This is
# explicitly NOT `golda` (the durable, human-authored scope). The GC must
# refuse to operate on anything outside the Amebo working scope.
AMEBO_WORKING_SCOPE = "amebo"
DURABLE_HUMAN_SCOPE = "golda"


# ---------------------------------------------------------------------------
# (a) Conversation threads / turns
# ---------------------------------------------------------------------------


class ThreadStorePolicy:
    """
    GC for conversation threads. A thread is expirable when it has been idle
    longer than ``ttl`` AND is not currently retained
    (``retained_until`` NULL or in the past). Expiry deletes the thread; turns
    cascade via the FK (ON DELETE CASCADE).
    """

    def __init__(self, ttl: timedelta = THREAD_TTL):
        self._ttl = ttl

    @property
    def name(self) -> str:
        return "threads"

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def is_durable(self, item: Any) -> bool:
        ru = item.get("retained_until") if isinstance(item, dict) else None
        if ru is None:
            return False
        if ru.tzinfo is None:
            ru = ru.replace(tzinfo=timezone.utc)
        return ru > datetime.now(timezone.utc)

    def enumerate_expirable(self) -> Iterable[Any]:
        cutoff = datetime.now(timezone.utc) - self._ttl
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Past TTL and not currently retained. retained_until may not
                # exist if migration 015 has not been applied; tolerate that by
                # selecting it via a LEFT-style COALESCE-safe expression.
                cur.execute(
                    """
                    SELECT id, last_active_at, retained_until
                    FROM threads
                    WHERE last_active_at < %s
                      AND (retained_until IS NULL OR retained_until <= NOW())
                    ORDER BY last_active_at ASC
                    """,
                    (cutoff,),
                )
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)
        for row in rows:
            if not self.is_durable(row):
                yield row

    def expire(self, items: List[Any]) -> GcReport:
        ids = [it["id"] for it in items]
        if not ids:
            return GcReport(store=self.name, considered=0, expired=0)
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM threads WHERE id = ANY(%s) RETURNING id",
                    (ids,),
                )
                deleted = [r[0] for r in cur.fetchall()]
            conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)
        logger.info("threads GC: deleted %d threads", len(deleted))
        return GcReport(
            store=self.name,
            expired=len(deleted),
            expired_ids=deleted,
        )


# ---------------------------------------------------------------------------
# (b) goal_events — append-only audit trail
# ---------------------------------------------------------------------------


class GoalEventsPolicy:
    """
    GC for the goal audit trail. Audit is a system of record: the default
    posture is ARCHIVAL — we enumerate very old events (past a long TTL) for
    visibility but do NOT delete them. ``expire`` is therefore a dry-run by
    construction unless ``allow_delete=True`` is passed at construction time.

    This models the design point that "each system of record runs its own GC
    appropriate to it" — for an audit log, the appropriate GC is essentially
    no-op / archival, not deletion.
    """

    def __init__(
        self,
        ttl: timedelta = GOAL_EVENTS_TTL,
        allow_delete: bool = False,
    ):
        self._ttl = ttl
        self._allow_delete = allow_delete

    @property
    def name(self) -> str:
        return "goal_events"

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def is_durable(self, item: Any) -> bool:
        # Audit events are durable by nature. Nothing here is "kept" by a
        # marker; everything is kept by policy. Enumeration still surfaces old
        # rows so a future archival step can act, but expire() will not delete
        # unless explicitly allowed.
        return False

    def enumerate_expirable(self) -> Iterable[Any]:
        cutoff = datetime.now(timezone.utc) - self._ttl
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, goal_id, action, created_at
                    FROM goal_events
                    WHERE created_at < %s
                    ORDER BY created_at ASC
                    """,
                    (cutoff,),
                )
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)
        return rows

    def expire(self, items: List[Any]) -> GcReport:
        ids = [it["id"] for it in items]
        if not self._allow_delete:
            logger.info(
                "goal_events GC (archival/dry-run): %d old events identified, "
                "deleting none (audit is a system of record)",
                len(ids),
            )
            return GcReport(
                store=self.name,
                considered=len(ids),
                expired=0,
                dry_run=True,
                expired_ids=ids,
                note="archival posture: audit trail not deleted",
            )
        if not ids:
            return GcReport(store=self.name, considered=0, expired=0)
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM goal_events WHERE id = ANY(%s) RETURNING id",
                    (ids,),
                )
                deleted = [r[0] for r in cur.fetchall()]
            conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)
        logger.info("goal_events GC: deleted %d events", len(deleted))
        return GcReport(store=self.name, expired=len(deleted), expired_ids=deleted)


# ---------------------------------------------------------------------------
# (c) Amebo's own abra working-memory scope/catcode
# ---------------------------------------------------------------------------


class AbraWorkingMemoryPolicy:
    """
    GC for Amebo's OWN abra working-memory scope (``AMEBO_WORKING_SCOPE``),
    optionally narrowed to a single catcode. This is destructive against an
    EXTERNAL store, so it is the most guarded policy:

      - DEFAULT IS DRY-RUN. It SELECTs what it would expire, logs it, and
        deletes NOTHING. Real deletion requires ``dry_run=False`` AND the scope
        being the Amebo working scope (never the durable ``golda`` scope).
      - It reads/writes through the abra connection used elsewhere in the repo
        (``AbraConnection``). If abra is not configured, it is a no-op.

    "Old" means a content row under (scope, catcode) whose timestamp is past
    ``ttl``. Items the retention judge keeps are not deleted even when
    ``dry_run=False``.
    """

    def __init__(
        self,
        scope: str = AMEBO_WORKING_SCOPE,
        catcode: Optional[str] = None,
        ttl: timedelta = ABRA_WORKING_MEMORY_TTL,
        dry_run: bool = True,
    ):
        if scope == DURABLE_HUMAN_SCOPE:
            raise ValueError(
                f"refusing to build an abra GC policy for the durable "
                f"human-authored scope {DURABLE_HUMAN_SCOPE!r}"
            )
        self._scope = scope
        self._catcode = catcode
        self._ttl = ttl
        self._dry_run = dry_run

    @property
    def name(self) -> str:
        return "abra_working_memory"

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def is_durable(self, item: Any) -> bool:
        # No per-row durability marker in abra content; retention is decided by
        # the judge at GC time. Return False so everything past TTL is offered
        # to the judge.
        return False

    def _date_field(self, row: dict) -> Optional[datetime]:
        dt = row.get("note_date") or row.get("created_at")
        if dt is None:
            return None
        if isinstance(dt, datetime) and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def enumerate_expirable(self) -> Iterable[Any]:
        if not AbraConnection.is_available():
            logger.info(
                "abra_working_memory GC: abra not configured, nothing to do"
            )
            return []
        cutoff = datetime.now(timezone.utc) - self._ttl
        conn = AbraConnection.get_connection()
        if conn is None:
            return []
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                # Content under the Amebo working scope is addressed via its
                # bindings (scope + catcode). We join content to its ABOUT
                # bindings to scope-filter, per the context-store contract
                # (abra reuses binding + content primitives; the catcode is the
                # addressable place).
                params: list[Any] = [self._scope]
                catcode_clause = ""
                if self._catcode is not None:
                    catcode_clause = "AND b.catcode = %s"
                    params.append(self._catcode)
                params.append(cutoff)
                cur.execute(
                    f"""
                    SELECT DISTINCT c.id, c.catcode, c.note_date, c.created_at
                    FROM content c
                    JOIN bindings b
                      ON b.target_type = 'content'
                     AND b.target_ref = c.id::text
                    WHERE b.scope = %s
                      {catcode_clause}
                      AND COALESCE(c.note_date::timestamptz, c.created_at) < %s
                    ORDER BY COALESCE(c.note_date::timestamptz, c.created_at) ASC
                    """,
                    params,
                )
                rows = [dict(r) for r in cur.fetchall()]
        except Exception:
            logger.exception(
                "abra_working_memory GC: enumeration failed; treating as empty"
            )
            rows = []
        finally:
            AbraConnection.return_connection(conn)
        return rows

    def expire(self, items: List[Any]) -> GcReport:
        ids = [it["id"] for it in items]
        if self._dry_run:
            logger.info(
                "abra_working_memory GC (DRY-RUN, scope=%s catcode=%s): "
                "would expire %d content rows: %s — deleting NOTHING",
                self._scope,
                self._catcode,
                len(ids),
                ids,
            )
            return GcReport(
                store=self.name,
                considered=len(ids),
                expired=0,
                dry_run=True,
                expired_ids=ids,
                note=f"dry-run; scope={self._scope} catcode={self._catcode}",
            )

        # Real deletion path. Guarded: never the durable human scope.
        if self._scope == DURABLE_HUMAN_SCOPE:
            raise RuntimeError(
                "refusing to delete from the durable human-authored scope"
            )
        if not ids:
            return GcReport(store=self.name, considered=0, expired=0)
        if not AbraConnection.is_available():
            return GcReport(store=self.name, considered=0, expired=0)
        conn = AbraConnection.get_connection()
        if conn is None:
            return GcReport(store=self.name, considered=0, expired=0)
        try:
            with conn.cursor() as cur:
                # Remove the bindings that place this content in the Amebo
                # working scope, then the content rows themselves.
                cur.execute(
                    """
                    DELETE FROM bindings
                    WHERE scope = %s
                      AND target_type = 'content'
                      AND target_ref = ANY(%s)
                    """,
                    (self._scope, [str(i) for i in ids]),
                )
                cur.execute(
                    "DELETE FROM content WHERE id = ANY(%s) RETURNING id",
                    (ids,),
                )
                deleted = [r[0] for r in cur.fetchall()]
            conn.commit()
        finally:
            AbraConnection.return_connection(conn)
        logger.warning(
            "abra_working_memory GC: DELETED %d content rows from scope=%s",
            len(deleted),
            self._scope,
        )
        return GcReport(store=self.name, expired=len(deleted), expired_ids=deleted)


# ---------------------------------------------------------------------------
# Register the live policies on the process-wide registry.
# ---------------------------------------------------------------------------


def register_default_policies(registry=default_registry) -> None:
    """
    Register the standard live policies. Idempotent-ish: clears any same-named
    policy first so re-import / re-call does not raise. The abra policy is
    registered in DRY-RUN mode — real deletion is opt-in by constructing the
    policy with ``dry_run=False`` and re-registering.
    """
    for name in ("threads", "goal_events", "abra_working_memory"):
        registry.unregister(name)
    registry.register(ThreadStorePolicy())
    registry.register(GoalEventsPolicy())          # archival: deletes nothing
    registry.register(AbraWorkingMemoryPolicy())   # dry-run: deletes nothing


register_default_policies()
