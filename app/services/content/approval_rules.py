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


def get_approval_rule(
    session: Session, *, tenant_id: int, rule_id: int
) -> Optional[ContentApprovalRule]:
    rule = session.exec(
        select(ContentApprovalRule).where(ContentApprovalRule.id == rule_id)
    ).first()
    if rule is None:
        return None
    if get_campaign(session, tenant_id=tenant_id, campaign_id=rule.campaign_id) is None:
        return None
    return rule


def update_approval_rule(
    session: Session,
    *,
    tenant_id: int,
    rule_id: int,
    condition: Optional[dict] = None,
    action: Optional[ApprovalAction] = None,
    priority: Optional[int] = None,
) -> Optional[ContentApprovalRule]:
    rule = get_approval_rule(session, tenant_id=tenant_id, rule_id=rule_id)
    if rule is None:
        return None
    if condition is not None:
        rule.condition = condition
    if action is not None:
        rule.action = action
    if priority is not None:
        rule.priority = priority
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def delete_approval_rule(session: Session, *, tenant_id: int, rule_id: int) -> bool:
    rule = get_approval_rule(session, tenant_id=tenant_id, rule_id=rule_id)
    if rule is None:
        return False
    session.delete(rule)
    session.commit()
    return True
