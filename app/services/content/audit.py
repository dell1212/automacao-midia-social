from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentAuditLog


def write_audit_log(
    session: Session,
    *,
    tenant_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str,
    details: Optional[dict] = None,
) -> ContentAuditLog:
    entry = ContentAuditLog(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        details=details,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_audit_log(
    session: Session,
    *,
    tenant_id: int,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    since: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[ContentAuditLog]:
    query = select(ContentAuditLog).where(ContentAuditLog.tenant_id == tenant_id)
    if entity_type is not None:
        query = query.where(ContentAuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(ContentAuditLog.entity_id == entity_id)
    if since is not None:
        query = query.where(ContentAuditLog.created_at >= since)
    query = query.order_by(ContentAuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(session.exec(query).all())
