import os
import secrets
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models.content import ContentTenant, EntitlementStatus
from app.services.content.crypto import hash_api_token

_ADMIN_TOKEN_ENV = "CONTENT_ADMIN_TOKEN"


def verify_admin_token(x_admin_token: Optional[str] = Header(default=None)) -> None:
    """Protege endpoints de provisionamento de tenant.

    Diferente do `verify_token` legado (que libera acesso quando a chave não
    está configurada), este falha fechado: sem CONTENT_ADMIN_TOKEN definido,
    o endpoint responde 500 em vez de abrir acesso.
    """
    configured = os.environ.get(_ADMIN_TOKEN_ENV)
    if not configured:
        raise HTTPException(
            status_code=500,
            detail=f"{_ADMIN_TOKEN_ENV} is not configured on the server",
        )
    if not x_admin_token or not secrets.compare_digest(
        x_admin_token.encode("utf-8"), configured.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid admin token")


def verify_tenant_token(
    x_tenant_token: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> ContentTenant:
    if not x_tenant_token:
        raise HTTPException(status_code=401, detail="Missing X-Tenant-Token header")

    token_hash = hash_api_token(x_tenant_token)
    tenant = session.exec(
        select(ContentTenant).where(ContentTenant.api_token_hash == token_hash)
    ).first()

    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid tenant token")

    if tenant.entitlement_status == EntitlementStatus.inactive:
        raise HTTPException(status_code=403, detail="Tenant is not entitled")

    return tenant
