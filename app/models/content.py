from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class EntitlementStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    trial = "trial"


class ContentPieceType(str, Enum):
    video = "video"
    image = "image"
    audio = "audio"


class ContentPieceStatus(str, Enum):
    draft = "draft"
    generating = "generating"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    posted = "posted"
    failed = "failed"


class ApprovalAction(str, Enum):
    auto_approve = "auto_approve"
    require_review = "require_review"


class ContentCategory(str, Enum):
    medical = "medical"
    pharmaceutical = "pharmaceutical"
    financial = "financial"
    insurance = "insurance"
    legal = "legal"
    alcohol = "alcohol"
    gambling = "gambling"
    political = "political"
    regulated_product = "regulated_product"


class RiskLevel(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


# --- Tabelas ---------------------------------------------------------------


class ContentTenant(SQLModel, table=True):
    __tablename__ = "content_tenants"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: str = Field(index=True)
    name: str
    slug: str = Field(unique=True, index=True)
    api_token_hash: str = Field(unique=True, index=True)
    entitlement_status: EntitlementStatus = Field(
        default=EntitlementStatus.trial,
        sa_column=Column(SAEnum(EntitlementStatus, name="content_entitlement_status")),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentClient(SQLModel, table=True):
    __tablename__ = "content_clients"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)


class ContentSocialAccount(SQLModel, table=True):
    __tablename__ = "content_social_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    platform: str
    external_account_id: str
    credentials_encrypted: str
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentCampaign(SQLModel, table=True):
    __tablename__ = "content_campaigns"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    name: str
    horizon_days: int = Field(default=7)
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentPiece(SQLModel, table=True):
    __tablename__ = "content_pieces"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "idempotency_key", name="uq_content_pieces_campaign_idempotency_key"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="content_campaigns.id", index=True)
    type: ContentPieceType = Field(
        sa_column=Column(SAEnum(ContentPieceType, name="content_piece_type"))
    )
    status: ContentPieceStatus = Field(
        default=ContentPieceStatus.draft,
        sa_column=Column(SAEnum(ContentPieceStatus, name="content_piece_status")),
    )
    asset_url: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    publication_summary: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    idempotency_key: Optional[str] = Field(default=None, index=True)
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = Field(default=None, foreign_key="content_avatars.id")
    source_image_piece_id: Optional[int] = Field(
        default=None, foreign_key="content_pieces.id"
    )
    voice_id: Optional[str] = None
    is_synthetic_media: bool = Field(default=False)
    content_category: Optional[ContentCategory] = Field(
        default=None,
        sa_column=Column(SAEnum(ContentCategory, name="content_category")),
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.none,
        sa_column=Column(
            SAEnum(RiskLevel, name="content_risk_level"),
            nullable=False,
            server_default="none",
        ),
    )
    requires_human_review: bool = Field(default=False)
    policy_version: str = Field(default="v1")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    approval_action: Optional[ApprovalAction] = Field(
        default=None,
        sa_column=Column(SAEnum(ApprovalAction, name="content_approval_action")),
    )
    approved_at: Optional[datetime] = None
    is_autogenerated: bool = Field(default=False)


class ContentApprovalRule(SQLModel, table=True):
    __tablename__ = "content_approval_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="content_campaigns.id", index=True)
    condition: dict = Field(default_factory=dict, sa_column=Column(JSON))
    action: ApprovalAction = Field(
        sa_column=Column(SAEnum(ApprovalAction, name="content_approval_action"))
    )
    priority: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentGenerationTemplate(SQLModel, table=True):
    __tablename__ = "content_generation_templates"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="content_campaigns.id", index=True)
    type: ContentPieceType = Field(
        sa_column=Column(SAEnum(ContentPieceType, name="content_piece_type"))
    )
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = Field(default=None, foreign_key="content_avatars.id")
    voice_id: Optional[str] = None
    is_synthetic_media: bool = Field(default=False)
    content_category: Optional[ContentCategory] = Field(
        default=None,
        sa_column=Column(SAEnum(ContentCategory, name="content_category")),
    )
    aspect_ratio: str = Field(default="9:16")
    resolution: Optional[str] = None
    duration: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentAuditLog(SQLModel, table=True):
    __tablename__ = "content_audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    entity_type: str
    entity_id: int
    action: str
    actor: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- DTOs --------------------------------------------------------------


class TenantCreate(BaseModel):
    owner_user_id: str
    name: str
    slug: str


class TenantRead(BaseModel):
    id: int
    owner_user_id: str
    name: str
    slug: str
    entitlement_status: EntitlementStatus
    created_at: datetime


class TenantCreateResponse(TenantRead):
    api_token: str


class ClientCreate(BaseModel):
    name: str


class ClientRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    is_active: bool
    created_at: datetime


class ClientUpdate(BaseModel):
    name: Optional[str] = None


class SocialAccountCreate(BaseModel):
    client_id: int
    platform: str
    external_account_id: str
    credentials: str


class SocialAccountRead(BaseModel):
    id: int
    client_id: int
    platform: str
    external_account_id: str
    status: str
    created_at: datetime


class SocialAccountUpdate(BaseModel):
    external_account_id: Optional[str] = None
    credentials: Optional[str] = None


class CampaignCreate(BaseModel):
    client_id: int
    name: str
    horizon_days: int = 7


class CampaignRead(BaseModel):
    id: int
    client_id: int
    name: str
    horizon_days: int
    status: str
    created_at: datetime


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    horizon_days: Optional[int] = None


class ApprovalRuleCreate(BaseModel):
    campaign_id: int
    condition: dict
    action: ApprovalAction
    priority: int = 0


class ApprovalRuleRead(BaseModel):
    id: int
    campaign_id: int
    condition: dict
    action: ApprovalAction
    priority: int
    created_at: datetime


class ApprovalRuleUpdate(BaseModel):
    condition: Optional[dict] = None
    action: Optional[ApprovalAction] = None
    priority: Optional[int] = None


class GenerationTemplateCreate(BaseModel):
    campaign_id: int
    type: ContentPieceType
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = None
    voice_id: Optional[str] = None
    is_synthetic_media: bool = False
    content_category: Optional[ContentCategory] = None
    aspect_ratio: str = "9:16"
    resolution: Optional[str] = None
    duration: Optional[int] = None


class GenerationTemplateRead(BaseModel):
    id: int
    campaign_id: int
    type: ContentPieceType
    generation_prompt: Optional[str]
    avatar_id: Optional[int]
    voice_id: Optional[str]
    is_synthetic_media: bool
    content_category: Optional[ContentCategory]
    aspect_ratio: str
    resolution: Optional[str]
    duration: Optional[int]
    created_at: datetime


class ContentPieceCreate(BaseModel):
    campaign_id: int
    type: ContentPieceType
    idempotency_key: str
    is_synthetic_media: bool
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = None
    source_image_piece_id: Optional[int] = None
    voice_id: Optional[str] = None
    content_category: Optional[ContentCategory] = None
    aspect_ratio: str = "9:16"
    resolution: Optional[str] = None
    duration: Optional[int] = None


class ContentPieceRead(BaseModel):
    id: int
    campaign_id: int
    type: ContentPieceType
    status: ContentPieceStatus
    asset_url: Optional[str]
    generation_prompt: Optional[str]
    avatar_id: Optional[int]
    source_image_piece_id: Optional[int]
    voice_id: Optional[str]
    is_synthetic_media: bool
    content_category: Optional[ContentCategory]
    risk_level: RiskLevel
    requires_human_review: bool
    policy_version: str
    scheduled_for: Optional[datetime]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
