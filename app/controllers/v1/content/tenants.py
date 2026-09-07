from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import (
    TenantCreate,
    TenantCreateResponse,
    TenantEntitlementRead,
    TenantEntitlementUpdate,
    TenantRead,
)
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


@router.patch(
    "/content/tenants/{tenant_id}/entitlement", response_model=TenantEntitlementRead
)
def set_tenant_entitlement(
    tenant_id: int,
    payload: TenantEntitlementUpdate,
    session: Session = Depends(get_session),
):
    """Server-to-server entitlement toggle, called by the parent app's
    set-module-entitlement Edge Function. Inherits verify_admin_token from the
    router: the browser never holds this token."""
    result = tenants_service.set_entitlement(
        session, tenant_id=tenant_id, entitlement_status=payload.entitlement_status
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant, previous = result
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="tenant",
        entity_id=tenant.id,
        action="entitlement_changed",
        actor="admin",
        details={"from": previous.value, "to": tenant.entitlement_status.value},
    )
    return TenantEntitlementRead(
        tenant_id=tenant.id, entitlement_status=tenant.entitlement_status
    )
