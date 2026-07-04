"""
Web chat API — source-agnostic conversation endpoint.

This is the Claude Code-pattern interface: send a message, get back a response.
The agentic loop (tool calls, knowledge search) happens server-side.
Thread context is maintained by ConversationManager.
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

from src.services.qa_service import QAService
from src.db.repositories.instance_repo import InstanceRepo
from src.api.middleware.auth import get_service_client, get_current_user

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
async def chat_message(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Send a message to amebo and get a response.

    The instance (identity, tools, knowledge, and — once wired — the org's CRM/
    Taiga credentials) is resolved from the AUTHENTICATED user's org, never from a
    client-supplied value. So a logged-in (SSO) user always talks to their own
    org's amebo with their org's tools. One instance per org (get_by_org).
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Generate session_id if not provided (first message in a conversation)
    session_id = req.session_id or str(uuid.uuid4())

    # Resolve the instance from the verified SSO org — secure, not client-supplied.
    instance_repo = InstanceRepo()
    instance = instance_repo.get_by_org(current_user['org_id'])
    if not instance:
        raise HTTPException(
            status_code=404,
            detail="No amebo instance is configured for your organization yet."
        )

    workspace_id = f"web-{instance['slug']}"

    # Use QA service with thread context (agentic path)
    qa_service = QAService(
        workspace_id=workspace_id,
        org_id=instance.get('org_id')
    )

    result = qa_service.answer_question(
        question=req.message,
        thread_ref=session_id,
        source_type="web",
        author_info={
            "user_id": current_user.get("user_id"),
            "email": current_user.get("email"),
        },
        instance_slug=instance['slug']
    )

    return ChatResponse(
        reply=result.get('answer', 'Sorry, I could not generate a response.'),
        session_id=session_id,
        confidence=result.get('confidence', 50),
        tool_rounds=result.get('context_used', 0)
    )


class PublicChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    instance_slug: str          # which instance's knowledge to answer from


@router.post("/public", response_model=ChatResponse)
async def public_chat_message(req: PublicChatRequest):
    """
    Public, UNAUTHENTICATED chat for embedding in tools — the unknown user
    (arch §4.3 T0). Scoped to one instance by slug.

    It NEVER executes anything: the QA runs read-only (``allow_tools=False`` ->
    zero tools offered), so the model can only answer from the instance's
    assembled knowledge — no writes, nothing privileged, no server-side actions.
    A T0 principal is passed as an independent second guard: even if a tool were
    ever offered here, the trust gate would refuse every write-class call.
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    instance_repo = InstanceRepo()
    instance = instance_repo.get_by_slug(req.instance_slug)
    if not instance:
        raise HTTPException(
            status_code=404, detail=f"Instance '{req.instance_slug}' not found"
        )

    session_id = req.session_id or str(uuid.uuid4())
    workspace_id = f"web-{instance['slug']}"
    org_id = instance.get("org_id")

    from src.services.org_context import OrgContext, Venue
    from src.services.trust import Principal

    org_context = (
        OrgContext(
            org_id=org_id, instance_id=instance["id"],
            actor_type="user", actor_person_id=None, authority="service",
            venue=Venue(channel_kind="web", thread_ref=session_id),
        )
        if org_id is not None else None
    )
    principal = Principal(transport="web", person_id=None, authenticated=False)  # T0

    qa_service = QAService(
        workspace_id=workspace_id,
        org_id=org_id,
        org_context=org_context,
        principal=principal,
    )
    result = qa_service.answer_question(
        question=req.message,
        thread_ref=session_id,
        source_type="web",
        instance_slug=instance["slug"],
        allow_tools=False,           # structurally read-only — no tools offered
    )

    return ChatResponse(
        reply=result.get("answer", "Sorry, I could not generate a response."),
        session_id=session_id,
        confidence=result.get("confidence", 50),
        tool_rounds=result.get("context_used", 0),
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


# ---------------------------------------------------------------------------
# Instance management (service-to-service, API key required)
# ---------------------------------------------------------------------------

class CreateInstanceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)
    identity_prompt: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class UpdateInstanceRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    identity_prompt: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class InstanceResponse(BaseModel):
    id: int
    name: str
    slug: str
    org_id: Optional[int] = None
    identity_prompt: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


def _instance_to_response(instance: dict) -> InstanceResponse:
    """Convert a raw instance dict to an InstanceResponse."""
    return InstanceResponse(
        id=instance["id"],
        name=instance["name"],
        slug=instance["slug"],
        org_id=instance.get("org_id"),
        identity_prompt=instance.get("identity_prompt"),
        config=instance.get("config"),
        created_at=instance["created_at"],
        updated_at=instance["updated_at"],
    )


@router.post("/instances", response_model=InstanceResponse, status_code=201)
async def create_instance(
    req: CreateInstanceRequest,
    client: dict = Depends(get_service_client),
):
    """
    Create a new amebo instance (service-to-service, API key required).
    The org_id is taken from the authenticated API key, not the request body.
    """
    instance_repo = InstanceRepo()

    # Check slug uniqueness
    existing = instance_repo.get_by_slug(req.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Instance slug '{req.slug}' already exists")

    instance = instance_repo.create(
        name=req.name,
        slug=req.slug,
        identity_prompt=req.identity_prompt,
        config=req.config,
        org_id=client["org_id"],
    )

    logger.info(f"Instance created: slug={req.slug} org_id={client['org_id']} by key={client['key_name']}")
    return _instance_to_response(instance)


@router.patch("/instances/{slug}", response_model=InstanceResponse)
async def update_instance(
    slug: str,
    req: UpdateInstanceRequest,
    client: dict = Depends(get_service_client),
):
    """
    Update an existing amebo instance (service-to-service, API key required).
    Only updates fields that are explicitly provided.
    The instance must belong to the authenticated org.
    """
    instance_repo = InstanceRepo()

    # Verify the instance exists and belongs to this org
    instance = instance_repo.get_by_slug_and_org(slug, client["org_id"])
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance '{slug}' not found")

    # Build update kwargs from provided fields
    update_fields = {}
    if req.name is not None:
        update_fields["name"] = req.name
    if req.identity_prompt is not None:
        update_fields["identity_prompt"] = req.identity_prompt
    if req.config is not None:
        update_fields["config"] = req.config

    if not update_fields:
        return _instance_to_response(instance)

    updated = instance_repo.update(instance["id"], **update_fields)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update instance")

    logger.info(f"Instance updated: slug={slug} fields={list(update_fields.keys())} by key={client['key_name']}")
    return _instance_to_response(updated)
