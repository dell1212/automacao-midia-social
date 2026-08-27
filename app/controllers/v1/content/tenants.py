from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import TenantCreate, TenantCreateResponse, TenantRead
from app.services.content import audit
from app.services.content import tenants as tenants_service

router = new_router(dependencies=[Depends(content_auth.verify_admin_token)])


@router.post("/content/tenants", response_model=TenantCreateResponse, status_code=201)
def create_tenant(payload: TenantCreate, session: Session = Depends(get_session)):
    tenant, plaintext_token = tenants_service.create_tenant(
        session,
        owner_user_id=payload.owner_user_id,
        name=payload.name,
        slug=payload.slug,
    )
    response = TenantCreateResponse(**tenant.model_dump(), api_token=plaintext_token)
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="tenant",
        entity_id=tenant.id,
        action="created",
        actor="admin",
    )
    return response


@router.get("/content/tenants", response_model=list[TenantRead])
def list_tenants(session: Session = Depends(get_session)):
    return tenants_service.list_tenants(session)


@router.get("/content/tenants/{tenant_id}", response_model=TenantRead)
def get_tenant(tenant_id: int, session: Session = Depends(get_session)):
    tenant = tenants_service.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant
