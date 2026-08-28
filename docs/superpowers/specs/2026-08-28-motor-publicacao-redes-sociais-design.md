# Design — Motor de publicação (redes sociais)

> **Status:** Final / Aprovado para Implementação
> **Data:** 2026-08-28
> **Sub-projeto:** 3 de 5

## Contexto e roadmap

O sub-projeto 2 fechou o ciclo de geração: uma `ContentPiece` chega a `status=approved` com um
artefato final em `content_assets`/`asset_url`, já carregando a disclosure de mídia sintética e a
classificação de conteúdo regulado. `ContentSocialAccount` também já existe (CRUD de credenciais).
A publicação de fato foi não-objetivo explícito do sub-projeto 2.

Esta fase:
1. Adiciona publicação real em seis redes sociais (Instagram, TikTok, YouTube, X, Facebook,
   LinkedIn), via adapter direto por plataforma.
2. Trata publicação como uma **execução técnica rastreável** (`ContentSocialPublication`), com
   cardinalidade `ContentPiece × ContentSocialAccount` (cross-post para múltiplas contas da mesma
   rede é suportado).
3. Introduz um **dispatcher operacional** com claim atômico via `FOR UPDATE SKIP LOCKED`, que nunca
   bloqueia um worker em `sleep()` durante backoff (rate-limits são rotina).
4. Fecha o ciclo: `ContentPiece.status` chega a `posted` na primeira publicação bem-sucedida.

Publicação **sob demanda** apenas — agendamento (`scheduled_for`) e regras de negócio são escopo do
sub-projeto 4.

## Objetivo desta fase

Dar ao módulo de conteúdo a capacidade de publicar uma `ContentPiece` aprovada em uma ou mais contas
sociais já cadastradas, com execução assíncrona rastreável, retry operacional sem bloquear workers,
proteção contra publicação concorrente duplicada, e taxonomia de erro consistente com o resto do
módulo.

## Princípios arquiteturais

- **Publish ≠ Schedule** — S3 executa; S4 decide quando/se.
- **Piece × Conta, não Piece → Conta** — uma piece pode ir para N contas. Cada par tem seu próprio
  ciclo de vida.
- **Sem fallback de destino** — erro não-retryable é sempre terminal para aquele par.
- **Retry é infraestrutura operacional** — o dispatcher só reexecuta jobs criados via API, nunca cria
  publicações autônomas.
- **Nunca segurar um worker esperando o relógio** — backoff é persistido (`next_run_at`), não
  dormido.
- **Claim atômico** — garantido pelo banco (`SELECT ... FOR UPDATE SKIP LOCKED`), nunca por
  aplicação.
- **`content_social_publications` é a única fonte de verdade** — `ContentPiece.status=posted` e
  `publication_summary` são apenas caches denormalizados de conveniência.

## Arquitetura

### Adapters por plataforma

Módulos por rede em `app/services/content/publishers/` (`instagram.py`, `tiktok.py`, `youtube.py`,
`x.py`, `facebook.py`, `linkedin.py`) implementando `PublisherAdapter`:

```python
class PublisherAdapter:
    platform: str

    def check_compatibility(piece, asset) -> None:
        # levanta PublicationError(unsupported_capability) se formato inválido
        # fail-fast antes de qualquer chamada de API

    def publish(piece, asset, account, credentials) -> PublishResult:
        # PublishResult(platform_post_id, platform_post_url)
        # levanta PublicationError classificado na taxonomia canônica
```

Erros mapeados para `PublicationErrorCode` (`app/services/content/publish_errors.py`, taxonomia
própria — não reaproveita `GenerationErrorCode`, os dois domínios compartilham a forma, não a
instância): `rate_limit | transient | invalid_credentials | invalid_params | content_policy |
unsupported_capability`. Apenas `rate_limit` e `transient` são retryable.

O adapter usa `try...finally` na execução para garantir o release de semáforos locais mesmo em caso
de exceções severas (`MemoryError`, timeout de lib externa).

Credenciais são decriptadas via o mesmo `app/services/content/crypto.py` já usado pelos generation
providers.

### Compatibilidade — fail-fast

`check_compatibility` roda **na criação do pedido**, dentro de `POST
/content/pieces/{id}/publish`. Um par incompatível nunca vira linha no banco; o erro é retornado
imediatamente no payload HTTP (sucesso parcial é suportado).

### `ContentSocialPublication` — execução técnica

Uma linha por par, garantido por `UNIQUE(content_piece_id, social_account_id)`:

```text
content_social_publications
  id, tenant_id, client_id, content_piece_id, social_account_id, platform,
  status (queued|running|retrying|succeeded|failed),
  attempt_count, max_attempts, publication_cycle,
  next_run_at (nullable),
  platform_post_id, platform_post_url,
  error_code, error_message,
  request_payload (jsonb),
  created_at, updated_at, completed_at
```

- **`attempt_count`**: número de tentativas *reais* iniciadas pelo worker. Criação começa com `0`.
  Quando o dispatcher captura o job (mesma transação do claim), sobe para `1`. Falha retryable vai
  para `retrying` sem incrementar de novo — o próximo claim (quando `next_run_at` vencer) é que sobe
  para `2`. `max_attempts` é comparado contra esse valor antes de decidir `retrying` vs. `failed`.
- **`max_attempts`**: teto máximo de tentativas reais permitidas.
- **`request_payload`**: guarda apenas o snapshot do pedido atual. Não acumula histórico de
  tentativas — se no futuro for preciso auditar tentativa a tentativa, a extensão natural é uma
  tabela de eventos `content_social_publication_events` (aditiva, sem migração destrutiva), não
  guardar array dentro de `request_payload`.

`tenant_id`/`client_id`/`platform` denormalizados na criação (deriváveis via
`piece → campaign → client → tenant` / conta), mesmo racional do `GenerationJob`: imutável desde a
criação, sem risco de divergência.

### Resumo denormalizado em `ContentPiece`

Atualizadas **transacionalmente** pelo serviço de publicação, na mesma transação que grava o novo
status da linha de publicação correspondente — nunca por trigger de banco nem por job separado:

- **`posted_at`**: preenchido na primeira publicação bem-sucedida de qualquer plataforma. O
  `status` da piece muda para `posted`. Falhas nas demais redes não regridem o status da piece.
- **`publication_summary`** (jsonb): cache agregado para contagens rápidas de UI, suportando
  múltiplas contas por plataforma. Nunca é lido como fonte de decisão — só
  `content_social_publications` é. Exemplo:
  ```json
  {
    "total": 3,
    "succeeded": 2,
    "failed": 1,
    "pending": 0,
    "platforms": {
      "instagram": { "succeeded": 1, "failed": 1 },
      "tiktok": { "succeeded": 1, "failed": 0 }
    }
  }
  ```

### Dispatcher — claim atômico e execução

Loop único registrado em `application_lifespan` (start/shutdown limpo — evitando repetir o achado
M11 do backlog de follow-up da geração, onde os executores da fase 2 nascem no import do módulo sem
hook de lifespan). A cada tick (`CONTENT_PUBLISH_DISPATCH_INTERVAL_SECONDS`, default indicativo 2s):

```sql
SELECT * FROM content_social_publications
WHERE status IN ('queued', 'retrying')
  AND (next_run_at IS NULL OR next_run_at <= now())
ORDER BY next_run_at NULLS FIRST
LIMIT :batch_size
FOR UPDATE SKIP LOCKED
```

executado numa transação que já marca as linhas capturadas como `running` e incrementa
`attempt_count` antes de liberar o lock — isso é o claim atômico: duas execuções concorrentes (dois
ticks sobrepostos, ou duas réplicas do processo) nunca pegam a mesma linha, porque `SKIP LOCKED` faz
a segunda simplesmente ignorar o que a primeira já travou. `batch_size` é
`CONTENT_PUBLISH_DISPATCH_BATCH_SIZE` (default indicativo: igual a `CONTENT_PUBLISH_WORKERS`).
`POST /publish` só cria linhas em `queued` (`next_run_at=null`, elegível já no próximo tick) —
**nunca** submete direto ao pool. O dispatcher é o único código que efetivamente chama um adapter, em
tentativa inicial e em retry igualmente.

Os workers pegam a linha (já marcada como `running` na transação do claim):

1. Adquire `Semaphore(platform)` (bloqueio aqui é aceitável e esperado — contenção curta pela duração
   de uma chamada HTTP real, não um `sleep` de backoff).
2. Chama `adapter.publish(...)`.
3. **Sucesso** → `status=succeeded`, preenche `platform_post_id`/`platform_post_url`,
   `completed_at=now`, atualiza transacionalmente o summary/`posted_at` da piece.
4. **Erro retryable** (`rate_limit`/`transient`) e `attempt_count < max_attempts` → `status=retrying`,
   `error_code`/`error_message` gravados, `next_run_at = now + backoff_delay(attempt_count)`
   (reaproveita a função pura `backoff_delay` de `app/services/content/retry.py`, que não faz I/O nem
   sleep — só calcula o atraso). Retorna **imediatamente**, sem `sleep()`, sem nova tentativa inline
   — só volta a ser elegível no tick que encontrar `next_run_at <= now()`.
5. **Erro retryable esgotado** (`attempt_count >= max_attempts`) ou **erro não-retryable** →
   `status=failed`, erro gravado, `completed_at=now`. Sem fallback de destino.
6. Libera o `Semaphore` no bloco `finally`.

### Pool compartilhado + semáforo por plataforma

Um único `ThreadPoolExecutor` (`CONTENT_PUBLISH_WORKERS`) — não seis pools dedicados. Concorrência
isolada por um dicionário local `{platform: Semaphore(limit)}`
(`CONTENT_PUBLISH_PLATFORM_CONCURRENCY`, default uniforme nesta fase). Uma plataforma congestionada
segura, no máximo, os workers que estão de fato tentando publicar nela; outras plataformas seguem
disputando normalmente a capacidade geral do pool.

**Nota sobre semáforos no P0:** o limite é **process-local**. Com Instagram=2 e 3 réplicas da
aplicação, o limite global efetivo é 6 requisições simultâneas — comportamento aceito para a v1, sem
exigir Redis. O `FOR UPDATE SKIP LOCKED` garante que réplicas nunca puxem o mesmo job
concorrentemente, independente dessa limitação do semáforo.

### Idempotência e retry explícito

`POST /content/pieces/{id}/publish` recebe `social_account_ids` e resolve por par
`(piece_id, social_account_id)`:

- **Não existe** → cria `status=queued`, `attempt_count=0`, `publication_cycle=1`.
- **`queued|running|retrying`** → no-op, retorna a linha existente (job em andamento).
- **`succeeded`** → no-op, retorna indicando que já foi publicado.
- **`failed`** (retry explícito) → hard reset na mesma linha: `status=queued`, `attempt_count=0`,
  `error_code=null`, `error_message=null`, `next_run_at=null`, incrementa `publication_cycle`.
  Histórico não é mantido na coluna payload — o reset é destrutivo por design.

Isso cobre idempotência por `(piece_id, social_account_id)` sem endpoint de retry separado: chamar
`/publish` de novo para um par que falhou **é** o retry.

## Fluxo de API

- **`POST /v1/content/pieces/{id}/publish`** — autenticado via `content_auth.verify_tenant_token`.
  Valida: piece existe e pertence ao tenant do token; `piece.status in (approved, posted)` (senão
  409 — `posted` continua elegível, já que é o próprio efeito colateral do primeiro sucesso desta
  fase, e uma piece publicada numa rede tem que poder ser publicada depois em outra; só
  `draft`/`generating`/`pending_approval`/`rejected`/`failed` bloqueiam); cada `social_account_id`
  existe, pertence ao mesmo `client_id` da campanha da piece, e está `status=active` (senão
  404/422). Roda `check_compatibility` e a regra de idempotência por conta — sucesso parcial
  suportado (uma conta rejeitada não derruba as demais da mesma chamada).

  Payload: `{ "social_account_ids": [1, 2, 3] }`

  Resposta (202 Accepted):
  ```json
  {
    "accepted": [
      {"social_account_id": 1, "platform": "instagram", "status": "queued"}
    ],
    "rejected": [
      {"social_account_id": 2, "platform": "tiktok", "reason": "unsupported_capability", "message": "..."}
    ]
  }
  ```

- **`GET /v1/content/pieces/{id}/publications`** — lista as linhas de `content_social_publications`
  da piece, leitura simples, sem CRUD de publicação via API — linhas só nascem pelo fluxo de
  `/publish`.

## Modelo de dados — mudanças

```
content_social_publications  (nova)
  id, tenant_id, client_id, content_piece_id, social_account_id, platform,
  status, attempt_count, max_attempts, publication_cycle,
  next_run_at, platform_post_id, platform_post_url,
  error_code, error_message, request_payload (jsonb),
  created_at, updated_at, completed_at
  UNIQUE (content_piece_id, social_account_id)

content_pieces  (alterada — novas colunas)
  publication_summary (jsonb, nullable, default null)
  posted_at (já existia — passa a ser escrito de fato nesta fase)
```

## Escopo P0 (Entregáveis)

- Criação da tabela `content_social_publications` + migrações Alembic.
- Colunas `publication_summary` e `posted_at` em `content_pieces`.
- `PublicationErrorCode` + mapeamento de erros HTTP (`publish_errors.py`).
- Adapters (Instagram, TikTok, YouTube, X, Facebook, LinkedIn) com `check_compatibility` + `publish`
  (chamadas reais às APIs oficiais, assumindo credencial/app já registrado pelo tenant em cada
  plataforma via `ContentSocialAccount`).
- Dispatcher `SKIP LOCKED` registrado em `application_lifespan` (start/shutdown limpo).
- Pool compartilhado com semáforos por plataforma (process-local), configuráveis
  (`CONTENT_PUBLISH_WORKERS`, `CONTENT_PUBLISH_PLATFORM_CONCURRENCY`,
  `CONTENT_PUBLISH_DISPATCH_INTERVAL_SECONDS`, `CONTENT_PUBLISH_DISPATCH_BATCH_SIZE`).
- `POST /v1/content/pieces/{id}/publish` e `GET /v1/content/pieces/{id}/publications`.
- Atualização transacional unificada de `publication_summary`/`posted_at`/`status=posted` no serviço
  de publicação.

## Não-objetivos (ficam para specs futuras)

**P1 — preparado, não implementado nesta fase:**
- `content_social_publication_events` (histórico por tentativa) — o desenho atual (`attempt_count`,
  `publication_cycle`, reset destrutivo em retry) não guarda histórico; extensão aditiva, sem
  migração destrutiva, se/quando a necessidade aparecer.
- Configuração de concorrência/`max_attempts` por plataforma (hoje um único default uniforme) — a
  estrutura já suporta, falta só o mecanismo de override.
- Polling de processamento assíncrono pós-upload de plataformas que processam em segundo plano (ex:
  YouTube) — `publish()` retorna no aceite do upload, não no fim do processamento.
- Semáforo de concorrência distribuído entre réplicas (Redis) — ver "Nota sobre semáforos no P0"; v1
  aceita limite process-local.

**P2 — fora de escopo até haver sinal de necessidade:**
- Scheduling por `scheduled_for` ou qualquer motor de regras (auto-post vs. aprovação, limites de
  `entitlement_status`) — sub-projeto 4 inteiro.
- Reaproveitamento do `UploadPostService`/agregador legado — descartado pela decisão de adapters
  diretos.
- Edição ou exclusão de um post já publicado na plataforma.
- Circuit breaker por plataforma (além do semáforo de concorrência estático).
- Balanceamento de carga inteligente entre réplicas do dispatcher (hoje a distribuição é só efeito
  colateral do `SKIP LOCKED`, sem otimização).

## Erros

Reaproveita `HttpException`. Casos novos: `piece.status` fora de `(approved, posted)` (409), conta
social não encontrada/de outro client (404), conta social inativa (422), incompatibilidade de
plataforma detectada em `check_compatibility` (422, retornado por conta dentro da resposta parcial de
`/publish`, não aborta as demais contas do pedido), publicação falhou após esgotar
`max_attempts`/erro não-retryable (`content_social_publications.status=failed`, não é erro de API —
a chamada original já retornou 202).

## Testes

Sem suíte obrigatória por padrão (convenção do projeto). Candidatos a teste pontual ao final:
classificação retryable/non-retryable de `PublicationErrorCode`, regra de idempotência prática
(criação/no-op/retry conforme status existente), claim atômico do dispatcher (duas capturas
concorrentes não pegam a mesma linha, `attempt_count` incrementa só no claim), e a atualização
transacional de `publication_summary`/`posted_at` — são as peças de lógica não-trivial desta fase.
