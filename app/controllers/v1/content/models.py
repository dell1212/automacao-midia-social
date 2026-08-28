from typing import Optional

from fastapi import Depends

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.models.content import ContentTenant
from app.models.content_generation import ModelRead
from app.services.content import catalog

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.get("/content/models", response_model=list[ModelRead])
def list_models(
    provider: Optional[str] = None,
    kind: Optional[str] = None,
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    entries = catalog.list_models(provider=provider, kind=kind)
    return [
        ModelRead(
            provider=entry.provider,
            kind=entry.kind,
            model_id=entry.model_id,
            name=entry.name,
            supported_ratios=list(entry.supported_ratios),
            supported_resolutions=list(entry.supported_resolutions),
            max_duration=entry.max_duration,
        )
        for entry in entries
    ]
