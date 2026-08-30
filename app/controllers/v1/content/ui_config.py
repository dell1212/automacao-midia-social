from typing import Optional

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import (
    ApprovalRuleCreate,
    ApprovalRuleRead,
    ApprovalRuleUpdate,
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    ClientCreate,
    ClientRead,
    ClientUpdate,
    GenerationTemplateCreate,
    GenerationTemplateRead,
    GenerationTemplateUpdate,
    SocialAccountCreate,
    SocialAccountRead,
    SocialAccountUpdate,
)
from app.models.content_generation import (
    AvatarCreate,
    AvatarRead,
    AvatarUpdate,
    GenerationKind,
    GenerationProviderCreate,
    GenerationProviderRead,
    GenerationProviderUpdate,
)
from app.services.content import approval_rules as approval_rules_service
from app.services.content import audit
from app.services.content import avatars as avatars_service
from app.services.content import campaigns as campaigns_service
from app.services.content import clients as clients_service
from app.services.content import generation_providers as providers_service
from app.services.content import generation_templates as templates_service
from app.services.content import providers as provider_adapters
from app.services.content import social_accounts as social_accounts_service
from app.services.content.errors import GenerationError, is_retryable

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


@router.get(
    "/content/ui/config/clients/{client_id}/social-accounts",
    response_model=list[SocialAccountRead],
)
def list_social_accounts(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return social_accounts_service.list_social_accounts(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )


@router.get("/content/ui/config/social-accounts/{account_id}", response_model=SocialAccountRead)
def get_social_account(
    account_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    account = social_accounts_service.get_social_account(
        session, tenant_id=user_session.tenant.id, account_id=account_id
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found")
    return account


@router.post(
    "/content/ui/config/social-accounts", response_model=SocialAccountRead, status_code=201
)
def create_social_account(
    payload: SocialAccountCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    account = social_accounts_service.create_social_account(
        session,
        tenant_id=user_session.tenant.id,
        client_id=payload.client_id,
        platform=payload.platform,
        external_account_id=payload.external_account_id,
        credentials=payload.credentials,
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return account


@router.put("/content/ui/config/social-accounts/{account_id}", response_model=SocialAccountRead)
def update_social_account(
    account_id: int,
    payload: SocialAccountUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    account = social_accounts_service.update_social_account(
        session,
        tenant_id=user_session.tenant.id,
        account_id=account_id,
        external_account_id=payload.external_account_id,
        credentials=payload.credentials,
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return account


@router.delete("/content/ui/config/social-accounts/{account_id}", response_model=SocialAccountRead)
def revoke_social_account(
    account_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    account = social_accounts_service.revoke_social_account(
        session, tenant_id=user_session.tenant.id, account_id=account_id
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="revoked",
        actor=f"user:{user_session.user_id}",
    )
    return account


@router.get("/content/ui/config/clients/{client_id}/avatars", response_model=list[AvatarRead])
def list_avatars(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return avatars_service.list_avatars(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )


@router.get("/content/ui/config/avatars/{avatar_id}", response_model=AvatarRead)
def get_avatar(
    avatar_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    avatar = avatars_service.get_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=avatar_id
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return avatar


@router.post("/content/ui/config/avatars", response_model=AvatarRead, status_code=201)
def create_avatar(
    payload: AvatarCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    avatar = avatars_service.create_avatar(
        session,
        tenant_id=user_session.tenant.id,
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
        tenant_id=user_session.tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return avatar


@router.put("/content/ui/config/avatars/{avatar_id}", response_model=AvatarRead)
def update_avatar(
    avatar_id: int,
    payload: AvatarUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    avatar = avatars_service.update_avatar(
        session,
        tenant_id=user_session.tenant.id,
        avatar_id=avatar_id,
        name=payload.name,
        reference_image_url=payload.reference_image_url,
        voice_provider=payload.voice_provider,
        voice_id=payload.voice_id,
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return avatar


@router.delete("/content/ui/config/avatars/{avatar_id}", response_model=AvatarRead)
def deactivate_avatar(
    avatar_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    avatar = avatars_service.deactivate_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=avatar_id
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return avatar


@router.get(
    "/content/ui/config/campaigns/{campaign_id}/approval-rules",
    response_model=list[ApprovalRuleRead],
)
def list_approval_rules(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return approval_rules_service.list_approval_rules(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )


@router.get("/content/ui/config/approval-rules/{rule_id}", response_model=ApprovalRuleRead)
def get_approval_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    rule = approval_rules_service.get_approval_rule(
        session, tenant_id=user_session.tenant.id, rule_id=rule_id
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    return rule


@router.post("/content/ui/config/approval-rules", response_model=ApprovalRuleRead, status_code=201)
def create_approval_rule(
    payload: ApprovalRuleCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    rule = approval_rules_service.create_approval_rule(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=payload.campaign_id,
        condition=payload.condition,
        action=payload.action,
        priority=payload.priority,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="approval_rule",
        entity_id=rule.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return rule


@router.put("/content/ui/config/approval-rules/{rule_id}", response_model=ApprovalRuleRead)
def update_approval_rule(
    rule_id: int,
    payload: ApprovalRuleUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    rule = approval_rules_service.update_approval_rule(
        session,
        tenant_id=user_session.tenant.id,
        rule_id=rule_id,
        condition=payload.condition,
        action=payload.action,
        priority=payload.priority,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="approval_rule",
        entity_id=rule.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return rule


@router.delete("/content/ui/config/approval-rules/{rule_id}", status_code=204)
def delete_approval_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    deleted = approval_rules_service.delete_approval_rule(
        session, tenant_id=user_session.tenant.id, rule_id=rule_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="approval_rule",
        entity_id=rule_id,
        action="deleted",
        actor=f"user:{user_session.user_id}",
    )


@router.get(
    "/content/ui/config/campaigns/{campaign_id}/templates",
    response_model=list[GenerationTemplateRead],
)
def list_templates(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return templates_service.list_templates(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )


@router.get("/content/ui/config/templates/{template_id}", response_model=GenerationTemplateRead)
def get_template(
    template_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    template = templates_service.get_template(
        session, tenant_id=user_session.tenant.id, template_id=template_id
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Generation template not found")
    return template


@router.post(
    "/content/ui/config/campaigns/{campaign_id}/templates",
    response_model=GenerationTemplateRead,
    status_code=201,
)
def create_template(
    campaign_id: int,
    payload: GenerationTemplateCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    if campaign_id != payload.campaign_id:
        raise HTTPException(status_code=422, detail="campaign_id in path and body must match")
    if payload.avatar_id is not None and avatars_service.get_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=payload.avatar_id
    ) is None:
        raise HTTPException(status_code=422, detail="avatar_id not found in this tenant")
    template = templates_service.create_template(
        session,
        tenant_id=user_session.tenant.id,
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
        tenant_id=user_session.tenant.id,
        entity_type="generation_template",
        entity_id=template.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return template


@router.put("/content/ui/config/templates/{template_id}", response_model=GenerationTemplateRead)
def update_template(
    template_id: int,
    payload: GenerationTemplateUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    if payload.avatar_id is not None and avatars_service.get_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=payload.avatar_id
    ) is None:
        raise HTTPException(status_code=422, detail="avatar_id not found in this tenant")
    template = templates_service.update_template(
        session,
        tenant_id=user_session.tenant.id,
        template_id=template_id,
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
        raise HTTPException(status_code=404, detail="Generation template not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_template",
        entity_id=template.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return template


@router.delete("/content/ui/config/templates/{template_id}", response_model=GenerationTemplateRead)
def deactivate_template(
    template_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    template = templates_service.deactivate_template(
        session, tenant_id=user_session.tenant.id, template_id=template_id
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Generation template not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_template",
        entity_id=template.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return template


@router.get("/content/ui/config/providers", response_model=list[GenerationProviderRead])
def list_providers(
    kind: Optional[GenerationKind] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return providers_service.list_generation_providers(
        session, tenant_id=user_session.tenant.id, kind=kind
    )


@router.post("/content/ui/config/providers", response_model=GenerationProviderRead, status_code=201)
def create_provider(
    payload: GenerationProviderCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    try:
        provider_adapters.validate_credentials(
            provider=payload.provider.value, api_key=payload.credentials
        )
    except GenerationError as error:
        if is_retryable(error.code):
            raise HTTPException(status_code=503, detail=error.message)
        raise HTTPException(status_code=422, detail=error.message)

    row = providers_service.create_generation_provider(
        session,
        tenant_id=user_session.tenant.id,
        kind=payload.kind,
        provider=payload.provider,
        credentials=payload.credentials,
        config=payload.config,
        priority=payload.priority,
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return row


@router.put("/content/ui/config/providers/{provider_id}", response_model=GenerationProviderRead)
def update_provider(
    provider_id: int,
    payload: GenerationProviderUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    existing = providers_service.get_generation_provider(
        session, tenant_id=user_session.tenant.id, provider_id=provider_id
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Generation provider not found")

    if payload.credentials is not None:
        try:
            provider_adapters.validate_credentials(
                provider=existing.provider.value, api_key=payload.credentials
            )
        except GenerationError as error:
            if is_retryable(error.code):
                raise HTTPException(status_code=503, detail=error.message)
            raise HTTPException(status_code=422, detail=error.message)

    row = providers_service.update_generation_provider(
        session,
        tenant_id=user_session.tenant.id,
        provider_id=provider_id,
        credentials=payload.credentials,
        config=payload.config,
        priority=payload.priority,
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return row


@router.delete("/content/ui/config/providers/{provider_id}", response_model=GenerationProviderRead)
def deactivate_provider(
    provider_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    row = providers_service.deactivate_generation_provider(
        session, tenant_id=user_session.tenant.id, provider_id=provider_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Generation provider not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return row
