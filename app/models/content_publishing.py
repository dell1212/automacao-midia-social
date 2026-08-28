from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class PublicationStatus(str, Enum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    succeeded = "succeeded"
    failed = "failed"


class ContentSocialPublication(SQLModel, table=True):
    __tablename__ = "content_social_publications"
    __table_args__ = (
        UniqueConstraint(
            "content_piece_id",
            "social_account_id",
            name="uq_content_social_publications_piece_account",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    social_account_id: int = Field(foreign_key="content_social_accounts.id", index=True)
    platform: str
    status: PublicationStatus = Field(
        default=PublicationStatus.queued,
        sa_column=Column(SAEnum(PublicationStatus, name="content_social_publication_status")),
    )
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=3)
    publication_cycle: int = Field(default=1)
    next_run_at: Optional[datetime] = None
    platform_post_id: Optional[str] = None
    platform_post_url: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    request_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# --- DTOs --------------------------------------------------------------


class PublishRequest(BaseModel):
    social_account_ids: list[int]


class PublishAcceptedItem(BaseModel):
    social_account_id: int
    platform: str
    status: str


class PublishRejectedItem(BaseModel):
    social_account_id: int
    platform: Optional[str]
    reason: str
    message: str


class PublishResponse(BaseModel):
    accepted: list[PublishAcceptedItem]
    rejected: list[PublishRejectedItem]


class PublicationRead(BaseModel):
    id: int
    content_piece_id: int
    social_account_id: int
    platform: str
    status: PublicationStatus
    attempt_count: int
    max_attempts: int
    publication_cycle: int
    platform_post_id: Optional[str]
    platform_post_url: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
