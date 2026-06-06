"""
Goal scheduler — picks up goals whose triggers fire and hands them to the
dispatcher.

Thin by design:
- One periodic tick (default 60s).
- Per-instance opt-in via `instance.config.goal_mode == "enabled"`.
- No assumptions about trigger semantics beyond what `_should_fire` decides.
- All actual work happens in GoalDispatcher.

The existing TaskScheduler (APScheduler/backfill) is left untouched; this
runs as its own task because the goal lifecycle is independent of backfill
scheduling and lumping them together complicates failure isolation.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from apscheduler.triggers.cron import CronTrigger

from src.db.connection import DatabaseConnection
from src.db.repositories.goal_repo import GoalRepo
from src.services.goal_dispatcher import GoalDispatcher

logger = logging.getLogger(__name__)


DEFAULT_TICK_SECONDS = 60


class GoalScheduler:
    """
    Periodic ticker that activates goals whose trigger fires and dispatches
    them. Designed to be created at app startup and stopped at shutdown.
    """

    def __init__(
        self,
        dispatcher: Optional[GoalDispatcher] = None,
        goal_repo: Optional[GoalRepo] = None,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
    ):
        self._dispatcher = dispatcher or GoalDispatcher()
        self._goal_repo = goal_repo or GoalRepo()
        self._tick_seconds = tick_seconds
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

        # State-decay GC: register the standard per-store policies (threads,
        # goal_events, abra working memory) so run_gc() in tick() can decay
        # idle state (docs/STATE_DECAY_GC.md). register_default_policies is
        # idempotent. GC is throttled (see _gc_due) — it need not run every tick.
        self._last_gc: Optional[datetime] = None
        self._gc_interval = timedelta(hours=1)
        try:
            from src.services.state_decay.stores import register_default_policies
            register_default_policies()
        except Exception:
            logger.exception("state-decay policy registration failed")

    def _gc_due(self, now: datetime) -> bool:
        return self._last_gc is None or (now - self._last_gc) >= self._gc_interval

    # ---------------------------------------------------------------- Loop

    async def start(self):
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run())
        logger.info("GoalScheduler started (tick=%ss)", self._tick_seconds)

    async def stop(self):
        if self._task is None:
            return
        self._stopped.set()
        await self._task
        self._task = None
        logger.info("GoalScheduler stopped")

    async def _run(self):
        while not self._stopped.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("GoalScheduler tick failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._tick_seconds)
            except asyncio.TimeoutError:
                pass

    # --------------------------------------------------------------- Tick

    def tick(self, now: Optional[datetime] = None) -> int:
        """
        Run one scheduling pass. Returns the number of goals dispatched.

        Synchronous; safe to call from tests or via an admin API endpoint.

        Goals whose most-recent event is `blocked_on_credential:<kind>`
        are skipped until something writes a subsequent event (e.g. the
        OAuth callback or a manual unblock).
        """
        now = now or datetime.now(timezone.utc)
        dispatched = 0

        for org_id in self._enabled_org_ids():
            # Pending goals fire on their trigger. Active goals are normally
            # being worked on right now — but if they were blocked on a
            # credential and have since been unblocked (e.g. OAuth callback
            # appended an "unblocked" event), we want to resume them.
            pending = self._goal_repo.list_pending(org_id=org_id)
            active = self._goal_repo.list_for_org(org_id, status="active")

            for goal in pending + active:
                if goal["status"] == "pending" and not _should_fire(goal, now=now):
                    continue
                if self._is_blocked_on_credential(goal["id"]):
                    continue
                # For active goals we skip unless an unblock just landed:
                # otherwise we'd re-dispatch an in-progress goal every tick.
                if goal["status"] == "active" and not self._just_unblocked(goal["id"]):
                    continue
                try:
                    result = self._dispatcher.dispatch(goal["id"])
                except Exception:
                    logger.exception("Dispatch failed for goal %s", goal["id"])
                    continue
                if result.status in ("completed", "failed"):
                    dispatched += 1

        # State-decay GC pass (throttled; cheap, side-effect-isolated). Threads
        # decay past their idle TTL, goal_events archival/no-delete, abra
        # working memory dry-run. docs/STATE_DECAY_GC.md.
        if self._gc_due(now):
            self._last_gc = now
            try:
                from src.services.state_decay import run_gc
                run_gc()
            except Exception:
                logger.exception("state-decay GC pass failed")

        return dispatched

    def _just_unblocked(self, goal_id: str) -> bool:
        """
        Most recent event is `unblocked` (i.e. credential just landed) and
        no `blocked_on_credential:*` after it. Used to decide whether to
        re-dispatch an active goal.
        """
        events = self._goal_repo.list_events(goal_id, limit=20)
        if not events:
            return False
        for ev in reversed(events):
            action = ev.get("action") or ""
            if action == "unblocked":
                return True
            if action.startswith("blocked_on_credential:"):
                return False
        return False

    def _is_blocked_on_credential(self, goal_id: str) -> bool:
        """
        True iff the most recent event on this goal is a
        `blocked_on_credential:<kind>` and no later "unblocked" event
        has been written.
        """
        events = self._goal_repo.list_events(goal_id, limit=20)
        if not events:
            return False
        # Walk backwards through the most recent events
        for ev in reversed(events):
            action = ev.get("action") or ""
            if action == "unblocked":
                return False
            if action.startswith("blocked_on_credential:"):
                return True
        return False

    # ---------------------------------------------------------- Org lookup

    def _enabled_org_ids(self) -> List[int]:
        """
        Orgs whose first instance has goal_mode == 'enabled'. The 'first
        instance' rule mirrors the dispatcher's instance lookup — keep them
        in lockstep.
        """
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT org_id
                    FROM instances
                    WHERE org_id IS NOT NULL
                      AND config->>'goal_mode' = 'enabled'
                    """
                )
                return [row[0] for row in cur.fetchall()]
        finally:
            DatabaseConnection.return_connection(conn)


def _should_fire(goal: Dict[str, Any], now: datetime) -> bool:
    """
    Decide whether a pending goal should be dispatched at `now`.

    Trigger semantics:

        {"type": "manual"}                          — never auto-fire
        {"type": "cron", "expression": "*/5 * * * *"} — fires when cron is due
        {"type": "event", "event": "..."}          — handled by event system,
                                                      not the periodic ticker
        None / missing                              — fire immediately
    """
    cfg = goal.get("trigger_config") or None
    if not cfg:
        return True

    ttype = (cfg.get("type") or "").lower()
    if ttype == "manual":
        return False
    if ttype == "event":
        return False  # event-driven goals are dispatched elsewhere
    if ttype == "cron":
        expression = cfg.get("expression")
        if not expression:
            logger.warning("Goal %s has cron trigger with no expression", goal.get("id"))
            return False
        return _cron_is_due(expression, goal, now)

    # Unknown type: skip rather than fire — fail safe.
    logger.warning("Goal %s has unknown trigger type %r", goal.get("id"), ttype)
    return False


def _cron_is_due(expression: str, goal: Dict[str, Any], now: datetime) -> bool:
    """
    True if the next cron fire-time after the goal's last activity is at or
    before now. Uses the goal's updated_at as the watermark so re-runs
    after a failed/paused/completed transition wait for the next cron edge.

    Uses APScheduler's CronTrigger (already a dependency for the existing
    backfill scheduler) rather than introducing croniter as a new dep.
    """
    last_seen = goal.get("updated_at") or goal.get("created_at")
    if last_seen is None:
        return False

    try:
        trigger = CronTrigger.from_crontab(expression, timezone=timezone.utc)
    except Exception as exc:
        logger.warning("Invalid cron expression %r on goal %s: %s",
                       expression, goal.get("id"), exc)
        return False

    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    next_fire = trigger.get_next_fire_time(last_seen, last_seen)
    if next_fire is None:
        return False
    return next_fire <= now
