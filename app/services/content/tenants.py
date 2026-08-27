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
