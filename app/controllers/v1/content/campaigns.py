from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import CampaignCreate, CampaignRead, ContentTenant
from app.services.content import audit
from app.services.content import campaigns as campaigns_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/campaigns", response_model=CampaignRead, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    campaign = campaigns_service.create_campaign(
        session,
        tenant_id=tenant.id,
        client_id=payload.client_id,
        name=payload.name,
        horizon_days=payload.horizon_days,
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return campaign


@router.get("/content/clients/{client_id}/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return campaigns_service.list_campaigns(session, tenant_id=tenant.id, client_id=client_id)


@router.get("/content/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    campaign = campaigns_service.get_campaign(session, tenant_id=tenant.id, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign
