from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ApprovalRuleCreate, ApprovalRuleRead, ContentTenant
from app.services.content import audit
from app.services.content import approval_rules as approval_rules_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/approval-rules", response_model=ApprovalRuleRead, status_code=201)
def create_approval_rule(
    payload: ApprovalRuleCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    rule = approval_rules_service.create_approval_rule(
        session,
        tenant_id=tenant.id,
        campaign_id=payload.campaign_id,
        condition=payload.condition,
        action=payload.action,
        priority=payload.priority,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="approval_rule",
        entity_id=rule.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return rule


@router.get(
    "/content/campaigns/{campaign_id}/approval-rules",
    response_model=list[ApprovalRuleRead],
)
def list_approval_rules(
    campaign_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return approval_rules_service.list_approval_rules(
        session, tenant_id=tenant.id, campaign_id=campaign_id
    )
