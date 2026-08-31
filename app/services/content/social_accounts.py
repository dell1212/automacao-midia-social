import json
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentClient, ContentSocialAccount
from app.services.content.clients import get_client
from app.services.content.crypto import decrypt_credentials, encrypt_credentials

_ACCOUNT_ID_CREDENTIAL_KEY = {
    "facebook": "page_id",
    "instagram": "ig_user_id",
    "linkedin": "author_urn",
}


def _check_external_account_id_matches_credentials(
    platform: str, external_account_id: str, credentials: str
) -> None:
    key = _ACCOUNT_ID_CREDENTIAL_KEY.get(platform)
    if key is None:
        return
    credential_id = json.loads(credentials).get(key)
    if credential_id is not None and credential_id != external_account_id:
        raise ValueError(f"external_account_id does not match credentials.{key}")


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
    _check_external_account_id_matches_credentials(
        platform, external_account_id, credentials
    )
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


def get_social_account(
    session: Session, *, tenant_id: int, account_id: int
) -> Optional[ContentSocialAccount]:
    return session.exec(
        select(ContentSocialAccount)
        .join(ContentClient, ContentClient.id == ContentSocialAccount.client_id)
        .where(ContentSocialAccount.id == account_id, ContentClient.tenant_id == tenant_id)
    ).first()


def update_social_account(
    session: Session,
    *,
    tenant_id: int,
    account_id: int,
    external_account_id: Optional[str] = None,
    credentials: Optional[str] = None,
) -> Optional[ContentSocialAccount]:
    account = get_social_account(session, tenant_id=tenant_id, account_id=account_id)
    if account is None:
        return None
    if external_account_id is not None or credentials is not None:
        final_external_account_id = (
            external_account_id if external_account_id is not None else account.external_account_id
        )
        final_credentials = (
            credentials
            if credentials is not None
            else decrypt_credentials(account.credentials_encrypted)
        )
        _check_external_account_id_matches_credentials(
            account.platform, final_external_account_id, final_credentials
        )
    if external_account_id is not None:
        account.external_account_id = external_account_id
    if credentials is not None:
        account.credentials_encrypted = encrypt_credentials(credentials)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def revoke_social_account(
    session: Session, *, tenant_id: int, account_id: int
) -> Optional[ContentSocialAccount]:
    account = get_social_account(session, tenant_id=tenant_id, account_id=account_id)
    if account is None:
        return None
    account.status = "revoked"
    session.add(account)
    session.commit()
    session.refresh(account)
    return account
