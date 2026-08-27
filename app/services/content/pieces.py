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
