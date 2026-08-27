from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentTenant, SocialAccountCreate, SocialAccountRead
from app.services.content import audit
from app.services.content import social_accounts as social_accounts_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post(
    "/content/social-accounts", response_model=SocialAccountRead, status_code=201
)
def create_social_account(
    payload: SocialAccountCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    account = social_accounts_service.create_social_account(
        session,
        tenant_id=tenant.id,
        client_id=payload.client_id,
        platform=payload.platform,
        external_account_id=payload.external_account_id,
        credentials=payload.credentials,
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return account


@router.get("/content/clients/{client_id}/social-accounts", response_model=list[SocialAccountRead])
def list_social_accounts(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return social_accounts_service.list_social_accounts(
        session, tenant_id=tenant.id, client_id=client_id
    )
