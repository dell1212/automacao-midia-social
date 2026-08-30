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
    limit: int = 50,
    offset: int = 0,
) -> List[ContentAuditLog]:
    # Conditionally include entity_type in SELECT only if filtering by it
    if entity_type is not None:
        query = select(ContentAuditLog).where(ContentAuditLog.tenant_id == tenant_id)
        query = query.where(ContentAuditLog.entity_type == entity_type)
    else:
        # Exclude entity_type from SELECT when not filtering by it
        query = select(
            ContentAuditLog.id,
            ContentAuditLog.tenant_id,
            ContentAuditLog.entity_id,
            ContentAuditLog.action,
            ContentAuditLog.actor,
            ContentAuditLog.details,
            ContentAuditLog.created_at,
        ).where(ContentAuditLog.tenant_id == tenant_id)

    if entity_id is not None:
        query = query.where(ContentAuditLog.entity_id == entity_id)
    query = query.order_by(ContentAuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(session.exec(query).all())
