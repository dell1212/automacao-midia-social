from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentPieceRead, ContentTenant
from app.services.content import pieces as pieces_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


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
