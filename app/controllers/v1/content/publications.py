from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentPieceStatus, ContentTenant
from app.models.content_publishing import (
    PublicationRead,
    PublishRequest,
    PublishResponse,
)
from app.services.content import pieces as pieces_service
from app.services.content import publications as publications_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])

_PUBLISHABLE_STATUSES = (ContentPieceStatus.approved, ContentPieceStatus.posted)


@router.post(
    "/content/pieces/{piece_id}/publish", response_model=PublishResponse, status_code=202
)
def publish_piece(
    piece_id: int,
    payload: PublishRequest,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status not in _PUBLISHABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be approved or already posted, got '{piece.status.value}'",
        )

    accepted, rejected = publications_service.resolve_publication_request(
        session, piece=piece, social_account_ids=payload.social_account_ids
    )

    return PublishResponse(
        accepted=[
            {"social_account_id": row.social_account_id, "platform": row.platform, "status": row.status.value}
            for row in accepted
        ],
        rejected=rejected,
    )


@router.get(
    "/content/pieces/{piece_id}/publications", response_model=list[PublicationRead]
)
def list_publications(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    return publications_service.list_publications_for_piece(session, content_piece_id=piece_id)
