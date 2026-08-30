from typing import List, Optional

from sqlmodel import Session, select

from app.models.content_generation import (
    ContentGenerationProvider,
    GenerationKind,
    GenerationProviderName,
)
from app.services.content.crypto import decrypt_credentials, encrypt_credentials


def create_generation_provider(
    session: Session,
    *,
    tenant_id: int,
    kind: GenerationKind,
    provider: GenerationProviderName,
    credentials: str,
    config: Optional[dict] = None,
    priority: int = 0,
) -> ContentGenerationProvider:
    row = ContentGenerationProvider(
        tenant_id=tenant_id,
        kind=kind,
        provider=provider,
        credentials_encrypted=encrypt_credentials(credentials),
        config=config or {},
        priority=priority,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_generation_providers(
    session: Session, *, tenant_id: int, kind: Optional[GenerationKind] = None
) -> List[ContentGenerationProvider]:
    statement = select(ContentGenerationProvider).where(
        ContentGenerationProvider.tenant_id == tenant_id
    )
    if kind is not None:
        statement = statement.where(ContentGenerationProvider.kind == kind)
    return list(session.exec(statement).all())


def get_generation_provider(
    session: Session, *, tenant_id: int, provider_id: int
) -> Optional[ContentGenerationProvider]:
    return session.exec(
        select(ContentGenerationProvider).where(
            ContentGenerationProvider.id == provider_id,
            ContentGenerationProvider.tenant_id == tenant_id,
        )
    ).first()


def deactivate_generation_provider(
    session: Session, *, tenant_id: int, provider_id: int
) -> Optional[ContentGenerationProvider]:
    """Soft delete: jobs already executed reference this row's provider name."""
    row = get_generation_provider(
        session, tenant_id=tenant_id, provider_id=provider_id
    )
    if row is None:
        return None
    row.is_active = False
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def has_active_provider(
    session: Session, *, tenant_id: int, kind: GenerationKind
) -> bool:
    return bool(
        session.exec(
            select(ContentGenerationProvider).where(
                ContentGenerationProvider.tenant_id == tenant_id,
                ContentGenerationProvider.kind == kind,
                ContentGenerationProvider.is_active == True,  # noqa: E712
            )
        ).first()
    )


def decrypt_provider_credentials(row: ContentGenerationProvider) -> str:
    return decrypt_credentials(row.credentials_encrypted)


def update_generation_provider(
    session: Session,
    *,
    tenant_id: int,
    provider_id: int,
    credentials: Optional[str] = None,
    config: Optional[dict] = None,
    priority: Optional[int] = None,
) -> Optional[ContentGenerationProvider]:
    row = get_generation_provider(session, tenant_id=tenant_id, provider_id=provider_id)
    if row is None:
        return None
    if credentials is not None:
        row.credentials_encrypted = encrypt_credentials(credentials)
    if config is not None:
        row.config = config
    if priority is not None:
        row.priority = priority
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
