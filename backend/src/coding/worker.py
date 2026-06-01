"""
Coding worker: the thing that actually runs the coding loop for one job.

The orchestrator is deliberately decoupled from the worker via this interface so
the whole spine (thread -> session -> serialized queue -> dispatch) can be built
and tested now with a stub, and the real Claude Agent SDK worker can be dropped
in without touching callers.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkerResult:
    text: str                              # human-facing result to send back
    sdk_session_id: Optional[str] = None   # SDK session id to persist for resume
    model: Optional[str] = None            # model actually used


class CodingWorker(ABC):
    """Runs one job against a coding session and returns a result."""

    @abstractmethod
    def run(self, session: Dict, prompt: str) -> WorkerResult:
        """
        session: a coding_sessions row (dict). Carries model, sdk_session_id
                 (None on first run), worktree_path, repo_url.
        prompt:  the instruction to act on.
        """
        raise NotImplementedError


class StubCodingWorker(CodingWorker):
    """
    Deterministic no-op worker for exercising the orchestration without the SDK.
    Does not write files or call any model. Echoes a structured acknowledgement
    and a stable fake session id derived from the coding session.
    """

    def run(self, session: Dict, prompt: str) -> WorkerResult:
        sid = session.get("sdk_session_id") or f"stub-{session['id']}"
        logger.info("StubCodingWorker handling session=%s model=%s", session["id"], session.get("model"))
        text = (
            f"[stub] would run on {session.get('model')}: {prompt.strip()[:200]}"
        )
        return WorkerResult(text=text, sdk_session_id=sid, model=session.get("model"))


class AgentSdkCodingWorker(CodingWorker):
    """
    Real worker backed by the Claude Agent SDK. Not wired yet.

    Remaining wiring (kept explicit rather than faked):
    - Auth: API key today; subscription Agent SDK credits via `claude setup-token`
      (CLAUDE_CODE_OAUTH_TOKEN) from 2026-06-15.
    - On first run: start a session and capture its sdk_session_id; on later runs
      resume that id so the thread's shared memory carries forward.
    - Run inside the session's isolated git worktree.
    - Stream/collect the final result for the reply.
    """

    def run(self, session: Dict, prompt: str) -> WorkerResult:
        raise NotImplementedError(
            "AgentSdkCodingWorker is not wired yet. Use StubCodingWorker until the "
            "Agent SDK auth + session/worktree run are implemented."
        )
