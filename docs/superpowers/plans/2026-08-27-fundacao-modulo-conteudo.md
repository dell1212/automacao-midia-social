# Fundação do Módulo de Conteúdo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao módulo de automação de conteúdo uma base de dados multi-tenant (Postgres/Supabase) e uma superfície de API mínima (CRUD de Tenant/Client/SocialAccount/Campaign/ApprovalRule + leitura de ContentPiece), autenticada por token de tenant, seguindo os padrões FastAPI já existentes no projeto.

**Architecture:** Módulo headless dentro do FastAPI existente (`app/controllers/v1/`, `app/services/`, `app/router.py`). Persistência via SQLModel/SQLAlchemy apontando para uma connection string Postgres padrão (Supabase ou não — o código não sabe a diferença), migrations via Alembic. Autenticação em duas camadas: um token de admin (env var, fail-closed) protege o provisionamento de tenants; um token por tenant (hash no banco) protege todo o resto, resolvido para um `ContentTenant` via dependency do FastAPI.

**Tech Stack:** FastAPI (já no projeto), SQLModel, Alembic, `cryptography` (Fernet) para credenciais de redes sociais, Postgres (Supabase).

**Spec:** `docs/superpowers/specs/2026-08-27-fundacao-modulo-conteudo-design.md`

## Global Constraints

- Tabelas prefixadas por módulo: `content_*`.
- Toda tabela tenant-scoped tem `tenant_id` (ou cadeia até tenant) com índice dedicado.
- `entitlement_status` enum: `active` / `inactive` / `trial`.
- `idempotency_key` único em `content_pieces` (usado pelas fases futuras de geração/postagem).
- `DATABASE_URL` só via variável de ambiente — nunca em `config.toml` (segredo).
- Acesso ao Postgres via SQLModel/SQLAlchemy com connection string padrão — nunca o SDK proprietário do Supabase (mantém migração futura trivial).
- `ContentPiece` nesta fase é **somente leitura** — criação é da fase "Motor de geração".
- Nenhuma lógica de regras de aprovação em runtime nesta fase — só a tabela `content_approval_rules` existe.
- Nenhuma UI.
- **Testes:** convenção do projeto é não escrever testes por padrão (ver `CLAUDE.md` global do usuário). Cada task abaixo usa passos de "implementar + verificar manualmente" em vez de TDD. Ao final do plano há uma nota sobre quais funções são candidatas a teste, para perguntar ao usuário depois de pronto — não escrever agora.
- **Pré-requisito de infraestrutura:** as tasks 3 e 11 (migration e smoke test end-to-end) exigem um Postgres alcançável (`DATABASE_URL` válido — Supabase ou local). Se ainda não houver um provisionado, pare nessas tasks e retome quando houver.

---

### Task 1: Dependências e engine de banco de dados

**Files:**
- Modify: `pyproject.toml` (seção `dependencies`)
- Modify: `requirements.txt`
- Create: `app/db.py`

**Interfaces:**
- Produces: `app.db.get_engine() -> sqlalchemy.Engine`, `app.db.get_session() -> Generator[sqlmodel.Session, None, None]` (FastAPI dependency), lendo `DATABASE_URL` do ambiente.

- [ ] **Step 1: Adicionar dependências**

Em `pyproject.toml`, dentro de `dependencies = [...]`, adicionar:

```toml
    "sqlmodel==0.0.22",
    "alembic==1.14.0",
    "psycopg[binary]==3.2.3",
    "cryptography==43.0.3",
```

Em `requirements.txt`, adicionar as mesmas linhas (sem colchetes/vírgula):

```
sqlmodel==0.0.22
alembic==1.14.0
psycopg[binary]==3.2.3
cryptography==43.0.3
```

- [ ] **Step 2: Instalar**

Run: `pip install -r requirements.txt`
Expected: instalação sem erro, `sqlmodel`, `alembic`, `psycopg`, `cryptography` presentes em `pip show sqlmodel`.

- [ ] **Step 3: Criar `app/db.py`**

```python
import os
from functools import lru_cache

from sqlmodel import Session, create_engine

_DATABASE_URL_ENV = "DATABASE_URL"


@lru_cache(maxsize=1)
def get_engine():
    url = os.environ.get(_DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"{_DATABASE_URL_ENV} is not set. Set it to a Postgres connection "
            "string (e.g. the Supabase project's connection string)."
        )
    return create_engine(url, pool_pre_ping=True)


def get_session():
    with Session(get_engine()) as session:
        yield session
```

- [ ] **Step 4: Verificar**

Run:
```bash
DATABASE_URL="postgresql://user:pass@localhost:5432/db" python -c "from app.db import get_engine; print(get_engine())"
```
Expected: imprime um objeto `Engine(postgresql://user:***@localhost:5432/db)` sem tentar conectar (SQLAlchemy `create_engine` é lazy).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt app/db.py
git commit -m "feat(content): add db engine module and postgres deps"
```

---

### Task 2: Modelo de dados (entidades + DTOs)

**Files:**
- Create: `app/models/content.py`

**Interfaces:**
- Consumes: nada (base do módulo).
- Produces: modelos de tabela `ContentTenant`, `ContentClient`, `ContentSocialAccount`, `ContentCampaign`, `ContentPiece`, `ContentApprovalRule`, `ContentAuditLog`; enums `EntitlementStatus`, `ContentPieceType`, `ContentPieceStatus`, `ApprovalAction`; DTOs `TenantCreate`, `TenantRead`, `TenantCreateResponse`, `ClientCreate`, `ClientRead`, `SocialAccountCreate`, `SocialAccountRead`, `CampaignCreate`, `CampaignRead`, `ApprovalRuleCreate`, `ApprovalRuleRead`, `ContentPieceRead`. Todas as tasks seguintes importam deste arquivo.

- [ ] **Step 1: Criar `app/models/content.py`**

```python
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class EntitlementStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    trial = "trial"


class ContentPieceType(str, Enum):
    video = "video"
    image = "image"
    audio = "audio"


class ContentPieceStatus(str, Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    posted = "posted"
    failed = "failed"


class ApprovalAction(str, Enum):
    auto_approve = "auto_approve"
    require_review = "require_review"


# --- Tabelas ---------------------------------------------------------------


class ContentTenant(SQLModel, table=True):
    __tablename__ = "content_tenants"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: str = Field(index=True)
    name: str
    slug: str = Field(unique=True, index=True)
    api_token_hash: str = Field(unique=True, index=True)
    entitlement_status: EntitlementStatus = Field(default=EntitlementStatus.trial)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentClient(SQLModel, table=True):
    __tablename__ = "content_clients"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentSocialAccount(SQLModel, table=True):
    __tablename__ = "content_social_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    platform: str
    external_account_id: str
    credentials_encrypted: str
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentCampaign(SQLModel, table=True):
    __tablename__ = "content_campaigns"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    name: str
    horizon_days: int = Field(default=7)
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentPiece(SQLModel, table=True):
    __tablename__ = "content_pieces"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="content_campaigns.id", index=True)
    type: ContentPieceType
    status: ContentPieceStatus = Field(default=ContentPieceStatus.draft)
    asset_url: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    idempotency_key: Optional[str] = Field(default=None, unique=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ContentApprovalRule(SQLModel, table=True):
    __tablename__ = "content_approval_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="content_campaigns.id", index=True)
    condition: dict = Field(default_factory=dict, sa_column=Column(JSON))
    action: ApprovalAction
    priority: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentAuditLog(SQLModel, table=True):
    __tablename__ = "content_audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    entity_type: str
    entity_id: int
    action: str
    actor: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- DTOs --------------------------------------------------------------


class TenantCreate(BaseModel):
    owner_user_id: str
    name: str
    slug: str


class TenantRead(BaseModel):
    id: int
    owner_user_id: str
    name: str
    slug: str
    entitlement_status: EntitlementStatus
    created_at: datetime


class TenantCreateResponse(TenantRead):
    api_token: str


class ClientCreate(BaseModel):
    name: str


class ClientRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    created_at: datetime


class SocialAccountCreate(BaseModel):
    client_id: int
    platform: str
    external_account_id: str
    credentials: str


class SocialAccountRead(BaseModel):
    id: int
    client_id: int
    platform: str
    external_account_id: str
    status: str
    created_at: datetime


class CampaignCreate(BaseModel):
    client_id: int
    name: str
    horizon_days: int = 7


class CampaignRead(BaseModel):
    id: int
    client_id: int
    name: str
    horizon_days: int
    status: str
    created_at: datetime


class ApprovalRuleCreate(BaseModel):
    campaign_id: int
    condition: dict
    action: ApprovalAction
    priority: int = 0


class ApprovalRuleRead(BaseModel):
    id: int
    campaign_id: int
    condition: dict
    action: ApprovalAction
    priority: int
    created_at: datetime


class ContentPieceRead(BaseModel):
    id: int
    campaign_id: int
    type: ContentPieceType
    status: ContentPieceStatus
    asset_url: Optional[str]
    scheduled_for: Optional[datetime]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Verificar**

Run:
```bash
python -c "
from sqlmodel import SQLModel
import app.models.content as c
print(sorted(SQLModel.metadata.tables.keys()))
"
```
Expected: `['content_approval_rules', 'content_audit_logs', 'content_campaigns', 'content_clients', 'content_pieces', 'content_social_accounts', 'content_tenants']`

- [ ] **Step 3: Commit**

```bash
git add app/models/content.py
git commit -m "feat(content): add content module data model"
```

---

### Task 3: Alembic — setup e migration inicial

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/.gitkeep`

**Interfaces:**
- Consumes: `app.models.content` (Task 2) para `SQLModel.metadata`; `DATABASE_URL` do ambiente.
- Produces: comando `alembic upgrade head` cria as 7 tabelas no Postgres configurado.

- [ ] **Step 1: Criar `alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Criar `alembic/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 3: Criar `alembic/env.py`**

```python
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.models.content  # noqa: E402,F401  (registra as tabelas no metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Criar diretório de versions**

Run: `mkdir -p alembic/versions && touch alembic/versions/.gitkeep`

- [ ] **Step 5: Gerar a migration inicial** (requer `DATABASE_URL` alcançável)

Run:
```bash
DATABASE_URL="<connection string do Postgres/Supabase>" alembic revision --autogenerate -m "create content module tables"
```
Expected: cria `alembic/versions/<hash>_create_content_module_tables.py` com `op.create_table(...)` para as 7 tabelas. Abrir o arquivo gerado e conferir que as 7 tabelas e seus índices/FKs aparecem.

- [ ] **Step 6: Aplicar a migration**

Run:
```bash
DATABASE_URL="<connection string>" alembic upgrade head
```
Expected: saída `Running upgrade -> <hash>, create content module tables`, sem erro.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat(content): add alembic setup and initial migration"
```

---

### Task 4: Helpers de criptografia e audit log

**Files:**
- Create: `app/services/content/__init__.py`
- Create: `app/services/content/crypto.py`
- Create: `app/services/content/audit.py`

**Interfaces:**
- Consumes: `app.models.content.ContentAuditLog` (Task 2).
- Produces: `encrypt_credentials(str) -> str`, `decrypt_credentials(str) -> str`, `generate_api_token() -> str`, `hash_api_token(str) -> str`, `write_audit_log(session, *, tenant_id, entity_type, entity_id, action, actor) -> ContentAuditLog`. Usados por todas as tasks seguintes.

- [ ] **Step 1: Criar `app/services/content/__init__.py`** (vazio, marca o pacote)

- [ ] **Step 2: Criar `app/services/content/crypto.py`**

```python
import hashlib
import os
import secrets

from cryptography.fernet import Fernet

_ENCRYPTION_KEY_ENV = "CONTENT_MODULE_ENCRYPTION_KEY"


def _fernet() -> Fernet:
    key = os.environ.get(_ENCRYPTION_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{_ENCRYPTION_KEY_ENV} is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and set it as an env var."
        )
    return Fernet(key.encode())


def encrypt_credentials(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_credentials(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
```

- [ ] **Step 3: Criar `app/services/content/audit.py`**

```python
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
```

- [ ] **Step 4: Verificar**

Run:
```bash
CONTENT_MODULE_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") \
python -c "
import os
from app.services.content.crypto import encrypt_credentials, decrypt_credentials, generate_api_token, hash_api_token
c = encrypt_credentials('secret-token')
assert decrypt_credentials(c) == 'secret-token'
t = generate_api_token()
assert hash_api_token(t) == hash_api_token(t)
assert hash_api_token(t) != t
print('ok')
"
```
Expected: imprime `ok`.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/__init__.py app/services/content/crypto.py app/services/content/audit.py
git commit -m "feat(content): add crypto and audit log helpers"
```

---

### Task 5: Autenticação (admin + tenant) e CRUD de Tenant

**Files:**
- Create: `app/controllers/content_auth.py`
- Create: `app/services/content/tenants.py`
- Create: `app/controllers/v1/content/__init__.py`
- Create: `app/controllers/v1/content/tenants.py`

**Interfaces:**
- Consumes: `app.db.get_session` (Task 1), `app.models.content.{ContentTenant, EntitlementStatus, TenantCreate, TenantRead, TenantCreateResponse}` (Task 2), `app.services.content.crypto.{generate_api_token, hash_api_token}` e `app.services.content.audit.write_audit_log` (Task 4).
- Produces: dependency `verify_admin_token` (protege provisionamento), dependency `verify_tenant_token(...) -> ContentTenant` (usada por todas as tasks seguintes), serviço `tenants_service.{create_tenant, list_tenants, get_tenant}`, router `content.tenants.router`.

- [ ] **Step 1: Criar `app/controllers/content_auth.py`**

```python
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
    if not x_admin_token or not secrets.compare_digest(x_admin_token, configured):
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
```

- [ ] **Step 2: Criar `app/services/content/tenants.py`**

```python
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
```

- [ ] **Step 3: Criar `app/controllers/v1/content/__init__.py`** (vazio, marca o pacote)

- [ ] **Step 4: Criar `app/controllers/v1/content/tenants.py`**

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import TenantCreate, TenantCreateResponse, TenantRead
from app.services.content import audit
from app.services.content import tenants as tenants_service

router = new_router(dependencies=[Depends(content_auth.verify_admin_token)])


@router.post("/content/tenants", response_model=TenantCreateResponse, status_code=201)
def create_tenant(payload: TenantCreate, session: Session = Depends(get_session)):
    tenant, plaintext_token = tenants_service.create_tenant(
        session,
        owner_user_id=payload.owner_user_id,
        name=payload.name,
        slug=payload.slug,
    )
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="tenant",
        entity_id=tenant.id,
        action="created",
        actor="admin",
    )
    return TenantCreateResponse(**tenant.model_dump(), api_token=plaintext_token)


@router.get("/content/tenants", response_model=list[TenantRead])
def list_tenants(session: Session = Depends(get_session)):
    return tenants_service.list_tenants(session)


@router.get("/content/tenants/{tenant_id}", response_model=TenantRead)
def get_tenant(tenant_id: int, session: Session = Depends(get_session)):
    tenant = tenants_service.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant
```

- [ ] **Step 5: Commit**

```bash
git add app/controllers/content_auth.py app/services/content/tenants.py app/controllers/v1/content/
git commit -m "feat(content): add admin/tenant auth and tenant CRUD"
```

---

### Task 6: CRUD de Client (tenant-scoped)

**Files:**
- Create: `app/services/content/clients.py`
- Create: `app/controllers/v1/content/clients.py`

**Interfaces:**
- Consumes: `content_auth.verify_tenant_token` (Task 5), `app.models.content.{ContentClient, ClientCreate, ClientRead}` (Task 2), `audit.write_audit_log` (Task 4).
- Produces: `clients_service.{create_client, list_clients, get_client}`, router `content.clients.router`. `get_client`/`list_clients` retornam apenas registros do tenant autenticado (usados como padrão de ownership check pelas tasks seguintes).

- [ ] **Step 1: Criar `app/services/content/clients.py`**

```python
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
```

- [ ] **Step 2: Criar `app/controllers/v1/content/clients.py`**

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ClientCreate, ClientRead, ContentTenant
from app.services.content import audit
from app.services.content import clients as clients_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/clients", response_model=ClientRead, status_code=201)
def create_client(
    payload: ClientCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    client = clients_service.create_client(session, tenant_id=tenant.id, name=payload.name)
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return client


@router.get("/content/clients", response_model=list[ClientRead])
def list_clients(
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return clients_service.list_clients(session, tenant_id=tenant.id)


@router.get("/content/clients/{client_id}", response_model=ClientRead)
def get_client(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    client = clients_service.get_client(session, tenant_id=tenant.id, client_id=client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client
```

- [ ] **Step 3: Commit**

```bash
git add app/services/content/clients.py app/controllers/v1/content/clients.py
git commit -m "feat(content): add tenant-scoped client CRUD"
```

---

### Task 7: CRUD de SocialAccount (tenant-scoped, credenciais criptografadas)

**Files:**
- Create: `app/services/content/social_accounts.py`
- Create: `app/controllers/v1/content/social_accounts.py`

**Interfaces:**
- Consumes: `clients_service` (Task 6, para checar ownership de `client_id`), `crypto.encrypt_credentials` (Task 4), `content_auth.verify_tenant_token` (Task 5).
- Produces: `social_accounts_service.{create_social_account, list_social_accounts}`, router `content.social_accounts.router`. `create_social_account` retorna `None` quando `client_id` não pertence ao tenant autenticado — o controller converte isso em 404 (nunca vaza a existência do client de outro tenant).

- [ ] **Step 1: Criar `app/services/content/social_accounts.py`**

```python
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
```

- [ ] **Step 2: Criar `app/controllers/v1/content/social_accounts.py`**

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentTenant, SocialAccountCreate, SocialAccountRead
from app.services.content import audit
from app.services.content import social_accounts as social_accounts_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post(
    "/content/social-accounts", response_model=SocialAccountRead, status_code=201
)
def create_social_account(
    payload: SocialAccountCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    account = social_accounts_service.create_social_account(
        session,
        tenant_id=tenant.id,
        client_id=payload.client_id,
        platform=payload.platform,
        external_account_id=payload.external_account_id,
        credentials=payload.credentials,
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return account


@router.get("/content/clients/{client_id}/social-accounts", response_model=list[SocialAccountRead])
def list_social_accounts(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return social_accounts_service.list_social_accounts(
        session, tenant_id=tenant.id, client_id=client_id
    )
```

- [ ] **Step 3: Commit**

```bash
git add app/services/content/social_accounts.py app/controllers/v1/content/social_accounts.py
git commit -m "feat(content): add tenant-scoped social account CRUD"
```

---

### Task 8: CRUD de Campaign (tenant-scoped)

**Files:**
- Create: `app/services/content/campaigns.py`
- Create: `app/controllers/v1/content/campaigns.py`

**Interfaces:**
- Consumes: `clients_service.get_client` (Task 6, ownership check), `content_auth.verify_tenant_token` (Task 5).
- Produces: `campaigns_service.{create_campaign, list_campaigns, get_campaign}` — `get_campaign` retorna `None` se a campanha não pertencer (via client) ao tenant; usado pelas tasks 9 e 10 para checar ownership em cadeia.

- [ ] **Step 1: Criar `app/services/content/campaigns.py`**

```python
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient
from app.services.content.clients import get_client


def create_campaign(
    session: Session, *, tenant_id: int, client_id: int, name: str, horizon_days: int
) -> Optional[ContentCampaign]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return None
    campaign = ContentCampaign(client_id=client_id, name=name, horizon_days=horizon_days)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


def list_campaigns(
    session: Session, *, tenant_id: int, client_id: int
) -> List[ContentCampaign]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return []
    return list(
        session.exec(
            select(ContentCampaign).where(ContentCampaign.client_id == client_id)
        ).all()
    )


def get_campaign(
    session: Session, *, tenant_id: int, campaign_id: int
) -> Optional[ContentCampaign]:
    return session.exec(
        select(ContentCampaign)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(ContentCampaign.id == campaign_id, ContentClient.tenant_id == tenant_id)
    ).first()
```

- [ ] **Step 2: Criar `app/controllers/v1/content/campaigns.py`**

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import CampaignCreate, CampaignRead, ContentTenant
from app.services.content import audit
from app.services.content import campaigns as campaigns_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/campaigns", response_model=CampaignRead, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    campaign = campaigns_service.create_campaign(
        session,
        tenant_id=tenant.id,
        client_id=payload.client_id,
        name=payload.name,
        horizon_days=payload.horizon_days,
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return campaign


@router.get("/content/clients/{client_id}/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return campaigns_service.list_campaigns(session, tenant_id=tenant.id, client_id=client_id)


@router.get("/content/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    campaign = campaigns_service.get_campaign(session, tenant_id=tenant.id, campaign_id=campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign
```

- [ ] **Step 3: Commit**

```bash
git add app/services/content/campaigns.py app/controllers/v1/content/campaigns.py
git commit -m "feat(content): add tenant-scoped campaign CRUD"
```

---

### Task 9: CRUD de ApprovalRule (tenant-scoped, via campaign)

**Files:**
- Create: `app/services/content/approval_rules.py`
- Create: `app/controllers/v1/content/approval_rules.py`

**Interfaces:**
- Consumes: `campaigns_service.get_campaign` (Task 8, ownership check em cadeia campaign→client→tenant).
- Produces: `approval_rules_service.{create_approval_rule, list_approval_rules}`.

- [ ] **Step 1: Criar `app/services/content/approval_rules.py`**

```python
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ApprovalAction, ContentApprovalRule
from app.services.content.campaigns import get_campaign


def create_approval_rule(
    session: Session,
    *,
    tenant_id: int,
    campaign_id: int,
    condition: dict,
    action: ApprovalAction,
    priority: int,
) -> Optional[ContentApprovalRule]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return None
    rule = ContentApprovalRule(
        campaign_id=campaign_id, condition=condition, action=action, priority=priority
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def list_approval_rules(
    session: Session, *, tenant_id: int, campaign_id: int
) -> List[ContentApprovalRule]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return []
    return list(
        session.exec(
            select(ContentApprovalRule)
            .where(ContentApprovalRule.campaign_id == campaign_id)
            .order_by(ContentApprovalRule.priority.desc())
        ).all()
    )
```

- [ ] **Step 2: Criar `app/controllers/v1/content/approval_rules.py`**

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ApprovalRuleCreate, ApprovalRuleRead, ContentTenant
from app.services.content import audit
from app.services.content import approval_rules as approval_rules_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/approval-rules", response_model=ApprovalRuleRead, status_code=201)
def create_approval_rule(
    payload: ApprovalRuleCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    rule = approval_rules_service.create_approval_rule(
        session,
        tenant_id=tenant.id,
        campaign_id=payload.campaign_id,
        condition=payload.condition,
        action=payload.action,
        priority=payload.priority,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="approval_rule",
        entity_id=rule.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return rule


@router.get(
    "/content/campaigns/{campaign_id}/approval-rules",
    response_model=list[ApprovalRuleRead],
)
def list_approval_rules(
    campaign_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return approval_rules_service.list_approval_rules(
        session, tenant_id=tenant.id, campaign_id=campaign_id
    )
```

- [ ] **Step 3: Commit**

```bash
git add app/services/content/approval_rules.py app/controllers/v1/content/approval_rules.py
git commit -m "feat(content): add tenant-scoped approval rule CRUD"
```

---

### Task 10: Leitura de ContentPiece (somente leitura)

**Files:**
- Create: `app/services/content/pieces.py`
- Create: `app/controllers/v1/content/pieces.py`

**Interfaces:**
- Consumes: `campaigns_service.get_campaign` (Task 8, ownership check).
- Produces: `pieces_service.{list_pieces, get_piece}`. Não há `create`/`update` nesta fase (ver Global Constraints) — a fase "Motor de geração" adiciona escrita reaproveitando este módulo.

- [ ] **Step 1: Criar `app/services/content/pieces.py`**

```python
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient, ContentPiece
from app.services.content.campaigns import get_campaign


def list_pieces(
    session: Session, *, tenant_id: int, campaign_id: int
) -> List[ContentPiece]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return []
    return list(
        session.exec(
            select(ContentPiece).where(ContentPiece.campaign_id == campaign_id)
        ).all()
    )


def get_piece(session: Session, *, tenant_id: int, piece_id: int) -> Optional[ContentPiece]:
    return session.exec(
        select(ContentPiece)
        .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(ContentPiece.id == piece_id, ContentClient.tenant_id == tenant_id)
    ).first()
```

- [ ] **Step 2: Criar `app/controllers/v1/content/pieces.py`**

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentPieceRead, ContentTenant
from app.services.content import pieces as pieces_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.get(
    "/content/campaigns/{campaign_id}/pieces", response_model=list[ContentPieceRead]
)
def list_pieces(
    campaign_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return pieces_service.list_pieces(session, tenant_id=tenant.id, campaign_id=campaign_id)


@router.get("/content/pieces/{piece_id}", response_model=ContentPieceRead)
def get_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return piece
```

- [ ] **Step 3: Commit**

```bash
git add app/services/content/pieces.py app/controllers/v1/content/pieces.py
git commit -m "feat(content): add read-only content piece endpoints"
```

---

### Task 11: Registrar routers e smoke test end-to-end

**Files:**
- Modify: `app/router.py`

**Interfaces:**
- Consumes: todos os `router` das tasks 5–10.
- Produces: API completa montada em `app.asgi:app`, acessível em `/api/v1/content/*`.

- [ ] **Step 1: Ler o `app/router.py` atual e adicionar os novos routers**

Adicionar os imports e `include_router` seguindo o padrão existente (`ping`, `video`, `llm`):

```python
from app.controllers.v1.content import (
    approval_rules,
    campaigns,
    clients,
    pieces,
    social_accounts,
    tenants,
)

# ... junto aos include_router existentes:
root_api_router.include_router(tenants.router)
root_api_router.include_router(clients.router)
root_api_router.include_router(social_accounts.router)
root_api_router.include_router(campaigns.router)
root_api_router.include_router(approval_rules.router)
root_api_router.include_router(pieces.router)
```

Aplique isso mantendo os imports e `include_router` já existentes (`ping`, `video`, `llm`) — não remova nada.

- [ ] **Step 2: Smoke test end-to-end** (requer `DATABASE_URL` com a migration da Task 3 já aplicada)

Run:
```bash
export DATABASE_URL="<connection string>"
export CONTENT_ADMIN_TOKEN="dev-admin-token"
export CONTENT_MODULE_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python main.py &
sleep 2

# 1. Provisionar tenant (admin)
TENANT_JSON=$(curl -s -X POST http://127.0.0.1:8080/api/v1/content/tenants \
  -H "x-admin-token: dev-admin-token" -H "Content-Type: application/json" \
  -d '{"owner_user_id":"u1","name":"Acme Agency","slug":"acme"}')
echo "$TENANT_JSON"
TENANT_TOKEN=$(echo "$TENANT_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_token'])")

# 2. Criar client com o token do tenant
CLIENT_JSON=$(curl -s -X POST http://127.0.0.1:8080/api/v1/content/clients \
  -H "x-tenant-token: $TENANT_TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Cliente Final A"}')
echo "$CLIENT_JSON"

# 3. Sem token deve dar 401
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/v1/content/clients
```

Expected:
- Passo 1 retorna JSON com `id`, `slug: "acme"`, `entitlement_status: "trial"` e `api_token`.
- Passo 2 retorna JSON com `id`, `tenant_id` (igual ao id do tenant criado), `name: "Cliente Final A"`.
- Passo 3 imprime `401`.

Encerrar o servidor: `kill %1`

- [ ] **Step 3: Commit**

```bash
git add app/router.py
git commit -m "feat(content): register content module routers"
```

---

## Notas finais

**Candidatos a teste (perguntar ao usuário depois de pronto, não escrever agora):** `content_auth.verify_tenant_token` e `verify_admin_token` (lógica de segurança — token inválido, tenant inativo, header ausente) e os helpers de `crypto.py` (roundtrip de criptografia, hash determinístico). Essas são as peças mais "críticas" no sentido do `CLAUDE.md` do usuário (não são cálculo financeiro, mas são a fronteira de autenticação/isolamento multi-tenant).

**Fora deste plano:** geração de imagens, integrações de postagem, motor de regras em runtime, UI — cada um vira seu próprio plano a partir da respectiva spec futura (ver `docs/superpowers/specs/2026-08-27-fundacao-modulo-conteudo-design.md`, seção "Contexto e roadmap").
