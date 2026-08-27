from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentSocialAccount
from app.services.content.clients import get_client
from app.services.content.crypto import encrypt_credentials


def create_social_account(
    session: Session,
    *,
    tenant_id: int,
    client_id: int,
    platform: str,
    external_account_id: str,
    credentials: str,
) -> Optional[ContentSocialAccount]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return None
    account = ContentSocialAccount(
        client_id=client_id,
        platform=platform,
        external_account_id=external_account_id,
        credentials_encrypted=encrypt_credentials(credentials),
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def list_social_accounts(
    session: Session, *, tenant_id: int, client_id: int
) -> List[ContentSocialAccount]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return []
    return list(
        session.exec(
            select(ContentSocialAccount).where(
                ContentSocialAccount.client_id == client_id
            )
        ).all()
    )
