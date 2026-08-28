from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentClient
from app.models.content_generation import ContentAvatar
from app.services.content.clients import get_client


def create_avatar(
    session: Session,
    *,
    tenant_id: int,
    client_id: int,
    name: str,
    reference_image_url: str,
    voice_provider: Optional[str] = None,
    voice_id: Optional[str] = None,
) -> Optional[ContentAvatar]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return None
    avatar = ContentAvatar(
        client_id=client_id,
        name=name,
        reference_image_url=reference_image_url,
        voice_provider=voice_provider,
        voice_id=voice_id,
    )
    session.add(avatar)
    session.commit()
    session.refresh(avatar)
    return avatar


def list_avatars(
    session: Session, *, tenant_id: int, client_id: int
) -> List[ContentAvatar]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return []
    return list(
        session.exec(
            select(ContentAvatar).where(ContentAvatar.client_id == client_id)
        ).all()
    )


def get_avatar(
    session: Session, *, tenant_id: int, avatar_id: int
) -> Optional[ContentAvatar]:
    """Tenant-scoped lookup: an avatar of another tenant must read as absent."""
    return session.exec(
        select(ContentAvatar)
        .join(ContentClient, ContentClient.id == ContentAvatar.client_id)
        .where(ContentAvatar.id == avatar_id, ContentClient.tenant_id == tenant_id)
    ).first()
