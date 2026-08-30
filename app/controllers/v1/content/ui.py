from typing import Optional

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentPieceRead, ContentPieceStatus
from app.models.content_ui import AuditLogEntryRead, PieceDetailRead, UserSessionRead
from app.services.content import audit
from app.services.content import pieces as pieces_service
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
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to approve, got '{piece.status.value}'",
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
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to reject, got '{piece.status.value}'",
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


@router.get("/content/ui/audit-log", response_model=list[AuditLogEntryRead])
def list_audit_log(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 50,
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
