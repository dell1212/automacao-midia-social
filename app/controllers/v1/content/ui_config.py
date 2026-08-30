from typing import Optional

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    ClientCreate,
    ClientRead,
    ClientUpdate,
)
from app.services.content import audit
from app.services.content import campaigns as campaigns_service
from app.services.content import clients as clients_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])


@router.get("/content/ui/config/clients", response_model=list[ClientRead])
def list_clients(
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return clients_service.list_clients(session, tenant_id=user_session.tenant.id)


@router.get("/content/ui/config/clients/{client_id}", response_model=ClientRead)
def get_client(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    client = clients_service.get_client(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.post("/content/ui/config/clients", response_model=ClientRead, status_code=201)
def create_client(
    payload: ClientCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    client = clients_service.create_client(
        session, tenant_id=user_session.tenant.id, name=payload.name
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return client


@router.put("/content/ui/config/clients/{client_id}", response_model=ClientRead)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    client = clients_service.update_client(
        session, tenant_id=user_session.tenant.id, client_id=client_id, name=payload.name
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return client


@router.delete("/content/ui/config/clients/{client_id}", response_model=ClientRead)
def deactivate_client(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    client = clients_service.deactivate_client(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return client


@router.get("/content/ui/config/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    client_id: Optional[int] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    if client_id is not None:
        return campaigns_service.list_campaigns(
            session, tenant_id=user_session.tenant.id, client_id=client_id
        )
    return campaigns_service.list_campaigns_for_tenant(
        session, tenant_id=user_session.tenant.id
    )


@router.get("/content/ui/config/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    campaign = campaigns_service.get_campaign(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/content/ui/config/campaigns", response_model=CampaignRead, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    campaign = campaigns_service.create_campaign(
        session,
        tenant_id=user_session.tenant.id,
        client_id=payload.client_id,
        name=payload.name,
        horizon_days=payload.horizon_days,
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return campaign


@router.put("/content/ui/config/campaigns/{campaign_id}", response_model=CampaignRead)
def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    campaign = campaigns_service.update_campaign(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=campaign_id,
        name=payload.name,
        horizon_days=payload.horizon_days,
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return campaign


@router.delete("/content/ui/config/campaigns/{campaign_id}", response_model=CampaignRead)
def archive_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    campaign = campaigns_service.archive_campaign(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="archived",
        actor=f"user:{user_session.user_id}",
    )
    return campaign
