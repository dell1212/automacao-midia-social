from fastapi import Depends, HTTPException, Response
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import (
    ContentPieceCreate,
    ContentPieceRead,
    ContentPieceType,
    ContentTenant,
)
from app.models.content_generation import GenerationJobRead
from app.services.content import audit
from app.services.content import avatars as avatars_service
from app.services.content import jobs as jobs_service
from app.services.content import pieces as pieces_service
from app.services.content.campaigns import get_campaign
from app.services.content.generation_providers import has_active_provider

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/pieces", response_model=ContentPieceRead, status_code=202)
def create_piece(
    payload: ContentPieceCreate,
    response: Response,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    if get_campaign(session, tenant_id=tenant.id, campaign_id=payload.campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if payload.type in (ContentPieceType.audio, ContentPieceType.video):
        if not payload.generation_prompt:
            raise HTTPException(
                status_code=422,
                detail=f"generation_prompt is required for type {payload.type.value}",
            )
    elif not payload.generation_prompt and not payload.avatar_id:
        raise HTTPException(
            status_code=422,
            detail="image pieces require generation_prompt or avatar_id",
        )

    avatar = None
    if payload.avatar_id is not None:
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant.id, avatar_id=payload.avatar_id
        )
        if avatar is None:
            raise HTTPException(status_code=404, detail="Avatar not found")

    if payload.type == ContentPieceType.audio:
        has_voice = payload.voice_id or (avatar is not None and avatar.voice_id)
        if not has_voice:
            raise HTTPException(
                status_code=422,
                detail="audio pieces require voice_id or an avatar_id with a configured voice",
            )

    if payload.source_image_piece_id is not None:
        source = pieces_service.get_piece(
            session, tenant_id=tenant.id, piece_id=payload.source_image_piece_id
        )
        if source is None:
            raise HTTPException(status_code=404, detail="Source image piece not found")

    for kind in pieces_service.required_kinds_for(payload):
        if not has_active_provider(session, tenant_id=tenant.id, kind=kind):
            raise HTTPException(
                status_code=422,
                detail=f"no active {kind.value} provider configured for this tenant",
            )

    piece, created = pieces_service.create_piece(
        session, tenant_id=tenant.id, payload=payload
    )
    if not created:
        # Idempotent replay: the piece already exists and its generation was
        # already paid for. Return it as-is instead of generating again.
        response.status_code = 200
        return piece

    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="content_piece",
        entity_id=piece.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return piece


@router.get("/content/pieces/{piece_id}/jobs", response_model=list[GenerationJobRead])
def list_piece_jobs(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    if pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id) is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return jobs_service.list_jobs_for_piece(
        session, tenant_id=tenant.id, piece_id=piece_id
    )


@router.get(
    "/content/campaigns/{campaign_id}/pieces", response_model=list[ContentPieceRead]
)
def list_pieces(
    campaign_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return pieces_service.list_pieces(session, tenant_id=tenant.id, campaign_id=campaign_id)


@router.get("/content/pieces/{piece_id}", response_model=ContentPieceRead)
def get_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return piece


@router.post("/content/pieces/{piece_id}/approve", response_model=ContentPieceRead)
def approve_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.approve_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if updated is None:
        # `piece` is the pre-transition read — a concurrent change is exactly
        # why this branch was reached, so re-fetch instead of reporting the
        # status that lost the race.
        current = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id) or piece
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to approve, got '{current.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="approved",
        actor=f"tenant:{tenant.id}",
    )
    return updated


@router.post("/content/pieces/{piece_id}/reject", response_model=ContentPieceRead)
def reject_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.reject_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if updated is None:
        current = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id) or piece
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to reject, got '{current.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="rejected",
        actor=f"tenant:{tenant.id}",
    )
    return updated
