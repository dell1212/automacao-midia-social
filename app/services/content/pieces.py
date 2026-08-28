from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient, ContentPiece
from app.services.content.campaigns import get_campaign


def list_pieces(
    session: Session, *, tenant_id: int, campaign_id: int
) -> List[ContentPiece]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return []
    return list(
        session.exec(
            select(ContentPiece).where(ContentPiece.campaign_id == campaign_id)
        ).all()
    )


def get_piece(session: Session, *, tenant_id: int, piece_id: int) -> Optional[ContentPiece]:
    return session.exec(
        select(ContentPiece)
        .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(ContentPiece.id == piece_id, ContentClient.tenant_id == tenant_id)
    ).first()


from datetime import datetime

from app.models.content import ContentPieceStatus, ContentPieceType
from app.models.content_generation import GenerationKind
from app.services.content import audit
from app.services.content.pipeline import schedule_piece
from app.services.content.policy import classify


def find_by_idempotency_key(
    session: Session, *, campaign_id: int, idempotency_key: str
) -> Optional[ContentPiece]:
    return session.exec(
        select(ContentPiece).where(
            ContentPiece.campaign_id == campaign_id,
            ContentPiece.idempotency_key == idempotency_key,
        )
    ).first()


def required_kinds_for(payload) -> List[GenerationKind]:
    """Which provider kinds this request will actually need.

    Coarse check only — it answers "does the tenant have a provider at all",
    not "is there a compatible model", which the capability engine resolves
    per job at run time.
    """
    if payload.type == ContentPieceType.image:
        if payload.avatar_id and not payload.generation_prompt:
            return []
        return [GenerationKind.image]

    if payload.type == ContentPieceType.audio:
        return [GenerationKind.voice]

    kinds = [GenerationKind.video]
    needs_generated_base = not payload.avatar_id and not payload.source_image_piece_id
    if needs_generated_base:
        kinds.append(GenerationKind.image)
    if payload.voice_id or payload.avatar_id:
        kinds.append(GenerationKind.voice)
    return kinds


def create_piece(session: Session, *, tenant_id: int, payload) -> tuple[ContentPiece, bool]:
    """Create a piece and kick off its generation.

    Returns (piece, created). `created` is False when the idempotency key
    already produced a piece — the caller must not schedule new work in that
    case, since every generation call is billable.
    """
    existing = find_by_idempotency_key(
        session,
        campaign_id=payload.campaign_id,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        return existing, False

    classification = classify(payload.content_category)

    piece = ContentPiece(
        campaign_id=payload.campaign_id,
        type=payload.type,
        status=ContentPieceStatus.generating,
        generation_prompt=payload.generation_prompt,
        avatar_id=payload.avatar_id,
        source_image_piece_id=payload.source_image_piece_id,
        voice_id=payload.voice_id,
        is_synthetic_media=payload.is_synthetic_media,
        content_category=payload.content_category,
        risk_level=classification.risk_level,
        requires_human_review=classification.requires_human_review,
        policy_version=classification.policy_version,
        idempotency_key=payload.idempotency_key,
        updated_at=datetime.utcnow(),
    )
    session.add(piece)
    session.commit()
    session.refresh(piece)

    # Request parameters live on the call, not on the row: aspect_ratio and
    # friends describe this generation, not the piece itself.
    scheduled = schedule_piece(
        piece.id,
        piece_type=payload.type,
        aspect_ratio=payload.aspect_ratio,
        resolution=payload.resolution,
        duration=payload.duration,
    )
    if not scheduled:
        # The pending-queue is saturated: no job was ever created, so without
        # this the piece sits in `generating` with nothing to show for it and
        # no way for an operator to distinguish it from one still in flight.
        audit.write_audit_log(
            session,
            tenant_id=tenant_id,
            entity_type="content_piece",
            entity_id=piece.id,
            action="generation_queue_saturated",
            actor="system:generation",
        )
    return piece, True
