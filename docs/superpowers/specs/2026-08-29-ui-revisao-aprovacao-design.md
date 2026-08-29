# Design — UI de revisão e aprovação (fase 5a)

> **Status:** Final / Aprovado para Implementação
> **Data:** 2026-08-29
> **Sub-projeto:** 5a de 5 (primeira fatia da fase "UI do módulo")

## Contexto e roadmap

Os sub-projetos 1-4 (fundação, motor de geração, motor de publicação, automação e aprovação)
entregaram uma API completa (`/v1/content/...`) mas **nenhum frontend existe** — a WebUI Streamlit
original do fork foi removida de propósito, e o projeto hoje é API-only. A fase 5 do roadmap ("UI
do módulo") cobre quatro áreas: revisão/aprovação, configuração, histórico e edição manual. Este
design cobre só a primeira fatia, decidida em brainstorming: **autenticação de usuário final + tela
de revisão/aprovação de content pieces**. Configuração, histórico dedicado e edição manual ficam
para specs seguintes (5b, 5c...).

Hoje a API só conhece dois tipos de credencial (`app/controllers/content_auth.py`):
`verify_admin_token` (provisionamento) e `verify_tenant_token` (um token por tenant, sem noção de
usuário individual — auditoria grava `actor=f"tenant:{tenant.id}"`, nunca "quem" dentro da agência
agiu). A fundação já havia deixado essa lacuna explicitamente para a fase 5. Este design a fecha
com um terceiro mecanismo, aditivo, usado só pelas rotas que esta UI consome.

## Decisões de brainstorming

- **Auth do usuário final**: sessão herdada do "app mãe" (produto de assinatura onde a agência
  compra o módulo) — não um sistema de login próprio (Supabase Auth) deste módulo. O app mãe ainda
  não existe; este design define o contrato de integração que qualquer app mãe futuro implementa.
- **Modo de embed**: iframe. O app mãe carrega esta UI num `<iframe>` e entrega a sessão via
  `postMessage` depois do load — não redirecionamento de página inteira.
- **Assinatura do token**: RS256 (par de chaves). O app mãe assina com a chave privada; este módulo
  só guarda a chave pública (env var) — não há segredo compartilhado entre os dois sistemas.
- **Papéis (RBAC)**: dois níveis vindos do claim `role` do JWT — `admin` e `member`. Nesta fatia,
  a única ação sensível a role é aprovar/rejeitar; a UI de configuração (fase 5b) é onde a
  distinção realmente importa.
- **Acesso a artefatos**: os buckets do Supabase Storage continuam públicos como hoje (nenhuma
  mudança em `storage.py`/pipeline de geração/publicação) — mas a UI nunca recebe a URL pública
  persistida em `content_assets.url`. O endpoint de detalhe da piece gera uma signed URL sob
  demanda, TTL curto, a partir do `storage_path` já persistido.
- **Stack frontend**: React + Vite + TypeScript, SPA standalone em `webui/`, sem framework de
  servidor (Next.js) — não há necessidade de SSR para um widget que vive dentro de um iframe.
- **Escopo desta fatia**: fila de pieces com abas de status + detalhe com preview de mídia,
  aprovar/rejeitar e status de publicação já ocorrida. Configuração de clients/contas
  sociais/avatares/regras/templates/provedores e uma tela de histórico dedicada ficam para depois.

## Contrato de integração (app mãe ↔ módulo)

1. App mãe carrega `<iframe src="https://.../webui/">`.
2. A SPA, ao montar, envia `window.parent.postMessage({type: "ready"}, appMotherOrigin)`.
3. App mãe responde `postMessage({type: "session", token: "<jwt>"}, iframeOrigin)`.
4. O JWT (RS256) carrega claims: `tenant_id` (int, obrigatório), `user_id` (string, obrigatório),
   `role` (`admin`|`member`, obrigatório), `name` (string, opcional, só para exibição/auditoria),
   `exp` (obrigatório, TTL curto — recomendado ≤ 1h; renovação é responsabilidade do app mãe
   reenviar um `postMessage` novo, este módulo não implementa refresh).
5. `webui/` guarda o token só em memória (nunca `localStorage`/`sessionStorage` — o iframe pode ser
   de origem cruzada e o token é efêmero). Todo `fetch` subsequente manda
   `Authorization: Bearer <jwt>`.
6. Origem do app mãe é validada nos dois lados via allowlist: a SPA só aceita `postMessage` cuja
   `event.origin` bate com uma env var de build (`VITE_PARENT_ORIGIN`); a `postMessage` de saída
   usa esse mesmo origin como alvo (nunca `"*"`).

## Backend — nova auth aditiva

`app/controllers/content_auth.py` ganha `verify_user_session`, no mesmo padrão de
`verify_tenant_token` (uma `Depends` que falha com `HTTPException`), mas decodificando o JWT em vez
de olhar o banco por hash:

```python
def verify_user_session(
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> UserSession:
    ...
```

- Header `Authorization: Bearer <jwt>`; `401` se ausente/malformado.
- Decodifica com `PyJWT` (`algorithms=["RS256"]`), chave pública de `CONTENT_UI_JWT_PUBLIC_KEY`
  (env, PEM). `401` genérico para qualquer falha de decodificação (assinatura inválida, expirado,
  claim obrigatório faltando) — não vaza qual validação falhou.
- Carrega o `ContentTenant` por `tenant_id`; mesma checagem de `entitlement_status != inactive` já
  usada em `verify_tenant_token` (`403` se inativo).
- Retorna um `UserSession` (dataclass simples: `tenant: ContentTenant`, `user_id: str`,
  `role: Literal["admin", "member"]`, `name: Optional[str]`).
- Nova dependência de app: `PyJWT` (adicionar a `requirements.txt`; `cryptography`, exigida pelo
  RS256 do PyJWT, já está presente).

`verify_tenant_token`/`verify_admin_token` permanecem exatamente como estão — nenhuma rota
existente muda de mecanismo de auth.

## Novas rotas — `app/controllers/v1/content/ui.py`

Prefixo `/v1/content/ui`, `dependencies=[Depends(content_auth.verify_user_session)]` no router
(mesmo padrão de `new_router(dependencies=[...])` usado pelos outros controllers de conteúdo).

- **`GET /ui/session`** → `{tenant_id, tenant_name, user_id, role, name}`. A SPA chama isso logo
  após receber o token, tanto para confirmar que a sessão é válida quanto para saber o que
  renderizar/habilitar.
- **`GET /ui/campaigns`** → lista campanhas do tenant (reusa `campaigns_service.list_campaigns`,
  já existente) — alimenta o filtro da fila.
- **`GET /ui/pieces?campaign_id=&status=`** → lista pieces. `status` é um dos valores de
  `ContentPieceStatus` (`pending_approval`, `approved`, `rejected`, `posted`, `failed`); omitido =
  todos. Requer estender `pieces_service.list_pieces` com um parâmetro `status` opcional (filtro
  `WHERE status = :status` quando presente) — sem mudar a assinatura para quem já chama sem esse
  parâmetro.
- **`GET /ui/pieces/{id}`** → detalhe: todos os campos de `ContentPieceRead` mais
  `assets: [{type, signed_url, mime_type, width, height, duration}]` (via `create_signed_url` sobre
  cada `content_assets.storage_path` da piece) e `publications:
  [{social_account_id, platform, status, posted_at, error}]` (reusa a leitura já existente de
  `content_social_publications` por piece, mesma fonte do endpoint
  `GET /content/pieces/{id}/publications` da fase 3).
- **`POST /ui/pieces/{id}/approve`** / **`POST /ui/pieces/{id}/reject`** → delegam a
  `pieces_service.approve_piece`/`reject_piece` (inalterados, guarda otimista já existente); `403`
  se `role != "admin"` — **checagem no backend, não só ocultação no frontend**. Em sucesso, grava em
  `content_audit_logs` com `actor=f"user:{session.user_id}"` (em vez de `tenant:{id}`) — corrige a
  lacuna de auditoria: agora dá pra saber qual pessoa aprovou/rejeitou, não só qual tenant. `409` no
  mesmo caso que os endpoints existentes (`status` não é mais `pending_approval` no momento da
  escrita).

Nenhuma rota existente (`/content/pieces/...` sob `verify_tenant_token`) é removida ou alterada —
as novas rotas `/ui/...` são um caminho paralelo para o mesmo dado, com auth e formato de resposta
pensados para este frontend.

## `storage.py` — signed URL sob demanda

Nova função, sem tocar em `upload_bytes` nem em nenhum consumidor existente do bucket:

```python
def create_signed_url(storage_path: str, *, expires_in: int = 600) -> str:
```

Chama o endpoint de sign da API REST do Supabase Storage
(`POST {base_url}/storage/v1/object/sign/{bucket}/{storage_path}`) com a mesma
`SUPABASE_SERVICE_ROLE_KEY` já usada por `upload_bytes`, retorna a URL assinada completa. Chamada
só pelo endpoint `GET /ui/pieces/{id}`, uma vez por asset por request (sem cache — TTL de 10 min já
é curto o suficiente para não valer a complexidade de cachear).

## Frontend — `webui/`

SPA React + Vite + TypeScript, buildada como estático (`webui/dist/`), servida separadamente do
backend Python (hospedagem a decidir na implementação — ex. um static host ou o próprio FastAPI
servindo os arquivos buildados; não é uma decisão de arquitetura, é operacional).

**Componentes principais:**

- `SessionProvider` — escuta `postMessage`, guarda o token em memória (`useState`, nunca storage
  persistente), chama `GET /ui/session`, expõe `{tenant, user, role}` via contexto e um helper
  `canApprove()` (`role === "admin"`). Enquanto nenhum token chegou: tela "aguardando sessão do
  app mãe" (não um erro — é o estado normal nos primeiros instantes).
- `PieceQueue` (`/`) — abas de status (`pending_approval` como aba inicial, `approved`, `rejected`,
  `posted`, `failed`), filtro por campanha, tabela com React Query (`useQuery` por
  `[campaign_id, status]`, refetch ao trocar de aba/filtro).
- `PieceDetail` (`/pieces/:id`) — preview de mídia por `content_type` (`<img>`/`<video>`/`<audio>`
  apontando pra `signed_url`), metadados (prompt, avatar, `content_category`, `risk_level`,
  `is_synthetic_media`), bloco de publicações (`platform: status`, com `posted_at`/`error` quando
  aplicável), botões Aprovar/Rejeitar — `disabled` com tooltip explicando o motivo quando
  `!canApprove()` ou quando o status atual não é `pending_approval`.
- `apiClient` — wrapper fino sobre `fetch`, injeta `Authorization`, trata `401` (mostra tela de
  sessão inválida, sem retry automático) e `409` (toast + refetch do detalhe) de forma uniforme.

## Fluxo de dados

1. Iframe monta → `postMessage({type: "ready"})` → app mãe responde com o token.
2. `SessionProvider` valida via `GET /ui/session`; `401` aqui vira tela de bloqueio permanente
   (sessão não se recupera sozinha nesta fase).
3. `PieceQueue` busca a aba `pending_approval` por padrão; trocar de aba/campanha refaz o fetch.
4. Abrir uma piece → `GET /ui/pieces/{id}` (assets já vêm com signed URL pronta pra uso direto).
5. Aprovar/rejeitar → `POST` correspondente → sucesso invalida as queries de lista e detalhe (React
   Query), a piece migra de aba na próxima renderização da lista.
6. Pieces já publicadas mostram o snapshot de `publications` no detalhe — sem polling; para ver uma
   atualização é preciso reabrir a piece (aceitável nesta fatia; tela de histórico com atualização
   ativa é 5c).

## Tratamento de erro

- **401** (token ausente/expirado/assinatura inválida): tela de bloqueio "sessão expirada, feche e
  reabra este painel" — sem refresh automático, sessão é responsabilidade do app mãe.
- **403** (role sem permissão OU tenant inativo): ação bloqueada tanto na UI (desabilitada) quanto
  no backend (nunca confiar só no frontend).
- **409** (guarda otimista — outra pessoa decidiu a piece primeiro): toast "esta piece já foi
  {approved|rejected} por outra pessoa", refetch automático do detalhe.
- **Rede/5xx**: banner de erro com retry manual; sem retry automático agressivo.
- **`postMessage` nunca chega** (app mãe não implementou o contrato, ou origin não bate no
  allowlist): tela de espera vira, depois de timeout configurável (ex. 15s), uma mensagem de erro
  explícita em vez de spinner infinito.

## Escopo P0 (Entregáveis)

- `verify_user_session` em `content_auth.py` + `UserSession` dataclass; `PyJWT` em
  `requirements.txt`.
- `app/controllers/v1/content/ui.py`: `GET /ui/session`, `GET /ui/campaigns`,
  `GET /ui/pieces`, `GET /ui/pieces/{id}`, `POST /ui/pieces/{id}/approve`,
  `POST /ui/pieces/{id}/reject`.
- `pieces_service.list_pieces` ganha parâmetro `status` opcional.
- `storage.create_signed_url`.
- Auditoria de approve/reject nas rotas `/ui/...` grava `actor=f"user:{user_id}"`.
- `webui/`: projeto Vite+React+TS, `SessionProvider`, `PieceQueue`, `PieceDetail`, `apiClient`.
- `config.example.toml` documentando `CONTENT_UI_JWT_PUBLIC_KEY` e `VITE_PARENT_ORIGIN`.
- Testes de backend: `verify_user_session` (válido/expirado/assinatura errada/claim faltando),
  `403` de approve/reject para `role=member`, geração de signed URL no endpoint de detalhe (mock do
  storage).
- Validação manual da SPA via `/run` cobrindo: sessão chegando por `postMessage`, filtro de status,
  aprovar/rejeitar, bloqueio de ação para `role=member`, preview de mídia via signed URL.

## Não-objetivos (ficam para specs futuras)

- Telas de configuração (clients, contas sociais, avatares, campanhas, regras de aprovação,
  templates de geração, provedores) — fase 5b.
- Tela de histórico dedicada com atualização ativa/polling de publicações — fase 5c.
- Edição manual de `ContentPiece` (regenerar, versionar) — não existe endpoint de backend para
  isso ainda; fora do escopo desta fatia e da fase 2 original.
- Refresh de token / renovação de sessão sem reload do iframe — o app mãe é responsável por
  reenviar `postMessage` antes do `exp`; este módulo não implementa refresh token nem
  keep-alive.
- Migrar os buckets do Supabase Storage para privados — a signed URL é gerada só para a resposta da
  UI; o restante do pipeline (geração, publicação) continua usando a URL pública existente sem
  nenhuma mudança.
- Qualquer mudança em `verify_tenant_token`/`verify_admin_token` ou nas rotas `/content/...`
  existentes — `verify_user_session` é estritamente aditivo.
