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
from datetime import datetime, timezone
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
        """
        now = now or datetime.now(timezone.utc)
        dispatched = 0

        for org_id in self._enabled_org_ids():
            goals = self._goal_repo.list_pending(org_id=org_id)
            for goal in goals:
                if not _should_fire(goal, now=now):
                    continue
                try:
                    result = self._dispatcher.dispatch(goal["id"])
                except Exception:
                    logger.exception("Dispatch failed for goal %s", goal["id"])
                    continue
                if result.status in ("completed", "failed"):
                    dispatched += 1

        return dispatched

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
