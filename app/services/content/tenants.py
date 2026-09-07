from typing import List, Optional, Tuple

from sqlmodel import Session, select

from app.models.content import ContentTenant, EntitlementStatus
from app.services.content.crypto import generate_api_token, hash_api_token


def create_tenant(
    session: Session, *, owner_user_id: str, name: str, slug: str
) -> Tuple[ContentTenant, str]:
    plaintext_token = generate_api_token()
    tenant = ContentTenant(
        owner_user_id=owner_user_id,
        name=name,
        slug=slug,
        api_token_hash=hash_api_token(plaintext_token),
        entitlement_status=EntitlementStatus.trial,
    )
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant, plaintext_token


def list_tenants(session: Session) -> List[ContentTenant]:
    return list(session.exec(select(ContentTenant)).all())


def get_tenant(session: Session, tenant_id: int) -> Optional[ContentTenant]:
    return session.get(ContentTenant, tenant_id)


def set_entitlement(
    session: Session, *, tenant_id: int, entitlement_status: EntitlementStatus
) -> Optional[Tuple[ContentTenant, EntitlementStatus]]:
    """Flips a tenant's entitlement, returning (tenant, previous_status).

    The previous status is returned rather than logged here so the caller can
    record the transition in ContentAuditLog without re-reading the row.
    """
    tenant = session.get(ContentTenant, tenant_id)
    if tenant is None:
        return None

    previous = tenant.entitlement_status
    tenant.entitlement_status = entitlement_status
    session.add(tenant)
    session.commit()
    session.refresh(tenant)
    return tenant, previous
