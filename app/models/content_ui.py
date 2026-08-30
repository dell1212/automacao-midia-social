from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.models.content import ApprovalAction, ContentCategory, ContentPieceStatus, ContentPieceType, RiskLevel
from app.models.content_generation import ContentAssetType
from app.models.content_publishing import PublicationRead


class UserSessionRead(BaseModel):
    tenant_id: int
    tenant_name: str
    user_id: str
    role: str
    name: Optional[str]


class PieceAssetRead(BaseModel):
    type: ContentAssetType
    # None when signing this particular asset failed — the asset still has to
    # appear, or a reviewer would approve a piece without being shown that one
    # of its assets exists at all.
    signed_url: Optional[str]
    mime_type: Optional[str]
    width: Optional[int]
    height: Optional[int]
    duration: Optional[float]


class AuditLogEntryRead(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    actor: str
    details: Optional[dict]
    created_at: datetime


class PieceDetailRead(BaseModel):
    id: int
    campaign_id: int
    type: ContentPieceType
    status: ContentPieceStatus
    generation_prompt: Optional[str]
    avatar_id: Optional[int]
    is_synthetic_media: bool
    content_category: Optional[ContentCategory]
    risk_level: RiskLevel
    requires_human_review: bool
    policy_version: str
    scheduled_for: Optional[datetime]
    approval_action: Optional[ApprovalAction]
    approved_at: Optional[datetime]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    assets: List[PieceAssetRead]
    publications: List[PublicationRead]
