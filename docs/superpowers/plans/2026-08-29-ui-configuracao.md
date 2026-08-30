# UI de Configuração (5b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor CRUD completo (create/edit/delete) das 7 entidades de configuração do módulo de conteúdo (Client, Campaign, SocialAccount, Avatar, ApprovalRule, GenerationTemplate, Provider) através de rotas UI-scoped (`/content/ui/config/...`, auth por sessão JWT) e telas correspondentes na SPA `webui/`.

**Architecture:** Novo controller `app/controllers/v1/content/ui_config.py` reaproveita os services existentes em `app/services/content/*.py`, que ganham as funções de update/delete que faltam. Leitura aberta a `admin`/`member`; escrita exige `role == "admin"` via `content_auth.require_role` (já existe, mesmo padrão usado em `POST /content/ui/pieces/{id}/approve`). Frontend replica o padrão já estabelecido em `PieceQueue.tsx`/`PieceDetail.tsx` (React Query + fetch client fino) para 7 novas páginas em `webui/src/pages/config/`.

**Tech Stack:** FastAPI + SQLModel + Alembic (backend), React + Vite + TypeScript + `@tanstack/react-query` + `react-router-dom` (frontend), `unittest` + `unittest.mock.MagicMock` (testes de service).

**Spec:** `docs/superpowers/specs/2026-08-29-ui-configuracao-design.md`

## Global Constraints

- Toda rota de escrita (create/update/delete) exige `role == "admin"`, checado via `content_auth.require_role(user_session, "admin")` no corpo da rota — nunca só ocultação no frontend.
- Toda query de service filtra por `tenant_id` (direto ou via join na cadeia de FKs) — não há RLS no banco.
- Nenhuma resposta de leitura inclui `credentials_encrypted` nem credencial em texto puro — os DTOs `*Read` existentes (`SocialAccountRead`, `GenerationProviderRead`) já garantem isso por não terem esse campo; não adicionar o campo a eles.
- `Client`, `Avatar`, `GenerationTemplate` usam soft-delete via `is_active: bool` (coluna nova). `Campaign`, `SocialAccount` usam soft-delete via `status: str` já existente (`"archived"`/`"revoked"`). `ApprovalRule` usa hard-delete.
- Um id de outra tenant deve responder `404`, nunca `200` com dado alheio nem `403` (não revelar que o id existe em outra tenant).
- Código, comentários e commits em inglês; nomes de arquivo/rotas seguem o padrão já usado no módulo (`snake_case` em Python, `kebab-case` em paths REST).

---

### Task 1: Migration — coluna `is_active` em Client, Avatar, GenerationTemplate

**Files:**
- Create: `alembic/versions/a7d3f8c1b2e9_add_is_active_to_config_entities.py`

**Interfaces:**
- Produces: colunas `content_clients.is_active`, `content_avatars.is_active`, `content_generation_templates.is_active` (todas `boolean not null default true`), consumidas pelos models SQLModel na Task 2/5/7.

- [ ] **Step 1: Escrever a migration**

```python
"""add is_active to config entities

Revision ID: a7d3f8c1b2e9
Revises: e4c2a9f1b6d3
Create Date: 2026-08-29 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7d3f8c1b2e9'
down_revision = 'e4c2a9f1b6d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'content_clients',
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        'content_avatars',
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        'content_generation_templates',
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('content_generation_templates', 'is_active')
    op.drop_column('content_avatars', 'is_active')
    op.drop_column('content_clients', 'is_active')
```

- [ ] **Step 2: Aplicar a migration**

Run: `alembic upgrade head`
Expected: migration `a7d3f8c1b2e9` aplicada sem erro, sem alterar nenhuma linha existente (`server_default true` preenche as linhas já existentes).

- [ ] **Step 3: Verificar reversibilidade**

Run: `alembic downgrade -1 && alembic upgrade head`
Expected: `downgrade` remove as 3 colunas sem erro; `upgrade` as recria.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/a7d3f8c1b2e9_add_is_active_to_config_entities.py
git commit -m "feat(content): add is_active column to clients, avatars, generation templates"
```

---

### Task 2: Client — service update/deactivate + rotas `ui_config` + DTO

**Files:**
- Create: `app/controllers/v1/content/ui_config.py`
- Modify: `app/router.py:14-27,48` — importar e registrar `ui_config.router`
- Modify: `app/models/content.py:75-81` (`ContentClient` ganha `is_active`), `app/models/content.py:229-237` (`ClientRead` ganha `is_active`; novo DTO `ClientUpdate`)
- Modify: `app/services/content/clients.py` — `update_client`, `deactivate_client`; `get_client`/`list_clients` sem mudança de filtro (mesma convenção de `list_generation_providers`: lista tudo, filtro por `is_active` é opt-in do chamador)
- Test: `test/services/test_content_clients.py` (novo)

**Interfaces:**
- Consumes: `content_auth.verify_user_session`, `content_auth.require_role` (já existem, `app/controllers/content_auth.py:67,112`); `clients_service.get_client` (já existe).
- Produces: `clients_service.update_client(session, *, tenant_id, client_id, name=None) -> Optional[ContentClient]`, `clients_service.deactivate_client(session, *, tenant_id, client_id) -> Optional[ContentClient]`. Rotas `GET/POST/PUT/DELETE /content/ui/config/clients[...]` no router `ui_config.router` — as tasks seguintes importam e estendem esse mesmo `router`.

- [ ] **Step 1: Escrever o teste de `update_client`/`deactivate_client`**

```python
# test/services/test_content_clients.py
import unittest
from unittest.mock import MagicMock

from app.models.content import ContentClient
from app.services.content import clients as clients_service


class TestUpdateClient(unittest.TestCase):
    def test_updates_name_when_found(self):
        client = ContentClient(id=1, tenant_id=1, name="Old Name")
        session = MagicMock()
        session.exec.return_value.first.return_value = client

        result = clients_service.update_client(
            session, tenant_id=1, client_id=1, name="New Name"
        )

        self.assertEqual(result.name, "New Name")
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = clients_service.update_client(
            session, tenant_id=1, client_id=999, name="New Name"
        )

        self.assertIsNone(result)


class TestDeactivateClient(unittest.TestCase):
    def test_sets_is_active_false(self):
        client = ContentClient(id=1, tenant_id=1, name="Acme", is_active=True)
        session = MagicMock()
        session.exec.return_value.first.return_value = client

        result = clients_service.deactivate_client(session, tenant_id=1, client_id=1)

        self.assertFalse(result.is_active)
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = clients_service.deactivate_client(session, tenant_id=1, client_id=999)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `python -m pytest test/services/test_content_clients.py -v`
Expected: FAIL — `AttributeError: module 'clients_service' has no attribute 'update_client'`

- [ ] **Step 3: Adicionar `is_active` ao model e implementar `update_client`/`deactivate_client`**

Em `app/models/content.py`, no corpo de `ContentClient` (linha 81, logo após `created_at`):

```python
    is_active: bool = Field(default=True)
```

Em `ClientRead` (linha ~233-237), acrescentar o campo:

```python
class ClientRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    is_active: bool
    created_at: datetime
```

Novo DTO logo abaixo de `ClientRead`:

```python
class ClientUpdate(BaseModel):
    name: Optional[str] = None
```

Em `app/services/content/clients.py`, adicionar ao final do arquivo:

```python
def update_client(
    session: Session, *, tenant_id: int, client_id: int, name: Optional[str] = None
) -> Optional[ContentClient]:
    client = get_client(session, tenant_id=tenant_id, client_id=client_id)
    if client is None:
        return None
    if name is not None:
        client.name = name
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


def deactivate_client(
    session: Session, *, tenant_id: int, client_id: int
) -> Optional[ContentClient]:
    client = get_client(session, tenant_id=tenant_id, client_id=client_id)
    if client is None:
        return None
    client.is_active = False
    session.add(client)
    session.commit()
    session.refresh(client)
    return client
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

Run: `python -m pytest test/services/test_content_clients.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Criar `ui_config.py` com as rotas de Client e registrar o router**

```python
# app/controllers/v1/content/ui_config.py
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ClientCreate, ClientRead, ClientUpdate
from app.services.content import audit
from app.services.content import clients as clients_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])


@router.get("/content/ui/config/clients", response_model=list[ClientRead])
def list_clients(
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return clients_service.list_clients(session, tenant_id=user_session.tenant.id)


@router.get("/content/ui/config/clients/{client_id}", response_model=ClientRead)
def get_client(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    client = clients_service.get_client(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.post("/content/ui/config/clients", response_model=ClientRead, status_code=201)
def create_client(
    payload: ClientCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    client = clients_service.create_client(
        session, tenant_id=user_session.tenant.id, name=payload.name
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return client


@router.put("/content/ui/config/clients/{client_id}", response_model=ClientRead)
def update_client(
    client_id: int,
    payload: ClientUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    client = clients_service.update_client(
        session, tenant_id=user_session.tenant.id, client_id=client_id, name=payload.name
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return client


@router.delete("/content/ui/config/clients/{client_id}", response_model=ClientRead)
def deactivate_client(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    client = clients_service.deactivate_client(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="client",
        entity_id=client.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return client
```

Em `app/router.py`, adicionar `ui_config` ao import (linha 14-27) e registrar o router logo após `ui`:

```python
from app.controllers.v1.content import (
    approval_rules,
    avatars,
    campaigns,
    clients,
    generation_templates,
    models,
    pieces,
    providers,
    publications,
    social_accounts,
    tenants,
    ui,
    ui_config,
)
```

```python
root_api_router.include_router(ui.router)
root_api_router.include_router(ui_config.router)
```

- [ ] **Step 6: Verificar as rotas manualmente**

Run: `python -c "from app.router import root_api_router; print([r.path for r in root_api_router.routes if 'ui/config/clients' in r.path])"`
Expected: lista com `/api/v1/content/ui/config/clients` e `/api/v1/content/ui/config/clients/{client_id}` (GET/POST/PUT/DELETE conforme registrado).

- [ ] **Step 7: Commit**

```bash
git add app/controllers/v1/content/ui_config.py app/router.py app/models/content.py app/services/content/clients.py test/services/test_content_clients.py
git commit -m "feat(content): add UI-scoped CRUD routes for Client"
```

---

### Task 3: Campaign — service update/archive + rotas `ui_config` (substitui `GET /ui/campaigns`)

**Files:**
- Modify: `app/models/content.py:96-104` (`ContentCampaign` sem mudança de coluna — reaproveita `status`), `app/models/content.py:262-269` (novo DTO `CampaignUpdate`)
- Modify: `app/services/content/campaigns.py` — `update_campaign`, `archive_campaign`
- Modify: `app/controllers/v1/content/ui_config.py` — rotas de Campaign
- Modify: `app/controllers/v1/content/ui.py` — remover `GET /content/ui/campaigns` (linhas 32-39; migrou para `ui_config.py`)
- Test: `test/services/test_content_campaigns.py` — acrescentar testes de `update_campaign`/`archive_campaign`

**Interfaces:**
- Consumes: `campaigns_service.get_campaign` (já existe, `app/services/content/campaigns.py:33`).
- Produces: `campaigns_service.update_campaign(session, *, tenant_id, campaign_id, name=None, horizon_days=None) -> Optional[ContentCampaign]`, `campaigns_service.archive_campaign(session, *, tenant_id, campaign_id) -> Optional[ContentCampaign]`. Rota `GET /content/ui/config/campaigns` (com `client_id` opcional) substitui `GET /content/ui/campaigns` — a Task 13 (frontend) aponta `PieceQueue.tsx` para o novo caminho.

- [ ] **Step 1: Escrever os testes de `update_campaign`/`archive_campaign`**

Acrescentar ao final de `test/services/test_content_campaigns.py` (preservar a classe `TestListCampaignsForTenant` já existente):

```python
from app.models.content import ContentCampaign


class TestUpdateCampaign(unittest.TestCase):
    def test_updates_name_and_horizon(self):
        campaign = ContentCampaign(id=1, client_id=1, name="Old", horizon_days=7)
        session = MagicMock()
        session.exec.return_value.first.return_value = campaign

        result = campaigns_service.update_campaign(
            session, tenant_id=1, campaign_id=1, name="New", horizon_days=14
        )

        self.assertEqual(result.name, "New")
        self.assertEqual(result.horizon_days, 14)
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = campaigns_service.update_campaign(
            session, tenant_id=1, campaign_id=999, name="New"
        )

        self.assertIsNone(result)


class TestArchiveCampaign(unittest.TestCase):
    def test_sets_status_archived(self):
        campaign = ContentCampaign(id=1, client_id=1, name="Acme", status="active")
        session = MagicMock()
        session.exec.return_value.first.return_value = campaign

        result = campaigns_service.archive_campaign(session, tenant_id=1, campaign_id=1)

        self.assertEqual(result.status, "archived")
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = campaigns_service.archive_campaign(session, tenant_id=1, campaign_id=999)

        self.assertIsNone(result)
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest test/services/test_content_campaigns.py -v`
Expected: FAIL — `AttributeError: module 'campaigns_service' has no attribute 'update_campaign'`

- [ ] **Step 3: Implementar `update_campaign`/`archive_campaign` e o DTO**

Em `app/models/content.py`, logo após `CampaignRead` (linha ~269):

```python
class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    horizon_days: Optional[int] = None
```

Em `app/services/content/campaigns.py`, ao final do arquivo:

```python
def update_campaign(
    session: Session,
    *,
    tenant_id: int,
    campaign_id: int,
    name: Optional[str] = None,
    horizon_days: Optional[int] = None,
) -> Optional[ContentCampaign]:
    campaign = get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    if campaign is None:
        return None
    if name is not None:
        campaign.name = name
    if horizon_days is not None:
        campaign.horizon_days = horizon_days
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


def archive_campaign(
    session: Session, *, tenant_id: int, campaign_id: int
) -> Optional[ContentCampaign]:
    campaign = get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    if campaign is None:
        return None
    campaign.status = "archived"
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `python -m pytest test/services/test_content_campaigns.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Adicionar as rotas de Campaign em `ui_config.py` e remover a rota antiga de `ui.py`**

Em `app/controllers/v1/content/ui_config.py`, ajustar o import e acrescentar as rotas:

```python
from app.models.content import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    ClientCreate,
    ClientRead,
    ClientUpdate,
)
from app.services.content import campaigns as campaigns_service
```

```python
@router.get("/content/ui/config/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    client_id: Optional[int] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    if client_id is not None:
        return campaigns_service.list_campaigns(
            session, tenant_id=user_session.tenant.id, client_id=client_id
        )
    return campaigns_service.list_campaigns_for_tenant(
        session, tenant_id=user_session.tenant.id
    )


@router.get("/content/ui/config/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    campaign = campaigns_service.get_campaign(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/content/ui/config/campaigns", response_model=CampaignRead, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    campaign = campaigns_service.create_campaign(
        session,
        tenant_id=user_session.tenant.id,
        client_id=payload.client_id,
        name=payload.name,
        horizon_days=payload.horizon_days,
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return campaign


@router.put("/content/ui/config/campaigns/{campaign_id}", response_model=CampaignRead)
def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    campaign = campaigns_service.update_campaign(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=campaign_id,
        name=payload.name,
        horizon_days=payload.horizon_days,
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return campaign


@router.delete("/content/ui/config/campaigns/{campaign_id}", response_model=CampaignRead)
def archive_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    campaign = campaigns_service.archive_campaign(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="campaign",
        entity_id=campaign.id,
        action="archived",
        actor=f"user:{user_session.user_id}",
    )
    return campaign
```

Adicionar `from typing import Optional` ao topo de `ui_config.py` se ainda não estiver lá.

Em `app/controllers/v1/content/ui.py`, remover a rota `list_campaigns` (linhas 32-39) e o import agora não usado de `campaigns_service` (verificar se `campaigns_service` ainda é usado em outra rota do arquivo — não é, então remover `from app.services.content import campaigns as campaigns_service` e `CampaignRead` do import de `app.models.content` também deixa de ser usado ali).

- [ ] **Step 6: Confirmar que a rota antiga sumiu e a nova responde**

Run: `python -c "from app.router import root_api_router; paths = [r.path for r in root_api_router.routes]; assert '/api/v1/content/ui/campaigns' not in paths; assert '/api/v1/content/ui/config/campaigns' in paths; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add app/controllers/v1/content/ui_config.py app/controllers/v1/content/ui.py app/models/content.py app/services/content/campaigns.py test/services/test_content_campaigns.py
git commit -m "feat(content): add UI-scoped CRUD routes for Campaign, replacing GET /ui/campaigns"
```

---

### Task 4: SocialAccount — GET individual + update/revoke + rotas `ui_config`

**Files:**
- Modify: `app/models/content.py:240-253` (novo DTO `SocialAccountUpdate`)
- Modify: `app/services/content/social_accounts.py` — `get_social_account`, `update_social_account`, `revoke_social_account`
- Modify: `app/controllers/v1/content/ui_config.py` — rotas de SocialAccount
- Test: `test/services/test_content_social_accounts.py` (novo)

**Interfaces:**
- Consumes: `social_accounts_service.list_social_accounts` (já existe), `crypto.encrypt_credentials` (já existe, `app/services/content/crypto.py:21`).
- Produces: `social_accounts_service.get_social_account(session, *, tenant_id, account_id) -> Optional[ContentSocialAccount]`, `update_social_account(session, *, tenant_id, account_id, external_account_id=None, credentials=None) -> Optional[ContentSocialAccount]`, `revoke_social_account(session, *, tenant_id, account_id) -> Optional[ContentSocialAccount]`.

- [ ] **Step 1: Escrever os testes**

```python
# test/services/test_content_social_accounts.py
import unittest
from unittest.mock import MagicMock

from app.models.content import ContentSocialAccount
from app.services.content import social_accounts as social_accounts_service


class TestGetSocialAccount(unittest.TestCase):
    def test_returns_account_when_found(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="ext-1",
            credentials_encrypted="enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.get_social_account(session, tenant_id=1, account_id=1)

        self.assertIs(result, account)

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = social_accounts_service.get_social_account(session, tenant_id=1, account_id=999)

        self.assertIsNone(result)


class TestUpdateSocialAccount(unittest.TestCase):
    def test_updates_external_id_and_reencrypts_credentials(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="old",
            credentials_encrypted="old-enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.update_social_account(
            session, tenant_id=1, account_id=1, external_account_id="new", credentials="new-secret"
        )

        self.assertEqual(result.external_account_id, "new")
        self.assertNotEqual(result.credentials_encrypted, "old-enc")
        session.commit.assert_called_once()

    def test_preserves_credentials_when_omitted(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="ext-1",
            credentials_encrypted="unchanged-enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.update_social_account(session, tenant_id=1, account_id=1)

        self.assertEqual(result.credentials_encrypted, "unchanged-enc")


class TestRevokeSocialAccount(unittest.TestCase):
    def test_sets_status_revoked(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="ext-1",
            credentials_encrypted="enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.revoke_social_account(session, tenant_id=1, account_id=1)

        self.assertEqual(result.status, "revoked")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest test/services/test_content_social_accounts.py -v`
Expected: FAIL — `AttributeError: module 'social_accounts_service' has no attribute 'get_social_account'`

- [ ] **Step 3: Implementar no service e o DTO**

Em `app/models/content.py`, logo após `SocialAccountRead` (linha ~253):

```python
class SocialAccountUpdate(BaseModel):
    external_account_id: Optional[str] = None
    credentials: Optional[str] = None
```

Em `app/services/content/social_accounts.py`, ajustar o import (`from app.models.content import ContentClient, ContentSocialAccount`) e adicionar ao final:

```python
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
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `python -m pytest test/services/test_content_social_accounts.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Adicionar as rotas em `ui_config.py`**

Ajustar imports:

```python
from app.models.content import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    ClientCreate,
    ClientRead,
    ClientUpdate,
    SocialAccountCreate,
    SocialAccountRead,
    SocialAccountUpdate,
)
from app.services.content import social_accounts as social_accounts_service
```

```python
@router.get(
    "/content/ui/config/clients/{client_id}/social-accounts",
    response_model=list[SocialAccountRead],
)
def list_social_accounts(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return social_accounts_service.list_social_accounts(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )


@router.get("/content/ui/config/social-accounts/{account_id}", response_model=SocialAccountRead)
def get_social_account(
    account_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    account = social_accounts_service.get_social_account(
        session, tenant_id=user_session.tenant.id, account_id=account_id
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found")
    return account


@router.post(
    "/content/ui/config/social-accounts", response_model=SocialAccountRead, status_code=201
)
def create_social_account(
    payload: SocialAccountCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    account = social_accounts_service.create_social_account(
        session,
        tenant_id=user_session.tenant.id,
        client_id=payload.client_id,
        platform=payload.platform,
        external_account_id=payload.external_account_id,
        credentials=payload.credentials,
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return account


@router.put("/content/ui/config/social-accounts/{account_id}", response_model=SocialAccountRead)
def update_social_account(
    account_id: int,
    payload: SocialAccountUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    account = social_accounts_service.update_social_account(
        session,
        tenant_id=user_session.tenant.id,
        account_id=account_id,
        external_account_id=payload.external_account_id,
        credentials=payload.credentials,
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return account


@router.delete("/content/ui/config/social-accounts/{account_id}", response_model=SocialAccountRead)
def revoke_social_account(
    account_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    account = social_accounts_service.revoke_social_account(
        session, tenant_id=user_session.tenant.id, account_id=account_id
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Social account not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="social_account",
        entity_id=account.id,
        action="revoked",
        actor=f"user:{user_session.user_id}",
    )
    return account
```

- [ ] **Step 6: Confirmar que a resposta nunca inclui a credencial**

Run: `python -c "from app.models.content import SocialAccountRead; assert 'credentials' not in SocialAccountRead.model_fields and 'credentials_encrypted' not in SocialAccountRead.model_fields; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add app/controllers/v1/content/ui_config.py app/models/content.py app/services/content/social_accounts.py test/services/test_content_social_accounts.py
git commit -m "feat(content): add UI-scoped CRUD routes for SocialAccount"
```

---

### Task 5: Avatar — service update/deactivate + rotas `ui_config` + DTO

**Files:**
- Modify: `app/models/content_generation.py:65-74` (`ContentAvatar` ganha `is_active`), `app/models/content_generation.py:173-181` (`AvatarRead` ganha `is_active`; novo DTO `AvatarUpdate`)
- Modify: `app/services/content/avatars.py` — `update_avatar`, `deactivate_avatar`
- Modify: `app/controllers/v1/content/ui_config.py` — rotas de Avatar
- Test: `test/services/test_content_avatars.py` (novo)

**Interfaces:**
- Consumes: `avatars_service.get_avatar` (já existe, `app/services/content/avatars.py:47`).
- Produces: `avatars_service.update_avatar(session, *, tenant_id, avatar_id, name=None, reference_image_url=None, voice_provider=None, voice_id=None) -> Optional[ContentAvatar]`, `avatars_service.deactivate_avatar(session, *, tenant_id, avatar_id) -> Optional[ContentAvatar]`.

- [ ] **Step 1: Escrever os testes**

```python
# test/services/test_content_avatars.py
import unittest
from unittest.mock import MagicMock

from app.models.content_generation import ContentAvatar
from app.services.content import avatars as avatars_service


class TestUpdateAvatar(unittest.TestCase):
    def test_updates_provided_fields(self):
        avatar = ContentAvatar(
            id=1, client_id=1, name="Old", reference_image_url="old.png", is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = avatar

        result = avatars_service.update_avatar(
            session, tenant_id=1, avatar_id=1, name="New", voice_id="voice-2"
        )

        self.assertEqual(result.name, "New")
        self.assertEqual(result.voice_id, "voice-2")
        self.assertEqual(result.reference_image_url, "old.png")
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = avatars_service.update_avatar(session, tenant_id=1, avatar_id=999, name="New")

        self.assertIsNone(result)


class TestDeactivateAvatar(unittest.TestCase):
    def test_sets_is_active_false(self):
        avatar = ContentAvatar(
            id=1, client_id=1, name="Acme", reference_image_url="a.png", is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = avatar

        result = avatars_service.deactivate_avatar(session, tenant_id=1, avatar_id=1)

        self.assertFalse(result.is_active)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest test/services/test_content_avatars.py -v`
Expected: FAIL — `AttributeError: module 'avatars_service' has no attribute 'update_avatar'`

- [ ] **Step 3: Implementar no model e no service**

Em `app/models/content_generation.py`, no corpo de `ContentAvatar` (linha 74, após `created_at`):

```python
    is_active: bool = Field(default=True)
```

Em `AvatarRead` (linha ~173-181):

```python
class AvatarRead(BaseModel):
    id: int
    client_id: int
    name: str
    reference_image_url: str
    voice_provider: Optional[str]
    voice_id: Optional[str]
    is_active: bool
    created_at: datetime
```

Novo DTO logo abaixo:

```python
class AvatarUpdate(BaseModel):
    name: Optional[str] = None
    reference_image_url: Optional[str] = None
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
```

Em `app/services/content/avatars.py`, ao final:

```python
def update_avatar(
    session: Session,
    *,
    tenant_id: int,
    avatar_id: int,
    name: Optional[str] = None,
    reference_image_url: Optional[str] = None,
    voice_provider: Optional[str] = None,
    voice_id: Optional[str] = None,
) -> Optional[ContentAvatar]:
    avatar = get_avatar(session, tenant_id=tenant_id, avatar_id=avatar_id)
    if avatar is None:
        return None
    if name is not None:
        avatar.name = name
    if reference_image_url is not None:
        avatar.reference_image_url = reference_image_url
    if voice_provider is not None:
        avatar.voice_provider = voice_provider
    if voice_id is not None:
        avatar.voice_id = voice_id
    session.add(avatar)
    session.commit()
    session.refresh(avatar)
    return avatar


def deactivate_avatar(
    session: Session, *, tenant_id: int, avatar_id: int
) -> Optional[ContentAvatar]:
    avatar = get_avatar(session, tenant_id=tenant_id, avatar_id=avatar_id)
    if avatar is None:
        return None
    avatar.is_active = False
    session.add(avatar)
    session.commit()
    session.refresh(avatar)
    return avatar
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `python -m pytest test/services/test_content_avatars.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Adicionar as rotas em `ui_config.py`**

Ajustar import (`app/models/content_generation` entra na lista de imports do arquivo):

```python
from app.models.content_generation import AvatarCreate, AvatarRead, AvatarUpdate
from app.services.content import avatars as avatars_service
```

```python
@router.get("/content/ui/config/clients/{client_id}/avatars", response_model=list[AvatarRead])
def list_avatars(
    client_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return avatars_service.list_avatars(
        session, tenant_id=user_session.tenant.id, client_id=client_id
    )


@router.get("/content/ui/config/avatars/{avatar_id}", response_model=AvatarRead)
def get_avatar(
    avatar_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    avatar = avatars_service.get_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=avatar_id
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return avatar


@router.post("/content/ui/config/avatars", response_model=AvatarRead, status_code=201)
def create_avatar(
    payload: AvatarCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    avatar = avatars_service.create_avatar(
        session,
        tenant_id=user_session.tenant.id,
        client_id=payload.client_id,
        name=payload.name,
        reference_image_url=payload.reference_image_url,
        voice_provider=payload.voice_provider,
        voice_id=payload.voice_id,
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Client not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return avatar


@router.put("/content/ui/config/avatars/{avatar_id}", response_model=AvatarRead)
def update_avatar(
    avatar_id: int,
    payload: AvatarUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    avatar = avatars_service.update_avatar(
        session,
        tenant_id=user_session.tenant.id,
        avatar_id=avatar_id,
        name=payload.name,
        reference_image_url=payload.reference_image_url,
        voice_provider=payload.voice_provider,
        voice_id=payload.voice_id,
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return avatar


@router.delete("/content/ui/config/avatars/{avatar_id}", response_model=AvatarRead)
def deactivate_avatar(
    avatar_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    avatar = avatars_service.deactivate_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=avatar_id
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return avatar
```

- [ ] **Step 6: Commit**

```bash
git add app/controllers/v1/content/ui_config.py app/models/content_generation.py app/services/content/avatars.py test/services/test_content_avatars.py
git commit -m "feat(content): add UI-scoped CRUD routes for Avatar"
```

---

### Task 6: ApprovalRule — GET individual + update/hard-delete + rotas `ui_config`

**Files:**
- Modify: `app/models/content.py:271-285` (novo DTO `ApprovalRuleUpdate`)
- Modify: `app/services/content/approval_rules.py` — `get_approval_rule`, `update_approval_rule`, `delete_approval_rule`
- Modify: `app/controllers/v1/content/ui_config.py` — rotas de ApprovalRule
- Test: `test/services/test_content_approval_rules.py` (novo)

**Interfaces:**
- Consumes: `approval_rules_service.list_approval_rules` (já existe); é a mesma função consumida por `automation_scheduler._decide_approval_action` — nenhuma mudança de assinatura nela.
- Produces: `approval_rules_service.get_approval_rule(session, *, tenant_id, rule_id) -> Optional[ContentApprovalRule]`, `update_approval_rule(session, *, tenant_id, rule_id, condition=None, action=None, priority=None) -> Optional[ContentApprovalRule]`, `delete_approval_rule(session, *, tenant_id, rule_id) -> bool` (hard-delete, retorna se encontrou e apagou).

- [ ] **Step 1: Escrever os testes**

```python
# test/services/test_content_approval_rules.py
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ApprovalAction, ContentApprovalRule
from app.services.content import approval_rules as approval_rules_service


class TestGetApprovalRule(unittest.TestCase):
    def test_returns_rule_when_campaign_belongs_to_tenant(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={}, action=ApprovalAction.auto_approve, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=MagicMock(id=1)):
            result = approval_rules_service.get_approval_rule(session, tenant_id=1, rule_id=1)

        self.assertIs(result, rule)

    def test_returns_none_when_rule_row_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = approval_rules_service.get_approval_rule(session, tenant_id=1, rule_id=999)

        self.assertIsNone(result)

    def test_returns_none_when_campaign_belongs_to_other_tenant(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={}, action=ApprovalAction.auto_approve, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=None):
            result = approval_rules_service.get_approval_rule(session, tenant_id=2, rule_id=1)

        self.assertIsNone(result)


class TestUpdateApprovalRule(unittest.TestCase):
    def test_updates_provided_fields(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={"a": 1}, action=ApprovalAction.require_review,
            priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=MagicMock(id=1)):
            result = approval_rules_service.update_approval_rule(
                session, tenant_id=1, rule_id=1, priority=10, action=ApprovalAction.auto_approve,
            )

        self.assertEqual(result.priority, 10)
        self.assertEqual(result.action, ApprovalAction.auto_approve)
        self.assertEqual(result.condition, {"a": 1})
        session.commit.assert_called_once()


class TestDeleteApprovalRule(unittest.TestCase):
    def test_deletes_and_returns_true_when_found(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={}, action=ApprovalAction.auto_approve, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=MagicMock(id=1)):
            result = approval_rules_service.delete_approval_rule(session, tenant_id=1, rule_id=1)

        self.assertTrue(result)
        session.delete.assert_called_once_with(rule)
        session.commit.assert_called_once()

    def test_returns_false_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = approval_rules_service.delete_approval_rule(session, tenant_id=1, rule_id=999)

        self.assertFalse(result)
        session.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest test/services/test_content_approval_rules.py -v`
Expected: FAIL — `AttributeError: module 'approval_rules_service' has no attribute 'get_approval_rule'`

- [ ] **Step 3: Implementar no service e o DTO**

Em `app/models/content.py`, logo após `ApprovalRuleRead` (linha ~285):

```python
class ApprovalRuleUpdate(BaseModel):
    condition: Optional[dict] = None
    action: Optional[ApprovalAction] = None
    priority: Optional[int] = None
```

Em `app/services/content/approval_rules.py`, ajustar o import (`from app.models.content import ApprovalAction, ContentApprovalRule, ContentCampaign` — `ContentCampaign` só é necessário se usar join direto; aqui reaproveita-se `get_campaign` do módulo `campaigns`, então basta um join simples via subquery-like filtro reaproveitando `get_campaign`). Ao final do arquivo:

```python
def get_approval_rule(
    session: Session, *, tenant_id: int, rule_id: int
) -> Optional[ContentApprovalRule]:
    rule = session.exec(
        select(ContentApprovalRule).where(ContentApprovalRule.id == rule_id)
    ).first()
    if rule is None:
        return None
    if get_campaign(session, tenant_id=tenant_id, campaign_id=rule.campaign_id) is None:
        return None
    return rule


def update_approval_rule(
    session: Session,
    *,
    tenant_id: int,
    rule_id: int,
    condition: Optional[dict] = None,
    action: Optional[ApprovalAction] = None,
    priority: Optional[int] = None,
) -> Optional[ContentApprovalRule]:
    rule = get_approval_rule(session, tenant_id=tenant_id, rule_id=rule_id)
    if rule is None:
        return None
    if condition is not None:
        rule.condition = condition
    if action is not None:
        rule.action = action
    if priority is not None:
        rule.priority = priority
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


def delete_approval_rule(session: Session, *, tenant_id: int, rule_id: int) -> bool:
    rule = get_approval_rule(session, tenant_id=tenant_id, rule_id=rule_id)
    if rule is None:
        return False
    session.delete(rule)
    session.commit()
    return True
```

Nota: `get_approval_rule` faz o filtro de tenant reaproveitando `get_campaign` (que já faz o join `Campaign→Client→tenant_id`) em vez de duplicar o join — `campaign_id` da regra encontrada só é aceito se `get_campaign` confirmar que aquela campanha pertence à tenant da sessão.

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `python -m pytest test/services/test_content_approval_rules.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Adicionar as rotas em `ui_config.py`**

```python
from app.models.content import ApprovalRuleCreate, ApprovalRuleRead, ApprovalRuleUpdate
from app.services.content import approval_rules as approval_rules_service
```

```python
@router.get(
    "/content/ui/config/campaigns/{campaign_id}/approval-rules",
    response_model=list[ApprovalRuleRead],
)
def list_approval_rules(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return approval_rules_service.list_approval_rules(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )


@router.get("/content/ui/config/approval-rules/{rule_id}", response_model=ApprovalRuleRead)
def get_approval_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    rule = approval_rules_service.get_approval_rule(
        session, tenant_id=user_session.tenant.id, rule_id=rule_id
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    return rule


@router.post("/content/ui/config/approval-rules", response_model=ApprovalRuleRead, status_code=201)
def create_approval_rule(
    payload: ApprovalRuleCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    rule = approval_rules_service.create_approval_rule(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=payload.campaign_id,
        condition=payload.condition,
        action=payload.action,
        priority=payload.priority,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="approval_rule",
        entity_id=rule.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return rule


@router.put("/content/ui/config/approval-rules/{rule_id}", response_model=ApprovalRuleRead)
def update_approval_rule(
    rule_id: int,
    payload: ApprovalRuleUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    rule = approval_rules_service.update_approval_rule(
        session,
        tenant_id=user_session.tenant.id,
        rule_id=rule_id,
        condition=payload.condition,
        action=payload.action,
        priority=payload.priority,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="approval_rule",
        entity_id=rule.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return rule


@router.delete("/content/ui/config/approval-rules/{rule_id}", status_code=204)
def delete_approval_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    deleted = approval_rules_service.delete_approval_rule(
        session, tenant_id=user_session.tenant.id, rule_id=rule_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Approval rule not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="approval_rule",
        entity_id=rule_id,
        action="deleted",
        actor=f"user:{user_session.user_id}",
    )
```

- [ ] **Step 6: Commit**

```bash
git add app/controllers/v1/content/ui_config.py app/models/content.py app/services/content/approval_rules.py test/services/test_content_approval_rules.py
git commit -m "feat(content): add UI-scoped CRUD routes for ApprovalRule"
```

---

### Task 7: GenerationTemplate — GET individual + update/deactivate + rotas `ui_config`

**Files:**
- Modify: `app/models/content.py:173-192` (`ContentGenerationTemplate` ganha `is_active`), `app/models/content.py:300-312` (`GenerationTemplateRead` ganha `is_active`; novo DTO `GenerationTemplateUpdate`)
- Modify: `app/services/content/generation_templates.py` — `get_template`, `update_template`, `deactivate_template`
- Modify: `app/controllers/v1/content/ui_config.py` — rotas de GenerationTemplate
- Test: `test/services/test_content_generation_templates.py` — acrescentar aos testes existentes

**Interfaces:**
- Consumes: `templates_service.list_templates` (já existe, consumido também por `orchestrator`/`pick_template_index` — assinatura inalterada).
- Produces: `templates_service.get_template(session, *, tenant_id, template_id) -> Optional[ContentGenerationTemplate]`, `update_template(session, *, tenant_id, template_id, **fields) -> Optional[...]`, `deactivate_template(session, *, tenant_id, template_id) -> Optional[...]`.

- [ ] **Step 1: Escrever os testes**

Acrescentar ao final de `test/services/test_content_generation_templates.py` (preservar os testes existentes de `TestCreateTemplate`/`TestListTemplates`; o arquivo já importa `unittest`, `MagicMock`, `patch` e `templates_service` — não duplicar esses imports, só acrescentar `ContentGenerationTemplate` ao import de `app.models.content`, que já traz `ContentPieceType`):

```python
class TestGetTemplate(unittest.TestCase):
    def test_returns_template_when_campaign_belongs_to_tenant(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=MagicMock(id=1)):
            result = templates_service.get_template(session, tenant_id=1, template_id=1)

        self.assertIs(result, template)

    def test_returns_none_when_campaign_belongs_to_other_tenant(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=None):
            result = templates_service.get_template(session, tenant_id=2, template_id=1)

        self.assertIsNone(result)


class TestUpdateTemplate(unittest.TestCase):
    def test_updates_provided_fields(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, generation_prompt="old",
            aspect_ratio="9:16", is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=MagicMock(id=1)):
            result = templates_service.update_template(
                session, tenant_id=1, template_id=1, generation_prompt="new", aspect_ratio="1:1",
            )

        self.assertEqual(result.generation_prompt, "new")
        self.assertEqual(result.aspect_ratio, "1:1")
        session.commit.assert_called_once()


class TestDeactivateTemplate(unittest.TestCase):
    def test_sets_is_active_false(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=MagicMock(id=1)):
            result = templates_service.deactivate_template(session, tenant_id=1, template_id=1)

        self.assertFalse(result.is_active)
```

Ajustar o import de `app.models.content` no topo do arquivo para incluir `ContentGenerationTemplate` junto de `ContentPieceType`.

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest test/services/test_content_generation_templates.py -v`
Expected: FAIL — `AttributeError: module 'templates_service' has no attribute 'get_template'`

- [ ] **Step 3: Implementar no model e no service**

Em `app/models/content.py`, no corpo de `ContentGenerationTemplate` (linha 192, após `created_at`):

```python
    is_active: bool = Field(default=True)
```

Em `GenerationTemplateRead` (linha ~300-312), acrescentar `is_active: bool` junto dos demais campos, e criar o DTO de update logo abaixo:

```python
class GenerationTemplateUpdate(BaseModel):
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = None
    voice_id: Optional[str] = None
    is_synthetic_media: Optional[bool] = None
    content_category: Optional[ContentCategory] = None
    aspect_ratio: Optional[str] = None
    resolution: Optional[str] = None
    duration: Optional[int] = None
```

Em `app/services/content/generation_templates.py`, ao final:

```python
def get_template(
    session: Session, *, tenant_id: int, template_id: int
) -> Optional[ContentGenerationTemplate]:
    template = session.exec(
        select(ContentGenerationTemplate).where(ContentGenerationTemplate.id == template_id)
    ).first()
    if template is None:
        return None
    if get_campaign(session, tenant_id=tenant_id, campaign_id=template.campaign_id) is None:
        return None
    return template


def update_template(
    session: Session,
    *,
    tenant_id: int,
    template_id: int,
    generation_prompt: Optional[str] = None,
    avatar_id: Optional[int] = None,
    voice_id: Optional[str] = None,
    is_synthetic_media: Optional[bool] = None,
    content_category: Optional[ContentCategory] = None,
    aspect_ratio: Optional[str] = None,
    resolution: Optional[str] = None,
    duration: Optional[int] = None,
) -> Optional[ContentGenerationTemplate]:
    template = get_template(session, tenant_id=tenant_id, template_id=template_id)
    if template is None:
        return None
    if generation_prompt is not None:
        template.generation_prompt = generation_prompt
    if avatar_id is not None:
        template.avatar_id = avatar_id
    if voice_id is not None:
        template.voice_id = voice_id
    if is_synthetic_media is not None:
        template.is_synthetic_media = is_synthetic_media
    if content_category is not None:
        template.content_category = content_category
    if aspect_ratio is not None:
        template.aspect_ratio = aspect_ratio
    if resolution is not None:
        template.resolution = resolution
    if duration is not None:
        template.duration = duration
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def deactivate_template(
    session: Session, *, tenant_id: int, template_id: int
) -> Optional[ContentGenerationTemplate]:
    template = get_template(session, tenant_id=tenant_id, template_id=template_id)
    if template is None:
        return None
    template.is_active = False
    session.add(template)
    session.commit()
    session.refresh(template)
    return template
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `python -m pytest test/services/test_content_generation_templates.py -v`
Expected: PASS (todos os testes, existentes + novos)

- [ ] **Step 5: Adicionar as rotas em `ui_config.py`**

```python
from app.models.content import (
    GenerationTemplateCreate,
    GenerationTemplateRead,
    GenerationTemplateUpdate,
)
from app.services.content import generation_templates as templates_service
```

```python
@router.get(
    "/content/ui/config/campaigns/{campaign_id}/templates",
    response_model=list[GenerationTemplateRead],
)
def list_templates(
    campaign_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return templates_service.list_templates(
        session, tenant_id=user_session.tenant.id, campaign_id=campaign_id
    )


@router.get("/content/ui/config/templates/{template_id}", response_model=GenerationTemplateRead)
def get_template(
    template_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    template = templates_service.get_template(
        session, tenant_id=user_session.tenant.id, template_id=template_id
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Generation template not found")
    return template


@router.post(
    "/content/ui/config/campaigns/{campaign_id}/templates",
    response_model=GenerationTemplateRead,
    status_code=201,
)
def create_template(
    campaign_id: int,
    payload: GenerationTemplateCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    if campaign_id != payload.campaign_id:
        raise HTTPException(status_code=422, detail="campaign_id in path and body must match")
    template = templates_service.create_template(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=payload.campaign_id,
        type=payload.type,
        generation_prompt=payload.generation_prompt,
        avatar_id=payload.avatar_id,
        voice_id=payload.voice_id,
        is_synthetic_media=payload.is_synthetic_media,
        content_category=payload.content_category,
        aspect_ratio=payload.aspect_ratio,
        resolution=payload.resolution,
        duration=payload.duration,
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_template",
        entity_id=template.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return template


@router.put("/content/ui/config/templates/{template_id}", response_model=GenerationTemplateRead)
def update_template(
    template_id: int,
    payload: GenerationTemplateUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    template = templates_service.update_template(
        session,
        tenant_id=user_session.tenant.id,
        template_id=template_id,
        generation_prompt=payload.generation_prompt,
        avatar_id=payload.avatar_id,
        voice_id=payload.voice_id,
        is_synthetic_media=payload.is_synthetic_media,
        content_category=payload.content_category,
        aspect_ratio=payload.aspect_ratio,
        resolution=payload.resolution,
        duration=payload.duration,
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Generation template not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_template",
        entity_id=template.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return template


@router.delete("/content/ui/config/templates/{template_id}", response_model=GenerationTemplateRead)
def deactivate_template(
    template_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    template = templates_service.deactivate_template(
        session, tenant_id=user_session.tenant.id, template_id=template_id
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Generation template not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_template",
        entity_id=template.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return template
```

- [ ] **Step 6: Commit**

```bash
git add app/controllers/v1/content/ui_config.py app/models/content.py app/services/content/generation_templates.py test/services/test_content_generation_templates.py
git commit -m "feat(content): add UI-scoped CRUD routes for GenerationTemplate"
```

---

### Task 8: Provider — update (priority/config/credentials) + rotas `ui_config`

**Files:**
- Modify: `app/models/content_generation.py:146-152` (novo DTO `GenerationProviderUpdate`)
- Modify: `app/services/content/generation_providers.py` — `update_generation_provider`
- Modify: `app/controllers/v1/content/ui_config.py` — rotas de Provider
- Test: `test/services/test_content_generation_providers.py` (novo)

**Interfaces:**
- Consumes: `providers_service.get_generation_provider`, `providers_service.list_generation_providers`, `providers_service.deactivate_generation_provider` (já existem, `app/services/content/generation_providers.py`); `provider_adapters.validate_credentials` (já existe, usado em `app/controllers/v1/content/providers.py:32`).
- Produces: `providers_service.update_generation_provider(session, *, tenant_id, provider_id, credentials=None, config=None, priority=None) -> Optional[ContentGenerationProvider]`.

- [ ] **Step 1: Escrever o teste**

```python
# test/services/test_content_generation_providers.py
import unittest
from unittest.mock import MagicMock

from app.models.content_generation import (
    ContentGenerationProvider,
    GenerationKind,
    GenerationProviderName,
)
from app.services.content import generation_providers as providers_service


class TestUpdateGenerationProvider(unittest.TestCase):
    def test_updates_priority_and_config_without_touching_credentials(self):
        row = ContentGenerationProvider(
            id=1, tenant_id=1, kind=GenerationKind.image, provider=GenerationProviderName.falai,
            credentials_encrypted="unchanged-enc", config={"a": 1}, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = row

        result = providers_service.update_generation_provider(
            session, tenant_id=1, provider_id=1, priority=5, config={"b": 2}
        )

        self.assertEqual(result.priority, 5)
        self.assertEqual(result.config, {"b": 2})
        self.assertEqual(result.credentials_encrypted, "unchanged-enc")
        session.commit.assert_called_once()

    def test_reencrypts_credentials_when_provided(self):
        row = ContentGenerationProvider(
            id=1, tenant_id=1, kind=GenerationKind.image, provider=GenerationProviderName.falai,
            credentials_encrypted="old-enc", config={}, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = row

        result = providers_service.update_generation_provider(
            session, tenant_id=1, provider_id=1, credentials="new-secret"
        )

        self.assertNotEqual(result.credentials_encrypted, "old-enc")

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = providers_service.update_generation_provider(
            session, tenant_id=1, provider_id=999, priority=5
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `python -m pytest test/services/test_content_generation_providers.py -v`
Expected: FAIL — `AttributeError: module 'providers_service' has no attribute 'update_generation_provider'`

- [ ] **Step 3: Implementar no service e o DTO**

Em `app/models/content_generation.py`, logo após `GenerationProviderRead` (linha ~163):

```python
class GenerationProviderUpdate(BaseModel):
    credentials: Optional[str] = None
    config: Optional[dict] = None
    priority: Optional[int] = None
```

Em `app/services/content/generation_providers.py`, ao final:

```python
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
```

- [ ] **Step 4: Rodar e confirmar sucesso**

Run: `python -m pytest test/services/test_content_generation_providers.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Adicionar as rotas em `ui_config.py`**

```python
from app.models.content_generation import (
    AvatarCreate,
    AvatarRead,
    AvatarUpdate,
    GenerationKind,
    GenerationProviderCreate,
    GenerationProviderRead,
    GenerationProviderUpdate,
)
from app.services.content import generation_providers as providers_service
from app.services.content import providers as provider_adapters
from app.services.content.errors import GenerationError, is_retryable
```

```python
@router.get("/content/ui/config/providers", response_model=list[GenerationProviderRead])
def list_providers(
    kind: Optional[GenerationKind] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return providers_service.list_generation_providers(
        session, tenant_id=user_session.tenant.id, kind=kind
    )


@router.post("/content/ui/config/providers", response_model=GenerationProviderRead, status_code=201)
def create_provider(
    payload: GenerationProviderCreate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    try:
        provider_adapters.validate_credentials(
            provider=payload.provider.value, api_key=payload.credentials
        )
    except GenerationError as error:
        if is_retryable(error.code):
            raise HTTPException(status_code=503, detail=error.message)
        raise HTTPException(status_code=422, detail=error.message)

    row = providers_service.create_generation_provider(
        session,
        tenant_id=user_session.tenant.id,
        kind=payload.kind,
        provider=payload.provider,
        credentials=payload.credentials,
        config=payload.config,
        priority=payload.priority,
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="created",
        actor=f"user:{user_session.user_id}",
    )
    return row


@router.put("/content/ui/config/providers/{provider_id}", response_model=GenerationProviderRead)
def update_provider(
    provider_id: int,
    payload: GenerationProviderUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    existing = providers_service.get_generation_provider(
        session, tenant_id=user_session.tenant.id, provider_id=provider_id
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Generation provider not found")

    if payload.credentials is not None:
        try:
            provider_adapters.validate_credentials(
                provider=existing.provider.value, api_key=payload.credentials
            )
        except GenerationError as error:
            if is_retryable(error.code):
                raise HTTPException(status_code=503, detail=error.message)
            raise HTTPException(status_code=422, detail=error.message)

    row = providers_service.update_generation_provider(
        session,
        tenant_id=user_session.tenant.id,
        provider_id=provider_id,
        credentials=payload.credentials,
        config=payload.config,
        priority=payload.priority,
    )
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="updated",
        actor=f"user:{user_session.user_id}",
    )
    return row


@router.delete("/content/ui/config/providers/{provider_id}", response_model=GenerationProviderRead)
def deactivate_provider(
    provider_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")
    row = providers_service.deactivate_generation_provider(
        session, tenant_id=user_session.tenant.id, provider_id=provider_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Generation provider not found")
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="deactivated",
        actor=f"user:{user_session.user_id}",
    )
    return row
```

Nota: `AvatarCreate`/`AvatarRead`/`AvatarUpdate` já foram importados na Task 5 — este bloco mostra o import consolidado esperado ao final de todas as tasks de backend; ao aplicar esta task, apenas acrescentar os símbolos novos (`GenerationKind`, `GenerationProviderCreate`, `GenerationProviderRead`, `GenerationProviderUpdate`) ao import já existente de `app.models.content_generation` em vez de duplicar a linha.

- [ ] **Step 6: Rodar toda a suíte de testes de content para garantir que nada quebrou**

Run: `python -m pytest test/services/ -k content -v`
Expected: PASS em todos os testes de `content` — incluindo os pré-existentes (`test_content_providers` se houver, `test_content_automation_scheduler.py`, etc.), confirmando que `ui_config.py` é aditivo e as rotas `/content/providers`, `/content/campaigns` etc. via `X-Tenant-Token` continuam intactas.

- [ ] **Step 7: Commit**

```bash
git add app/controllers/v1/content/ui_config.py app/models/content_generation.py app/services/content/generation_providers.py test/services/test_content_generation_providers.py
git commit -m "feat(content): add UI-scoped update route for GenerationProvider"
```

---

### Task 9: Frontend — `apiClient` ganha put/patch/delete + corrige import de CSS

**Files:**
- Modify: `webui/src/lib/apiClient.ts:40-44`
- Modify: `webui/src/main.tsx:1-5`

**Interfaces:**
- Produces: `apiClient.put<T>(path, body)`, `apiClient.patch<T>(path, body)`, `apiClient.delete<T>(path)` — consumidos por todas as páginas de `pages/config/*.tsx` das tasks seguintes.

- [ ] **Step 1: Estender `apiClient`**

```typescript
// webui/src/lib/apiClient.ts — substituir o bloco final (linhas 40-44)
export const apiClient = {
  get: <T>(path: string): Promise<T> => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string): Promise<T> => request<T>(path, { method: "DELETE" }),
  setToken,
};
```

Nota: `apiClient.post` ganha um segundo parâmetro `body` opcional aqui — `PieceDetail.tsx` já chama `apiClient.post(`/content/ui/pieces/${id}/${action}`)` sem body, que continua funcionando (`body` fica `undefined`, sem quebrar a assinatura existente).

- [ ] **Step 2: Corrigir o import de CSS faltando**

```typescript
// webui/src/main.tsx — acrescentar logo após os imports existentes (linha 4)
import "./index.css";
```

- [ ] **Step 3: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add webui/src/lib/apiClient.ts webui/src/main.tsx
git commit -m "fix(webui): add put/patch/delete to apiClient, import missing index.css"
```

---

### Task 10: Frontend — `RequireRole` (guard de rota por role)

**Files:**
- Create: `webui/src/components/RequireRole.tsx`

**Interfaces:**
- Consumes: `useSession()` de `webui/src/context/SessionProvider.tsx` (já existe, expõe `session: { role: "admin" | "member" } | null`).
- Produces: `<RequireRole role="admin">{children}</RequireRole>` — usado por todas as páginas de `pages/config/*.tsx` para envolver os controles de escrita (formulário de create/edit, botão de delete).

- [ ] **Step 1: Criar o componente**

```tsx
// webui/src/components/RequireRole.tsx
import type { ReactNode } from "react";
import { useSession } from "../context/SessionProvider";

export function RequireRole({
  role,
  children,
  fallback,
}: {
  role: "admin" | "member";
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { session } = useSession();

  if (session?.role !== role) {
    return <>{fallback ?? <p>Acesso restrito a administradores.</p>}</>;
  }

  return <>{children}</>;
}
```

- [ ] **Step 2: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 3: Commit**

```bash
git add webui/src/components/RequireRole.tsx
git commit -m "feat(webui): add RequireRole route guard component"
```

---

### Task 11: Frontend — tipos das 7 entidades em `types.ts`

**Files:**
- Modify: `webui/src/lib/types.ts`

**Interfaces:**
- Produces: `Client`, `SocialAccount`, `Avatar`, `ApprovalRule`, `GenerationTemplate`, `Provider` e os respectivos `*CreatePayload`/`*UpdatePayload` — consumidos por todas as páginas das tasks 12-18. `Campaign` já existe (linha 10-17) e ganha nenhum campo novo (o backend não adicionou coluna nova a Campaign, só reaproveitou `status`).

- [ ] **Step 1: Acrescentar os tipos ao final de `types.ts`**

```typescript
export interface Client {
  id: number;
  tenant_id: number;
  name: string;
  is_active: boolean;
  created_at: string;
}

export interface ClientPayload {
  name: string;
}

export interface SocialAccount {
  id: number;
  client_id: number;
  platform: string;
  external_account_id: string;
  status: string;
  created_at: string;
}

export interface SocialAccountCreatePayload {
  client_id: number;
  platform: string;
  external_account_id: string;
  credentials: string;
}

export interface SocialAccountUpdatePayload {
  external_account_id?: string;
  credentials?: string;
}

export interface Avatar {
  id: number;
  client_id: number;
  name: string;
  reference_image_url: string;
  voice_provider: string | null;
  voice_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AvatarPayload {
  client_id?: number;
  name: string;
  reference_image_url: string;
  voice_provider?: string | null;
  voice_id?: string | null;
}

export interface ApprovalRule {
  id: number;
  campaign_id: number;
  condition: Record<string, unknown>;
  action: "auto_approve" | "require_review";
  priority: number;
  created_at: string;
}

export interface ApprovalRulePayload {
  campaign_id?: number;
  condition: Record<string, unknown>;
  action: "auto_approve" | "require_review";
  priority: number;
}

export interface GenerationTemplate {
  id: number;
  campaign_id: number;
  type: "video" | "image" | "audio";
  generation_prompt: string | null;
  avatar_id: number | null;
  voice_id: string | null;
  is_synthetic_media: boolean;
  content_category: string | null;
  aspect_ratio: string;
  resolution: string | null;
  duration: number | null;
  is_active: boolean;
  created_at: string;
}

export interface GenerationTemplatePayload {
  campaign_id?: number;
  type: "video" | "image" | "audio";
  generation_prompt?: string | null;
  avatar_id?: number | null;
  voice_id?: string | null;
  is_synthetic_media: boolean;
  content_category?: string | null;
  aspect_ratio: string;
  resolution?: string | null;
  duration?: number | null;
}

export interface Provider {
  id: number;
  tenant_id: number;
  kind: "image" | "video" | "voice";
  provider: "wavespeed" | "falai" | "gemini" | "elevenlabs";
  config: Record<string, unknown>;
  priority: number;
  is_active: boolean;
  created_at: string;
}

export interface ProviderCreatePayload {
  kind: "image" | "video" | "voice";
  provider: "wavespeed" | "falai" | "gemini" | "elevenlabs";
  credentials: string;
  config: Record<string, unknown>;
  priority: number;
}

export interface ProviderUpdatePayload {
  credentials?: string;
  config?: Record<string, unknown>;
  priority?: number;
}
```

- [ ] **Step 2: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 3: Commit**

```bash
git add webui/src/lib/types.ts
git commit -m "feat(webui): add TypeScript types for the 7 config entities"
```

---

### Task 12: Frontend — nav de configuração + página `Clients`

**Files:**
- Create: `webui/src/components/ConfigNav.tsx`
- Create: `webui/src/pages/config/Clients.tsx`
- Modify: `webui/src/App.tsx` — nav + rota `/config/clients`

**Interfaces:**
- Consumes: `apiClient`, `RequireRole` (Task 10), tipos `Client`/`ClientPayload` (Task 11).
- Produces: `ConfigNav` — lista de links para as 7 telas de config, estendida a cada task seguinte conforme a página correspondente é criada.

- [ ] **Step 1: Criar `ConfigNav`**

```tsx
// webui/src/components/ConfigNav.tsx
import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/config/clients", label: "Clients" },
  { to: "/config/campaigns", label: "Campaigns" },
  { to: "/config/social-accounts", label: "Social Accounts" },
  { to: "/config/avatars", label: "Avatars" },
  { to: "/config/approval-rules", label: "Approval Rules" },
  { to: "/config/templates", label: "Templates" },
  { to: "/config/providers", label: "Providers" },
];

export function ConfigNav() {
  return (
    <nav>
      <NavLink to="/" end>
        Fila de peças
      </NavLink>
      {LINKS.map((link) => (
        <NavLink key={link.to} to={link.to}>
          {link.label}
        </NavLink>
      ))}
    </nav>
  );
}
```

- [ ] **Step 2: Criar a página `Clients`**

```tsx
// webui/src/pages/config/Clients.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiError } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Client, ClientPayload } from "../../lib/types";

export function Clients() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const create = useMutation({
    mutationFn: (payload: ClientPayload) =>
      apiClient.post<Client>("/content/ui/config/clients", payload),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["config", "clients"] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Client>(`/content/ui/config/clients/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "clients"] }),
  });

  const forbidden = create.error instanceof ApiError && create.error.status === 403;

  return (
    <div>
      <h1>Clients</h1>

      {clients.isLoading && <p>Carregando...</p>}
      {clients.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {clients.data?.map((client) => (
          <li key={client.id}>
            {client.name} {!client.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!client.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(client.id)}
              >
                Desativar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ name });
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nome do client"
            required
          />
          <button type="submit" disabled={create.isPending}>
            Criar
          </button>
          {forbidden && <p>Você não tem permissão para criar clients.</p>}
        </form>
      </RequireRole>
    </div>
  );
}
```

- [ ] **Step 3: Registrar a rota e o nav em `App.tsx`**

```tsx
// webui/src/App.tsx — versão completa após esta task
import type { ReactNode } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SessionProvider, useSession } from "./context/SessionProvider";
import { ConfigNav } from "./components/ConfigNav";
import { PieceQueue } from "./pages/PieceQueue";
import { PieceDetail } from "./pages/PieceDetail";
import { Clients } from "./pages/config/Clients";

function Gate({ children }: { children: ReactNode }) {
  const { status } = useSession();

  if (status === "waiting") return <p>Aguardando sessão do app mãe...</p>;
  if (status === "loading") return <p>Validando sessão...</p>;
  if (status === "error") return <p>Sessão expirada ou inválida. Feche e reabra este painel.</p>;

  return <>{children}</>;
}

export function App() {
  return (
    <SessionProvider>
      <Gate>
        <BrowserRouter>
          <ConfigNav />
          <Routes>
            <Route path="/" element={<PieceQueue />} />
            <Route path="/pieces/:id" element={<PieceDetail />} />
            <Route path="/config/clients" element={<Clients />} />
          </Routes>
        </BrowserRouter>
      </Gate>
    </SessionProvider>
  );
}
```

- [ ] **Step 4: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 5: Commit**

```bash
git add webui/src/components/ConfigNav.tsx webui/src/pages/config/Clients.tsx webui/src/App.tsx
git commit -m "feat(webui): add config nav and Clients page"
```

---

### Task 13: Frontend — página `Campaigns` + atualizar `PieceQueue` para o novo endpoint

**Files:**
- Create: `webui/src/pages/config/Campaigns.tsx`
- Modify: `webui/src/App.tsx` — rota `/config/campaigns`
- Modify: `webui/src/pages/PieceQueue.tsx:21` — `/content/ui/campaigns` → `/content/ui/config/campaigns`

**Interfaces:**
- Consumes: `Campaign` (já existe em `types.ts`), `apiClient`, `RequireRole`.

- [ ] **Step 1: Criar a página `Campaigns`**

```tsx
// webui/src/pages/config/Campaigns.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Campaign, Client } from "../../lib/types";

export function Campaigns() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [horizonDays, setHorizonDays] = useState(7);

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const create = useMutation({
    mutationFn: () =>
      apiClient.post<Campaign>("/content/ui/config/campaigns", {
        client_id: clientId,
        name,
        horizon_days: horizonDays,
      }),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] });
    },
  });

  const archive = useMutation({
    mutationFn: (id: number) => apiClient.delete<Campaign>(`/content/ui/config/campaigns/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "campaigns"] }),
  });

  return (
    <div>
      <h1>Campaigns</h1>

      {campaigns.isLoading && <p>Carregando...</p>}
      {campaigns.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {campaigns.data?.map((campaign) => (
          <li key={campaign.id}>
            {campaign.name} — {campaign.status}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={campaign.status !== "active" || archive.isPending}
                onClick={() => archive.mutate(campaign.id)}
              >
                Arquivar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId !== null) create.mutate();
          }}
        >
          <select
            value={clientId ?? ""}
            onChange={(event) => setClientId(Number(event.target.value))}
            required
          >
            <option value="" disabled>
              Selecione um client
            </option>
            {clients.data?.map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
              </option>
            ))}
          </select>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nome da campanha"
            required
          />
          <input
            type="number"
            value={horizonDays}
            onChange={(event) => setHorizonDays(Number(event.target.value))}
            min={1}
          />
          <button type="submit" disabled={create.isPending}>
            Criar
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
```

- [ ] **Step 2: Atualizar `PieceQueue.tsx` para o novo endpoint de campanhas**

```typescript
// webui/src/pages/PieceQueue.tsx — linha 21, dentro do useQuery de campaigns
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
```

- [ ] **Step 3: Registrar a rota em `App.tsx`**

```tsx
import { Campaigns } from "./pages/config/Campaigns";
// ...
            <Route path="/config/campaigns" element={<Campaigns />} />
```

- [ ] **Step 4: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 5: Commit**

```bash
git add webui/src/pages/config/Campaigns.tsx webui/src/pages/PieceQueue.tsx webui/src/App.tsx
git commit -m "feat(webui): add Campaigns page, point PieceQueue at /ui/config/campaigns"
```

---

### Task 14: Frontend — página `SocialAccounts`

**Files:**
- Create: `webui/src/pages/config/SocialAccounts.tsx`
- Modify: `webui/src/App.tsx` — rota `/config/social-accounts`

**Interfaces:**
- Consumes: `SocialAccount`, `SocialAccountCreatePayload`, `Client` (`types.ts`), `apiClient`, `RequireRole`.

- [ ] **Step 1: Criar a página**

```tsx
// webui/src/pages/config/SocialAccounts.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Client, SocialAccount, SocialAccountCreatePayload } from "../../lib/types";

export function SocialAccounts() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [platform, setPlatform] = useState("instagram");
  const [externalAccountId, setExternalAccountId] = useState("");
  const [credentials, setCredentials] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const accounts = useQuery({
    queryKey: ["config", "social-accounts", clientId],
    queryFn: () =>
      apiClient.get<SocialAccount[]>(
        `/content/ui/config/clients/${clientId}/social-accounts`
      ),
    enabled: clientId !== null,
  });

  const create = useMutation({
    mutationFn: (payload: SocialAccountCreatePayload) =>
      apiClient.post<SocialAccount>("/content/ui/config/social-accounts", payload),
    onSuccess: () => {
      setExternalAccountId("");
      setCredentials("");
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<SocialAccount>(`/content/ui/config/social-accounts/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "social-accounts", clientId] }),
  });

  return (
    <div>
      <h1>Social Accounts</h1>

      <select
        value={clientId ?? ""}
        onChange={(event) => setClientId(Number(event.target.value) || null)}
      >
        <option value="">Selecione um client</option>
        {clients.data?.map((client) => (
          <option key={client.id} value={client.id}>
            {client.name}
          </option>
        ))}
      </select>

      {accounts.isLoading && <p>Carregando...</p>}
      {accounts.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {accounts.data?.map((account) => (
          <li key={account.id}>
            {account.platform} — {account.external_account_id} — {account.status}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={account.status !== "active" || revoke.isPending}
                onClick={() => revoke.mutate(account.id)}
              >
                Revogar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId === null) return;
            create.mutate({
              client_id: clientId,
              platform,
              external_account_id: externalAccountId,
              credentials,
            });
          }}
        >
          <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
            <option value="instagram">Instagram</option>
            <option value="tiktok">TikTok</option>
            <option value="youtube">YouTube</option>
            <option value="x">X</option>
            <option value="facebook">Facebook</option>
            <option value="linkedin">LinkedIn</option>
          </select>
          <input
            value={externalAccountId}
            onChange={(event) => setExternalAccountId(event.target.value)}
            placeholder="ID da conta na plataforma"
            required
          />
          <input
            type="password"
            value={credentials}
            onChange={(event) => setCredentials(event.target.value)}
            placeholder="Credencial de acesso"
            required
          />
          <button type="submit" disabled={create.isPending || clientId === null}>
            Conectar
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
```

- [ ] **Step 2: Registrar a rota**

```tsx
import { SocialAccounts } from "./pages/config/SocialAccounts";
// ...
            <Route path="/config/social-accounts" element={<SocialAccounts />} />
```

- [ ] **Step 3: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/SocialAccounts.tsx webui/src/App.tsx
git commit -m "feat(webui): add SocialAccounts page"
```

---

### Task 15: Frontend — página `Avatars`

**Files:**
- Create: `webui/src/pages/config/Avatars.tsx`
- Modify: `webui/src/App.tsx` — rota `/config/avatars`

**Interfaces:**
- Consumes: `Avatar`, `AvatarPayload`, `Client` (`types.ts`), `apiClient`, `RequireRole`.

- [ ] **Step 1: Criar a página**

```tsx
// webui/src/pages/config/Avatars.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Avatar, AvatarPayload, Client } from "../../lib/types";

export function Avatars() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [referenceImageUrl, setReferenceImageUrl] = useState("");

  const clients = useQuery({
    queryKey: ["config", "clients"],
    queryFn: () => apiClient.get<Client[]>("/content/ui/config/clients"),
  });

  const avatars = useQuery({
    queryKey: ["config", "avatars", clientId],
    queryFn: () => apiClient.get<Avatar[]>(`/content/ui/config/clients/${clientId}/avatars`),
    enabled: clientId !== null,
  });

  const create = useMutation({
    mutationFn: (payload: AvatarPayload) =>
      apiClient.post<Avatar>("/content/ui/config/avatars", payload),
    onSuccess: () => {
      setName("");
      setReferenceImageUrl("");
      queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Avatar>(`/content/ui/config/avatars/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "avatars", clientId] }),
  });

  return (
    <div>
      <h1>Avatars</h1>

      <select
        value={clientId ?? ""}
        onChange={(event) => setClientId(Number(event.target.value) || null)}
      >
        <option value="">Selecione um client</option>
        {clients.data?.map((client) => (
          <option key={client.id} value={client.id}>
            {client.name}
          </option>
        ))}
      </select>

      {avatars.isLoading && <p>Carregando...</p>}
      {avatars.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {avatars.data?.map((avatar) => (
          <li key={avatar.id}>
            {avatar.name} {!avatar.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!avatar.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(avatar.id)}
              >
                Desativar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (clientId === null) return;
            create.mutate({ client_id: clientId, name, reference_image_url: referenceImageUrl });
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nome do avatar"
            required
          />
          <input
            value={referenceImageUrl}
            onChange={(event) => setReferenceImageUrl(event.target.value)}
            placeholder="URL da imagem de referência"
            required
          />
          <button type="submit" disabled={create.isPending || clientId === null}>
            Criar
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
```

- [ ] **Step 2: Registrar a rota**

```tsx
import { Avatars } from "./pages/config/Avatars";
// ...
            <Route path="/config/avatars" element={<Avatars />} />
```

- [ ] **Step 3: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/Avatars.tsx webui/src/App.tsx
git commit -m "feat(webui): add Avatars page"
```

---

### Task 16: Frontend — página `ApprovalRules`

**Files:**
- Create: `webui/src/pages/config/ApprovalRules.tsx`
- Modify: `webui/src/App.tsx` — rota `/config/approval-rules`

**Interfaces:**
- Consumes: `ApprovalRule`, `ApprovalRulePayload`, `Campaign` (`types.ts`), `apiClient`, `RequireRole`.

- [ ] **Step 1: Criar a página**

```tsx
// webui/src/pages/config/ApprovalRules.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { ApprovalRule, Campaign } from "../../lib/types";

export function ApprovalRules() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [action, setAction] = useState<"auto_approve" | "require_review">("require_review");
  const [priority, setPriority] = useState(0);
  const [conditionJson, setConditionJson] = useState("{}");
  const [conditionError, setConditionError] = useState<string | null>(null);

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const rules = useQuery({
    queryKey: ["config", "approval-rules", campaignId],
    queryFn: () =>
      apiClient.get<ApprovalRule[]>(
        `/content/ui/config/campaigns/${campaignId}/approval-rules`
      ),
    enabled: campaignId !== null,
  });

  const create = useMutation({
    mutationFn: (condition: Record<string, unknown>) =>
      apiClient.post<ApprovalRule>("/content/ui/config/approval-rules", {
        campaign_id: campaignId,
        condition,
        action,
        priority,
      }),
    onSuccess: () => {
      setConditionJson("{}");
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/content/ui/config/approval-rules/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "approval-rules", campaignId] }),
  });

  return (
    <div>
      <h1>Approval Rules</h1>

      <select
        value={campaignId ?? ""}
        onChange={(event) => setCampaignId(Number(event.target.value) || null)}
      >
        <option value="">Selecione uma campanha</option>
        {campaigns.data?.map((campaign) => (
          <option key={campaign.id} value={campaign.id}>
            {campaign.name}
          </option>
        ))}
      </select>

      {rules.isLoading && <p>Carregando...</p>}
      {rules.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {rules.data?.map((rule) => (
          <li key={rule.id}>
            prioridade {rule.priority} — {rule.action} — {JSON.stringify(rule.condition)}
            <RequireRole role="admin" fallback={null}>
              <button disabled={remove.isPending} onClick={() => remove.mutate(rule.id)}>
                Excluir
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId === null) return;
            try {
              const condition = JSON.parse(conditionJson);
              setConditionError(null);
              create.mutate(condition);
            } catch {
              setConditionError("JSON inválido");
            }
          }}
        >
          <select
            value={action}
            onChange={(event) => setAction(event.target.value as "auto_approve" | "require_review")}
          >
            <option value="require_review">Requer revisão</option>
            <option value="auto_approve">Aprovação automática</option>
          </select>
          <input
            type="number"
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
          />
          <textarea
            value={conditionJson}
            onChange={(event) => setConditionJson(event.target.value)}
            placeholder='Condição em JSON, ex: {"content_category": "medical"}'
          />
          {conditionError && <p>{conditionError}</p>}
          <button type="submit" disabled={create.isPending || campaignId === null}>
            Criar regra
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
```

- [ ] **Step 2: Registrar a rota**

```tsx
import { ApprovalRules } from "./pages/config/ApprovalRules";
// ...
            <Route path="/config/approval-rules" element={<ApprovalRules />} />
```

- [ ] **Step 3: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/ApprovalRules.tsx webui/src/App.tsx
git commit -m "feat(webui): add ApprovalRules page"
```

---

### Task 17: Frontend — página `GenerationTemplates`

**Files:**
- Create: `webui/src/pages/config/GenerationTemplates.tsx`
- Modify: `webui/src/App.tsx` — rota `/config/templates`

**Interfaces:**
- Consumes: `GenerationTemplate`, `GenerationTemplatePayload`, `Campaign` (`types.ts`), `apiClient`, `RequireRole`.

- [ ] **Step 1: Criar a página**

```tsx
// webui/src/pages/config/GenerationTemplates.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Campaign, GenerationTemplate } from "../../lib/types";

export function GenerationTemplates() {
  const queryClient = useQueryClient();
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [type, setType] = useState<"video" | "image" | "audio">("image");
  const [generationPrompt, setGenerationPrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState("9:16");

  const campaigns = useQuery({
    queryKey: ["config", "campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/config/campaigns"),
  });

  const templates = useQuery({
    queryKey: ["config", "templates", campaignId],
    queryFn: () =>
      apiClient.get<GenerationTemplate[]>(`/content/ui/config/campaigns/${campaignId}/templates`),
    enabled: campaignId !== null,
  });

  const create = useMutation({
    mutationFn: () =>
      apiClient.post<GenerationTemplate>(
        `/content/ui/config/campaigns/${campaignId}/templates`,
        {
          campaign_id: campaignId,
          type,
          generation_prompt: generationPrompt,
          is_synthetic_media: false,
          aspect_ratio: aspectRatio,
        }
      ),
    onSuccess: () => {
      setGenerationPrompt("");
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] });
    },
  });

  const deactivate = useMutation({
    mutationFn: (id: number) =>
      apiClient.delete<GenerationTemplate>(`/content/ui/config/templates/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["config", "templates", campaignId] }),
  });

  return (
    <div>
      <h1>Generation Templates</h1>

      <select
        value={campaignId ?? ""}
        onChange={(event) => setCampaignId(Number(event.target.value) || null)}
      >
        <option value="">Selecione uma campanha</option>
        {campaigns.data?.map((campaign) => (
          <option key={campaign.id} value={campaign.id}>
            {campaign.name}
          </option>
        ))}
      </select>

      {templates.isLoading && <p>Carregando...</p>}
      {templates.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {templates.data?.map((template) => (
          <li key={template.id}>
            {template.type} — {template.generation_prompt ?? "(sem prompt)"}{" "}
            {!template.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!template.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(template.id)}
              >
                Desativar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (campaignId !== null) create.mutate();
          }}
        >
          <select value={type} onChange={(event) => setType(event.target.value as typeof type)}>
            <option value="image">Imagem</option>
            <option value="video">Vídeo</option>
            <option value="audio">Áudio</option>
          </select>
          <input
            value={generationPrompt}
            onChange={(event) => setGenerationPrompt(event.target.value)}
            placeholder="Prompt de geração"
          />
          <input
            value={aspectRatio}
            onChange={(event) => setAspectRatio(event.target.value)}
            placeholder="Aspect ratio (ex: 9:16)"
          />
          <button type="submit" disabled={create.isPending || campaignId === null}>
            Criar template
          </button>
        </form>
      </RequireRole>
    </div>
  );
}
```

- [ ] **Step 2: Registrar a rota**

```tsx
import { GenerationTemplates } from "./pages/config/GenerationTemplates";
// ...
            <Route path="/config/templates" element={<GenerationTemplates />} />
```

- [ ] **Step 3: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/GenerationTemplates.tsx webui/src/App.tsx
git commit -m "feat(webui): add GenerationTemplates page"
```

---

### Task 18: Frontend — página `Providers`

**Files:**
- Create: `webui/src/pages/config/Providers.tsx`
- Modify: `webui/src/App.tsx` — rota `/config/providers`

**Interfaces:**
- Consumes: `Provider`, `ProviderCreatePayload`, `ProviderUpdatePayload` (`types.ts`), `apiClient`, `RequireRole`.

- [ ] **Step 1: Criar a página**

```tsx
// webui/src/pages/config/Providers.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiError } from "../../lib/apiClient";
import { RequireRole } from "../../components/RequireRole";
import type { Provider, ProviderCreatePayload } from "../../lib/types";

export function Providers() {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<"image" | "video" | "voice">("image");
  const [providerName, setProviderName] = useState<
    "wavespeed" | "falai" | "gemini" | "elevenlabs"
  >("falai");
  const [credentials, setCredentials] = useState("");
  const [priority, setPriority] = useState(0);

  const providers = useQuery({
    queryKey: ["config", "providers"],
    queryFn: () => apiClient.get<Provider[]>("/content/ui/config/providers"),
  });

  const create = useMutation({
    mutationFn: (payload: ProviderCreatePayload) =>
      apiClient.post<Provider>("/content/ui/config/providers", payload),
    onSuccess: () => {
      setCredentials("");
      queryClient.invalidateQueries({ queryKey: ["config", "providers"] });
    },
  });

  const updatePriority = useMutation({
    mutationFn: ({ id, priority }: { id: number; priority: number }) =>
      apiClient.put<Provider>(`/content/ui/config/providers/${id}`, { priority }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "providers"] }),
  });

  const deactivate = useMutation({
    mutationFn: (id: number) => apiClient.delete<Provider>(`/content/ui/config/providers/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config", "providers"] }),
  });

  const invalidCredentials = create.error instanceof ApiError && create.error.status === 422;

  return (
    <div>
      <h1>Providers</h1>

      {providers.isLoading && <p>Carregando...</p>}
      {providers.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {providers.data?.map((provider) => (
          <li key={provider.id}>
            {provider.kind} — {provider.provider} — prioridade
            <input
              type="number"
              defaultValue={provider.priority}
              disabled={!provider.is_active}
              onBlur={(event) =>
                updatePriority.mutate({ id: provider.id, priority: Number(event.target.value) })
              }
            />
            {!provider.is_active && "(inativo)"}
            <RequireRole role="admin" fallback={null}>
              <button
                disabled={!provider.is_active || deactivate.isPending}
                onClick={() => deactivate.mutate(provider.id)}
              >
                Desativar
              </button>
            </RequireRole>
          </li>
        ))}
      </ul>

      <RequireRole role="admin">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ kind, provider: providerName, credentials, config: {}, priority });
          }}
        >
          <select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
            <option value="image">Imagem</option>
            <option value="video">Vídeo</option>
            <option value="voice">Voz</option>
          </select>
          <select
            value={providerName}
            onChange={(event) => setProviderName(event.target.value as typeof providerName)}
          >
            <option value="wavespeed">Wavespeed</option>
            <option value="falai">fal.ai</option>
            <option value="gemini">Gemini</option>
            <option value="elevenlabs">ElevenLabs</option>
          </select>
          <input
            type="password"
            value={credentials}
            onChange={(event) => setCredentials(event.target.value)}
            placeholder="API key"
            required
          />
          <input
            type="number"
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
          />
          <button type="submit" disabled={create.isPending}>
            Adicionar
          </button>
          {invalidCredentials && <p>Credencial inválida para este provider.</p>}
        </form>
      </RequireRole>
    </div>
  );
}
```

- [ ] **Step 2: Registrar a rota**

```tsx
import { Providers } from "./pages/config/Providers";
// ...
            <Route path="/config/providers" element={<Providers />} />
```

- [ ] **Step 3: Verificar que o projeto compila**

Run: `cd webui && npm run build`
Expected: build sem erros de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add webui/src/pages/config/Providers.tsx webui/src/App.tsx
git commit -m "feat(webui): add Providers page"
```

---

## Verificação final

- [ ] Rodar `python -m pytest test/services/ -v` na raiz do projeto — todos os testes de `content` (novos e pré-existentes) devem passar.
- [ ] Rodar `cd webui && npm run build` — build final sem erros de TypeScript.
- [ ] Validação manual via `/run`: com `role=admin`, percorrer as 7 telas de config (`/config/clients`, `/config/campaigns`, `/config/social-accounts`, `/config/avatars`, `/config/approval-rules`, `/config/templates`, `/config/providers`) criando, editando (onde há PUT na UI) e desativando/excluindo um registro em cada uma. Repetir navegando como `role=member`: confirmar que os formulários de escrita ficam ocultos (via `RequireRole`) e que uma tentativa de request direta (ex. via devtools) recebe `403` do backend. Confirmar visualmente que o CSS de `index.css` está aplicado (cores/tipografia de `:root` visíveis, não mais texto sem estilo).
- [ ] Confirmar que `GET /content/ui/campaigns` (rota antiga do 5a) não existe mais e que `PieceQueue` (fila de aprovação) continua funcionando normalmente via `GET /content/ui/config/campaigns`.
