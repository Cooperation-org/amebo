"""
Web chat API — source-agnostic conversation endpoint.

This is the Claude Code-pattern interface: send a message, get back a response.
The agentic loop (tool calls, knowledge search) happens server-side.
Thread context is maintained by ConversationManager.
"""

import logging
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from src.services.qa_service import QAService
from src.db.repositories.instance_repo import InstanceRepo

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    instance_slug: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    confidence: int = 50
    tool_rounds: int = 0


@router.post("/message", response_model=ChatResponse)
async def chat_message(req: ChatRequest):
    """
    Send a message to an amebo instance and get a response.

    - message: the user's message
    - session_id: reuse to maintain conversation context (like a Slack thread)
    - instance_slug: which instance to talk to (determines identity, tools, knowledge)
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Generate session_id if not provided (first message in a conversation)
    session_id = req.session_id or str(uuid.uuid4())

    # Resolve instance
    instance = None
    instance_repo = InstanceRepo()
    if req.instance_slug:
        instance = instance_repo.get_by_slug(req.instance_slug)
        if not instance:
            raise HTTPException(status_code=404, detail=f"Instance '{req.instance_slug}' not found")

    # Get workspace_id from instance org, or use a synthetic one for web
    workspace_id = f"web-{instance['slug']}" if instance else "web-default"

    # Use QA service with thread context (agentic path)
    qa_service = QAService(
        workspace_id=workspace_id,
        org_id=instance.get('org_id') if instance else None
    )

    result = qa_service.answer_question(
        question=req.message,
        thread_ref=session_id,
        source_type="web",
        author_info=None
    )

    return ChatResponse(
        reply=result.get('answer', 'Sorry, I could not generate a response.'),
        session_id=session_id,
        confidence=result.get('confidence', 50),
        tool_rounds=result.get('context_used', 0)
    )


@router.get("/instances/{slug}")
async def get_instance_info(slug: str):
    """Get public info about an instance (for the chat UI header)."""
    instance_repo = InstanceRepo()
    instance = instance_repo.get_by_slug(slug)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance '{slug}' not found")

    return {
        "name": instance['name'],
        "slug": instance['slug'],
    }


class DocUploadRequest(BaseModel):
    instance_slug: str
    title: str
    content: str


@router.post("/documents")
async def upload_document(req: DocUploadRequest):
    """
    Add a document to an instance's knowledge base.
    Generates embedding and stores in abra_content with the instance's org_id.
    """
    instance_repo = InstanceRepo()
    instance = instance_repo.get_by_slug(req.instance_slug)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance '{req.instance_slug}' not found")

    org_id = instance.get('org_id')
    if not org_id:
        raise HTTPException(status_code=400, detail="Instance has no org_id — cannot store documents")

    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    try:
        from src.db.embedding import embed_text
        from src.db.repositories.binding_repo import BindingRepo

        embedding = embed_text(req.content)
        repo = BindingRepo(org_id=org_id)
        content_id = repo.create_content(
            content=req.content,
            source_file=f"upload/{req.title}",
            embedding=embedding
        )

        logger.info(f"Document uploaded: '{req.title}' -> content_id={content_id} (org_id={org_id})")
        return {"status": "ok", "content_id": content_id, "title": req.title}

    except Exception as e:
        logger.error(f"Document upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
