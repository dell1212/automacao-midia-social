from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select, update

from app.models.content import (
    ContentCampaign,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentPieceType,
)
from app.models.content_generation import GenerationKind
from app.services.content import audit
from app.services.content.campaigns import get_campaign
from app.services.content.pipeline import schedule_piece
from app.services.content.policy import classify


def list_pieces(
    session: Session,
    *,
    tenant_id: int,
    campaign_id: int,
    status: Optional[ContentPieceStatus] = None,
) -> List[ContentPiece]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return []
    if status is None:
        # Select all columns except STATUS when no filter is provided
        cols = [
            getattr(ContentPiece, c.name)
            for c in ContentPiece.__table__.columns
            if c.name != "status"
        ]
        statement = select(*cols).where(ContentPiece.campaign_id == campaign_id)
    else:
        statement = select(ContentPiece).where(
            ContentPiece.campaign_id == campaign_id, ContentPiece.status == status
        )
    return list(session.exec(statement).all())


def get_piece(session: Session, *, tenant_id: int, piece_id: int) -> Optional[ContentPiece]:
    return session.exec(
        select(ContentPiece)
        .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(ContentPiece.id == piece_id, ContentClient.tenant_id == tenant_id)
    ).first()


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


def _conditional_transition(
    session: Session, *, piece_id: int, values: dict
) -> bool:
    """UPDATE guardado: só aplica se a piece ainda estiver pending_approval.

    Fecha a corrida entre uma decisão automática (approval_action, Passe 2 do
    scheduler) e uma ação manual do humano chegando ao mesmo tempo — quem
    escrever primeiro vence, o outro descarta sem sobrescrever. Retorna se a
    escrita realmente aconteceu.
    """
    result = session.exec(
        update(ContentPiece)
        .where(
            ContentPiece.id == piece_id,
            ContentPiece.status == ContentPieceStatus.pending_approval,
        )
        .values(**values)
    )
    session.commit()
    return result.rowcount > 0


def approve_piece(session: Session, *, tenant_id: int, piece_id: int) -> Optional[ContentPiece]:
    piece = get_piece(session, tenant_id=tenant_id, piece_id=piece_id)
    if piece is None:
        return None
    applied = _conditional_transition(
        session,
        piece_id=piece_id,
        values={
            "status": ContentPieceStatus.approved,
            "approved_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
    )
    if not applied:
        return None
    session.refresh(piece)
    return piece


def reject_piece(session: Session, *, tenant_id: int, piece_id: int) -> Optional[ContentPiece]:
    piece = get_piece(session, tenant_id=tenant_id, piece_id=piece_id)
    if piece is None:
        return None
    applied = _conditional_transition(
        session,
        piece_id=piece_id,
        values={
            "status": ContentPieceStatus.rejected,
            "updated_at": datetime.utcnow(),
        },
    )
    if not applied:
        return None
    session.refresh(piece)
    return piece
