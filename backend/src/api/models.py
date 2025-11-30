"""
Pydantic models for request/response validation
"""

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime


# ============================================================================
# AUTHENTICATION MODELS
# ============================================================================

class UserSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=255)
    org_name: str = Field(..., min_length=2, max_length=255)
    org_slug: Optional[str] = None

    @validator('password')
    def password_strength(cls, v):
        """Validate password strength"""
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600  # seconds


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    user_id: int
    org_id: int
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# ORGANIZATION MODELS
# ============================================================================

class OrganizationResponse(BaseModel):
    org_id: int
    org_name: str
    org_slug: str
    subscription_plan: str
    subscription_status: str
    max_workspaces: int
    max_users: int
    max_documents: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class OrganizationUpdateRequest(BaseModel):
    org_name: Optional[str] = None
    email_domain: Optional[str] = None


class InviteUserRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class InviteUserResponse(BaseModel):
    success: bool
    message: str
    user_id: int


class TeamMember(BaseModel):
    user_id: int
    name: str
    email: str
    role: str
    status: str  # 'active', 'pending', 'inactive'
    last_active: Optional[str] = None
    invited_at: str


# ============================================================================
# DOCUMENT MODELS
# ============================================================================

class DocumentUploadResponse(BaseModel):
    document_id: int
    title: str
    file_name: str
    file_type: str
    file_size_bytes: int
    chunk_count: int
    created_at: datetime


class DocumentResponse(BaseModel):
    document_id: int
    org_id: int
    workspace_id: Optional[str]
    title: str
    file_name: str
    file_type: str
    file_size_bytes: int
    chunk_count: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int
    page_size: int


# ============================================================================
# Q&A MODELS
# ============================================================================

class QARequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    workspace_id: Optional[str] = None
    channel_filter: Optional[str] = None
    days_back: Optional[int] = Field(default=30, ge=1, le=365)
    include_documents: bool = True
    include_slack: bool = True
    max_sources: int = Field(default=10, ge=1, le=50)


class QASource(BaseModel):
    source_type: str  # 'slack_message' or 'document'
    text: str
    metadata: dict
    relevance_score: Optional[float] = None


class QAResponse(BaseModel):
    answer: str
    confidence: int  # 0-100 percentage
    confidence_explanation: Optional[str] = None
    project_links: Optional[List[dict]] = []
    sources: List[QASource]
    question: str
    processing_time_ms: Optional[float] = None


# ============================================================================
# SLACK INTEGRATION MODELS
# ============================================================================

class SlackOAuthStartResponse(BaseModel):
    authorization_url: str
    state: str


class SlackWorkspaceResponse(BaseModel):
    workspace_id: str
    team_name: str
    team_domain: Optional[str]
    icon_url: Optional[str]
    is_active: bool
    installed_at: datetime
    last_active: Optional[datetime]


class SlackWorkspaceListResponse(BaseModel):
    workspaces: List[SlackWorkspaceResponse]
    total: int


# ============================================================================
# USAGE & ANALYTICS MODELS
# ============================================================================

class UsageMetrics(BaseModel):
    queries_count: int
    documents_count: int
    messages_count: int
    api_calls_count: int
    period_start: datetime
    period_end: datetime


class DashboardStats(BaseModel):
    total_workspaces: int
    total_documents: int
    total_messages: int
    total_queries_this_month: int
    most_active_channel: Optional[str] = None
    most_queried_topic: Optional[str] = None


# ============================================================================
# ERROR MODELS
# ============================================================================

class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[dict] = None
