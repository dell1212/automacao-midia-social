from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ContentPublicationInsight(SQLModel, table=True):
    """One engagement snapshot per (publication, collection) — never overwritten.

    A post published today keeps accumulating likes for days; overwriting a
    row would destroy the answer to "when did this happen". A failed
    collection also becomes a row, with all five metrics null and
    `error_code` filled in — so a broken token stays visible in the same
    table instead of turning into silence, and "when was the last attempt"
    needs no separate state.

    See docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md.
    """

    __tablename__ = "content_publication_insights"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    publication_id: int = Field(
        foreign_key="content_social_publications.id", index=True
    )
    social_account_id: int = Field(
        foreign_key="content_social_accounts.id", index=True
    )
    platform: str
    # Mirrors ContentSocialPublication.publication_cycle: republishing a
    # piece creates a new post on the platform, and the old post's metrics
    # must not blend with the new one's.
    publication_cycle: int
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    # Reach (unique people) only genuinely exists on Instagram and Facebook.
    # The other four platforms only publish impressions (exposure volume,
    # not people) — which is why these are two separate, nullable columns,
    # never one sum under a single label. See the per-platform metric table
    # in the design spec.
    reach: Optional[int] = None
    impressions: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    # The response as it arrived. APIs add fields without warning; when a
    # number looks wrong, this is the only way to tell whether the bug is
    # ours or theirs.
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))

    error_code: Optional[str] = None
    error_message: Optional[str] = None
