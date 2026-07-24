"""
S2S org provisioning — POST /api/orgs/provision.

Lets trusted sibling services (GovKit's accept flow, earnkit's add-team
playbook) create/update an organization and its members in amebo's registry
tables (organizations, platform_users, org_members, member_tool_accounts).
Members arrive identified by email and/or lt_sub (LinkedTrust OIDC subject),
never by user_id; resolution happens in src/services/org_provisioning.py.

Auth: a static service token from env AMEBO_S2S_TOKEN, compared constant-time.
This is deliberately NOT get_current_user / user-session JWTs — no human is in
the loop. The global auth gate (middleware/auth_gate.py) passes this exact
path through because the endpoint self-gates on the token:
  - 403 if the server has no AMEBO_S2S_TOKEN configured (fails closed);
  - 401 for a missing or wrong bearer.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from src.services.org_provisioning import provision_org_s2s
from src.services.team_stack_runner import sync_members, trigger_add_team

router = APIRouter()
logger = logging.getLogger(__name__)


def require_s2s_token(authorization: Optional[str] = Header(None)) -> None:
    """Gate on the static service token (env AMEBO_S2S_TOKEN), constant-time."""
    configured = os.environ.get("AMEBO_S2S_TOKEN") or ""
    if not configured:
        # Fail closed and say why: the operator has not enabled S2S provisioning.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="S2S provisioning is disabled: AMEBO_S2S_TOKEN is not "
                   "configured on this server.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer service token.",
        )
    presented = authorization[len("Bearer "):].strip()
    if not hmac.compare_digest(presented.encode(), configured.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token.",
        )


class ToolAccountIn(BaseModel):
    tool_key: str = Field(..., min_length=1)   # e.g. 'govkit'
    external_id: str = Field(..., min_length=1)
    username: Optional[str] = None


class MemberIn(BaseModel):
    email: Optional[str] = None
    lt_sub: Optional[str] = None               # LinkedTrust OIDC subject
    display_name: Optional[str] = None
    role: Literal["member", "admin"] = "member"
    tool_accounts: List[ToolAccountIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _needs_identifier(self):
        if not ((self.email or "").strip() or (self.lt_sub or "").strip()):
            raise ValueError("member needs at least one of email, lt_sub")
        return self


class ProvisionRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: Optional[str] = None                 # required when the org doesn't exist yet
    source: Optional[str] = None               # provenance, e.g. 'govkit-accept'
    members: List[MemberIn] = Field(default_factory=list)


class MemberOut(BaseModel):
    user_id: int
    created: bool


class ProvisionResponse(BaseModel):
    org_id: int
    created: bool
    members: List[MemberOut]


@router.post("/provision", response_model=ProvisionResponse)
async def provision(
    request: ProvisionRequest,
    background_tasks: BackgroundTasks,
    _token: None = Depends(require_s2s_token),
) -> ProvisionResponse:
    """Create/update an org and its members. Idempotent — re-POSTing the same
    body changes nothing and reports created=false throughout."""
    try:
        result = provision_org_s2s(
            request.slug,
            name=request.name,
            source=request.source,
            members=[m.model_dump() for m in request.members],
        )
    except ValueError as exc:
        # e.g. new org without a name — caller error, same class as validation.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except RuntimeError as exc:
        # Server-side precondition (LEGACY_ENV_ORG_ID pin) — not a caller error.
        logger.error("S2S provision unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    # A BRAND-NEW org arriving from a GovKit accept is a founder's venture: GovKit
    # created its own org at accept, and the rest of the team stack (Odoo DB, Taiga
    # project, instance row, Caddy route) comes from earnkit add-team — which the
    # earnkit runner executes on this VM. Only on created=True (idempotent re-posts
    # and add-team's own self-registration report created=False and never re-fire).
    # After the response, never blocking it; trigger_add_team never raises.
    if result["created"] and request.source == "govkit-accept":
        background_tasks.add_task(
            trigger_add_team, request.slug, request.name or request.slug)
    elif result["members"] and request.source != "add-team":
        # An invite accept into an ALREADY-EXISTING org: reconcile that org's
        # Odoo CRM + Taiga membership NOW instead of waiting up to 5 min for the
        # earnkit-sync-members timer. Fire-and-forget after the response;
        # sync_members never raises, and the timer is the safety net if the
        # runner is down. Deliberately NOT the founder-bootstrap path above
        # (add-team already runs a full member sync as part of its playbook) nor
        # add-team's own self-registration POST (same reason) — those would only
        # queue a redundant sync.
        background_tasks.add_task(sync_members, request.slug)
    return ProvisionResponse(**result)
