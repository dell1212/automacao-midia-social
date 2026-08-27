from sqlmodel import Session

from app.models.content import ContentAuditLog


def write_audit_log(
    session: Session,
    *,
    tenant_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str,
) -> ContentAuditLog:
    entry = ContentAuditLog(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry
