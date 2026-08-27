from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentClient


def create_client(session: Session, *, tenant_id: int, name: str) -> ContentClient:
    client = ContentClient(tenant_id=tenant_id, name=name)
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


def list_clients(session: Session, *, tenant_id: int) -> List[ContentClient]:
    return list(
        session.exec(
            select(ContentClient).where(ContentClient.tenant_id == tenant_id)
        ).all()
    )


def get_client(session: Session, *, tenant_id: int, client_id: int) -> Optional[ContentClient]:
    return session.exec(
        select(ContentClient).where(
            ContentClient.id == client_id, ContentClient.tenant_id == tenant_id
        )
    ).first()
