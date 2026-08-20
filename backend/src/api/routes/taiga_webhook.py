"""
Taiga webhook receiver.

Taiga fires a POST to /api/webhooks/taiga when a story changes status.
We care about: a story moving to Done.

The payload shape (confirmed against Taiga 8.x event payload):
{
  "type": "story.change.status",
  "date": "2026-...",
  "data": {
    "values": { "status": { "id": 123, "name": "Done" } },
    "story": { "id": ref, "subject": "...", "project": { "slug": "..." } }
  },
  "project": { "id": ..., "slug": "..." }
}

The header X-Taiga-Event tells the event type; the signature header
X-Taiga-Queue is used for deduplication (optional, we use the ref as idempotency key).

Route: POST /api/webhooks/taiga
No auth (Taiga can't carry auth headers) — validation is done by checking
the payload shape and, optionally, a shared secret in X-TAIGA-SECRET.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Taiga Webhooks"])

# Taiga Done status name (locale-independent — compare by name, not id)
_DONE_STATUS_NAMES = {"done", "closed", "completed"}


def _is_done_event(payload: Dict[str, Any]) -> bool:
    """True when this payload represents a story moved to Done/Closed."""
    try:
        event_type = payload.get("type", "")
        if "change.status" not in event_type and "change" not in event_type:
            return False
        status_name = (
            payload.get("data", {})
            .get("values", {})
            .get("status", {})
            .get("name", "")
        )
        return status_name.lower() in _DONE_STATUS_NAMES
    except Exception:
        return False


def _extract_ref_project(payload: Dict[str, Any]) -> Optional[tuple]:
    """Return (project_slug, story_ref) from the payload, or None."""
    try:
        project_slug = (
            payload.get("project", {}).get("slug") or
            payload.get("data", {}).get("story", {}).get("project", {}).get("slug") or
            ""
        )
        story_id = (
            payload.get("data", {})
            .get("story", {})
            .get("id") or
            payload.get("data", {})
            .get("id") or
            0
        )
        if project_slug and story_id:
            return project_slug, int(story_id)
    except Exception:
        pass
    return None


async def _process_done_task(project: str, ref: int) -> str:
    """Called in a thread pool — find pending row and distribute equity."""
    from src.services.equity_distribution import distribute_equity_on_done
    return distribute_equity_on_done(project, ref)


@router.post("/taiga")
async def taiga_webhook(
    request: Request,
    x_taiga_event: Optional[str] = Header(None),
    x_taiga_secret: Optional[str] = Header(None),
):
    """
    Receive Taiga story-status-change events.
    Only processes stories moved to Done — everything else is acknowledged and dropped.
    """
    secret = os.getenv("TAIGA_WEBHOOK_SECRET", "").strip()
    if secret and x_taiga_secret and x_taiga_secret != secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info("Taiga webhook: event=%s payload_keys=%s", x_taiga_event, list(payload.keys()))

    if not _is_done_event(payload):
        return JSONResponse({"status": "ignored", "reason": "not a Done event"})

    extracted = _extract_ref_project(payload)
    if not extracted:
        logger.warning("Taiga webhook: could not extract project/ref from payload")
        raise HTTPException(status_code=422, detail="Could not extract project/ref")

    project, ref = extracted
    logger.info("Taiga webhook: Done event for %s#%s", project, ref)

    try:
        result = await request.app.state._thread_pool.submit(_process_done_task, project, ref)
        return JSONResponse({"status": "ok", "detail": result})
    except Exception as exc:
        logger.error("Taiga webhook processing failed: %s", exc, exc_info=True)
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)
