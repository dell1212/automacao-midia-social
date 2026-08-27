# Design — Fundação do Módulo de Automação de Conteúdo

> **Status:** Draft para revisão
> **Data:** 2026-08-27
> **Sub-projeto:** 1 de 5 (ver Contexto e roadmap)

## Contexto e roadmap

O MoneyPrinterTurbo (gerador de vídeo curto via IA: roteiro → material → legenda → trilha) vai
virar a base de um módulo de automação de conteúdo (ideia → vídeo/imagem/áudio → postagem),
vendido como add-on de um app maior de assinatura para agências e empresas. Esse app maior tem
outro módulo, de agendamento/controle de cliente, contratável separadamente — este módulo de
conteúdo é irmão dele, não depende dele.

O projeto completo foi decomposto em 5 sub-projetos, cada um com sua própria spec e plano de
implementação:

1. **Fundação** (este documento) — modelo de dados, persistência, autenticação, esqueleto de API.
2. Motor de geração estendido — adiciona geração de imagens ao pipeline existente, padroniza saída
   como `ContentPiece`.
3. Motor de publicação — integrações com APIs de redes sociais para postar automaticamente.
4. Automação e aprovação — calendário de N dias de conteúdo futuro, regras de trigger que decidem
   auto-postar vs. exigir aprovação humana.
5. UI do módulo — telas de revisão/aprovação, configuração, histórico, edição manual.

Sub-projetos 2–5 ficam fora de escopo aqui; suas interfaces com a Fundação são descritas em
"Não-objetivos" abaixo.

## Objetivo desta fase

Dar ao módulo de conteúdo uma base de dados e uma superfície de API mínima e coerente com o
restante do produto (arquitetura headless, API-only — o app mãe cuida do frontend final).

## Arquitetura

- Módulo headless dentro do MoneyPrinterTurbo, seguindo o padrão FastAPI já existente
  (`app/controllers/v1/`, `app/services/`, roteador agregado em `app/router.py`).
- Comunicação com o app mãe via REST/HTTP — desacopla stack e permite escalar/hospedar
  separadamente. Fila de mensagens fica em aberto para o pipeline interno assíncrono (a geração já
  roda como task hoje via `app/services/state.py`), não é contrato de integração externo nesta
  fase.
- Persistência: **Supabase** (Postgres gerenciado), acessado via **SQLModel/SQLAlchemy com a
  connection string Postgres padrão** — não o SDK proprietário do Supabase. Isso mantém migração
  futura para Postgres self-hosted trivial (`pg_dump`/`pg_restore`), já que RLS é feature nativa do
  Postgres e não do Supabase. `DATABASE_URL` entra via variável de ambiente (segredo, não vai para
  `config.toml`).
- Migrations via Alembic.
- Storage: Supabase Storage para os artefatos gerados (vídeo/imagem) que a UI de revisão (fase 5)
  vai precisar exibir — substitui o atual `StaticFiles` em `/tasks`, que não tem isolamento
  multi-tenant.

## Multi-tenancy

Hierarquia: **Tenant (agência)** → **Client (cliente final da agência)** → **Campaign**. O
isolamento é reforçado por Row Level Security no Postgres, não só em código de aplicação.

Convenções de nomenclatura alinhadas ao módulo irmão de agendamento (Protocol Pal Scheduling),
para reduzir atrito numa eventual interoperação futura:
- Tabelas prefixadas por módulo: `content_*`.
- Toda tabela tenant-scoped tem `tenant_id` (FK) com índice dedicado `<tabela>_tenant_idx`.
- `entitlement_status` enum (`active` / `inactive` / `trial`) no tenant, para gating de acesso.
- `owner_user_id` no tenant (referência ao usuário responsável no app mãe).
- `idempotency_key` em ações críticas (criação de `ContentPiece`, postagem) — evita duplicação por
  retry.

## Autenticação

Token por tenant (hash armazenado no banco), estendendo o padrão já existente de
`Depends(verify_token)` em `app/controllers/base.py`: em vez de comparar contra uma API key global
fixa, o token do request é resolvido para um `Tenant` (ou rejeitado). O restante do pipeline de
request continua igual (mesma dependency injection do FastAPI).

Autenticação de usuário final (login humano na UI de revisão, fase 5) é decisão adiada para aquela
spec — pode usar Supabase Auth ou herdar sessão do app mãe; não afeta o modelo de dados desta fase.

## Modelo de dados (v1 — campos indicativos, refinados no plano de implementação)

```
content_tenants
  id, owner_user_id, name, slug, api_token_hash, entitlement_status, created_at

content_clients
  id, tenant_id, name, created_at

content_social_accounts
  id, client_id, platform, external_account_id, credentials (criptografado), status, created_at

content_campaigns
  id, client_id, name, horizon_days, status, created_at

content_pieces
  id, campaign_id, type (video|image|audio), status
    (draft|pending_approval|approved|rejected|posted|failed),
  asset_url, scheduled_for, posted_at, idempotency_key, created_at, updated_at

content_approval_rules
  id, campaign_id, condition (jsonb), action (auto_approve|require_review), priority, created_at

content_audit_logs
  id, tenant_id, entity_type, entity_id, action, actor, created_at
```

## Escopo desta fase

- Schema completo acima + migrations Alembic.
- Conexão com o banco (Supabase/Postgres) e sessão SQLModel.
- Autenticação por tenant (`verify_tenant_token`, substituindo `verify_token` para as rotas deste
  módulo).
- CRUD básico (create/list/get/update) para `Tenant`, `Client`, `SocialAccount`, `Campaign`,
  `ApprovalRule`.
- `ContentPiece`: apenas leitura/listagem — criação real é da fase 2 (Motor de geração).
- Escrita em `content_audit_logs` a cada mutação (infraestrutura básica de auditoria).

## Não-objetivos (ficam para specs futuras)

- Geração de imagens ou qualquer lógica de pipeline de geração (fase 2).
- Integrações reais com APIs de redes sociais / postagem (fase 3).
- Motor de regras rodando em runtime (avaliar `ApprovalRule` contra um `ContentPiece` e decidir
  ação) e o calendário de N dias efetivamente populado (fase 4) — nesta fase as tabelas existem,
  mas não há lógica de automação sobre elas.
- Qualquer UI, incluindo tela de login (fase 5).

## Estrutura de código

```
app/models/content.py          # entidades SQLModel + DTOs Pydantic
app/services/content/          # funções de acesso a dados por entidade
app/controllers/v1/content/    # routers por recurso (tenants.py, clients.py, ...)
app/db.py                      # engine/sessão SQLModel, leitura de DATABASE_URL
alembic/                       # migrations
```

Registrado em `app/router.py` junto aos routers existentes (`ping`, `video`, `llm`).

## Erros

Reaproveita o padrão existente de `HttpException` (`app/models/exception.py`) e os exception
handlers já registrados em `app/asgi.py`. Casos novos: token inválido/tenant não encontrado (401),
violação de isolamento entre tenants (403), FK inválida (404/422).

## Testes

Sem suíte de testes obrigatória nesta fase (convenção do projeto: não escrever testes por padrão).
Ao final da implementação, avaliar se alguma função de resolução de tenant/token é crítica o
suficiente para justificar um teste pontual.
