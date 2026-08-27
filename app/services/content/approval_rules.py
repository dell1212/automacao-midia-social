from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ApprovalAction, ContentApprovalRule
from app.services.content.campaigns import get_campaign


def create_approval_rule(
    session: Session,
    *,
    tenant_id: int,
    campaign_id: int,
    condition: dict,
    action: ApprovalAction,
    priority: int,
) -> Optional[ContentApprovalRule]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return None
    rule = ContentApprovalRule(
        campaign_id=campaign_id, condition=condition, action=action, priority=priority
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def list_approval_rules(
    session: Session, *, tenant_id: int, campaign_id: int
) -> List[ContentApprovalRule]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return []
    return list(
        session.exec(
            select(ContentApprovalRule)
            .where(ContentApprovalRule.campaign_id == campaign_id)
            .order_by(ContentApprovalRule.priority.desc())
        ).all()
    )
