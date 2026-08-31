from typing import Optional

from loguru import logger
from sqlmodel import Session

from app.models.content_publishing import PublicationRead
from app.models.content_ui import PieceAssetRead, PieceDetailRead
from app.services.content import assets as assets_service
from app.services.content import pieces as pieces_service
from app.services.content import publications as publications_service
from app.services.content import storage


def _resolve_signed_url(*, storage_path: Optional[str], url: str) -> Optional[str]:
    """One unsignable asset must not take the whole piece down with it — the
    detail response is what the reviewer needs to decide, and a 500 here left
    the piece impossible to review at all.

    storage_path is None for an asset registered from an external URL (e.g.
    reusing an avatar's reference image) — nothing of ours to sign, so the
    plain url is what the reviewer gets instead.
    """
    if storage_path is None:
        return url
    try:
        return storage.create_signed_url(storage_path)
    except storage.StorageError:
        logger.warning(f"failed to sign asset for review UI: {storage_path}")
        return None


def get_piece_detail(
    session: Session, *, tenant_id: int, piece_id: int
) -> Optional[PieceDetailRead]:
    piece = pieces_service.get_piece(session, tenant_id=tenant_id, piece_id=piece_id)
    if piece is None:
        return None

    assets = [
        PieceAssetRead(
            type=asset.type,
            signed_url=_resolve_signed_url(storage_path=asset.storage_path, url=asset.url),
            mime_type=asset.mime_type,
            width=asset.width,
            height=asset.height,
            duration=asset.duration,
        )
        for asset in assets_service.list_assets_for_piece(session, content_piece_id=piece.id)
        if not asset.is_intermediate
    ]

    publications = [
        PublicationRead.model_validate(publication, from_attributes=True)
        for publication in publications_service.list_publications_for_piece(
            session, content_piece_id=piece.id
        )
    ]

    return PieceDetailRead(
        id=piece.id,
        campaign_id=piece.campaign_id,
        type=piece.type,
        status=piece.status,
        generation_prompt=piece.generation_prompt,
        avatar_id=piece.avatar_id,
        is_synthetic_media=piece.is_synthetic_media,
        content_category=piece.content_category,
        risk_level=piece.risk_level,
        requires_human_review=piece.requires_human_review,
        policy_version=piece.policy_version,
        scheduled_for=piece.scheduled_for,
        approval_action=piece.approval_action,
        approved_at=piece.approved_at,
        posted_at=piece.posted_at,
        created_at=piece.created_at,
        updated_at=piece.updated_at,
        assets=assets,
        publications=publications,
    )
