from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentTenant, GenerationTemplateCreate, GenerationTemplateRead
from app.services.content import audit
from app.services.content import generation_templates as templates_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post(
    "/content/campaigns/{campaign_id}/templates",
    response_model=GenerationTemplateRead,
    status_code=201,
)
def create_template(
    campaign_id: int,
    payload: GenerationTemplateCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    if campaign_id != payload.campaign_id:
        raise HTTPException(
            status_code=422, detail="campaign_id in path and body must match"
        )
    template = templates_service.create_template(
        session,
        tenant_id=tenant.id,
        campaign_id=payload.campaign_id,
        type=payload.type,
        generation_prompt=payload.generation_prompt,
        avatar_id=payload.avatar_id,
        voice_id=payload.voice_id,
        is_synthetic_media=payload.is_synthetic_media,
        content_category=payload.content_category,
        aspect_ratio=payload.aspect_ratio,
        resolution=payload.resolution,
        duration=payload.duration,
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="generation_template",
        entity_id=template.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return template


@router.get(
    "/content/campaigns/{campaign_id}/templates",
    response_model=list[GenerationTemplateRead],
)
def list_templates(
    campaign_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return templates_service.list_templates(
        session, tenant_id=tenant.id, campaign_id=campaign_id
    )
