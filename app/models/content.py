from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column
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
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    posted = "posted"
    failed = "failed"


class ApprovalAction(str, Enum):
    auto_approve = "auto_approve"
    require_review = "require_review"


# --- Tabelas ---------------------------------------------------------------


class ContentTenant(SQLModel, table=True):
    __tablename__ = "content_tenants"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: str = Field(index=True)
    name: str
    slug: str = Field(unique=True, index=True)
    api_token_hash: str = Field(unique=True, index=True)
    entitlement_status: EntitlementStatus = Field(default=EntitlementStatus.trial)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentClient(SQLModel, table=True):
    __tablename__ = "content_clients"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


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

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="content_campaigns.id", index=True)
    type: ContentPieceType
    status: ContentPieceStatus = Field(default=ContentPieceStatus.draft)
    asset_url: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    idempotency_key: Optional[str] = Field(default=None, unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ContentApprovalRule(SQLModel, table=True):
    __tablename__ = "content_approval_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="content_campaigns.id", index=True)
    condition: dict = Field(default_factory=dict, sa_column=Column(JSON))
    action: ApprovalAction
    priority: int = Field(default=0)
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
    created_at: datetime


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


class ContentPieceRead(BaseModel):
    id: int
    campaign_id: int
    type: ContentPieceType
    status: ContentPieceStatus
    asset_url: Optional[str]
    scheduled_for: Optional[datetime]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
