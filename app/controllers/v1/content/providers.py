from typing import Optional

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentTenant
from app.models.content_generation import (
    GenerationKind,
    GenerationProviderCreate,
    GenerationProviderRead,
)
from app.services.content import audit
from app.services.content import generation_providers as providers_service
from app.services.content import providers as provider_adapters
from app.services.content.errors import GenerationError, is_retryable

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/providers", response_model=GenerationProviderRead, status_code=201)
def create_provider(
    payload: GenerationProviderCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    # Validate before persisting: a bad key should fail at registration time,
    # not silently at the tenant's first paid generation.
    try:
        provider_adapters.validate_credentials(
            provider=payload.provider.value, api_key=payload.credentials
        )
    except GenerationError as error:
        if is_retryable(error.code):
            # rate_limit/transient/timeout mean the provider was briefly
            # unreachable, not that the credential is wrong — telling the
            # tenant "your key is bad" here would send them chasing a
            # problem that isn't theirs.
            raise HTTPException(status_code=503, detail=error.message)
        raise HTTPException(status_code=422, detail=error.message)

    row = providers_service.create_generation_provider(
        session,
        tenant_id=tenant.id,
        kind=payload.kind,
        provider=payload.provider,
        credentials=payload.credentials,
        config=payload.config,
        priority=payload.priority,
    )
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return row


@router.get("/content/providers", response_model=list[GenerationProviderRead])
def list_providers(
    kind: Optional[GenerationKind] = None,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return providers_service.list_generation_providers(
        session, tenant_id=tenant.id, kind=kind
    )


@router.delete("/content/providers/{provider_id}", response_model=GenerationProviderRead)
def deactivate_provider(
    provider_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    row = providers_service.deactivate_generation_provider(
        session, tenant_id=tenant.id, provider_id=provider_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Generation provider not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="deactivated",
        actor=f"tenant:{tenant.id}",
    )
    return row
