"""
Coding orchestrator: the seam between conversation threads and coding workers.

Mirrors what `src/channels/dispatch.py` does for question-answering, but routes
to a coding worker instead. It is a separate entry point and is NOT wired into
the live dispatch path.

Flow:
  submit()   -> resolve intention thread, get/create its coding session (model
                chosen at creation), enqueue a job on the session's serial queue.
  run_next() -> claim the next runnable job (Postgres enforces one-per-session,
                in order), run the worker, persist the result, and return an
                OutboundAction the caller can deliver through any channel.
"""

import logging
from typing import Dict, List, Optional

from src.channels.contract import OutboundAction, ActionKind
from src.coding.model_router import choose_model
from src.coding.worker import CodingWorker, StubCodingWorker
from src.db.repositories.coding_job_repo import CodingJobRepo
from src.db.repositories.coding_session_repo import CodingSessionRepo
from src.db.repositories.thread_repo import ThreadRepo

logger = logging.getLogger(__name__)


class CodingOrchestrator:

    def __init__(
        self,
        worker: Optional[CodingWorker] = None,
        thread_repo: Optional[ThreadRepo] = None,
        session_repo: Optional[CodingSessionRepo] = None,
        job_repo: Optional[CodingJobRepo] = None,
    ):
        self.worker = worker or StubCodingWorker()
        self.threads = thread_repo or ThreadRepo()
        self.sessions = session_repo or CodingSessionRepo()
        self.jobs = job_repo or CodingJobRepo()

    # -- intake -------------------------------------------------------------

    def submit(
        self,
        source_type: str,
        source_ref: str,
        prompt: str,
        workspace_id: Optional[str] = None,
        instance_id: Optional[int] = None,
        model_hint: Optional[str] = None,
        payload: Optional[Dict] = None,
    ) -> Dict:
        """
        Resolve the intention thread, ensure it has a coding session, and enqueue
        a job. The model is chosen only when the session is first created.
        Returns {'thread', 'session', 'job'}.
        """
        thread = self.threads.get_or_create_thread(
            source_type=source_type, source_ref=source_ref,
            workspace_id=workspace_id, instance_id=instance_id,
        )
        session = self.sessions.get_by_thread(thread["id"])
        if session is None:
            model = choose_model(prompt, hint=model_hint)
            session = self.sessions.get_or_create_session(
                thread_id=thread["id"], model=model, instance_id=instance_id,
            )

        # Carry enough channel context to route the reply back later.
        job_payload = dict(payload or {})
        job_payload.setdefault("source_type", source_type)
        job_payload.setdefault("source_ref", source_ref)

        job = self.jobs.enqueue(session["id"], prompt, payload=job_payload)
        return {"thread": thread, "session": session, "job": job}

    def submit_envelope(self, envelope, model_hint: Optional[str] = None) -> Dict:
        """Convenience intake from a channel `InboundEnvelope`."""
        return self.submit(
            source_type=envelope.source_type,
            source_ref=envelope.source_ref,
            prompt=envelope.text,
            workspace_id=getattr(envelope, "workspace_id", None),
            model_hint=model_hint,
            payload={"author": envelope.author_info},
        )

    # -- execution ----------------------------------------------------------

    def run_next(self) -> Optional[OutboundAction]:
        """
        Claim and run the next runnable job. Returns an OutboundAction with the
        result (or an error message), or None if nothing is runnable.
        """
        job = self.jobs.claim_next()
        if job is None:
            return None

        session = self.sessions.get_session(job["session_id"])
        thread_ref = (job.get("payload") or {}).get("source_ref")

        try:
            result = self.worker.run(session, job["prompt"])
            if result.sdk_session_id and not session.get("sdk_session_id"):
                self.sessions.attach_sdk_session(session["id"], result.sdk_session_id)
            self.jobs.complete(job["id"], result.text)
            self.sessions.set_status(session["id"], "idle")
            return OutboundAction(kind=ActionKind.REPLY, text=result.text, thread_ref=thread_ref)
        except Exception as e:  # worker failure is contained to this job
            logger.error("Coding job %s failed: %s", job["id"], e, exc_info=True)
            self.jobs.fail(job["id"], str(e))
            return OutboundAction(
                kind=ActionKind.REPLY,
                text=f"Coding task failed: {e}",
                thread_ref=thread_ref,
            )

    def drain(self, max_jobs: int = 100) -> List[OutboundAction]:
        """Run jobs until the queue has nothing runnable (or max_jobs reached)."""
        actions: List[OutboundAction] = []
        for _ in range(max_jobs):
            action = self.run_next()
            if action is None:
                break
            actions.append(action)
        return actions
