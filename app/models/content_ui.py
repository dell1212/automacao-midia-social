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
    narration_script: Optional[str]
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


# --- Captions (the copy published with a piece's media) ---


class PieceCaptionRead(BaseModel):
    # None on the shared "Global" row every platform falls back to.
    platform: Optional[str]
    title: Optional[str]
    body: Optional[str]
    hashtags: List[str]
    link_url: Optional[str]
    is_override: bool


class CaptionUpsert(BaseModel):
    """Write to one caption row. `platform: null` writes the global copy."""

    platform: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    hashtags: Optional[List[str]] = None
    link_url: Optional[str] = None


class CaptionSuggestRequest(BaseModel):
    """Ask the LLM for copy. Defaults to the piece's own prompt/script as the
    brief, so the common case needs no body at all."""

    platform: Optional[str] = None
    language: str = "auto"


class ResolvedCaptionRead(BaseModel):
    """What would actually be published to one platform right now, after the
    override → global → generation_prompt fallback and the length clamp."""

    platform: str
    body: str
    source: str
    length: int
    caption_max: int
    over_limit: bool


class AgentBriefRequest(BaseModel):
    """Plain-language description of what the agent should plan."""

    brief: str


# --- Composer: targeting and per-channel validation ---


class PieceTargetOption(BaseModel):
    social_account_id: int
    platform: str
    label: str
    selected: bool


class PieceTargetsRead(BaseModel):
    # False when the piece has no target rows: it falls back to every active
    # account, which is what the scheduler did before targeting existed.
    is_targeted: bool
    options: List[PieceTargetOption]


class PieceTargetsUpdate(BaseModel):
    """Empty list clears targeting (back to all active accounts) rather than
    meaning "publish nowhere" — that is expressed by not approving."""

    social_account_ids: List[int]


class ChannelIssueRead(BaseModel):
    code: str
    message: str


class ChannelValidationRead(BaseModel):
    platform: str
    social_account_id: Optional[int]
    label: str
    ready: bool
    issues: List[ChannelIssueRead]
    caption_length: int
    caption_max: int


class NextSlotRead(BaseModel):
    """The next free half-hour after the campaign's latest scheduled piece."""

    scheduled_for: datetime
