# Design — UI de Configuração (fase 5b)

> **Status:** Final / Aprovado para Implementação
> **Data:** 2026-08-29
> **Sub-projeto:** 5b de 5 (segunda fatia da fase "UI do módulo")

## Contexto e roadmap

Os sub-projetos 1-4 (fundação, motor de geração, motor de publicação, automação e
aprovação) e a fatia 5a (auth de usuário final + revisão/aprovação, `webui/`) já estão
mergeados em `main`. O 5a deixou explícito nos seus "não-objetivos"
(`docs/superpowers/specs/2026-08-29-ui-revisao-aprovacao-design.md:203-206`) que a UI de
configuração — clients, contas sociais, avatares, campanhas, regras de aprovação,
templates de geração, provedores — ficaria para uma fatia seguinte. Este design cobre
essa fatia.

Hoje o CRUD dessas 7 entidades só existe via `X-Tenant-Token` (rotas
`app/controllers/v1/content/{clients,social_accounts,campaigns,avatars,approval_rules,generation_templates,providers}.py`),
pensado pra integração servidor-a-servidor. A `webui/` só sabe autenticar via sessão de
usuário (JWT RS256, `verify_user_session`, ver 5a) — ela não tem, e não deveria ter, o
token de tenant. Além disso, quase nenhuma dessas rotas tem UPDATE ou DELETE: hoje não há
como editar uma regra de aprovação já criada, revogar uma conta social, ou atualizar a
prioridade de um provider sem recriá-lo. O objetivo desta fatia é fechar as duas lacunas
juntas: expor as 7 entidades por rotas UI-scoped (mesmo mecanismo de auth do 5a) e
completar o CRUD que falta nos services.

## Decisões de brainstorming

- **Escopo**: uma spec só cobrindo as 7 entidades, não fatiada em specs menores — o
  padrão de CRUD se repete entidade a entidade (mesmo esqueleto de rota UI-scoped +
  tela list/form), então tratar como uma spec grande e mecânica evita o overhead de
  coordenar 3+ specs sequenciais para o mesmo padrão.
- **Profundidade**: CRUD completo (create/edit/delete) em todas as 7 entidades — não só
  as que já doíam mais (ApprovalRule, Provider). Fecha lacunas reais identificadas na
  exploração: ApprovalRule sem editar/excluir, SocialAccount sem revogar, Provider sem
  atualizar, e nenhuma das 7 com uma tela de configuração de fato.
- **Semântica de delete por entidade**: decidida entidade a entidade, verificada contra
  os models reais (ver seção "Migrations e soft-delete" abaixo) — reaproveitar campos de
  estado já existentes onde possível, em vez de adicionar `is_active` indiscriminadamente.
- **RBAC de escrita**: leitura aberta a `admin` e `member`; escrita (`create`/`update`/
  `delete`) exige `role == "admin"`, checado no backend — mesmo princípio já usado em
  `POST /content/ui/pieces/{id}/approve` no 5a. É a primeira área do módulo onde a
  distinção de role importa numa tela inteira, não só num botão.
- **Consolidação de rota**: `GET /ui/campaigns` (criado no 5a, em `ui.py`, usado hoje só
  pelo filtro de `PieceQueue`) migra para `GET /ui/config/campaigns`, já que Campaign
  entra no CRUD completo desta fatia de qualquer forma — evita manter duas rotas de
  listagem de campanha em paralelo.

## Backend — autorização de escrita

Verificado contra o código: `content_auth.require_role(user_session, role)` já existe
(`app/controllers/content_auth.py:112`), já testado, e já é o padrão usado por
`POST /content/ui/pieces/{id}/approve` no 5a — não é necessário criar um novo helper.
Rotas de leitura dependem só de `Depends(verify_user_session)`; rotas de escrita chamam
`content_auth.require_role(user_session, "admin")` como primeira linha do corpo da rota,
levantando `403` se a sessão não for `admin`. Nenhuma mudança em
`verify_tenant_token`/`verify_admin_token`/`require_role` ou nas rotas `/content/...`
existentes — `ui_config.py` é estritamente aditivo, mesmo princípio do 5a.

## Novas rotas — `app/controllers/v1/content/ui_config.py`

Prefixo `/v1/content/ui/config`, roteador com
`dependencies=[Depends(content_auth.verify_user_session)]` (garante 401 uniforme antes de
qualquer checagem de role específica de rota). Todas as rotas reaproveitam os services
existentes em `app/services/content/*.py`, que ganham as funções de escrita que faltam
(`update_x`, `delete_x`/`deactivate_x`), repetindo o filtro por `tenant_id` já usado nas
funções de leitura (não há RLS no banco — isolamento é 100% na camada de aplicação).

**Client** (`app/models/content.py:75`)
- `GET /ui/config/clients` — lista do tenant.
- `GET /ui/config/clients/{id}`
- `POST /ui/config/clients` — admin.
- `PUT /ui/config/clients/{id}` — admin.
- `DELETE /ui/config/clients/{id}` — admin; soft-delete (`is_active=False`, coluna nova).

**Campaign** (`app/models/content.py:96`) — substitui `GET /ui/campaigns` do 5a
- `GET /ui/config/campaigns` (com filtro `client_id` opcional)
- `GET /ui/config/campaigns/{id}`
- `POST /ui/config/campaigns` — admin.
- `PUT /ui/config/campaigns/{id}` — admin.
- `DELETE /ui/config/campaigns/{id}` — admin; soft-delete via `status="archived"`
  (reaproveita a coluna `status: str` já existente, sem migration).

**SocialAccount** (`app/models/content.py:84`)
- `GET /ui/config/clients/{client_id}/social-accounts`
- `GET /ui/config/social-accounts/{id}` — novo (hoje não existe GET individual).
- `POST /ui/config/social-accounts` — admin; credencial recebida em texto puro no body,
  cifrada no backend antes de persistir (reaproveita `app/services/content/crypto.py`,
  mesmo padrão de `POST /content/social-accounts`).
- `PUT /ui/config/social-accounts/{id}` — admin.
- `DELETE /ui/config/social-accounts/{id}` — admin; soft-delete via `status="revoked"`
  (reaproveita a coluna `status: str` já existente, sem migration).

**Avatar** (`app/models/content_generation.py:65`)
- `GET /ui/config/clients/{client_id}/avatars`
- `GET /ui/config/avatars/{id}`
- `POST /ui/config/avatars` — admin.
- `PUT /ui/config/avatars/{id}` — admin.
- `DELETE /ui/config/avatars/{id}` — admin; soft-delete (`is_active=False`, coluna nova).

**ApprovalRule** (`app/models/content.py:160`)
- `GET /ui/config/campaigns/{campaign_id}/approval-rules`
- `GET /ui/config/approval-rules/{id}` — novo.
- `POST /ui/config/approval-rules` — admin.
- `PUT /ui/config/approval-rules/{id}` — admin (permite corrigir `condition`/`action`/
  `priority` sem precisar criar uma regra nova de prioridade maior, que era o único jeito
  hoje).
- `DELETE /ui/config/approval-rules/{id}` — admin; **hard-delete** (sem FK de outra
  tabela apontando pra ela, só lida em runtime por
  `automation_scheduler._decide_approval_action`).

**GenerationTemplate** (`app/models/content.py:173`)
- `GET /ui/config/campaigns/{campaign_id}/templates`
- `GET /ui/config/templates/{id}` — novo.
- `POST /ui/config/campaigns/{campaign_id}/templates` — admin.
- `PUT /ui/config/templates/{id}` — admin.
- `DELETE /ui/config/templates/{id}` — admin; soft-delete (`is_active=False`, coluna
  nova).

**Provider** (`app/models/content_generation.py:45`)
- `GET /ui/config/providers?kind=`
- `POST /ui/config/providers` — admin; credencial em texto puro no body, validada via
  `provider_adapters.validate_credentials` e cifrada antes de persistir (reaproveita a
  lógica já existente em `POST /content/providers`).
- `PUT /ui/config/providers/{id}` — admin; permite atualizar `priority`/`config` sem
  recriar (hoje só é possível recriar). Se `credentials` vier no body, revalida antes de
  substituir; se omitido, mantém a credencial atual.
- `DELETE /ui/config/providers/{id}` — admin; reaproveita o soft-delete já existente
  (`is_active=False`).

### Dados sensíveis — nunca expostos pela UI

Nenhuma resposta de leitura (`GET`) inclui `credentials_encrypted` nem a credencial em
texto puro — nem de `SocialAccount` nem de `Provider`. As respostas trazem só metadados
(`platform`/`provider`, `external_account_id`, `status`/`is_active`, `priority`,
`config`). Mesmo princípio de "nunca vazar o segredo persistido" já aplicado às signed
URLs de asset no 5a. Ao editar (`PUT`), o campo de credencial é sempre write-only — se
omitido, a credencial atual é preservada sem round-trip pelo frontend.

## Migrations e soft-delete — verificado contra os models reais

Verificação direta dos models (não assumida): `ContentSocialAccount.status: str` e
`ContentCampaign.status: str` já existem, default `"active"`, sem `Enum` no banco —
reaproveitáveis para soft-delete sem migration. `ContentGenerationProvider.is_active: bool`
já existe. `ContentClient`, `ContentAvatar` e `ContentGenerationTemplate` não têm nenhum
campo de estado hoje. `ContentApprovalRule` também não tem campo de estado, e não é
referenciada por FK de nenhuma outra tabela.

Uma única migration Alembic adiciona `is_active: bool` (default `True`, `NOT NULL`) a
`content_clients`, `content_avatars` e `content_generation_templates`. Nenhuma outra
migration é necessária — `status` em Campaign/SocialAccount e `is_active` em Provider já
existem; ApprovalRule não recebe flag nenhuma (hard-delete).

Toda query de leitura existente (`list_clients`, `list_avatars`, `list_templates` etc.)
passa a filtrar `is_active=True` por padrão, mesmo princípio já aplicado a
`list_providers` hoje (que já filtra por `is_active`).

## Frontend — `webui/`

**`lib/apiClient.ts`** ganha `put`, `patch` e `delete` (hoje só `get`/`post`), mesma
injeção de `Authorization` e mesmo formato de erro (`ApiError` com `.status`) já usados.

**`components/RequireRole.tsx`** — novo, primeiro guard de rota por role do projeto (RBAC
hoje só existe como `useSession().canApprove()` checado dentro de um componente, nunca na
definição de rota). Envolve as rotas de escrita de configuração; para `role !== "admin"`
renderiza uma mensagem de acesso restrito em vez do formulário. Rotas de leitura da
configuração continuam acessíveis a `member` (útil pra quem só aprova poder ver o
contexto de campanha/regras sem poder editar).

**`pages/config/`** — uma página por entidade: `Clients.tsx`, `Campaigns.tsx`,
`SocialAccounts.tsx`, `Avatars.tsx`, `ApprovalRules.tsx`, `GenerationTemplates.tsx`,
`Providers.tsx`. Cada uma segue o padrão já estabelecido em `PieceQueue.tsx`/
`PieceDetail.tsx`: `useQuery` para a lista (keyed pelos filtros relevantes, ex.
`client_id` para campanhas), formulário de create/edit com `useMutation` +
`queryClient.invalidateQueries` no `onSuccess`, e o mesmo tratamento uniforme de
`ApiError`/`401`/`403`/`409` já usado em `PieceDetail.tsx`.

**Navegação** — nav simples (tabs ou sidebar) entre a fila de pieces (`/`) e as 7 telas de
configuração; hoje `App.tsx` só tem duas rotas e nenhum nav.

**Correção de CSS herdada do 5a** — pré-requisito desta fatia, não trabalho novo: o
projeto usa CSS puro (custom properties em `index.css`, **sem Tailwind e sem lib de UI**);
`App.css` está vazio e `index.css` nunca é importado em `main.tsx`/`App.tsx` (zero
ocorrências confirmadas via grep). Basta adicionar `import "./index.css"`. Telas de
formulário/tabela de configuração são o primeiro lugar onde isso importa de verdade — sem
essa correção, as novas telas também rodam sem nenhum estilo aplicado.

## Fluxo de dados (exemplo — ApprovalRule)

1. Admin abre `/config/approval-rules?campaign_id=X` → `GET /ui/config/campaigns/{X}/approval-rules`.
2. Cria uma regra → `POST /ui/config/approval-rules` → sucesso invalida a query de lista.
3. Edita prioridade de uma regra existente → `PUT /ui/config/approval-rules/{id}` →
   invalida lista e detalhe.
4. Exclui uma regra obsoleta → `DELETE /ui/config/approval-rules/{id}` (hard-delete) →
   invalida lista; a próxima execução do `automation_scheduler` já não a considera.

## Tratamento de erro

Mesmo modelo já estabelecido no 5a:
- **401**: token ausente/expirado/inválido → tela de bloqueio, sem retry automático.
- **403**: role sem permissão (rota de escrita para `member`) ou tenant inativo → ação
  bloqueada na UI (via `RequireRole`) **e** no backend (`require_admin` nunca confia só
  no frontend).
- **404**: entidade não encontrada ou pertence a outro tenant (services filtram por
  `tenant_id`; um id de outro tenant deve responder 404, nunca 200 com dado alheio nem
  403 — não revelar que o id existe em outro tenant).
- **409**: onde aplicável (ex. dois admins editando a mesma regra ao mesmo tempo — sem
  guarda otimista nova além da já existente em pieces; se o backend não implementar
  optimistic locking pra config, esse caso fica como "último a salvar vence", já que
  não há requisito de concorrência forte nesta fatia).
- **Rede/5xx**: banner de erro com retry manual.

## Escopo P0 (Entregáveis)

- `app/controllers/v1/content/ui_config.py` com todas as rotas listadas acima, usando
  `content_auth.require_role` (já existe) nas rotas de escrita
  (substitui `GET /ui/campaigns` de `ui.py`).
- Services (`clients`, `campaigns`, `social_accounts`, `avatars`, `approval_rules`,
  `generation_templates`, providers) ganham `update_x`/`delete_x`/`deactivate_x` onde
  faltam, todos filtrando por `tenant_id`.
- Migration Alembic: `is_active` em `content_clients`, `content_avatars`,
  `content_generation_templates`.
- `webui/src/lib/apiClient.ts`: `put`/`patch`/`delete`.
- `webui/src/components/RequireRole.tsx`.
- `webui/src/pages/config/*.tsx` (7 arquivos) + nav.
- `webui/src/pages/PieceQueue.tsx` ajustado para `GET /ui/config/campaigns`.
- Import de `index.css` corrigido.
- Testes de backend: 403 para `role=member` nas rotas de escrita, CRUD completo por entidade,
  isolamento por `tenant_id` (404 ao acessar entidade de outro tenant), nunca expor
  `credentials_encrypted`/credencial em texto puro nas respostas de leitura.
- Validação manual da SPA via `/run`: as 7 telas como `admin` (CRUD completo) e como
  `member` (leitura ok, escrita bloqueada na UI e confirmada bloqueada via rede/console),
  confirmar CSS aplicado.

## Não-objetivos (ficam para specs futuras)

- Customização de catálogo de modelos por tenant (`app/services/content/models_catalog.yaml`
  continua global) — mudar isso é decisão de produto separada, não parte desta fatia.
- Testes automatizados de frontend — não existe convenção no projeto ainda (nenhum
  `*.test.*` hoje); pode ser proposto como seguimento, não bloqueia esta fatia.
- Refresh/renovação de token JWT sem reload do iframe — não-objetivo já herdado do 5a.
- Optimistic locking novo para as entidades de configuração além do que já existe em
  pieces.
- Sub-projeto 5c (histórico dedicado + edição manual de `ContentPiece`).
