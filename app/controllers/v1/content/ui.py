from typing import Optional

from fastapi import Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentPieceRead, ContentPieceStatus, PieceUpdate
from app.models.content_generation import ContentAssetType
from app.models.content_ui import AuditLogEntryRead, PieceDetailRead, UserSessionRead
from app.services.content import assets as assets_service
from app.services.content import audit
from app.services.content import avatars as avatars_service
from app.services.content import campaigns as campaigns_service
from app.services.content import pieces as pieces_service
from app.services.content import storage
from app.services.content import ui_pieces as ui_pieces_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])


@router.get("/content/ui/session", response_model=UserSessionRead)
def get_session_info(
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return UserSessionRead(
        tenant_id=user_session.tenant.id,
        tenant_name=user_session.tenant.name,
        user_id=user_session.user_id,
        role=user_session.role,
        name=user_session.name,
    )


@router.get("/content/ui/pieces", response_model=list[ContentPieceRead])
def list_pieces(
    campaign_id: int,
    status: Optional[ContentPieceStatus] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return pieces_service.list_pieces(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=campaign_id,
        status=status,
    )


@router.get("/content/ui/pieces/{piece_id}", response_model=PieceDetailRead)
def get_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    detail = ui_pieces_service.get_piece_detail(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return detail


@router.patch("/content/ui/pieces/{piece_id}", response_model=ContentPieceRead)
def update_piece(
    piece_id: int,
    payload: PieceUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to edit"
        )

    if payload.avatar_id is not None and avatars_service.get_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=payload.avatar_id
    ) is None:
        raise HTTPException(status_code=422, detail="avatar_id not found in this tenant")

    result = pieces_service.update_piece(
        session,
        tenant_id=user_session.tenant.id,
        piece_id=piece_id,
        generation_prompt=payload.generation_prompt,
        avatar_id=payload.avatar_id,
        voice_id=payload.voice_id,
        content_category=payload.content_category,
        risk_level=payload.risk_level,
        scheduled_for=payload.scheduled_for,
    )
    if result is None:
        raise HTTPException(
            status_code=409, detail="Piece became 'posted' before the edit was applied"
        )
    updated, diff = result

    if diff:
        audit.write_audit_log(
            session,
            tenant_id=user_session.tenant.id,
            entity_type="content_piece",
            entity_id=piece_id,
            action="edited",
            actor=f"user:{user_session.user_id}",
            details=diff,
        )
    return updated


@router.post("/content/ui/pieces/{piece_id}/approve", response_model=ContentPieceRead)
def approve_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.approve_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if updated is None:
        # `piece` is the pre-transition read — a concurrent change is exactly
        # why this branch was reached, so re-fetch instead of reporting the
        # status that lost the race.
        current = pieces_service.get_piece(
            session, tenant_id=user_session.tenant.id, piece_id=piece_id
        ) or piece
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to approve, got '{current.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="approved",
        actor=f"user:{user_session.user_id}",
    )
    return updated


@router.post("/content/ui/pieces/{piece_id}/reject", response_model=ContentPieceRead)
def reject_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.reject_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if updated is None:
        current = pieces_service.get_piece(
            session, tenant_id=user_session.tenant.id, piece_id=piece_id
        ) or piece
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to reject, got '{current.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="rejected",
        actor=f"user:{user_session.user_id}",
    )
    return updated


@router.post("/content/ui/pieces/{piece_id}/asset", response_model=ContentPieceRead)
async def replace_piece_asset(
    piece_id: int,
    type: ContentAssetType = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to replace its asset"
        )
    if type.value != piece.type.value:
        raise HTTPException(
            status_code=422,
            detail=f"asset type '{type.value}' does not match piece type '{piece.type.value}'",
        )

    campaign = campaigns_service.get_campaign(
        session, tenant_id=user_session.tenant.id, campaign_id=piece.campaign_id
    )

    data = await file.read()
    uploaded = storage.upload_bytes(
        tenant_id=user_session.tenant.id,
        content_piece_id=piece_id,
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type or "application/octet-stream",
    )

    result = pieces_service.mark_asset_replaced(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if result is None:
        raise HTTPException(
            status_code=409, detail="Piece became 'posted' before the asset was replaced"
        )
    updated, diff = result

    archived = assets_service.archive_assets_of_type(
        session, content_piece_id=piece_id, asset_type=type
    )
    new_asset = assets_service.create_manual_asset(
        session,
        tenant_id=user_session.tenant.id,
        client_id=campaign.client_id,
        content_piece_id=piece_id,
        asset_type=type,
        uploaded=uploaded,
        mime_type=file.content_type,
    )

    diff["asset"] = {
        "before": archived[0].storage_path if archived else None,
        "after": new_asset.storage_path,
    }
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="asset_replaced",
        actor=f"user:{user_session.user_id}",
        details=diff,
    )
    return updated


@router.get("/content/ui/audit-log", response_model=list[AuditLogEntryRead])
def list_audit_log(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return audit.list_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
