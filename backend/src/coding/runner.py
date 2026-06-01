"""
Coding worker loop.

Periodically drains the coding work queue and delivers each result. Mirrors the
GoalScheduler pattern (start/stop + an asyncio.Event tick loop) so it can be
created at app startup and stopped at shutdown, or driven a single tick at a
time from tests or an admin endpoint.

`tick()` is synchronous and side-effect-contained: it pulls runnable jobs from
the orchestrator (Postgres guarantees ordering and one-in-flight per session)
and hands each resulting OutboundAction to `deliver`. Delivery itself is
pluggable; until a coding route is wired to a channel adapter, the default just
logs.
"""

import asyncio
import logging
from typing import Callable, List, Optional

from src.channels.contract import OutboundAction
from src.coding.orchestrator import CodingOrchestrator

logger = logging.getLogger(__name__)

DEFAULT_TICK_SECONDS = 2
DEFAULT_BATCH = 25


def _log_deliver(action: OutboundAction) -> None:
    logger.info("Coding result (thread=%s): %s", action.thread_ref, action.text)


class CodingRunner:

    def __init__(
        self,
        orchestrator: Optional[CodingOrchestrator] = None,
        deliver: Optional[Callable[[OutboundAction], None]] = None,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
        batch: int = DEFAULT_BATCH,
    ):
        self._orchestrator = orchestrator or CodingOrchestrator()
        self._deliver = deliver or _log_deliver
        self._tick_seconds = tick_seconds
        self._batch = batch
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    # ---------------------------------------------------------------- Loop

    async def start(self):
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run())
        logger.info("CodingRunner started (tick=%ss)", self._tick_seconds)

    async def stop(self):
        if self._task is None:
            return
        self._stopped.set()
        await self._task
        self._task = None
        logger.info("CodingRunner stopped")

    async def _run(self):
        while not self._stopped.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("CodingRunner tick failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._tick_seconds)
            except asyncio.TimeoutError:
                pass

    # --------------------------------------------------------------- Tick

    def tick(self) -> int:
        """
        Run one drain pass. Returns the number of jobs processed and delivered.
        Synchronous; safe to call from tests or an admin endpoint.
        """
        actions: List[OutboundAction] = self._orchestrator.drain(max_jobs=self._batch)
        for action in actions:
            try:
                self._deliver(action)
            except Exception:
                logger.exception("CodingRunner delivery failed for thread=%s", action.thread_ref)
        return len(actions)
