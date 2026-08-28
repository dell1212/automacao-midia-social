# Motor de publicação (redes sociais) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao módulo de conteúdo a capacidade de publicar uma `ContentPiece` aprovada em contas
sociais (Instagram, TikTok, YouTube, X, Facebook, LinkedIn), com execução assíncrona rastreável,
retry operacional sem bloquear worker, e proteção contra publicação concorrente duplicada.

**Architecture:** Adapter direto por plataforma (`app/services/content/publishers/`) atrás de uma
interface comum. `POST /publish` só cria linhas em `content_social_publications`
(`status=queued`); um dispatcher em thread própria (registrado no lifespan da aplicação) captura
linhas elegíveis via `SELECT ... FOR UPDATE SKIP LOCKED`, roda o adapter num pool compartilhado com
semáforo por plataforma, e persiste `next_run_at` em vez de dormir o worker em retry.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy (Postgres), Alembic, `requests`, `threading`
(`ThreadPoolExecutor` + `BoundedSemaphore`), `unittest`/`unittest.mock` (padrão de teste já em uso
no módulo).

**Spec:** `docs/superpowers/specs/2026-08-28-motor-publicacao-redes-sociais-design.md`

## Global Constraints

- Python `>=3.11`, FastAPI `0.136.3`, SQLModel `0.0.22`, Alembic `1.14.0` (versões já fixadas no
  projeto — não alterar).
- Enums de coluna sempre via `from sqlalchemy import Enum as SAEnum`, `sa_column=Column(SAEnum(Enum,
  name="..."))`, com `name=` explícito.
- Colunas jsonb usam `from sqlalchemy import JSON, Column` (JSON genérico do SQLAlchemy core) — o
  projeto **não** usa `sqlalchemy.dialects.postgresql.JSONB`.
- Services recebem `session: Session` como parâmetro (nunca abrem sessão própria, exceto código que
  roda em thread separada de um `ThreadPoolExecutor`, que usa `Session(get_engine())` diretamente).
  Padrão de escrita: `session.add(row)` → `session.commit()` → `session.refresh(row)`. Sem
  try/except nos services — erro propaga.
- Controllers de `app/controllers/v1/content/` usam `fastapi.HTTPException` (não
  `app.models.exception.HttpException`, que é do resto do app). Router via
  `new_router(dependencies=[Depends(content_auth.verify_tenant_token)])`
  (`app/controllers/v1/base.py`); cada handler redeclara
  `tenant: ContentTenant = Depends(content_auth.verify_tenant_token)` para obter o objeto.
- Credenciais: sempre `encrypt_credentials`/`decrypt_credentials` de
  `app/services/content/crypto.py` (Fernet, chave em `CONTENT_MODULE_ENCRYPTION_KEY`).
- Testes: `unittest.TestCase` + `unittest.mock.MagicMock`/`patch`, arquivos em
  `test/services/test_content_<nome>.py`. Não há Postgres real na suíte local — sessão é sempre
  mockada. `SELECT ... FOR UPDATE SKIP LOCKED` não é exercitável em teste unitário; a query em si é
  testada mockando a cadeia `session.exec(...)`, não o locking real.
- `PublicationErrorCode`/`PublicationError` são taxonomia própria — não reaproveitam
  `GenerationErrorCode`/`GenerationError` de `app/services/content/errors.py` (domínios distintos,
  ver spec).

---

## File Structure

```
app/models/
  content.py                          (modificar: + publication_summary em ContentPiece)
  content_publishing.py               (novo: PublicationStatus, ContentSocialPublication, DTOs)

app/services/content/
  publish_errors.py                   (novo: PublicationErrorCode, PublicationError, classify_http_status)
  publications.py                     (novo: idempotência/CRUD de ContentSocialPublication)
  publish_dispatcher.py               (novo: claim atômico, execução, pool+semáforo, thread loop)
  publishers/
    __init__.py                       (novo: importa os 6 módulos, populando o registry)
    base.py                           (novo: PublisherAdapter, PublishResult, registry, HTTP helpers)
    instagram.py
    tiktok.py
    youtube.py
    x.py
    facebook.py
    linkedin.py

app/controllers/v1/content/
  publications.py                     (novo: POST /publish, GET /publications)

app/router.py                         (modificar: registrar o novo router)
app/asgi.py                           (modificar: start/stop do dispatcher no lifespan)
config.example.toml                   (modificar: documentar CONTENT_PUBLISH_*)

alembic/versions/
  b6a1f9c3d2e7_add_content_social_publications.py   (novo)

test/services/
  test_content_publish_errors.py
  test_content_publishers_base.py
  test_content_publishers_instagram.py
  test_content_publishers_tiktok.py
  test_content_publishers_youtube.py
  test_content_publishers_x.py
  test_content_publishers_facebook.py
  test_content_publishers_linkedin.py
  test_content_publications.py
  test_content_publish_dispatcher.py
```

---

### Task 1: Modelo de dados — `ContentSocialPublication` + `publication_summary`

**Files:**
- Create: `app/models/content_publishing.py`
- Modify: `app/models/content.py` (adiciona `publication_summary` em `ContentPiece`)
- Create: `alembic/versions/b6a1f9c3d2e7_add_content_social_publications.py`

**Interfaces:**
- Produces: `PublicationStatus` (enum: `queued|running|retrying|succeeded|failed`),
  `ContentSocialPublication` (SQLModel table `content_social_publications`, campos:
  `id, tenant_id, client_id, content_piece_id, social_account_id, platform, status, attempt_count,
  max_attempts, publication_cycle, next_run_at, platform_post_id, platform_post_url, error_code,
  error_message, request_payload, created_at, updated_at, completed_at`), DTOs `PublishRequest`
  (`social_account_ids: list[int]`), `PublishAcceptedItem`, `PublishRejectedItem`,
  `PublishResponse`, `PublicationRead`. `ContentPiece.publication_summary: Optional[dict]`.

Não há teste dedicado para classes de modelo puro neste projeto (não existe teste para
`ContentGenerationJob`/`ContentAsset` em `app/models/content_generation.py`) — este task não segue
TDD, mas inclui um passo de verificação de import/instanciação.

- [ ] **Step 1: Criar `app/models/content_publishing.py`**

```python
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class PublicationStatus(str, Enum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    succeeded = "succeeded"
    failed = "failed"


class ContentSocialPublication(SQLModel, table=True):
    __tablename__ = "content_social_publications"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    social_account_id: int = Field(foreign_key="content_social_accounts.id", index=True)
    platform: str
    status: PublicationStatus = Field(
        default=PublicationStatus.queued,
        sa_column=Column(SAEnum(PublicationStatus, name="content_social_publication_status")),
    )
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=3)
    publication_cycle: int = Field(default=1)
    next_run_at: Optional[datetime] = None
    platform_post_id: Optional[str] = None
    platform_post_url: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    request_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# --- DTOs --------------------------------------------------------------


class PublishRequest(BaseModel):
    social_account_ids: list[int]


class PublishAcceptedItem(BaseModel):
    social_account_id: int
    platform: str
    status: str


class PublishRejectedItem(BaseModel):
    social_account_id: int
    platform: Optional[str]
    reason: str
    message: str


class PublishResponse(BaseModel):
    accepted: list[PublishAcceptedItem]
    rejected: list[PublishRejectedItem]


class PublicationRead(BaseModel):
    id: int
    content_piece_id: int
    social_account_id: int
    platform: str
    status: PublicationStatus
    attempt_count: int
    max_attempts: int
    publication_cycle: int
    platform_post_id: Optional[str]
    platform_post_url: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
```

- [ ] **Step 2: Adicionar `UniqueConstraint` do par piece/conta**

Edite `ContentSocialPublication` para incluir `__table_args__` (igual ao padrão já usado em
`ContentPiece` em `app/models/content.py:109-113`):

```python
class ContentSocialPublication(SQLModel, table=True):
    __tablename__ = "content_social_publications"
    __table_args__ = (
        UniqueConstraint(
            "content_piece_id",
            "social_account_id",
            name="uq_content_social_publications_piece_account",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # ... (resto igual ao Step 1)
```

E ajuste o import no topo do arquivo:

```python
from sqlalchemy import JSON, Column, UniqueConstraint
```

- [ ] **Step 3: Adicionar `publication_summary` em `ContentPiece`**

Em `app/models/content.py`, dentro da classe `ContentPiece` (logo após `posted_at: Optional[datetime]
= None`, linha 126):

```python
    posted_at: Optional[datetime] = None
    publication_summary: Optional[dict] = Field(default=None, sa_column=Column(JSON))
```

`JSON` já está importado no topo do arquivo (`from sqlalchemy import JSON, Column,
UniqueConstraint`, linha 6) — não precisa editar o import.

- [ ] **Step 4: Verificar que os módulos importam sem erro**

Run: `python -c "from app.models.content_publishing import ContentSocialPublication, PublicationStatus; from app.models.content import ContentPiece; print(ContentPiece.__table__.c.publication_summary)"`
Expected: imprime a coluna sem levantar exceção.

- [ ] **Step 5: Criar a migration Alembic**

Crie `alembic/versions/b6a1f9c3d2e7_add_content_social_publications.py`:

```python
"""add content_social_publications table

Revision ID: b6a1f9c3d2e7
Revises: 574ed629fa1f
Create Date: 2026-08-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'b6a1f9c3d2e7'
down_revision = '574ed629fa1f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'content_social_publications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('content_piece_id', sa.Integer(), nullable=False),
        sa.Column('social_account_id', sa.Integer(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('queued', 'running', 'retrying', 'succeeded', 'failed', name='content_social_publication_status'),
            nullable=False,
        ),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('publication_cycle', sa.Integer(), nullable=False),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('platform_post_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('platform_post_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('error_code', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('request_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['content_tenants.id']),
        sa.ForeignKeyConstraint(['client_id'], ['content_clients.id']),
        sa.ForeignKeyConstraint(['content_piece_id'], ['content_pieces.id']),
        sa.ForeignKeyConstraint(['social_account_id'], ['content_social_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'content_piece_id', 'social_account_id',
            name='uq_content_social_publications_piece_account',
        ),
    )
    op.create_index(
        op.f('ix_content_social_publications_tenant_id'),
        'content_social_publications', ['tenant_id'], unique=False,
    )
    op.create_index(
        op.f('ix_content_social_publications_client_id'),
        'content_social_publications', ['client_id'], unique=False,
    )
    op.create_index(
        op.f('ix_content_social_publications_content_piece_id'),
        'content_social_publications', ['content_piece_id'], unique=False,
    )
    op.create_index(
        op.f('ix_content_social_publications_social_account_id'),
        'content_social_publications', ['social_account_id'], unique=False,
    )
    # Dispatcher claim query filters on (status, next_run_at) together —
    # a composite index keeps that scan cheap as the table grows.
    op.create_index(
        'ix_content_social_publications_status_next_run_at',
        'content_social_publications', ['status', 'next_run_at'], unique=False,
    )
    op.add_column('content_pieces', sa.Column('publication_summary', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('content_pieces', 'publication_summary')
    op.drop_index(
        'ix_content_social_publications_status_next_run_at',
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_social_account_id'),
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_content_piece_id'),
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_client_id'),
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_tenant_id'),
        table_name='content_social_publications',
    )
    op.drop_table('content_social_publications')
    sa.Enum(name='content_social_publication_status').drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 6: Commit**

```bash
git add app/models/content_publishing.py app/models/content.py alembic/versions/b6a1f9c3d2e7_add_content_social_publications.py
git commit -m "feat(content): add content_social_publications model and migration"
```

---

### Task 2: Taxonomia de erro — `PublicationErrorCode`

**Files:**
- Create: `app/services/content/publish_errors.py`
- Test: `test/services/test_content_publish_errors.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces: `PublicationErrorCode` (enum: `rate_limit|transient|invalid_credentials|invalid_params|
  content_policy|unsupported_capability`), `PublicationError(Exception)` (`.code`, `.message`),
  `is_retryable(code) -> bool`, `classify_http_status(status_code: int) -> PublicationErrorCode`.

- [ ] **Step 1: Escrever o teste (mirror de `test/services/test_content_retry.py::TestErrorClassification`)**

```python
import unittest

from app.services.content.publish_errors import (
    PublicationErrorCode,
    classify_http_status,
    is_retryable,
)


class TestPublicationErrorClassification(unittest.TestCase):
    def test_rate_limit_is_retryable(self):
        self.assertTrue(is_retryable(PublicationErrorCode.rate_limit))

    def test_transient_is_retryable(self):
        self.assertTrue(is_retryable(PublicationErrorCode.transient))

    def test_invalid_credentials_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.invalid_credentials))

    def test_invalid_params_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.invalid_params))

    def test_content_policy_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.content_policy))

    def test_unsupported_capability_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.unsupported_capability))

    def test_http_429_maps_to_rate_limit(self):
        self.assertEqual(classify_http_status(429), PublicationErrorCode.rate_limit)

    def test_http_5xx_maps_to_transient(self):
        self.assertEqual(classify_http_status(503), PublicationErrorCode.transient)

    def test_http_401_maps_to_invalid_credentials(self):
        self.assertEqual(classify_http_status(401), PublicationErrorCode.invalid_credentials)

    def test_http_403_maps_to_invalid_credentials(self):
        self.assertEqual(classify_http_status(403), PublicationErrorCode.invalid_credentials)

    def test_http_400_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(400), PublicationErrorCode.invalid_params)

    def test_http_422_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(422), PublicationErrorCode.invalid_params)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publish_errors.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.content.publish_errors'`

- [ ] **Step 3: Implementar `app/services/content/publish_errors.py`**

```python
from enum import Enum


class PublicationErrorCode(str, Enum):
    rate_limit = "rate_limit"
    transient = "transient"
    invalid_credentials = "invalid_credentials"
    invalid_params = "invalid_params"
    content_policy = "content_policy"
    unsupported_capability = "unsupported_capability"


# Only the moment-dependent failures are worth retrying — a bad token or a
# rejected upload fails identically on every attempt.
RETRYABLE_ERROR_CODES = frozenset(
    {PublicationErrorCode.rate_limit, PublicationErrorCode.transient}
)


class PublicationError(Exception):
    """An adapter call failed, classified into the canonical publish taxonomy."""

    def __init__(self, code: PublicationErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_retryable(code: PublicationErrorCode) -> bool:
    return code in RETRYABLE_ERROR_CODES


def classify_http_status(status_code: int) -> PublicationErrorCode:
    if status_code == 429:
        return PublicationErrorCode.rate_limit
    if status_code >= 500:
        return PublicationErrorCode.transient
    if status_code in (401, 403):
        return PublicationErrorCode.invalid_credentials
    if status_code in (400, 404, 422):
        return PublicationErrorCode.invalid_params
    return PublicationErrorCode.invalid_params
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publish_errors.py -v`
Expected: PASS (12 testes)

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publish_errors.py test/services/test_content_publish_errors.py
git commit -m "feat(content): add canonical error taxonomy for social publishing"
```

---

### Task 3: Adapter base — interface, registry e helpers HTTP

**Files:**
- Create: `app/services/content/publishers/__init__.py`
- Create: `app/services/content/publishers/base.py`
- Test: `test/services/test_content_publishers_base.py`

**Interfaces:**
- Consumes: `PublicationError`, `PublicationErrorCode`, `classify_http_status` (Task 2).
- Produces: `PublishResult(platform_post_id: str, platform_post_url: str)` (dataclass),
  `PublisherAdapter` (ABC: atributo `platform: str`, métodos abstratos
  `check_compatibility(piece, asset) -> None` e
  `publish(piece, asset, account, credentials) -> PublishResult`), `register_adapter(adapter)`,
  `get_adapter(platform: str) -> PublisherAdapter`, `load_credentials(account) -> dict`,
  `post_form(url, data=None, *, headers=None, files=None, timeout=(10, 60))`,
  `post_json(url, json_body, *, headers, timeout=(10, 60))`,
  `raise_for_response(response) -> None`.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from unittest.mock import MagicMock, patch

import requests

from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers import base


class _StubAdapter(base.PublisherAdapter):
    platform = "stub"

    def check_compatibility(self, piece, asset):
        pass

    def publish(self, piece, asset, account, credentials):
        return base.PublishResult(platform_post_id="1", platform_post_url="https://example.com/1")


class TestAdapterRegistry(unittest.TestCase):
    def setUp(self):
        base._ADAPTER_REGISTRY.clear()

    def test_registered_adapter_is_returned(self):
        adapter = _StubAdapter()
        base.register_adapter(adapter)

        self.assertIs(base.get_adapter("stub"), adapter)

    def test_unknown_platform_raises_unsupported_capability(self):
        with self.assertRaises(PublicationError) as ctx:
            base.get_adapter("myspace")

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestLoadCredentials(unittest.TestCase):
    def test_decrypts_and_parses_json(self):
        account = MagicMock(credentials_encrypted="cipher")

        with patch.object(
            base, "decrypt_credentials", return_value='{"access_token": "tok"}'
        ):
            result = base.load_credentials(account)

        self.assertEqual(result, {"access_token": "tok"})


class TestRaiseForResponse(unittest.TestCase):
    def test_success_status_does_not_raise(self):
        response = MagicMock(status_code=200)

        base.raise_for_response(response)  # should not raise

    def test_rate_limit_status_raises_rate_limit(self):
        response = MagicMock(status_code=429)
        response.json.return_value = {"error": {"message": "slow down"}}

        with self.assertRaises(PublicationError) as ctx:
            base.raise_for_response(response)

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)
        self.assertEqual(ctx.exception.message, "slow down")

    def test_error_text_mentioning_policy_overrides_status_classification(self):
        response = MagicMock(status_code=400)
        response.json.return_value = {"error": {"message": "Content violates community guideline"}}

        with self.assertRaises(PublicationError) as ctx:
            base.raise_for_response(response)

        self.assertEqual(ctx.exception.code, PublicationErrorCode.content_policy)

    def test_non_json_error_body_falls_back_to_text(self):
        response = MagicMock(status_code=500)
        response.json.side_effect = ValueError()
        response.text = "internal error"

        with self.assertRaises(PublicationError) as ctx:
            base.raise_for_response(response)

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)
        self.assertEqual(ctx.exception.message, "internal error")


class TestPostForm(unittest.TestCase):
    def test_network_error_is_classified_as_transient(self):
        with patch.object(
            base.requests, "post", side_effect=requests.ConnectionError("boom")
        ):
            with self.assertRaises(PublicationError) as ctx:
                base.post_form("https://api.example.com", data={"a": "b"})

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)

    def test_successful_response_is_returned(self):
        ok_response = MagicMock(status_code=200)

        with patch.object(base.requests, "post", return_value=ok_response):
            result = base.post_form("https://api.example.com", data={"a": "b"})

        self.assertIs(result, ok_response)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publishers_base.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.content.publishers'`

- [ ] **Step 3: Criar `app/services/content/publishers/__init__.py` (vazio por enquanto)**

```python
```

- [ ] **Step 4: Implementar `app/services/content/publishers/base.py`**

```python
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests

from app.models.content import ContentSocialAccount, ContentPiece
from app.models.content_generation import ContentAsset
from app.services.content.crypto import decrypt_credentials
from app.services.content.publish_errors import (
    PublicationError,
    PublicationErrorCode,
    classify_http_status,
)

_POLICY_KEYWORDS = (
    "policy",
    "content violat",
    "community guideline",
    "not allowed",
    "prohibited",
)


@dataclass(frozen=True)
class PublishResult:
    platform_post_id: str
    platform_post_url: str


class PublisherAdapter(ABC):
    platform: str

    @abstractmethod
    def check_compatibility(self, piece: ContentPiece, asset: ContentAsset) -> None:
        ...

    @abstractmethod
    def publish(
        self,
        piece: ContentPiece,
        asset: ContentAsset,
        account: ContentSocialAccount,
        credentials: dict,
    ) -> PublishResult:
        ...


_ADAPTER_REGISTRY: dict[str, PublisherAdapter] = {}


def register_adapter(adapter: PublisherAdapter) -> None:
    _ADAPTER_REGISTRY[adapter.platform] = adapter


def get_adapter(platform: str) -> PublisherAdapter:
    adapter = _ADAPTER_REGISTRY.get(platform)
    if adapter is None:
        raise PublicationError(
            PublicationErrorCode.unsupported_capability,
            f"No publisher adapter registered for platform '{platform}'",
        )
    return adapter


def load_credentials(account: ContentSocialAccount) -> dict:
    return json.loads(decrypt_credentials(account.credentials_encrypted))


def _extract_error_message(response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message", data))
        return str(data.get("message", data))
    return str(data)


def _looks_like_content_policy_rejection(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in _POLICY_KEYWORDS)


def raise_for_response(response) -> None:
    if response.status_code < 400:
        return
    message = _extract_error_message(response)
    code = (
        PublicationErrorCode.content_policy
        if _looks_like_content_policy_rejection(message)
        else classify_http_status(response.status_code)
    )
    raise PublicationError(code, message)


def post_form(url: str, data=None, *, headers=None, files=None, timeout=(10, 60)):
    try:
        response = requests.post(url, data=data, headers=headers, files=files, timeout=timeout)
    except requests.RequestException as exc:
        raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
    raise_for_response(response)
    return response


def post_json(url: str, json_body: dict, *, headers: dict, timeout=(10, 60)):
    try:
        response = requests.post(url, json=json_body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
    raise_for_response(response)
    return response


def get_bytes(url: str, *, timeout=(10, 120)) -> bytes:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise PublicationError(
            PublicationErrorCode.transient, f"failed to fetch asset: {exc}"
        ) from exc
    return response.content
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publishers_base.py -v`
Expected: PASS (9 testes)

- [ ] **Step 6: Commit**

```bash
git add app/services/content/publishers/__init__.py app/services/content/publishers/base.py test/services/test_content_publishers_base.py
git commit -m "feat(content): add publisher adapter interface, registry and HTTP helpers"
```

---

### Task 4: Adapter Instagram

**Files:**
- Create: `app/services/content/publishers/instagram.py`
- Modify: `app/services/content/publishers/__init__.py`
- Test: `test/services/test_content_publishers_instagram.py`

**Interfaces:**
- Consumes: `PublisherAdapter`, `PublishResult`, `register_adapter`, `post_form`, `load_credentials`
  (Task 3); `PublicationError`, `PublicationErrorCode` (Task 2); `ContentPieceType` (existente,
  `app/models/content.py`).
- Produces: `InstagramAdapter` registrado sob `platform="instagram"`.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.instagram import InstagramAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="a cat")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


class TestInstagramCompatibility(unittest.TestCase):
    def test_image_is_compatible(self):
        InstagramAdapter().check_compatibility(_piece(type=ContentPieceType.image), _asset())

    def test_video_is_compatible(self):
        InstagramAdapter().check_compatibility(_piece(type=ContentPieceType.video), _asset())

    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            InstagramAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestInstagramPublish(unittest.TestCase):
    def test_publish_creates_container_then_publishes_it(self):
        container_response = MagicMock(status_code=200)
        container_response.json.return_value = {"id": "container-1"}
        publish_response = MagicMock(status_code=200)
        publish_response.json.return_value = {"id": "media-1"}

        with patch(
            "app.services.content.publishers.instagram.post_form",
            side_effect=[container_response, publish_response],
        ) as post_form:
            result = InstagramAdapter().publish(
                _piece(),
                _asset(),
                _account(),
                {"access_token": "tok", "ig_user_id": "ig-1"},
            )

        self.assertEqual(result.platform_post_id, "media-1")
        self.assertIn("media-1", result.platform_post_url)
        self.assertEqual(post_form.call_count, 2)

    def test_container_creation_failure_propagates(self):
        with patch(
            "app.services.content.publishers.instagram.post_form",
            side_effect=PublicationError(PublicationErrorCode.rate_limit, "slow down"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                InstagramAdapter().publish(
                    _piece(), _asset(), _account(), {"access_token": "tok", "ig_user_id": "ig-1"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publishers_instagram.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publishers/instagram.py`**

```python
from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    post_form,
    register_adapter,
)

_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramAdapter(PublisherAdapter):
    platform = "instagram"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "Instagram only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        ig_user_id = credentials["ig_user_id"]

        media_field = "video_url" if piece.type == ContentPieceType.video else "image_url"
        container_payload = {media_field: asset.url, "access_token": access_token}
        if piece.type == ContentPieceType.video:
            container_payload["media_type"] = "REELS"

        container_response = post_form(
            f"{_GRAPH_API_BASE}/{ig_user_id}/media", data=container_payload
        )
        container_id = container_response.json()["id"]

        publish_response = post_form(
            f"{_GRAPH_API_BASE}/{ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": access_token},
        )
        media_id = publish_response.json()["id"]

        return PublishResult(
            platform_post_id=media_id,
            platform_post_url=f"https://www.instagram.com/p/{media_id}/",
        )


register_adapter(InstagramAdapter())
```

- [ ] **Step 4: Registrar o import em `app/services/content/publishers/__init__.py`**

```python
from app.services.content.publishers import instagram  # noqa: F401
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publishers_instagram.py -v`
Expected: PASS (5 testes)

- [ ] **Step 6: Commit**

```bash
git add app/services/content/publishers/instagram.py app/services/content/publishers/__init__.py test/services/test_content_publishers_instagram.py
git commit -m "feat(content): add Instagram publisher adapter"
```

---

### Task 5: Adapter Facebook

**Files:**
- Create: `app/services/content/publishers/facebook.py`
- Modify: `app/services/content/publishers/__init__.py`
- Test: `test/services/test_content_publishers_facebook.py`

**Interfaces:**
- Consumes: mesmos de Task 4.
- Produces: `FacebookAdapter` registrado sob `platform="facebook"`.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.facebook import FacebookAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="a cat")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


class TestFacebookCompatibility(unittest.TestCase):
    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            FacebookAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)

    def test_image_is_compatible(self):
        FacebookAdapter().check_compatibility(_piece(), _asset())


class TestFacebookPublish(unittest.TestCase):
    def test_image_posts_to_photos_endpoint(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"id": "post-1"}

        with patch(
            "app.services.content.publishers.facebook.post_form", return_value=response
        ) as post_form:
            result = FacebookAdapter().publish(
                _piece(), _asset(), MagicMock(), {"access_token": "tok", "page_id": "page-1"}
            )

        self.assertEqual(result.platform_post_id, "post-1")
        called_url = post_form.call_args.args[0]
        self.assertIn("/photos", called_url)

    def test_video_posts_to_videos_endpoint(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"id": "post-2"}

        with patch(
            "app.services.content.publishers.facebook.post_form", return_value=response
        ) as post_form:
            FacebookAdapter().publish(
                _piece(type=ContentPieceType.video),
                _asset(),
                MagicMock(),
                {"access_token": "tok", "page_id": "page-1"},
            )

        called_url = post_form.call_args.args[0]
        self.assertIn("/videos", called_url)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publishers_facebook.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publishers/facebook.py`**

```python
from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    post_form,
    register_adapter,
)

_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class FacebookAdapter(PublisherAdapter):
    platform = "facebook"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "Facebook only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        page_id = credentials["page_id"]
        endpoint = "videos" if piece.type == ContentPieceType.video else "photos"
        media_field = "file_url" if piece.type == ContentPieceType.video else "url"

        response = post_form(
            f"{_GRAPH_API_BASE}/{page_id}/{endpoint}",
            data={media_field: asset.url, "access_token": access_token},
        )
        post_id = response.json()["id"]

        return PublishResult(
            platform_post_id=post_id,
            platform_post_url=f"https://www.facebook.com/{post_id}",
        )


register_adapter(FacebookAdapter())
```

- [ ] **Step 4: Registrar o import em `app/services/content/publishers/__init__.py`**

```python
from app.services.content.publishers import facebook  # noqa: F401
from app.services.content.publishers import instagram  # noqa: F401
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publishers_facebook.py -v`
Expected: PASS (4 testes)

- [ ] **Step 6: Commit**

```bash
git add app/services/content/publishers/facebook.py app/services/content/publishers/__init__.py test/services/test_content_publishers_facebook.py
git commit -m "feat(content): add Facebook publisher adapter"
```

---

### Task 6: Adapter YouTube

**Files:**
- Create: `app/services/content/publishers/youtube.py`
- Modify: `app/services/content/publishers/__init__.py`
- Test: `test/services/test_content_publishers_youtube.py`

**Interfaces:**
- Consumes: `PublisherAdapter`, `PublishResult`, `register_adapter`, `get_bytes` (Task 3);
  `requests` diretamente para o upload multipart (autenticação via header `Bearer`, não via
  `post_form`, porque o corpo é multipart com metadata + bytes de vídeo).
- Produces: `YouTubeAdapter` registrado sob `platform="youtube"`.

Assunção documentada nesta task (não coberta pela spec): a piece já tem um `access_token` OAuth
válido nas credenciais da conta — renovação de token (`refresh_token`) fica fora de escopo do P0
(token expirado aparece como `invalid_credentials`, mesmo tratamento de qualquer outra credencial
inválida). Upload usa `uploadType=multipart` (não o protocolo resumable completo) — suficiente para
vídeos gerados pelo motor de geração, que não são arquivos longos/grandes.

- [ ] **Step 1: Escrever o teste**

```python
import json
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.youtube import YouTubeAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.video, generation_prompt="a cat video")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.mp4"):
    return MagicMock(url=url)


class TestYouTubeCompatibility(unittest.TestCase):
    def test_image_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            YouTubeAdapter().check_compatibility(_piece(type=ContentPieceType.image), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)

    def test_video_is_compatible(self):
        YouTubeAdapter().check_compatibility(_piece(), _asset())


class TestYouTubePublish(unittest.TestCase):
    def test_publish_fetches_asset_and_uploads(self):
        upload_response = MagicMock(status_code=200)
        upload_response.json.return_value = {"id": "video-1"}

        with patch(
            "app.services.content.publishers.youtube.get_bytes", return_value=b"binary-video"
        ) as get_bytes:
            with patch(
                "app.services.content.publishers.youtube.requests.post",
                return_value=upload_response,
            ) as post:
                result = YouTubeAdapter().publish(
                    _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                )

        get_bytes.assert_called_once_with("https://cdn.example.com/a.mp4")
        self.assertEqual(result.platform_post_id, "video-1")
        self.assertIn("video-1", result.platform_post_url)
        self.assertIn("Bearer tok", post.call_args.kwargs["headers"]["Authorization"])

    def test_upload_error_is_classified(self):
        error_response = MagicMock(status_code=401)
        error_response.json.return_value = {"error": {"message": "invalid token"}}

        with patch(
            "app.services.content.publishers.youtube.get_bytes", return_value=b"binary-video"
        ):
            with patch(
                "app.services.content.publishers.youtube.requests.post",
                return_value=error_response,
            ):
                with self.assertRaises(PublicationError) as ctx:
                    YouTubeAdapter().publish(
                        _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                    )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publishers_youtube.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publishers/youtube.py`**

```python
import json

import requests

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    get_bytes,
    raise_for_response,
    register_adapter,
)

_UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=multipart&part=snippet,status"
)


class YouTubeAdapter(PublisherAdapter):
    platform = "youtube"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type != ContentPieceType.video:
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "YouTube only accepts video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        video_bytes = get_bytes(asset.url)

        metadata = {
            "snippet": {
                "title": (piece.generation_prompt or f"Content piece {piece.id}")[:100],
                "description": piece.generation_prompt or "",
            },
            "status": {"privacyStatus": "public"},
        }
        files = {
            "metadata": (None, json.dumps(metadata), "application/json"),
            "video": (f"piece-{piece.id}.mp4", video_bytes, "video/mp4"),
        }

        try:
            response = requests.post(
                _UPLOAD_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                files=files,
                timeout=(10, 300),
            )
        except requests.RequestException as exc:
            raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
        raise_for_response(response)

        video_id = response.json()["id"]
        return PublishResult(
            platform_post_id=video_id,
            platform_post_url=f"https://www.youtube.com/watch?v={video_id}",
        )


register_adapter(YouTubeAdapter())
```

- [ ] **Step 4: Registrar o import em `app/services/content/publishers/__init__.py`**

```python
from app.services.content.publishers import facebook  # noqa: F401
from app.services.content.publishers import instagram  # noqa: F401
from app.services.content.publishers import youtube  # noqa: F401
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publishers_youtube.py -v`
Expected: PASS (4 testes)

- [ ] **Step 6: Commit**

```bash
git add app/services/content/publishers/youtube.py app/services/content/publishers/__init__.py test/services/test_content_publishers_youtube.py
git commit -m "feat(content): add YouTube publisher adapter"
```

---

### Task 7: Adapter X

**Files:**
- Create: `app/services/content/publishers/x.py`
- Modify: `app/services/content/publishers/__init__.py`
- Test: `test/services/test_content_publishers_x.py`

**Interfaces:**
- Consumes: `PublisherAdapter`, `PublishResult`, `register_adapter`, `post_form`, `post_json`,
  `get_bytes` (Task 3).
- Produces: `XAdapter` registrado sob `platform="x"`.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.x import XAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="hello world")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


class TestXCompatibility(unittest.TestCase):
    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            XAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestXPublish(unittest.TestCase):
    def test_publish_uploads_media_then_creates_tweet(self):
        upload_response = MagicMock(status_code=200)
        upload_response.json.return_value = {"media_id_string": "media-1"}
        tweet_response = MagicMock(status_code=201)
        tweet_response.json.return_value = {"data": {"id": "tweet-1"}}

        with patch(
            "app.services.content.publishers.x.get_bytes", return_value=b"binary-image"
        ):
            with patch(
                "app.services.content.publishers.x.post_form", return_value=upload_response
            ):
                with patch(
                    "app.services.content.publishers.x.post_json",
                    return_value=tweet_response,
                ) as post_json:
                    result = XAdapter().publish(
                        _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                    )

        self.assertEqual(result.platform_post_id, "tweet-1")
        body = post_json.call_args.args[1]
        self.assertEqual(body["media"]["media_ids"], ["media-1"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publishers_x.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publishers/x.py`**

```python
from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    get_bytes,
    post_form,
    post_json,
    register_adapter,
)

_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
_TWEETS_URL = "https://api.twitter.com/2/tweets"


class XAdapter(PublisherAdapter):
    platform = "x"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "X only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        media_bytes = get_bytes(asset.url)
        media_category = (
            "tweet_video" if piece.type == ContentPieceType.video else "tweet_image"
        )

        upload_response = post_form(
            _UPLOAD_URL,
            data={"media_category": media_category},
            headers={"Authorization": f"Bearer {access_token}"},
            files={"media": media_bytes},
        )
        media_id = upload_response.json()["media_id_string"]

        tweet_response = post_json(
            _TWEETS_URL,
            {"text": piece.generation_prompt or "", "media": {"media_ids": [media_id]}},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        tweet_id = tweet_response.json()["data"]["id"]

        return PublishResult(
            platform_post_id=tweet_id,
            platform_post_url=f"https://x.com/i/web/status/{tweet_id}",
        )


register_adapter(XAdapter())
```

- [ ] **Step 4: Registrar o import em `app/services/content/publishers/__init__.py`**

```python
from app.services.content.publishers import facebook  # noqa: F401
from app.services.content.publishers import instagram  # noqa: F401
from app.services.content.publishers import x  # noqa: F401
from app.services.content.publishers import youtube  # noqa: F401
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publishers_x.py -v`
Expected: PASS (2 testes)

- [ ] **Step 6: Commit**

```bash
git add app/services/content/publishers/x.py app/services/content/publishers/__init__.py test/services/test_content_publishers_x.py
git commit -m "feat(content): add X publisher adapter"
```

---

### Task 8: Adapter TikTok

**Files:**
- Create: `app/services/content/publishers/tiktok.py`
- Modify: `app/services/content/publishers/__init__.py`
- Test: `test/services/test_content_publishers_tiktok.py`

**Interfaces:**
- Consumes: `PublisherAdapter`, `PublishResult`, `register_adapter`, `post_json` (Task 3).
- Produces: `TikTokAdapter` registrado sob `platform="tiktok"`.

Assunção documentada: usa `source: "PULL_FROM_URL"` (TikTok busca o vídeo direto da URL do Supabase
Storage) — isso exige o domínio de Storage verificado no TikTok Developer Portal pelo tenant; é um
pré-requisito operacional, não algo que este adapter resolve em código.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.tiktok import TikTokAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.video, generation_prompt="a cat video")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.mp4"):
    return MagicMock(url=url)


class TestTikTokCompatibility(unittest.TestCase):
    def test_image_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            TikTokAdapter().check_compatibility(_piece(type=ContentPieceType.image), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestTikTokPublish(unittest.TestCase):
    def test_publish_returns_publish_id(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"publish_id": "pub-1"}}

        with patch(
            "app.services.content.publishers.tiktok.post_json", return_value=response
        ) as post_json:
            result = TikTokAdapter().publish(
                _piece(), _asset(), MagicMock(), {"access_token": "tok"}
            )

        self.assertEqual(result.platform_post_id, "pub-1")
        body = post_json.call_args.args[1]
        self.assertEqual(body["source_info"]["video_url"], "https://cdn.example.com/a.mp4")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publishers_tiktok.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publishers/tiktok.py`**

```python
from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    post_json,
    register_adapter,
)

_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"


class TikTokAdapter(PublisherAdapter):
    platform = "tiktok"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type != ContentPieceType.video:
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "TikTok only accepts video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        response = post_json(
            _INIT_URL,
            {
                "post_info": {
                    "title": (piece.generation_prompt or f"Content piece {piece.id}")[:150],
                    "privacy_level": "PUBLIC_TO_EVERYONE",
                },
                "source_info": {"source": "PULL_FROM_URL", "video_url": asset.url},
            },
            headers=headers,
        )
        publish_id = response.json()["data"]["publish_id"]

        return PublishResult(
            platform_post_id=publish_id,
            platform_post_url=f"https://www.tiktok.com/publish/status/{publish_id}",
        )


register_adapter(TikTokAdapter())
```

- [ ] **Step 4: Registrar o import em `app/services/content/publishers/__init__.py`**

```python
from app.services.content.publishers import facebook  # noqa: F401
from app.services.content.publishers import instagram  # noqa: F401
from app.services.content.publishers import tiktok  # noqa: F401
from app.services.content.publishers import x  # noqa: F401
from app.services.content.publishers import youtube  # noqa: F401
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publishers_tiktok.py -v`
Expected: PASS (2 testes)

- [ ] **Step 6: Commit**

```bash
git add app/services/content/publishers/tiktok.py app/services/content/publishers/__init__.py test/services/test_content_publishers_tiktok.py
git commit -m "feat(content): add TikTok publisher adapter"
```

---

### Task 9: Adapter LinkedIn

**Files:**
- Create: `app/services/content/publishers/linkedin.py`
- Modify: `app/services/content/publishers/__init__.py`
- Test: `test/services/test_content_publishers_linkedin.py`

**Interfaces:**
- Consumes: `PublisherAdapter`, `PublishResult`, `register_adapter`, `post_json`, `get_bytes` (Task
  3); `requests.put` diretamente (upload do binário para a `uploadUrl` retornada pelo registro).
- Produces: `LinkedInAdapter` registrado sob `platform="linkedin"`.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.linkedin import LinkedInAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="hello world")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


class TestLinkedInCompatibility(unittest.TestCase):
    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            LinkedInAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestLinkedInPublish(unittest.TestCase):
    def test_publish_registers_uploads_and_posts(self):
        register_response = MagicMock(status_code=200)
        register_response.json.return_value = {
            "value": {
                "uploadMechanism": {
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {
                        "uploadUrl": "https://upload.linkedin.com/put-here"
                    }
                },
                "asset": "urn:li:digitalmediaAsset:abc",
            }
        }
        upload_result = MagicMock(status_code=201)
        post_response = MagicMock(status_code=201)
        post_response.headers = {"x-restli-id": "urn:li:share:123"}

        with patch(
            "app.services.content.publishers.linkedin.get_bytes", return_value=b"binary-image"
        ):
            with patch(
                "app.services.content.publishers.linkedin.post_json",
                side_effect=[register_response, post_response],
            ):
                with patch(
                    "app.services.content.publishers.linkedin.requests.put",
                    return_value=upload_result,
                ):
                    result = LinkedInAdapter().publish(
                        _piece(),
                        _asset(),
                        MagicMock(),
                        {"access_token": "tok", "author_urn": "urn:li:person:1"},
                    )

        self.assertEqual(result.platform_post_id, "urn:li:share:123")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publishers_linkedin.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publishers/linkedin.py`**

```python
import requests

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    get_bytes,
    post_json,
    raise_for_response,
    register_adapter,
)

_REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


class LinkedInAdapter(PublisherAdapter):
    platform = "linkedin"

    def check_compatibility(self, piece, asset) -> None:
        if piece.type not in (ContentPieceType.image, ContentPieceType.video):
            raise PublicationError(
                PublicationErrorCode.unsupported_capability,
                "LinkedIn only accepts image or video pieces",
            )

    def publish(self, piece, asset, account, credentials) -> PublishResult:
        access_token = credentials["access_token"]
        author_urn = credentials["author_urn"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        recipe = (
            "urn:li:digitalmediaRecipe:feedshare-video"
            if piece.type == ContentPieceType.video
            else "urn:li:digitalmediaRecipe:feedshare-image"
        )

        register_response = post_json(
            _REGISTER_UPLOAD_URL,
            {
                "registerUploadRequest": {
                    "recipes": [recipe],
                    "owner": author_urn,
                    "serviceRelationships": [
                        {
                            "relationshipType": "OWNER",
                            "identifier": "urn:li:userGeneratedContent",
                        }
                    ],
                }
            },
            headers=headers,
        )
        upload_data = register_response.json()["value"]
        upload_url = upload_data["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = upload_data["asset"]

        media_bytes = get_bytes(asset.url)
        try:
            upload_result = requests.put(
                upload_url,
                data=media_bytes,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=(10, 300),
            )
        except requests.RequestException as exc:
            raise PublicationError(PublicationErrorCode.transient, str(exc)) from exc
        raise_for_response(upload_result)

        media_category = "VIDEO" if piece.type == ContentPieceType.video else "IMAGE"
        post_response = post_json(
            _UGC_POSTS_URL,
            {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": piece.generation_prompt or ""},
                        "shareMediaCategory": media_category,
                        "media": [{"status": "READY", "media": asset_urn}],
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            },
            headers=headers,
        )
        post_id = post_response.headers.get("x-restli-id", asset_urn)

        return PublishResult(
            platform_post_id=post_id,
            platform_post_url=f"https://www.linkedin.com/feed/update/{post_id}/",
        )


register_adapter(LinkedInAdapter())
```

- [ ] **Step 4: Registrar o import em `app/services/content/publishers/__init__.py`**

```python
from app.services.content.publishers import facebook  # noqa: F401
from app.services.content.publishers import instagram  # noqa: F401
from app.services.content.publishers import linkedin  # noqa: F401
from app.services.content.publishers import tiktok  # noqa: F401
from app.services.content.publishers import x  # noqa: F401
from app.services.content.publishers import youtube  # noqa: F401
```

- [ ] **Step 5: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publishers_linkedin.py -v`
Expected: PASS (2 testes)

- [ ] **Step 6: Commit**

```bash
git add app/services/content/publishers/linkedin.py app/services/content/publishers/__init__.py test/services/test_content_publishers_linkedin.py
git commit -m "feat(content): add LinkedIn publisher adapter"
```

---

### Task 10: Service `publications.py` — idempotência e resolução por conta

**Files:**
- Create: `app/services/content/publications.py`
- Test: `test/services/test_content_publications.py`

**Interfaces:**
- Consumes: `ContentSocialPublication`, `PublicationStatus` (Task 1); `get_adapter`,
  `PublisherAdapter` (Task 3); `list_assets_for_piece` (`app/services/content/assets.py`,
  já existente); `ContentSocialAccount` (`app/models/content.py`, já existente).
- Produces: `get_final_asset(session, *, content_piece_id) -> Optional[ContentAsset]`,
  `resolve_publication_request(session, *, piece, social_account_ids) ->
  tuple[list[ContentSocialPublication], list[dict]]` (aceitas vs. rejeitadas, já persistidas/
  resetadas conforme a regra de idempotência), `get_social_account_for_piece(session, *, piece,
  social_account_id) -> Optional[ContentSocialAccount]` (valida mesmo `client_id` da campanha da
  piece e `status="active"`), `list_publications_for_piece(session, *, content_piece_id) ->
  list[ContentSocialPublication]`.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content_publishing import PublicationStatus
from app.services.content import publications as publications_service


def _piece(**overrides):
    base = dict(id=10, campaign_id=1)
    base.update(overrides)
    return MagicMock(**base)


def _account(**overrides):
    base = dict(id=5, client_id=2, platform="instagram", status="active")
    base.update(overrides)
    return MagicMock(**base)


class TestGetSocialAccountForPiece(unittest.TestCase):
    def test_wrong_client_is_rejected(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = publications_service.get_social_account_for_piece(
            session, piece=_piece(), social_account_id=5
        )

        self.assertIsNone(result)

    def test_inactive_account_is_rejected(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = publications_service.get_social_account_for_piece(
            session, piece=_piece(), social_account_id=5
        )

        self.assertIsNone(result)

    def test_active_account_of_same_client_is_returned(self):
        account = _account()
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = publications_service.get_social_account_for_piece(
            session, piece=_piece(), social_account_id=5
        )

        self.assertIs(result, account)


class TestResolvePublicationRequest(unittest.TestCase):
    def test_unknown_account_is_rejected(self):
        session = MagicMock()
        piece = _piece()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=None
        ):
            accepted, rejected = publications_service.resolve_publication_request(
                session, piece=piece, social_account_ids=[5]
            )

        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["social_account_id"], 5)
        self.assertEqual(rejected[0]["reason"], "account_not_found")

    def test_incompatible_platform_is_rejected_without_creating_a_row(self):
        session = MagicMock()
        piece = _piece()
        account = _account()
        adapter = MagicMock()
        adapter.check_compatibility.side_effect = Exception("boom")

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                from app.services.content.publish_errors import (
                    PublicationError,
                    PublicationErrorCode,
                )

                adapter.check_compatibility.side_effect = PublicationError(
                    PublicationErrorCode.unsupported_capability, "nope"
                )
                with patch.object(
                    publications_service, "get_adapter", return_value=adapter
                ):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["reason"], "unsupported_capability")
        session.add.assert_not_called()

    def test_new_pair_is_created_as_queued(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None  # no existing row
        piece = _piece()
        account = _account()
        adapter = MagicMock()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                with patch.object(publications_service, "get_adapter", return_value=adapter):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].status, PublicationStatus.queued)
        session.add.assert_called()
        session.commit.assert_called()

    def test_failed_pair_is_reset_as_retry(self):
        existing = MagicMock(
            status=PublicationStatus.failed,
            attempt_count=3,
            error_code="rate_limit",
            error_message="slow down",
            next_run_at="something",
            publication_cycle=1,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = existing
        piece = _piece()
        account = _account()
        adapter = MagicMock()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                with patch.object(publications_service, "get_adapter", return_value=adapter):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(accepted, [existing])
        self.assertEqual(existing.status, PublicationStatus.queued)
        self.assertEqual(existing.attempt_count, 0)
        self.assertIsNone(existing.error_code)
        self.assertIsNone(existing.error_message)
        self.assertIsNone(existing.next_run_at)
        self.assertEqual(existing.publication_cycle, 2)

    def test_succeeded_pair_is_a_no_op(self):
        existing = MagicMock(status=PublicationStatus.succeeded)
        session = MagicMock()
        session.exec.return_value.first.return_value = existing
        piece = _piece()
        account = _account()
        adapter = MagicMock()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                with patch.object(publications_service, "get_adapter", return_value=adapter):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(accepted, [existing])
        session.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publications.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publications.py`**

```python
from datetime import datetime
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient, ContentPiece, ContentSocialAccount
from app.models.content_generation import ContentAsset
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content.assets import list_assets_for_piece
from app.services.content.publish_errors import PublicationError
from app.services.content.publishers.base import get_adapter


def get_final_asset(session: Session, *, content_piece_id: int) -> Optional[ContentAsset]:
    assets = list_assets_for_piece(session, content_piece_id=content_piece_id)
    return next((asset for asset in assets if not asset.is_intermediate), None)


def get_social_account_for_piece(
    session: Session, *, piece: ContentPiece, social_account_id: int
) -> Optional[ContentSocialAccount]:
    campaign = session.get(ContentCampaign, piece.campaign_id)
    if campaign is None:
        return None
    return session.exec(
        select(ContentSocialAccount).where(
            ContentSocialAccount.id == social_account_id,
            ContentSocialAccount.client_id == campaign.client_id,
            ContentSocialAccount.status == "active",
        )
    ).first()


def get_publication_for_pair(
    session: Session, *, content_piece_id: int, social_account_id: int
) -> Optional[ContentSocialPublication]:
    return session.exec(
        select(ContentSocialPublication).where(
            ContentSocialPublication.content_piece_id == content_piece_id,
            ContentSocialPublication.social_account_id == social_account_id,
        )
    ).first()


def list_publications_for_piece(
    session: Session, *, content_piece_id: int
) -> List[ContentSocialPublication]:
    return list(
        session.exec(
            select(ContentSocialPublication)
            .where(ContentSocialPublication.content_piece_id == content_piece_id)
            .order_by(ContentSocialPublication.id)
        ).all()
    )


def _tenant_id_for_piece(session: Session, piece: ContentPiece) -> int:
    campaign = session.get(ContentCampaign, piece.campaign_id)
    client = session.get(ContentClient, campaign.client_id)
    return client.tenant_id


def resolve_publication_request(
    session: Session, *, piece: ContentPiece, social_account_ids: List[int]
) -> Tuple[List[ContentSocialPublication], List[dict]]:
    """Resolve one /publish call into accepted rows and rejected reasons.

    Compatibility is checked here, before any row exists — an incompatible
    pair never becomes a doomed job (see spec: "Compatibilidade — fail-fast").
    """
    accepted: List[ContentSocialPublication] = []
    rejected: List[dict] = []
    asset = get_final_asset(session, content_piece_id=piece.id)

    for social_account_id in social_account_ids:
        account = get_social_account_for_piece(
            session, piece=piece, social_account_id=social_account_id
        )
        if account is None:
            rejected.append(
                {
                    "social_account_id": social_account_id,
                    "platform": None,
                    "reason": "account_not_found",
                    "message": "Social account not found, inactive, or belongs to another client",
                }
            )
            continue

        try:
            adapter = get_adapter(account.platform)
            adapter.check_compatibility(piece, asset)
        except PublicationError as error:
            rejected.append(
                {
                    "social_account_id": social_account_id,
                    "platform": account.platform,
                    "reason": error.code.value,
                    "message": error.message,
                }
            )
            continue

        existing = get_publication_for_pair(
            session, content_piece_id=piece.id, social_account_id=social_account_id
        )
        if existing is None:
            row = ContentSocialPublication(
                tenant_id=_tenant_id_for_piece(session, piece),
                client_id=account.client_id,
                content_piece_id=piece.id,
                social_account_id=social_account_id,
                platform=account.platform,
                status=PublicationStatus.queued,
                request_payload={"generation_prompt": piece.generation_prompt},
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            accepted.append(row)
        elif existing.status == PublicationStatus.failed:
            existing.status = PublicationStatus.queued
            existing.attempt_count = 0
            existing.error_code = None
            existing.error_message = None
            existing.next_run_at = None
            existing.publication_cycle += 1
            existing.updated_at = datetime.utcnow()
            session.add(existing)
            session.commit()
            session.refresh(existing)
            accepted.append(existing)
        else:
            accepted.append(existing)

    return accepted, rejected
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publications.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publications.py test/services/test_content_publications.py
git commit -m "feat(content): add publication idempotency and per-account resolution"
```

---

### Task 11: Dispatcher — claim atômico, execução, pool e semáforo

**Files:**
- Create: `app/services/content/publish_dispatcher.py`
- Test: `test/services/test_content_publish_dispatcher.py`

**Interfaces:**
- Consumes: `ContentSocialPublication`, `PublicationStatus` (Task 1); `PublicationError`,
  `PublicationErrorCode`, `is_retryable` (Task 2); `get_adapter`, `load_credentials` (Task 3);
  `get_final_asset` (Task 10);
  `backoff_delay` (`app/services/content/retry.py`, já existente); `ContentPiece`,
  `ContentPieceStatus` (existente); `ContentSocialAccount` (existente); `get_engine`
  (`app/db.py`, já existente).
- Produces: `claim_due_publications(session, *, limit) -> list[ContentSocialPublication]`,
  `recompute_publication_summary(session, *, content_piece_id) -> dict`,
  `execute_claimed_publication(session, publication_id) -> None`, `start_dispatcher() -> None`,
  `stop_dispatcher() -> None`, constantes `DISPATCH_INTERVAL_SECONDS`, `WORKERS`, `BATCH_SIZE`,
  `PLATFORM_CONCURRENCY`.

- [ ] **Step 1: Escrever o teste**

```python
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceStatus
from app.models.content_publishing import PublicationStatus
from app.services.content import publish_dispatcher as dispatcher
from app.services.content.publish_errors import PublicationError, PublicationErrorCode


class TestClaimDuePublications(unittest.TestCase):
    def test_claim_marks_rows_running_and_bumps_attempt_count(self):
        row = MagicMock(status=PublicationStatus.queued, attempt_count=0)
        session = MagicMock()
        session.exec.return_value.all.return_value = [row]

        result = dispatcher.claim_due_publications(session, limit=5)

        self.assertEqual(result, [row])
        self.assertEqual(row.status, PublicationStatus.running)
        self.assertEqual(row.attempt_count, 1)
        session.commit.assert_called_once()


class TestRecomputePublicationSummary(unittest.TestCase):
    def test_aggregates_by_platform_and_outcome(self):
        rows = [
            MagicMock(platform="instagram", status=PublicationStatus.succeeded),
            MagicMock(platform="instagram", status=PublicationStatus.failed),
            MagicMock(platform="tiktok", status=PublicationStatus.succeeded),
            MagicMock(platform="youtube", status=PublicationStatus.queued),
        ]
        session = MagicMock()
        session.exec.return_value.all.return_value = rows

        summary = dispatcher.recompute_publication_summary(session, content_piece_id=1)

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["platforms"]["instagram"], {"succeeded": 1, "failed": 1})
        self.assertEqual(summary["platforms"]["tiktok"], {"succeeded": 1, "failed": 0})


class TestExecuteClaimedPublication(unittest.TestCase):
    def _row(self, **overrides):
        base = dict(
            id=1,
            content_piece_id=10,
            social_account_id=5,
            platform="instagram",
            status=PublicationStatus.running,
            attempt_count=1,
            max_attempts=3,
        )
        base.update(overrides)
        return MagicMock(**base)

    def test_success_marks_succeeded_and_updates_piece(self):
        row = self._row()
        piece = MagicMock(id=10, posted_at=None, status=ContentPieceStatus.approved)
        account = MagicMock()
        session = MagicMock()
        session.get.side_effect = lambda model, id_: {
            ("ContentSocialPublication", 1): row,
        }.get((model.__name__, id_), None)

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.return_value = MagicMock(
            platform_post_id="p1", platform_post_url="https://x/p1"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher,
                        "recompute_publication_summary",
                        return_value={"total": 1, "succeeded": 1, "failed": 0, "pending": 0, "platforms": {}},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.succeeded)
        self.assertEqual(row.platform_post_id, "p1")
        self.assertEqual(piece.status, ContentPieceStatus.posted)
        self.assertIsNotNone(piece.posted_at)

    def test_retryable_failure_schedules_next_run_without_marking_failed(self):
        row = self._row(attempt_count=1, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.side_effect = PublicationError(
            PublicationErrorCode.rate_limit, "slow down"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.retrying)
        self.assertIsNotNone(row.next_run_at)
        self.assertEqual(row.error_code, "rate_limit")

    def test_non_retryable_failure_marks_failed_and_updates_summary(self):
        row = self._row()
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.side_effect = PublicationError(
            PublicationErrorCode.invalid_params, "bad payload"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher,
                        "recompute_publication_summary",
                        return_value={"total": 1, "succeeded": 0, "failed": 1, "pending": 0, "platforms": {}},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.failed)
        self.assertEqual(row.error_code, "invalid_params")

    def test_exhausted_retries_marks_failed(self):
        row = self._row(attempt_count=3, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.side_effect = PublicationError(
            PublicationErrorCode.transient, "boom"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher,
                        "recompute_publication_summary",
                        return_value={"total": 1, "succeeded": 0, "failed": 1, "pending": 0, "platforms": {}},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.failed)

    def test_unexpected_exception_during_setup_is_retried_not_left_running(self):
        """A row claimed as `running` must never get stuck there — even a bug
        in asset/credential lookup has to resolve to retrying/failed."""
        row = self._row(attempt_count=1, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        with patch.object(
            dispatcher, "get_final_asset", side_effect=RuntimeError("db exploded")
        ):
            dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.retrying)
        self.assertIsNotNone(row.next_run_at)
        self.assertEqual(row.error_code, "transient")


class TestDispatcherLifecycle(unittest.TestCase):
    def test_start_and_stop_do_not_raise(self):
        with patch.object(dispatcher, "_tick"):
            dispatcher.start_dispatcher()
            dispatcher.stop_dispatcher()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_publish_dispatcher.py -v`
Expected: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `app/services/content/publish_dispatcher.py`**

```python
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Optional

from loguru import logger
from sqlalchemy import or_
from sqlmodel import Session, select

from app.db import get_engine
from app.models.content import ContentPiece, ContentPieceStatus, ContentSocialAccount
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content import retry
from app.services.content.publish_errors import PublicationError, PublicationErrorCode, is_retryable
from app.services.content.publications import get_final_asset
from app.services.content.publishers.base import get_adapter, load_credentials

DISPATCH_INTERVAL_SECONDS = float(
    os.environ.get("CONTENT_PUBLISH_DISPATCH_INTERVAL_SECONDS", 2)
)
WORKERS = int(os.environ.get("CONTENT_PUBLISH_WORKERS", 4))
BATCH_SIZE = int(os.environ.get("CONTENT_PUBLISH_DISPATCH_BATCH_SIZE", WORKERS))
PLATFORM_CONCURRENCY = int(os.environ.get("CONTENT_PUBLISH_PLATFORM_CONCURRENCY", 2))

_executor = ThreadPoolExecutor(
    max_workers=WORKERS, thread_name_prefix="mpt-content-publish"
)
_platform_semaphores: dict[str, threading.BoundedSemaphore] = {}
_platform_semaphores_lock = threading.Lock()
_stop_event = threading.Event()
_dispatcher_thread: Optional[threading.Thread] = None


def _platform_semaphore(platform: str) -> threading.BoundedSemaphore:
    with _platform_semaphores_lock:
        if platform not in _platform_semaphores:
            _platform_semaphores[platform] = threading.BoundedSemaphore(PLATFORM_CONCURRENCY)
        return _platform_semaphores[platform]


def claim_due_publications(
    session: Session, *, limit: int
) -> List[ContentSocialPublication]:
    """Atomically claim due rows so two dispatcher ticks (or replicas) never
    run the same publication — SKIP LOCKED, not application-level locking.
    """
    now = datetime.utcnow()
    statement = (
        select(ContentSocialPublication)
        .where(
            ContentSocialPublication.status.in_(
                [PublicationStatus.queued, PublicationStatus.retrying]
            ),
            or_(
                ContentSocialPublication.next_run_at.is_(None),
                ContentSocialPublication.next_run_at <= now,
            ),
        )
        .order_by(ContentSocialPublication.next_run_at.nulls_first())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list(session.exec(statement).all())
    for row in rows:
        row.status = PublicationStatus.running
        row.attempt_count += 1
        row.updated_at = datetime.utcnow()
        session.add(row)
    session.commit()
    return rows


def recompute_publication_summary(session: Session, *, content_piece_id: int) -> dict:
    """Recomputed from source of truth on every call — a jsonb cache patched
    incrementally can drift; recomputing cannot.
    """
    rows = session.exec(
        select(ContentSocialPublication).where(
            ContentSocialPublication.content_piece_id == content_piece_id
        )
    ).all()
    summary = {"total": len(rows), "succeeded": 0, "failed": 0, "pending": 0, "platforms": {}}
    for row in rows:
        platform_counts = summary["platforms"].setdefault(
            row.platform, {"succeeded": 0, "failed": 0}
        )
        if row.status == PublicationStatus.succeeded:
            summary["succeeded"] += 1
            platform_counts["succeeded"] += 1
        elif row.status == PublicationStatus.failed:
            summary["failed"] += 1
            platform_counts["failed"] += 1
        else:
            summary["pending"] += 1
    return summary


def _handle_success(session: Session, row: ContentSocialPublication, piece: ContentPiece, result) -> None:
    row.status = PublicationStatus.succeeded
    row.platform_post_id = result.platform_post_id
    row.platform_post_url = result.platform_post_url
    row.completed_at = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()

    piece.publication_summary = recompute_publication_summary(
        session, content_piece_id=piece.id
    )
    if piece.posted_at is None:
        piece.posted_at = datetime.utcnow()
        piece.status = ContentPieceStatus.posted
    piece.updated_at = datetime.utcnow()
    session.add(piece)
    session.commit()


def _handle_failure(
    session: Session, row: ContentSocialPublication, piece: ContentPiece, error: PublicationError
) -> None:
    row.error_code = error.code.value
    row.error_message = error.message
    row.updated_at = datetime.utcnow()

    if is_retryable(error.code) and row.attempt_count < row.max_attempts:
        row.status = PublicationStatus.retrying
        row.next_run_at = datetime.utcnow() + timedelta(
            seconds=retry.backoff_delay(row.attempt_count)
        )
        session.add(row)
        session.commit()
        return

    row.status = PublicationStatus.failed
    row.completed_at = datetime.utcnow()
    session.add(row)
    session.commit()

    piece.publication_summary = recompute_publication_summary(
        session, content_piece_id=piece.id
    )
    piece.updated_at = datetime.utcnow()
    session.add(piece)
    session.commit()


def execute_claimed_publication(session: Session, publication_id: int) -> None:
    row = session.get(ContentSocialPublication, publication_id)
    if row is None:
        return
    piece = session.get(ContentPiece, row.content_piece_id)
    account = session.get(ContentSocialAccount, row.social_account_id)

    # Setup (asset/adapter/credential lookup) and the adapter call itself are
    # both inside this try — a row already marked `running` by the claim
    # must never be left stuck there. Anything unexpected here still has to
    # resolve to retrying/failed, not silence.
    try:
        asset = get_final_asset(session, content_piece_id=row.content_piece_id)
        adapter = get_adapter(row.platform)
        credentials = load_credentials(account)

        semaphore = _platform_semaphore(row.platform)
        semaphore.acquire()
        try:
            result = adapter.publish(piece, asset, account, credentials)
        finally:
            semaphore.release()
    except PublicationError as error:
        _handle_failure(session, row, piece, error)
        return
    except Exception as error:
        _handle_failure(
            session, row, piece, PublicationError(PublicationErrorCode.transient, str(error))
        )
        return

    _handle_success(session, row, piece, result)


def _run_and_log(publication_id: int) -> None:
    with Session(get_engine()) as session:
        try:
            execute_claimed_publication(session, publication_id)
        except Exception:
            logger.exception(f"unhandled error executing publication {publication_id}")


def _tick() -> None:
    with Session(get_engine()) as session:
        claimed = claim_due_publications(session, limit=BATCH_SIZE)
        claimed_ids = [row.id for row in claimed]
    for publication_id in claimed_ids:
        _executor.submit(_run_and_log, publication_id)


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception:
            logger.exception("publish dispatcher tick failed")
        _stop_event.wait(DISPATCH_INTERVAL_SECONDS)


def start_dispatcher() -> None:
    global _dispatcher_thread
    if _dispatcher_thread is not None:
        return
    _stop_event.clear()
    _dispatcher_thread = threading.Thread(
        target=_loop, name="mpt-content-publish-dispatcher", daemon=True
    )
    _dispatcher_thread.start()


def stop_dispatcher() -> None:
    global _dispatcher_thread
    _stop_event.set()
    if _dispatcher_thread is not None:
        _dispatcher_thread.join(timeout=5)
        _dispatcher_thread = None
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_publish_dispatcher.py -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publish_dispatcher.py test/services/test_content_publish_dispatcher.py
git commit -m "feat(content): add publish dispatcher with atomic claim and platform semaphores"
```

---

### Task 12: Controller — `POST /publish` e `GET /publications`

**Files:**
- Create: `app/controllers/v1/content/publications.py`
- Modify: `app/router.py`

**Interfaces:**
- Consumes: `PublishRequest`, `PublishResponse`, `PublicationRead` (Task 1);
  `resolve_publication_request`, `list_publications_for_piece` (Task 10); `pieces_service.get_piece`
  (`app/services/content/pieces.py`, já existente); `content_auth.verify_tenant_token` (existente).
- Produces: rotas `POST /api/v1/content/pieces/{id}/publish`,
  `GET /api/v1/content/pieces/{id}/publications`.

Sem teste dedicado neste task — não há precedente de teste de rota via `TestClient` no módulo
content (os testes existentes cobrem services e a dependency `verify_tenant_token` diretamente, não
os controllers). A lógica de negócio (idempotência, gate de status, compatibilidade) já está coberta
pelos testes de `publications.py` (Task 10); este task só liga isso a HTTP.

- [ ] **Step 1: Implementar `app/controllers/v1/content/publications.py`**

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentPieceStatus, ContentTenant
from app.models.content_publishing import (
    PublicationRead,
    PublishRequest,
    PublishResponse,
)
from app.services.content import pieces as pieces_service
from app.services.content import publications as publications_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])

_PUBLISHABLE_STATUSES = (ContentPieceStatus.approved, ContentPieceStatus.posted)


@router.post(
    "/content/pieces/{piece_id}/publish", response_model=PublishResponse, status_code=202
)
def publish_piece(
    piece_id: int,
    payload: PublishRequest,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status not in _PUBLISHABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be approved or already posted, got '{piece.status.value}'",
        )

    accepted, rejected = publications_service.resolve_publication_request(
        session, piece=piece, social_account_ids=payload.social_account_ids
    )

    return PublishResponse(
        accepted=[
            {"social_account_id": row.social_account_id, "platform": row.platform, "status": row.status.value}
            for row in accepted
        ],
        rejected=rejected,
    )


@router.get(
    "/content/pieces/{piece_id}/publications", response_model=list[PublicationRead]
)
def list_publications(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    piece = pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id)
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    return publications_service.list_publications_for_piece(session, content_piece_id=piece_id)
```

- [ ] **Step 2: Registrar o router em `app/router.py`**

Adicione `publications` ao import de `app.controllers.v1.content` e ao `include_router`:

```python
from app.controllers.v1.content import (
    approval_rules,
    avatars,
    campaigns,
    clients,
    models,
    pieces,
    providers,
    publications,
    social_accounts,
    tenants,
)
```

```python
root_api_router.include_router(pieces.router)
root_api_router.include_router(providers.router)
root_api_router.include_router(publications.router)
root_api_router.include_router(models.router)
```

- [ ] **Step 3: Verificar que a app sobe sem erro de import**

Run: `python -c "from app.asgi import get_application; get_application()"`
Expected: sem exceção (falha aqui geralmente indica erro de import/nome de rota duplicado).

- [ ] **Step 4: Commit**

```bash
git add app/controllers/v1/content/publications.py app/router.py
git commit -m "feat(content): expose POST /publish and GET /publications endpoints"
```

---

### Task 13: Ligar o dispatcher ao lifespan da aplicação

**Files:**
- Modify: `app/asgi.py`

**Interfaces:**
- Consumes: `start_dispatcher`, `stop_dispatcher` (Task 11).

- [ ] **Step 1: Editar `application_lifespan` em `app/asgi.py`**

Adicione o import no topo do arquivo, junto aos outros imports locais dentro da função (mantendo o
padrão já usado ali para `get_catalog`/`task_service`):

```python
@asynccontextmanager
async def application_lifespan(_: FastAPI):
    """集中处理 API 进程启动恢复和关闭日志。"""
    logger.info("startup event")

    from app.services.content.catalog import get_catalog

    get_catalog()
    logger.info("content model catalog loaded")

    from app.services.content.publish_dispatcher import start_dispatcher, stop_dispatcher

    start_dispatcher()
    logger.info("content publish dispatcher started")

    configured_api_key = config.app.get("api_key", "")
    if configured_api_key in (None, ""):
        logger.warning(
            "API key authentication is disabled; keep the API on a trusted network"
        )
    elif isinstance(configured_api_key, str):
        logger.info("API key authentication is enabled for /api/v1 and /tasks")
    else:
        logger.error(
            "API key authentication is misconfigured: app.api_key must be a string"
        )

    from app.services import task as task_service

    task_service.recover_interrupted_cross_posts()
    try:
        yield
    finally:
        stop_dispatcher()
        logger.info("content publish dispatcher stopped")
        logger.info("shutdown event")
```

- [ ] **Step 2: Verificar que a app ainda sobe sem erro**

Run: `python -c "from app.asgi import get_application; get_application()"`
Expected: sem exceção.

- [ ] **Step 3: Commit**

```bash
git add app/asgi.py
git commit -m "feat(content): start/stop the publish dispatcher in the application lifespan"
```

---

### Task 14: Documentar as novas variáveis de ambiente

**Files:**
- Modify: `config.example.toml`

- [ ] **Step 1: Adicionar bloco de comentário seguindo o único precedente existente no arquivo**

No final de `config.example.toml`, logo após o bloco de comentário do Supabase Storage:

```toml
# Content module — social publishing (sub-project 3).
# These are secrets and must be set as environment variables, never here:
#   CONTENT_PUBLISH_WORKERS=4                       # optional, shared thread pool size
#   CONTENT_PUBLISH_PLATFORM_CONCURRENCY=2           # optional, per-platform semaphore limit (process-local)
#   CONTENT_PUBLISH_DISPATCH_INTERVAL_SECONDS=2      # optional, dispatcher poll interval
#   CONTENT_PUBLISH_DISPATCH_BATCH_SIZE=4            # optional, defaults to CONTENT_PUBLISH_WORKERS
```

- [ ] **Step 2: Commit**

```bash
git add config.example.toml
git commit -m "docs(content): document publish dispatcher env vars"
```

---

## Self-Review

**1. Cobertura da spec:** Adapters por plataforma (Tasks 4-9) ✓; compatibilidade fail-fast antes de
criar linha (Task 10, `resolve_publication_request`) ✓; `ContentSocialPublication` com `UNIQUE`
(Task 1) ✓; `publication_summary` recomputado transacionalmente + `posted_at`/`status=posted` (Task
11, `_handle_success`) ✓; dispatcher com `FOR UPDATE SKIP LOCKED`, `attempt_count` incrementado só
no claim, `next_run_at` sem `sleep()` (Task 11) ✓; pool compartilhado + semáforo por plataforma
process-local (Task 11) ✓; idempotência/retry explícito por par (Task 10) ✓; gate
`status in (approved, posted)` (Task 12) ✓; `POST /publish` e `GET /publications` com resposta
parcial (Task 12) ✓; lifespan start/stop (Task 13) ✓; migration com tabela + coluna +
`UniqueConstraint` + índice composto `(status, next_run_at)` (Task 1) ✓; env vars documentadas
(Task 14) ✓.

**2. Placeholder scan:** Nenhum "TBD"/"implementar depois" restante. Um resíduo didático no Step 1
da Task 1 (bloco de código deliberadamente incorreto usado para "ilustrar" a correção do enum) foi
removido nesta revisão — violava a própria regra de no-placeholders do plano.

**3. Consistência de tipos:** `PublicationStatus`/`PublicationErrorCode` usados de forma idêntica em
Tasks 1-2-3-4-9-10-11-12 (`.value` só na serialização HTTP, Task 12). `get_adapter`/
`register_adapter`/`load_credentials`/`post_form`/`post_json`/`get_bytes`/`raise_for_response`
(Task 3) importados com a mesma assinatura em todas as Tasks 4-9-10-11. `resolve_publication_request`
retorna `(accepted: list[ContentSocialPublication], rejected: list[dict])` consistentemente entre
Task 10 (produção) e Task 12 (consumo). `execute_claimed_publication(session, publication_id: int)`
consistente entre Task 11 (produção) e `_run_and_log`/`_tick` (mesma task, consumo interno).
`get_final_asset(session, *, content_piece_id)` consistente entre Task 10 (produção) e Task 11
(consumo).

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-28-motor-publicacao-redes-sociais.md`.
Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks,
fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with
checkpoints

**Which approach?**
