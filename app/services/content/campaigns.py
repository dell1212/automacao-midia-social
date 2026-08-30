from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient
from app.services.content.clients import get_client


def create_campaign(
    session: Session, *, tenant_id: int, client_id: int, name: str, horizon_days: int
) -> Optional[ContentCampaign]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return None
    campaign = ContentCampaign(client_id=client_id, name=name, horizon_days=horizon_days)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


def list_campaigns(
    session: Session, *, tenant_id: int, client_id: int
) -> List[ContentCampaign]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return []
    return list(
        session.exec(
            select(ContentCampaign).where(ContentCampaign.client_id == client_id)
        ).all()
    )


def get_campaign(
    session: Session, *, tenant_id: int, campaign_id: int
) -> Optional[ContentCampaign]:
    return session.exec(
        select(ContentCampaign)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(ContentCampaign.id == campaign_id, ContentClient.tenant_id == tenant_id)
    ).first()


def list_campaigns_for_tenant(session: Session, *, tenant_id: int) -> List[ContentCampaign]:
    return list(
        session.exec(
            select(ContentCampaign)
            .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
            .where(ContentClient.tenant_id == tenant_id)
        ).all()
    )


def update_campaign(
    session: Session,
    *,
    tenant_id: int,
    campaign_id: int,
    name: Optional[str] = None,
    horizon_days: Optional[int] = None,
) -> Optional[ContentCampaign]:
    campaign = get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    if campaign is None:
        return None
    if name is not None:
        campaign.name = name
    if horizon_days is not None:
        campaign.horizon_days = horizon_days
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


def archive_campaign(
    session: Session, *, tenant_id: int, campaign_id: int
) -> Optional[ContentCampaign]:
    campaign = get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    if campaign is None:
        return None
    campaign.status = "archived"
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign
