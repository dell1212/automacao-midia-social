import os
import secrets
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models.content import ContentTenant, EntitlementStatus
from app.services.content.crypto import hash_api_token

_ADMIN_TOKEN_ENV = "CONTENT_ADMIN_TOKEN"
_UI_JWT_PUBLIC_KEY_ENV = "CONTENT_UI_JWT_PUBLIC_KEY"
_VALID_ROLES = {"admin", "member"}


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


@dataclass(frozen=True)
class UserSession:
    tenant: ContentTenant
    user_id: str
    role: str
    name: Optional[str]


def verify_user_session(
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> UserSession:
    """Validates the RS256 session JWT the parent app hands the iframe.

    Additive to verify_tenant_token/verify_admin_token — used only by the
    new /v1/content/ui/... routes. Fails closed like verify_admin_token:
    an unconfigured public key is a 500, not an open door.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[len("Bearer ") :]

    public_key = os.environ.get(_UI_JWT_PUBLIC_KEY_ENV)
    if not public_key:
        raise HTTPException(
            status_code=500,
            detail=f"{_UI_JWT_PUBLIC_KEY_ENV} is not configured on the server",
        )

    try:
        claims = jwt.decode(token, public_key, algorithms=["RS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid session token")

    tenant_id = claims.get("tenant_id")
    user_id = claims.get("user_id")
    role = claims.get("role")
    if tenant_id is None or not user_id or role not in _VALID_ROLES:
        raise HTTPException(status_code=401, detail="Invalid session token")

    tenant = session.get(ContentTenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid session token")

    if tenant.entitlement_status == EntitlementStatus.inactive:
        raise HTTPException(status_code=403, detail="Tenant is not entitled")

    return UserSession(tenant=tenant, user_id=str(user_id), role=role, name=claims.get("name"))


def require_role(user_session: UserSession, role: str) -> None:
    if user_session.role != role:
        raise HTTPException(status_code=403, detail=f"Requires role '{role}'")
