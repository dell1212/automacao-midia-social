# Design — UI de Histórico e Edição Manual (fase 5c)

> **Status:** Final / Aprovado para Implementação
> **Data:** 2026-08-30
> **Sub-projeto:** 5c de 5 (terceira e última fatia da fase "UI do módulo")

## Contexto e roadmap

Os sub-projetos 1-4 e as fatias 5a (auth + revisão/aprovação) e 5b (configuração das 7
entidades) já estão mergeados em `main`. O 5b deixou claro no roadmap que restava só o
5c: "histórico dedicado + edição manual", com a nota de que a edição manual "também
depende de endpoint de backend que ainda não existe". Confirmado direto no código:
`pieces_service.py` só tem `create_piece`/`approve_piece`/`reject_piece` — não há
nenhum `update_piece`, e nenhuma rota de leitura do `ContentAuditLog` existe hoje (a
tabela só é escrita, nunca lida pela UI).

Toda escrita do 5b (as 7 entidades de configuração) e o approve/reject do 5a já
gravam em `ContentAuditLog` (`app/services/content/audit.py`) — a base de dados do
histórico já existe, só falta expor. Este design cobre as duas lacunas: uma leitura
genérica desse log (feed geral + aba por peça) e a capacidade de um admin corrigir
manualmente uma peça (metadados e/ou asset) já gerada.

## Decisões de brainstorming

- **Escopo do histórico**: os dois — feed geral do tenant (nova tela) e aba de
  histórico dentro do `PieceDetail`, ambos reaproveitando o mesmo endpoint de leitura
  filtrado por `entity_type`/`entity_id`.
- **Escopo da edição**: metadados (`generation_prompt`, `avatar_id`, `voice_id`,
  `content_category`, `risk_level`, `scheduled_for`) **e** reenvio de asset (upload de
  um arquivo substituto pro asset principal da peça, sem re-rodar o pipeline de
  geração).
- **Regra de status**: edição é permitida em qualquer status exceto `posted` (que
  rejeita com 409 — não faz sentido corrigir algo já publicado por esta via). Editar
  uma peça `approved` ou `rejected` a devolve para `pending_approval` e limpa
  `approved_at`, forçando reaprovação — a correção manual não pode ficar "aprovada"
  silenciosamente. Peças em `draft`/`generating`/`pending_approval`/`failed`
  permanecem no mesmo status após a edição.
- **Detalhe do log**: `ContentAuditLog` ganha uma coluna `details` (JSON, nullable)
  pra guardar o before/after dos campos alterados em cada edição — sem isso, uma
  entrada "edited" não diz o que mudou, e o histórico vira decoração em vez de
  auditoria de verdade. Chamada de `details`, não `metadata` — `metadata` é um nome
  reservado pela API Declarative do SQLAlchemy/SQLModel (colide com o atributo de
  classe que guarda o `MetaData` do schema) e quebraria a definição do model.
- **Rastreio explícito da perda de aprovação**: quando a edição reverte o status de
  `approved`/`rejected` para `pending_approval`, essa reversão entra no `details` do
  mesmo evento (`"status": {"before": "approved", "after": "pending_approval"}`),
  junto dos demais campos alterados — nunca fica implícita só no banco. Isso é
  crítico porque a perda da assinatura de aprovação é o tipo de coisa que uma
  auditoria precisa conseguir responder sem ambiguidade.

## Backend — dado novo

Migration Alembic aditiva única: coluna `details: Optional[dict]` (JSON, nullable,
sem default) em `content_audit_logs`. `audit.write_audit_log()` ganha parâmetro
opcional `details: Optional[dict] = None`; os 19 call-sites existentes (5a/5b) não
mudam — continuam gravando `details=NULL`, exatamente como hoje.

```python
def write_audit_log(
    session, *, tenant_id, entity_type, entity_id, action, actor,
    details: Optional[dict] = None,
) -> ContentAuditLog: ...
```

## Backend — novas rotas (`app/controllers/v1/content/ui.py`)

Mesmo roteador do 5a (`dependencies=[Depends(verify_user_session)]`).

**`GET /content/ui/audit-log`** — leitura, qualquer sessão autenticada (mesmo
princípio de leitura aberta do 5b: `member` também pode ver histórico, só não
editar). Sempre filtrado por `tenant_id` da sessão.
- Query params: `entity_type: Optional[str]`, `entity_id: Optional[int]`,
  `limit: int = 50`, `offset: int = 0`.
- Alimenta os dois consumidores: a aba de histórico da peça passa
  `entity_type=content_piece&entity_id={id}`; o feed geral não passa filtro de
  entidade (só paginação, opcionalmente `entity_type` sozinho pra filtrar por tipo).
- Resposta ordenada por `created_at desc`. DTO novo `AuditLogEntryRead` (`entity_type`,
  `entity_id`, `action`, `actor`, `details: Optional[dict]`, `created_at`).

**`PATCH /content/ui/pieces/{id}`** — só admin (`require_role(user_session, "admin")`).
- Corpo `PieceUpdate`: todos os campos `Optional`, mesma convenção já usada em
  `GenerationTemplateUpdate`/`update_template` — campo `None` significa "não
  alterar" (não há como limpar `avatar_id`/`voice_id`/`scheduled_for` via este
  endpoint; é a mesma limitação já aceita no resto do módulo, não uma lacuna nova).
- `avatar_id`, se fornecido, é validado contra o tenant do jeito que o fix do 5b já
  fez em `create_template`/`update_template` (`avatars_service.get_avatar`, 422 se
  não pertencer ao tenant).
- Rejeita com 409 se `piece.status == posted`.
- Calcula o diff campo-a-campo (só os campos efetivamente diferentes do valor atual
  entram no log) e monta a atualização atômica via UPDATE condicionado
  (`WHERE id = :id AND status != 'posted'`), mesmo padrão de escrita-guardada já
  usado em `_conditional_transition` (`app/services/content/pieces.py:140`) — a
  transição de status (`approved`/`rejected` → `pending_approval`, limpando
  `approved_at`) é computada dentro do mesmo UPDATE condicional para evitar uma
  janela de corrida entre leitura e escrita.
- Grava audit log `action="edited"`, `details={"before": {...}, "after": {...}}`
  incluindo a entrada `"status"` quando houver reversão (ver decisão acima).

**`POST /content/ui/pieces/{id}/asset`** (multipart, `file` + `type`) — só admin.
- `type` deve bater com `piece.type` (rejeita 422 caso contrário — não faz sentido
  substituir o vídeo de uma peça de imagem).
- Rejeita com 409 se `piece.status == posted`.
- Sobe o arquivo via `storage.upload_bytes` (mesmo bucket/padrão de path já usado
  pelo pipeline).
- Marca o(s) `ContentAsset` atual(is) não-intermediário(s) do mesmo tipo como
  `is_intermediate=True` — preserva o asset antigo no banco (histórico real,
  recuperável) e some da UI porque `get_piece_detail` já filtra
  `if not asset.is_intermediate` (`app/services/content/ui_pieces.py:30`).
- Cria o `ContentAsset` novo. `assets_service.create_asset` hoje exige um
  `ContentGenerationJob` (usa `job.tenant_id`/`job.client_id`/`job.id`); ganha uma
  variante `create_manual_asset(session, *, tenant_id, client_id, content_piece_id,
  asset_type, uploaded, mime_type=None, ...)` que não depende de job
  (`generation_job_id=None` no asset resultante — já é nullable no model).
- Mesma regra de status/reversão do PATCH acima, e mesmo formato de `details` no
  audit log (`action="asset_replaced"`, `before`/`after` com o `storage_path` antigo
  e o novo, mais a entrada `"status"` quando houver reversão).

## Frontend — `webui/`

**`PieceDetail.tsx`**
- Formulário de edição de metadados (admin-only via `canApprove()`, sem exigir
  `status === "pending_approval"` — só bloqueia se `status === "posted"`), `useMutation`
  chamando `PATCH /content/ui/pieces/{id}`, invalidando `["piece", id]` no sucesso.
- Input de arquivo pra substituir o asset (mesmo gate de admin), `useMutation` com
  `FormData` para `POST /content/ui/pieces/{id}/asset`.
- Seção "Histórico" nova: `useQuery` em
  `GET /content/ui/audit-log?entity_type=content_piece&entity_id={id}`, renderizando
  `action`, `actor`, `created_at` e, se houver, o diff de `details.before`/`after`
  campo a campo.

**`pages/History.tsx`** (nova) — feed geral: `useQuery` em `GET /content/ui/audit-log`
paginado (`limit`/`offset`), filtro por `entity_type` (select simples: peça, cliente,
campanha, avatar, etc.), mesma tabela de listagem já usada nas telas de `config/`.
Entra na nav (`ConfigNav.tsx`) e em `App.tsx` como `/history`.

**Null-safety do `details`** — como o banco já tem histórico de eventos anteriores
ao 5c (approve/reject do 5a, todo o CRUD do 5b) gravados com `details=NULL`, tanto
`PieceDetail.tsx` quanto `History.tsx` **precisam** tratar `entry.details == null`
sem quebrar: renderizar a linha só com `action`/`actor`/`created_at` (sem seção de
diff) quando `details` for `null`, nunca acessar `details.before`/`details.after`
sem checar a presença antes. No `types.ts`, `AuditLogEntry.details` é tipado como
`Record<string, { before: unknown; after: unknown }> | null`.

## Fluxo de dados (exemplo — edição revertendo aprovação)

1. Peça `#42` está `approved`. Admin abre `/pieces/42`, edita `content_category` no
   formulário.
2. `PATCH /content/ui/pieces/42` com `{"content_category": "financial"}`.
3. Backend calcula diff (`content_category` mudou; `status` também muda como efeito
   colateral da edição em peça `approved`), aplica tudo num único UPDATE condicional,
   grava audit log:
   ```json
   {
     "action": "edited",
     "details": {
       "content_category": {"before": "insurance", "after": "financial"},
       "status": {"before": "approved", "after": "pending_approval"}
     }
   }
   ```
4. Frontend invalida `["piece", 42]` e `["pieces"]` — peça reaparece na fila de
   revisão como `pending_approval`.
5. Aba de histórico da peça e o feed geral (`/history`) mostram a mesma entrada.

## Tratamento de erro

Mesmo modelo já estabelecido no 5a/5b:
- **401**: sessão ausente/expirada → tela de bloqueio.
- **403**: `role != admin` tentando `PATCH`/`POST asset` (bloqueado na UI e
  novamente no backend via `require_role`); leitura do audit log nunca dá 403 pra
  `member`.
- **404**: peça de outro tenant (mesmo filtro por `tenant_id` já usado em todo o
  módulo).
- **409**: `status == posted` em `PATCH`/`POST asset`.
- **422**: `avatar_id` cross-tenant no `PATCH`; `type` do asset não bate com
  `piece.type` no upload.
- **Rede/5xx**: banner de erro com retry manual, mesmo padrão das telas de config.

## Escopo P0 (Entregáveis)

- Migration Alembic: coluna `details` (JSON, nullable) em `content_audit_logs`.
- `audit.write_audit_log()` com parâmetro `details` opcional.
- `GET /content/ui/audit-log` em `ui.py` + DTO `AuditLogEntryRead`.
- `PATCH /content/ui/pieces/{id}` + `pieces_service.update_piece` (UPDATE condicional
  com transição de status embutida) + validação cross-tenant de `avatar_id`.
- `POST /content/ui/pieces/{id}/asset` + `assets_service.create_manual_asset`.
- `webui/src/pages/History.tsx` + rota `/history` + entrada na nav.
- `PieceDetail.tsx`: formulário de edição, upload de asset, seção de histórico —
  todos com tratamento explícito de `details === null`.
- `webui/src/lib/types.ts`: `AuditLogEntry`, `PieceUpdate`.
- Testes de backend (HTTP-layer, mesmo padrão de `test_content_ui_config.py`): 403
  para `member` em `PATCH`/`POST asset`, 409 em peça `posted`, 422 de `avatar_id`
  cross-tenant, reversão de status `approved`/`rejected` → `pending_approval` com o
  `details["status"]` correspondente no audit log, filtro de `audit-log` por
  `entity_type`/`entity_id` e por `tenant_id` — sugerido depois do código pronto,
  perguntando antes de escrever.
- Validação manual da SPA via `/run`: editar peça em cada status não-`posted`,
  confirmar reversão de `approved`→`pending_approval`, substituir asset, conferir
  aba de histórico da peça e feed geral, confirmar que `member` não vê os controles
  de edição mas vê o histórico.

## Não-objetivos

- Editar `type`/`campaign_id`/`source_image_piece_id` da peça (mudariam a identidade
  estrutural da peça, não são "correção manual").
- Re-rodar o pipeline de geração a partir da edição (o reenvio de asset é sempre um
  upload manual, nunca dispara `orchestrator`/`pipeline`).
- Limpar (`null`) `avatar_id`/`voice_id`/`scheduled_for` via `PATCH` — mesma
  limitação já aceita em `GenerationTemplateUpdate` no resto do módulo.
- Optimistic locking além do UPDATE condicional descrito (nenhum ETag/version novo).
- Exportação do histórico (CSV/PDF) — fica pra uma spec futura se vier a ser pedido.
