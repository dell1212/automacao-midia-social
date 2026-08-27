# Design — Motor de geração estendido (+ imagens)

> **Status:** Draft para revisão
> **Data:** 2026-08-27
> **Sub-projeto:** 2 de 5 (ver [Fundação do Módulo de Conteúdo](2026-08-27-fundacao-modulo-conteudo-design.md))

## Contexto e roadmap

A Fundação (sub-projeto 1) entregou o modelo de dados, autenticação por tenant e CRUD básico do
módulo de conteúdo, com `ContentPiece` disponível apenas para leitura — a criação real ficou
adiada pra esta fase. Hoje o pipeline de geração do projeto (`app/services/material.py`,
`app/services/video.py`) só sabe buscar vídeo de estoque (Pexels/Pixabay/Coverr) ou gerar vídeo por
IA via WaveSpeed, com credenciais globais em `config.toml`. Não existe geração de imagem.

Esta fase:
1. Adiciona geração de imagem, vídeo (text-to-video **e** image-to-video) e voz por IA ao pipeline.
2. Migra as credenciais desses provedores de config global para **configuração por tenant**, com
   múltiplos provedores e fallback por capability + prioridade.
3. Introduz o conceito de **avatar** — uma identidade visual/vocal reutilizável (ex: um
   influenciador real ou fictício) associada a um client.
4. Trata a geração como uma **execução técnica rastreável** (`GenerationJob`), separada da entidade
   de conteúdo (`ContentPiece`), com registro de assets, retry/fallback por capability e telemetria
   de custo — infraestrutura pensada pra durar conforme novos providers/modelos entrarem.
5. Fecha o ciclo de criação de `ContentPiece`, produzindo `image`, `audio` ou `video` de fato, já
   carimbando a classificação de conteúdo regulado (categoria, risco) que a revisão/publicação
   futura vai precisar.

## Objetivo desta fase

Dar ao módulo de conteúdo a capacidade de gerar peças de conteúdo (imagem, áudio, vídeo) por IA,
com infraestrutura de execução observável (jobs, assets, custo), seleção de modelo por capability
(não só por prioridade cega) e provedores plugáveis/configuráveis por tenant, incluindo suporte a
avatares com voz clonada.

## Princípios arquiteturais

- **Content ≠ Execution** — `ContentPiece` é a entidade de conteúdo; `GenerationJob` é a execução
  técnica que a produz. Uma piece pode ter vários jobs (ex: vídeo = job de imagem + job de voz + job
  de vídeo).
- **Provider ≠ Model** — um provider (WaveSpeed, fal.ai, Gemini) tem vários modelos, cada um com
  capacidades diferentes. Capacidade é propriedade do modelo, não do provider.
- **Priority ≠ Capability** — um provider/modelo só entra na disputa de prioridade se atender os
  requisitos técnicos do pedido (resolução, duração, modo image-to-x, etc). Prioridade desempata
  entre compatíveis, nunca substitui compatibilidade.
- **Generation → Asset (1:N)** — uma execução pode gerar mais de um artefato (ex: thumbnail junto
  com o vídeo); nada assume 1 job = 1 arquivo.
- **Nem todo erro merece retry** — falha é classificada antes de decidir se tenta de novo.
- **Classification ≠ enforcement** — classificar conteúdo regulado (categoria, risco) e agir sobre
  essa classificação são coisas separadas. Esta fase classifica e persiste; nada bloqueia.
- **Tudo é rastreável** — toda geração é auditável por tenant, client, campaign, piece, job,
  provider, model, tentativa, asset e custo.

## Arquitetura

### Catálogo de modelos (global)

`generation_models` é um catálogo **da plataforma**, não do tenant — a capacidade de um modelo
(ex: "wavespeed/seedream-v3 suporta image-to-video em 1080p, até 8s") é verdade pra qualquer tenant
que o use, então não faz sentido duplicar por tenant. Populado/mantido pelo time (seed via migration
+ manutenção manual nesta fase; um painel de administração fica pra depois, não é objetivo aqui):

```
generation_models
  id, provider, kind (image|video|voice), model_id, name, is_active,
  supports_text_to_image, supports_image_to_image,
  supports_text_to_video, supports_image_to_video,
  supports_reference_image, supports_avatar,
  supported_ratios (jsonb), supported_resolutions (jsonb), max_duration,
  cost_config (jsonb),
  created_at, updated_at
```

### Provedores por tenant

`content_generation_providers` fica mais enxuta do que na primeira versão desta spec — carrega só o
que é específico do tenant (credencial, ativação, prioridade, overrides), não capacidade de modelo:

```
content_generation_providers
  id, tenant_id, kind (image|video|voice), provider (wavespeed|falai|gemini|elevenlabs),
  credentials_encrypted, config (jsonb — overrides pontuais, ex: limitar a certos model_ids),
  priority, is_active, created_at
```

Reaproveita o padrão de criptografia já existente (`app/services/content/crypto.py`, o mesmo usado
em `content_social_accounts`). Ao cadastrar um provedor (`POST /content/providers`), o backend faz
uma chamada de validação mínima contra a API do provedor antes de persistir — credencial inválida
falha na hora do cadastro, não na primeira geração real.

### Capability Engine (seleção de provider+modelo)

O orquestrador não escolhe por prioridade cega — resolve requisitos primeiro:

```
1. Generation request declara: kind, mode (text_to_x | image_to_x), aspect_ratio,
   resolution, duration, reference_image (bool), avatar (bool)
2. Busca content_generation_providers do tenant com kind pedido e is_active=true
3. Pra cada provider candidato, busca em generation_models os modelos ativos desse
   provider+kind
4. Filtra por capability match (supports_* + supported_ratios/resolutions/max_duration
   compatíveis com o pedido)
5. Do conjunto (provider, model) compatível, ordena pela priority do tenant
6. Tenta o primeiro; nenhum candidato compatível → job falha de imediato
   (error_code=no_compatible_model), sem tentar nada
```

### Adapters

Interface única por `kind`, agora recebendo o `model_id` resolvido pelo Capability Engine (não mais
implícito por provider):
- `generate_image(model_id, prompt, **params) -> GeneratedAsset`
- `generate_video(model_id, prompt, source_image_url=None, **params) -> GeneratedAsset`
- `generate_voice(model_id, text, voice_id, **params) -> GeneratedAsset`

Um módulo por provider em `app/services/content/providers/`: `wavespeed.py`, `falai.py`,
`gemini.py` (todos com `generate_image` + `generate_video`), `elevenlabs.py` (`generate_voice`).
`wavespeed.py` reaproveita o client HTTP, retry e polling já escritos em
`generate_videos_wavespeed`. Cada adapter mapeia os erros do provider pra uma taxonomia canônica
(`rate_limit`, `transient`, `invalid_credentials`, `invalid_params`, `content_policy`,
`unsupported_capability`) — é essa taxonomia que a Retry Policy usa pra decidir se tenta de novo.
`content_policy` aqui é a recusa do próprio provider (o modelo se negou a gerar), sem relação com o
Regulated Content Policy Gate descrito adiante, que é classificação nossa e não bloqueia nada.

### GenerationJob — execução técnica

```
content_generation_jobs
  id, tenant_id, client_id, content_piece_id,
  kind (image|video|voice), status
    (queued|running|retrying|completed|failed|cancelled|timeout),
  provider, model,
  request_payload (jsonb — prompt, negative_prompt, parameters, seed, reference_assets,
    avatar_id, aspect_ratio, resolution, duration, additional_provider_parameters),
  response_metadata (jsonb),
  attempt_count, retry_count,
  input_units, output_units, estimated_cost, actual_cost, currency, duration_ms,
  started_at, completed_at, failed_at,
  error_code, error_message,
  created_at, updated_at
```

`tenant_id`/`client_id` ficam denormalizados aqui (também deriváveis via
`content_piece → campaign → client → tenant`) pra permitir query/observabilidade direta sem join
longo — é dado imutável no momento da criação do job, não há risco de divergência.

`request_payload` já captura os parâmetros necessários pra reproduzir a geração (prompt, seed,
modelo, referências) — cobre a necessidade de auditoria/reprodutibilidade estruturalmente, sem
precisar de uma tabela `generation_request` separada nesta fase (ver Não-objetivos).

Uma `ContentPiece` pode ter mais de um `GenerationJob` — uma piece `type=video` com avatar, por
exemplo, gera: job `kind=image` (imagem-base, se não vier de avatar/`source_image_piece_id`) → job
`kind=voice` (narração, se houver) → job `kind=video` (o vídeo em si, image-to-video usando a
imagem-base). `ContentPiece.status` deriva do conjunto de jobs: todos completos → `pending_approval`;
qualquer um falhou após esgotar retry/fallback → `failed`.

### Asset Registry

`ContentPiece.asset_url` deixa de ser a fonte de verdade — vira um ponteiro denormalizado (pra leitura
rápida em listagens) pro asset "final" da piece. A fonte de verdade passa a ser:

```
content_assets
  id, tenant_id, client_id, content_piece_id, generation_job_id,
  type (image|audio|video|thumbnail|subtitle),
  url, storage_path,
  mime_type, size_bytes, width, height, duration,
  provider, model,
  metadata (jsonb),
  created_at
```

Cada `GenerationJob` bem-sucedido produz pelo menos um `content_asset`. Isso permite uma piece
`type=video` reter também a imagem-base e o áudio de narração que a compuseram (rastreável,
reaproveitável), não só o vídeo final.

### Retry Policy

Classificação de erro decide a ação — não é retry cego:

- **Retryable**: `429`, `5xx`, timeout, falha de rede temporária, provider indisponível.
- **Non-retryable**: credencial inválida, parâmetro inválido, modelo inválido, capability não
  suportada, rejeição por política de conteúdo do provider.

Erro non-retryable pula direto pro próximo candidato compatível (não insiste no mesmo par
provider+model). Erro retryable tenta de novo no mesmo candidato até `max_attempts`, com backoff
exponencial + jitter, antes de cair pro próximo candidato. Configuração
(`max_attempts`/`backoff`/`backoff_multiplier`/`max_backoff`/`jitter`) fica em constante de
aplicação nesta fase (não precisa ser configurável por tenant ainda).

### Cost Telemetry

Sem billing nesta fase — só telemetria. Cada `GenerationJob` registra `input_units`/`output_units`
(quando o provider expõe) e `estimated_cost`/`actual_cost`/`currency`, usando `cost_config` do
`generation_models` como base de estimativa. Habilita análise futura por tenant/client/campaign/
piece/provider/model sem precisar de nova coluna — os dados já nascem no formato certo.

### Observability

`GenerationJob.id` **é** o `generation_id` rastreável — não se cria um identificador paralelo.
Trace mínimo por execução: request → seleção de candidato → tentativa → (erro → fallback →
tentativa)\* → sucesso → upload → asset(s) criados → piece atualizada. Redação de segredo em log
reaproveita o padrão já existente em `app/services/material.py`
(`_redact_secret`/`_redact_request_error`, hoje usado pra chave do Pixabay) — nunca logar
credencial, API key, token ou header de autorização.

### Avatar

Sem mudança em relação à versão anterior desta spec — identidade reutilizável (imagem de referência
+ voz), escopada ao client:

```
content_avatars
  id, client_id, name, reference_image_url, voice_provider, voice_id, created_at
```

`voice_provider`/`voice_id` apontam pra uma voz já cadastrada/clonada no ElevenLabs da conta do
tenant — a clonagem em si acontece fora desta API.

### Composição de `ContentPiece`

`POST /content/pieces` aceita `campaign_id`, `type`, `generation_prompt`, `avatar_id` (opcional),
`source_image_piece_id` (opcional), `voice_id` (opcional), `is_synthetic_media` (obrigatório),
`content_category` (opcional, nullable — ver "Regulated Content Policy Gate"), `idempotency_key`
(obrigatório). Validação por `type`: `audio` e `video` exigem `generation_prompt` não vazio; `image`
exige `generation_prompt` **ou** `avatar_id`. Falta de campo obrigatório → 422.

Orquestração por `type`, agora expressa como grafo de jobs (execução sequencial simples em código de
aplicação — não um workflow engine genérico, ver Não-objetivos):

- **image**: 1 `GenerationJob(kind=image)` → 1 `content_asset(type=image)` → `asset_url` da piece
  aponta pra ele. Se `avatar_id` informado e `generation_prompt` vazio, usa direto a
  `reference_image_url` do avatar (sem job, sem chamar provider).
- **audio**: 1 `GenerationJob(kind=voice)` com a voz resolvida (`voice_id` explícito ou a do
  `avatar_id`) → 1 `content_asset(type=audio)`.
- **video**: resolve imagem-base (avatar → `source_image_piece_id` → gera nova via job `kind=image`,
  nessa ordem de preferência) → resolve narração (voz do avatar, `voice_id` explícito, ou nenhuma;
  se houver, `GenerationJob(kind=voice)`) → `GenerationJob(kind=video)` (image-to-video com a
  imagem-base resolvida, ou text-to-video se nenhuma se aplica) → se há narração, compõe áudio+vídeo
  reaproveitando as funções de merge já existentes em `app/services/video.py` → `content_asset`s
  intermediários (imagem-base, áudio) e final (vídeo) todos persistidos, `asset_url` da piece aponta
  pro vídeo final.

## Fluxo assíncrono

1. `POST /content/pieces` valida: campanha existe, e há provedor ativo pra cada `kind` que os jobs
   dessa piece vão precisar no mínimo — `type=image` exige `kind=image` (a menos que resolva via
   `avatar_id` sem prompt, aí não precisa de provider nenhum); `type=audio` exige `kind=voice`;
   `type=video` exige `kind=video` sempre, mais `kind=image`/`kind=voice` só se a piece for de fato
   gerar imagem-base/narração (não vier de avatar/`source_image_piece_id`/sem `voice_id`). Falta de
   provider pra algum `kind` necessário → 422 antes de criar qualquer coisa. Essa é a checagem
   grossa (provider existe); a checagem fina de capability acontece por job, na hora de rodar.
2. Cria a `ContentPiece` com `status=generating` e o(s) `GenerationJob`(s) necessários com
   `status=queued`, retorna 202 com a piece criada.
3. Jobs rodam em background (`ThreadPoolExecutor`, mesmo padrão já validado em `task.py` via
   `_schedule_cross_post` — não a máquina de estado Redis/Memory do pipeline de vídeo legado, que é
   feita pra outro formato de polling de UI). Job passa por `running` → `completed`/`retrying`
   (segundo a Retry Policy) → eventualmente `completed`/`failed`/`timeout`.
4. Todos os jobs da piece completos → upload dos assets no Supabase Storage, `content_asset`s
   criados, `ContentPiece.status=pending_approval`. Qualquer job falhou após esgotar
   retry/fallback → `ContentPiece.status=failed` + linha em `content_audit_logs` com o motivo.
5. Timeout por `kind` é configurável (default indicativo: 60s pra `image`/`voice`, 10min pra
   `video`). Resultado que chega depois do job já ter sido marcado `timeout`/`failed` é descartado
   (revalida o status do job antes de gravar; se não estiver mais em execução, no-op).

## Idempotência

`idempotency_key` obrigatório em `POST /content/pieces`. Antes de criar qualquer coisa, busca uma
piece existente com a mesma chave dentro do mesmo `campaign_id`: existe → retorna como está (200),
sem novos jobs; não existe → segue o fluxo normal. Protege contra retry de rede duplicando chamadas
pagas.

## Disclosure de mídia sintética

`is_synthetic_media` é obrigatório e **explícito**, definido por quem cria a piece — não inferido
pelo sistema a partir de haver ou não `avatar_id`. Quem monta o plano de conteúdo decide peça a peça
se ela é declarada como IA-gerada; o risco de declarar incorretamente é do cliente. O sistema só
persiste e expõe o valor, pra fase 3 (publicação) usar.

## Regulated Content Policy Gate (fundação mínima)

Conteúdo em nicho regulado (saúde, farmacêutico, financeiro, jurídico, etc.) eventualmente vai
precisar de classificação de risco e revisão humana obrigatória. O motor completo disso é fase
futura — mas os **dados** precisam nascer junto com a piece, senão a fase futura não tem como
reconstruir a classificação de conteúdo já gerado. Esta fase implementa só a estrutura persistida e
a classificação estática.

**Princípio: `classification ≠ enforcement`.** Nesta fase o gate apenas registra; não bloqueia
geração, upload nem publicação, e não altera o workflow existente da piece.

Quatro colunas novas em `content_pieces`:

- **`content_category`** (nullable, extensível): `medical`, `pharmaceutical`, `financial`,
  `insurance`, `legal`, `alcohol`, `gambling`, `political`, `regulated_product` ou `null`.
  Declarado **explicitamente** por quem cria a piece — mesmo padrão de `is_synthetic_media`, sem
  classificação automática do prompt ou do asset. `null` é valor válido e continua sendo o default.
- **`risk_level`** (`none|low|medium|high`): derivado por função pura e determinística a partir de
  uma tabela estática `content_category → risk_level`, centralizada em um único módulo de fácil
  alteração. Sem chamada externa, sem IA. Persistido na criação e **nunca** recalculado
  retroativamente. Mapeamento inicial indicativo: `null → none`; `medical`/`pharmaceutical` →
  `high`; `financial`/`insurance`/`legal` → `medium` (valores concretos das demais categorias são
  definidos no plano de implementação).
- **`requires_human_review`** (bool): derivado — `risk_level = high` → `true`, caso contrário
  `false`. Nesta fase o campo é **inerte por construção**: a piece segue o fluxo normal e chega a
  `pending_approval` como qualquer outra (não existe auto-approve até a fase 4, então não há o que
  bloquear). Existe pra que o motor de regras da fase 4 possa consultá-lo sem migration nova.
- **`policy_version`** (string, valor inicial `"v1"`): versão da tabela estática usada na
  classificação, persistida na criação. Se a tabela mudar depois, pieces antigas continuam
  associadas à versão sob a qual foram classificadas.

`risk_level`, `requires_human_review` e `policy_version` são **derivados pelo backend** — o cliente
não pode informá-los na request; só `content_category` é aceito como entrada, e um valor fora da
lista suportada → 422.

Exemplo — request com `content_category: "medical"` persiste:
`risk_level=high`, `requires_human_review=true`, `policy_version="v1"`, sem nenhuma chamada externa
e sem mudança no fluxo de geração/aprovação.

Auditabilidade se resolve pelas próprias quatro colunas (dá pra reconstruir como a classificação
foi determinada sem recalcular a regra vigente) — sem audit log dedicado a policy nesta fase.

## Modelo de dados — mudanças

```
generation_models  (nova, catálogo global)
  id, provider, kind, model_id, name, is_active,
  supports_text_to_image, supports_image_to_image,
  supports_text_to_video, supports_image_to_video,
  supports_reference_image, supports_avatar,
  supported_ratios (jsonb), supported_resolutions (jsonb), max_duration,
  cost_config (jsonb), created_at, updated_at

content_generation_providers  (nova, tenant-scoped)
  id, tenant_id, kind, provider, credentials_encrypted, config (jsonb),
  priority, is_active, created_at

content_generation_jobs  (nova)
  id, tenant_id, client_id, content_piece_id, kind, status,
  provider, model, request_payload (jsonb), response_metadata (jsonb),
  attempt_count, retry_count,
  input_units, output_units, estimated_cost, actual_cost, currency, duration_ms,
  started_at, completed_at, failed_at, error_code, error_message,
  created_at, updated_at

content_assets  (nova)
  id, tenant_id, client_id, content_piece_id, generation_job_id,
  type, url, storage_path, mime_type, size_bytes, width, height, duration,
  provider, model, metadata (jsonb), created_at

content_avatars  (nova)
  id, client_id, name, reference_image_url, voice_provider, voice_id, created_at

content_pieces  (alterada — novas colunas)
  generation_prompt (text, nullable)
  avatar_id (FK content_avatars.id, nullable)
  source_image_piece_id (FK content_pieces.id, nullable — auto-referência)
  voice_id (text, nullable)
  is_synthetic_media (bool, not null)
  content_category (text/enum, nullable)
  risk_level (enum none|low|medium|high, not null, default none — derivado)
  requires_human_review (bool, not null, default false — derivado)
  policy_version (text, not null, default 'v1' — derivado)
  asset_url passa a ser ponteiro denormalizado pro content_asset final (continua nullable,
    preenchido só quando a piece completa)
```

`idempotency_key` (já existia na Fundação como `unique` global) passa a ser obrigatório no create;
dedup olha por `campaign_id`.

## Escopo desta fase (P0)

- `generation_models`, `content_generation_providers`, `content_generation_jobs`, `content_assets`,
  `content_avatars` + migrations Alembic + colunas novas em `content_pieces`.
- Seed inicial de `generation_models` (migration de dados) com os modelos concretos de WaveSpeed,
  fal.ai, Gemini (image + video) e ElevenLabs (voice) que forem usados nesta fase.
- CRUD de provedores (`app/controllers/v1/content/providers.py`) com validação de credencial no
  create.
- CRUD de avatares (`app/controllers/v1/content/avatars.py`).
- `GET /content/models` (leitura, filtro por `provider`/`kind`) — suporte pra UI futura de
  configuração de provider escolher/priorizar modelos.
- `GET /content/pieces/{id}/jobs` (leitura, debug/observabilidade) — sem CRUD de job via API, jobs
  só são criados pelo orquestrador internamente.
- Adapters WaveSpeed, fal.ai, Gemini (`generate_image` + `generate_video`) e ElevenLabs
  (`generate_voice`), com taxonomia de erro canônica.
- Capability Engine + Retry Policy no orquestrador (`app/services/content/generation.py`).
- `POST /content/pieces` funcional (cria piece + job(s) + gera de fato), com idempotência, timeout
  por `kind` e disclosure de mídia sintética.
- Regulated Content Policy Gate mínimo: `content_category` como entrada opcional validada +
  derivação estática de `risk_level`/`requires_human_review`/`policy_version` (classificação
  persistida, sem enforcement).
- Cost telemetry (campos preenchidos, sem lógica de billing/limite).
- Observability básica (trace via `GenerationJob.id`, redaction de segredo reaproveitado).
- Upload de artefatos gerados pro Supabase Storage (novo — hoje não existe integração com Storage
  no projeto).
- Migração de `generate_videos_wavespeed` (vídeo legado/global) pra buscar credenciais via
  `content_generation_providers` quando chamado no contexto do módulo de conteúdo.

## Não-objetivos (ficam para specs futuras)

**P1 — preparado, não implementado nesta fase:**
- Circuit breaker por provider/model (estados CLOSED/OPEN/HALF_OPEN, cooldown). O schema de
  `content_generation_jobs` já dá o histórico de falha necessário pra calcular isso depois sem
  migration nova.
- Regulated Content Policy **Engine** — a fundação de classificação entra em P0 (ver seção
  própria); o que fica pra depois é tudo que age sobre ela: `policy_status` como máquina de estados
  própria, enforcement/bloqueio automático por categoria ou risco, workflow especial de revisão
  humana, classificação automática por IA (análise semântica do prompt ou do asset gerado, detecção
  de claims, fact checking), policies por país/jurisdição, policies configuráveis por tenant e motor
  dinâmico de regras.
- `generation_request` como entidade própria reutilizável/replayable — o `request_payload` do job já
  guarda o necessário pra reprodutibilidade estruturalmente; uma abstração dedicada de "refazer essa
  geração exata" fica pra quando houver demanda real.

**P2 — fora de escopo até haver sinal de necessidade:**
- Basic Asset Validation (arquivo existe/legível/mime/tamanho/resolução/integridade) — nenhuma
  validação técnica pós-geração nesta fase; `GenerationJob.status=completed` do provider já basta
  pra marcar a piece `pending_approval`.
- Workflow engine genérico com dependências arbitrárias entre jobs — a composição de vídeo desta
  fase já é multi-job, mas orquestrada em código de aplicação (sequência fixa: imagem → voz → vídeo
  → composição), não um motor de grafo configurável.
- Provider/model health dinâmico influenciando ranking (além de priority pura).
- Scoring de qualidade avançado (face detection, black-frame, brand compliance).
- Controle de custo/limite de geração por `entitlement_status` — fase 4 (automação e aprovação).
- Consistência visual do avatar entre cenas/vídeos diferentes — limitação inerente dos provedores.
- Regenerar/versionar uma piece existente — pra gerar de novo, cria-se uma nova piece por ora.
- Política de retenção/limpeza de artefatos descartados no Supabase Storage.
- Clonagem de voz em si (cadastro da voz no ElevenLabs) — acontece fora desta API.
- Integrações reais com redes sociais / postagem (fase 3) e motor de regras em runtime (fase 4).

## Erros

Reaproveita `HttpException` (`app/models/exception.py`). Casos novos: `content_category` fora da
lista suportada (422), nenhum provedor ativo pro
`kind` exigido (422 na criação da piece), nenhum modelo compatível com os requisitos técnicos do
pedido (`GenerationJob.error_code=no_compatible_model`, não é erro HTTP — a piece já foi criada com
202, o job falha depois), `source_image_piece_id`/`avatar_id`/`voice_id` inválido ou de outro client
(404/422), credencial de provedor inválida no cadastro (422), job falhou após esgotar
retry/fallback (piece `failed`, não é erro de API).

## Testes

Sem suíte obrigatória por padrão (convenção do projeto). Candidatos a teste pontual ao final:
capability matching (o filtro certo de modelo pro pedido certo), classificação retryable/
non-retryable da Retry Policy, checagem de idempotência, e a função pura de derivação
`content_category → risk_level → requires_human_review` — são as peças de lógica não-trivial desta
fase.
