from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentTenant
from app.models.content_generation import AvatarCreate, AvatarRead
from app.services.content import audit
from app.services.content import avatars as avatars_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/avatars", response_model=AvatarRead, status_code=201)
def create_avatar(
    payload: AvatarCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    avatar = avatars_service.create_avatar(
        session,
        tenant_id=tenant.id,
        client_id=payload.client_id,
        name=payload.name,
        reference_image_url=payload.reference_image_url,
        voice_provider=payload.voice_provider,
        voice_id=payload.voice_id,
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return avatar


@router.get("/content/clients/{client_id}/avatars", response_model=list[AvatarRead])
def list_avatars(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return avatars_service.list_avatars(
        session, tenant_id=tenant.id, client_id=client_id
    )


@router.get("/content/avatars/{avatar_id}", response_model=AvatarRead)
def get_avatar(
    avatar_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    avatar = avatars_service.get_avatar(
        session, tenant_id=tenant.id, avatar_id=avatar_id
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return avatar
