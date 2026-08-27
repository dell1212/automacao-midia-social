from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ClientCreate, ClientRead, ContentTenant
from app.services.content import audit
from app.services.content import clients as clients_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/clients", response_model=ClientRead, status_code=201)
def create_client(
    payload: ClientCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    client = clients_service.create_client(session, tenant_id=tenant.id, name=payload.name)
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return client


@router.get("/content/clients", response_model=list[ClientRead])
def list_clients(
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return clients_service.list_clients(session, tenant_id=tenant.id)


@router.get("/content/clients/{client_id}", response_model=ClientRead)
def get_client(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    client = clients_service.get_client(session, tenant_id=tenant.id, client_id=client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client
