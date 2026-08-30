from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class GenerationKind(str, Enum):
    image = "image"
    video = "video"
    voice = "voice"


class GenerationProviderName(str, Enum):
    wavespeed = "wavespeed"
    falai = "falai"
    gemini = "gemini"
    elevenlabs = "elevenlabs"


class GenerationJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"


class ContentAssetType(str, Enum):
    image = "image"
    audio = "audio"
    video = "video"
    thumbnail = "thumbnail"
    subtitle = "subtitle"


# --- Tables ----------------------------------------------------------------


class ContentGenerationProvider(SQLModel, table=True):
    __tablename__ = "content_generation_providers"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    kind: GenerationKind = Field(
        sa_column=Column(SAEnum(GenerationKind, name="content_generation_provider_kind"))
    )
    provider: GenerationProviderName = Field(
        sa_column=Column(
            SAEnum(GenerationProviderName, name="content_generation_provider_name")
        )
    )
    credentials_encrypted: str
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    priority: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentAvatar(SQLModel, table=True):
    __tablename__ = "content_avatars"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    name: str
    reference_image_url: str
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentGenerationJob(SQLModel, table=True):
    __tablename__ = "content_generation_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    kind: GenerationKind = Field(
        sa_column=Column(SAEnum(GenerationKind, name="content_generation_job_kind"))
    )
    status: GenerationJobStatus = Field(
        default=GenerationJobStatus.queued,
        sa_column=Column(
            SAEnum(GenerationJobStatus, name="content_generation_job_status")
        ),
    )
    provider: Optional[str] = None
    model: Optional[str] = None
    request_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    response_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
    attempt_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    input_units: Optional[float] = None
    output_units: Optional[float] = None
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    currency: Optional[str] = None
    duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ContentAsset(SQLModel, table=True):
    __tablename__ = "content_assets"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    generation_job_id: Optional[int] = Field(
        default=None, foreign_key="content_generation_jobs.id", index=True
    )
    type: ContentAssetType = Field(
        sa_column=Column(SAEnum(ContentAssetType, name="content_asset_type"))
    )
    url: str
    storage_path: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    is_intermediate: bool = Field(default=False)
    asset_metadata: dict = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- DTOs ------------------------------------------------------------------


class GenerationProviderCreate(BaseModel):
    kind: GenerationKind
    provider: GenerationProviderName
    credentials: str
    config: dict = {}
    priority: int = 0


class GenerationProviderRead(BaseModel):
    id: int
    tenant_id: int
    kind: GenerationKind
    provider: GenerationProviderName
    config: dict
    priority: int
    is_active: bool
    created_at: datetime


class AvatarCreate(BaseModel):
    client_id: int
    name: str
    reference_image_url: str
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None


class AvatarRead(BaseModel):
    id: int
    client_id: int
    name: str
    reference_image_url: str
    voice_provider: Optional[str]
    voice_id: Optional[str]
    is_active: bool
    created_at: datetime


class AvatarUpdate(BaseModel):
    name: Optional[str] = None
    reference_image_url: Optional[str] = None
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None


class GenerationJobRead(BaseModel):
    id: int
    content_piece_id: int
    kind: GenerationKind
    status: GenerationJobStatus
    provider: Optional[str]
    model: Optional[str]
    attempt_count: int
    retry_count: int
    estimated_cost: Optional[float]
    actual_cost: Optional[float]
    currency: Optional[str]
    duration_ms: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class ModelRead(BaseModel):
    provider: str
    kind: str
    model_id: str
    name: str
    supported_ratios: list[str]
    supported_resolutions: list[str]
    max_duration: Optional[int]
