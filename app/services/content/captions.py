"""Resolving and storing the copy that gets published with a piece.

Resolution order for a platform: its override row, then the global row, then
`generation_prompt`. That last fallback is what makes the migration
backfill-free — a piece with no caption rows publishes exactly as it did
before this table existed.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentPiece, ContentPieceCaption
from app.services.content import platform_specs


@dataclass(frozen=True)
class ResolvedCaption:
    title: Optional[str]
    body: str
    hashtags: List[str]
    link_url: Optional[str]
    # Which row this came from, for the audit snapshot: "override", "global"
    # or "generation_prompt".
    source: str

    def rendered(self, *, platform: str) -> str:
        """Body plus hashtags, clamped to the platform's caption limit.

        Clamped here rather than at write time so a caption stays intact when
        it is only over the limit for one of several target platforms.
        """
        text = self.body
        if self.hashtags:
            tags = " ".join(
                tag if tag.startswith("#") else f"#{tag}" for tag in self.hashtags
            )
            text = f"{text}\n\n{tags}" if text else tags
        spec = platform_specs.spec_for(platform)
        if spec and len(text) > spec.caption_max:
            text = text[: spec.caption_max - 1].rstrip() + "…"
        return text


def list_captions(session: Session, *, content_piece_id: int) -> List[ContentPieceCaption]:
    return list(
        session.exec(
            select(ContentPieceCaption)
            .where(ContentPieceCaption.content_piece_id == content_piece_id)
            .order_by(ContentPieceCaption.platform)
        ).all()
    )


def get_caption(
    session: Session, *, content_piece_id: int, platform: Optional[str]
) -> Optional[ContentPieceCaption]:
    return session.exec(
        select(ContentPieceCaption).where(
            ContentPieceCaption.content_piece_id == content_piece_id,
            ContentPieceCaption.platform == platform,
        )
    ).first()


def resolve_for_platform(
    session: Session, *, piece: ContentPiece, platform: str
) -> ResolvedCaption:
    override = get_caption(
        session, content_piece_id=piece.id, platform=platform
    )
    if override is not None and override.is_override:
        return ResolvedCaption(
            title=override.title,
            body=override.body or "",
            hashtags=list(override.hashtags or []),
            link_url=override.link_url,
            source="override",
        )

    shared = get_caption(session, content_piece_id=piece.id, platform=None)
    if shared is not None:
        return ResolvedCaption(
            title=shared.title,
            body=shared.body or "",
            hashtags=list(shared.hashtags or []),
            link_url=shared.link_url,
            source="global",
        )

    # No caption written yet. Falling back to generation_prompt preserves the
    # pre-migration behaviour exactly — including the fact that it is the
    # wrong text to publish, which is why the composer exists.
    return ResolvedCaption(
        title=None,
        body=piece.generation_prompt or "",
        hashtags=[],
        link_url=None,
        source="generation_prompt",
    )


def upsert_caption(
    session: Session,
    *,
    content_piece_id: int,
    platform: Optional[str],
    title: Optional[str] = None,
    body: Optional[str] = None,
    hashtags: Optional[List[str]] = None,
    link_url: Optional[str] = None,
) -> ContentPieceCaption:
    row = get_caption(session, content_piece_id=content_piece_id, platform=platform)
    if row is None:
        row = ContentPieceCaption(
            content_piece_id=content_piece_id,
            platform=platform,
            # A platform row only exists because someone customised it; the
            # global row is never an override.
            is_override=platform is not None,
        )
    if title is not None:
        row.title = title
    if body is not None:
        row.body = body
    if hashtags is not None:
        row.hashtags = hashtags
    if link_url is not None:
        row.link_url = link_url
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_override(
    session: Session, *, content_piece_id: int, platform: str
) -> bool:
    """Drops a platform override so it falls back to the global copy — the
    "Use global content" action."""
    row = get_caption(session, content_piece_id=content_piece_id, platform=platform)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
