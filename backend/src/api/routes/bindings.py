"""
Bindings API Routes
CRUD for structured knowledge (abra bindings, hot tags).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from typing import List, Optional
import logging

from src.api.middleware.auth import get_current_user
from src.db.repositories.binding_repo import BindingRepo

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Pydantic models ---

class BindingCreate(BaseModel):
    scope: str
    name: str
    relationship: str
    target_type: str
    target_ref: str
    qualifier: Optional[str] = None
    permanence: str = "CURRENT"
    workspace_id: Optional[str] = None
    catcode: Optional[str] = None


class BindingResponse(BaseModel):
    id: int
    scope: str
    name: str
    relationship: str
    target_type: str
    target_ref: str
    qualifier: Optional[str] = None
    permanence: Optional[str] = None
    source_date: Optional[str] = None


class HotTagCreate(BaseModel):
    scope: str
    name: str
    priority: int = 0
    expires_at: Optional[str] = None


class HotTagResponse(BaseModel):
    scope: str
    name: str
    priority: int
    added_at: Optional[str] = None
    expires_at: Optional[str] = None


# --- Binding endpoints ---

@router.get("/search")
async def search_bindings(
    name: str,
    scope: Optional[str] = None,
    workspace_id: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """Search bindings by name."""
    repo = BindingRepo(user["org_id"])
    results = repo.search_bindings_by_name(name, scope=scope, workspace_id=workspace_id)
    return {"bindings": results}


@router.get("/who")
async def who_knows(
    term: str,
    scope: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """Find people/names connected to a topic."""
    repo = BindingRepo(user["org_id"])
    results = repo.who(term, scope=scope)
    return {"results": results}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_binding(
    binding: BindingCreate,
    user: dict = Depends(get_current_user)
):
    """Create a new binding."""
    repo = BindingRepo(user["org_id"])
    try:
        binding_id = repo.create_binding(
            scope=binding.scope,
            name=binding.name,
            relationship=binding.relationship,
            target_type=binding.target_type,
            target_ref=binding.target_ref,
            qualifier=binding.qualifier,
            permanence=binding.permanence,
            workspace_id=binding.workspace_id,
            catcode=binding.catcode
        )
        return {"id": binding_id}
    except Exception as e:
        logger.error(f"Failed to create binding: {e}")
        raise HTTPException(status_code=500, detail="Failed to create binding")


@router.post("/batch", status_code=status.HTTP_201_CREATED)
async def create_bindings_batch(
    bindings: List[BindingCreate],
    user: dict = Depends(get_current_user)
):
    """Create multiple bindings at once."""
    repo = BindingRepo(user["org_id"])
    ids = []
    for b in bindings:
        try:
            binding_id = repo.create_binding(
                scope=b.scope,
                name=b.name,
                relationship=b.relationship,
                target_type=b.target_type,
                target_ref=b.target_ref,
                qualifier=b.qualifier,
                permanence=b.permanence,
                workspace_id=b.workspace_id,
                catcode=b.catcode
            )
            ids.append(binding_id)
        except Exception as e:
            logger.warning(f"Failed to create binding for {b.name}: {e}")
    return {"created": len(ids), "ids": ids}


# --- Hot tag endpoints ---

@router.get("/hot")
async def list_hot_tags(
    scope: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """List active hot tags."""
    repo = BindingRepo(user["org_id"])
    tags = repo.get_hot_tags(scope=scope)
    return {"hot_tags": tags}


@router.get("/hot/{name}")
async def check_hot(
    name: str,
    scope: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """Check if a name is hot."""
    repo = BindingRepo(user["org_id"])
    is_hot = repo.is_hot(name, scope=scope)
    return {"name": name, "is_hot": is_hot}


@router.post("/hot", status_code=status.HTTP_201_CREATED)
async def set_hot_tag(
    tag: HotTagCreate,
    user: dict = Depends(get_current_user)
):
    """Set a hot tag."""
    repo = BindingRepo(user["org_id"])
    try:
        repo.set_hot_tag(
            scope=tag.scope,
            name=tag.name,
            priority=tag.priority,
            expires_at=tag.expires_at
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to set hot tag: {e}")
        raise HTTPException(status_code=500, detail="Failed to set hot tag")


@router.delete("/hot/{scope}/{name}")
async def unset_hot_tag(
    scope: str,
    name: str,
    user: dict = Depends(get_current_user)
):
    """Remove a hot tag."""
    repo = BindingRepo(user["org_id"])
    try:
        repo.unset_hot_tag(scope, name)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to unset hot tag: {e}")
        raise HTTPException(status_code=500, detail="Failed to unset hot tag")
