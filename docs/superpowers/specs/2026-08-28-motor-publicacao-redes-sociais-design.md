# Design — Motor de publicação (redes sociais)

> **Status:** Draft para revisão
> **Data:** 2026-08-28
> **Sub-projeto:** 3 de 5 (ver [Fundação do Módulo de Conteúdo](2026-08-27-fundacao-modulo-conteudo-design.md) e [Motor de geração estendido](2026-08-27-motor-geracao-imagens-design.md))

## Contexto e roadmap

O sub-projeto 2 fechou o ciclo de geração: uma `ContentPiece` chega a `status=approved` com um
artefato final em `content_assets`/`asset_url`, já carregando a disclosure de mídia sintética
(`is_synthetic_media`) e a classificação de conteúdo regulado (`content_category`, `risk_level`,
`requires_human_review`) que essa fase vai precisar respeitar. `ContentSocialAccount` também já
existe (`app/models/content.py:84`, CRUD em `app/services/content/social_accounts.py` +
`app/controllers/v1/content/social_accounts.py`) — mas é só cadastro de credencial por client, sem
nenhuma lógica de postagem real. A publicação de fato foi não-objetivo explícito do sub-projeto 2.

O único código de postagem que existe hoje no repo é legado do MoneyPrinterTurbo
(`app/services/upload_post.py`, `_cross_post_executor`/`_run_cross_post` em `app/services/task.py`)
— um integrador único (agregador tipo upload-post.com), fora do módulo de conteúdo multi-tenant e
sem os conceitos de tenant/policy gate/idempotência que este módulo já estabeleceu. Esta fase não o
reaproveita como integração — só empresta o padrão de pool/semáforo já validado nele.

Esta fase:
1. Adiciona publicação real em seis redes sociais (Instagram, TikTok, YouTube, X, Facebook,
   LinkedIn), via adapter direto por plataforma — mesma filosofia dos adapters de geração do
   sub-projeto 2, sem depender de agregador de terceiro.
2. Trata publicação, como geração, como uma **execução técnica rastreável**
   (`ContentSocialPublication`), separada da entidade de conteúdo — mas com cardinalidade
   `ContentPiece × ContentSocialAccount`, já que uma piece pode ir para várias contas/redes
   (cross-post).
3. Introduz um **dispatcher operacional** com claim atômico de linhas via `FOR UPDATE SKIP LOCKED`,
   que nunca bloqueia um worker em `sleep()` durante backoff — condição explícita desta fase, dado
   que rate-limit de rede social é rotina, não exceção.
4. Fecha o ciclo: `ContentPiece.status` chega a `posted` quando a primeira publicação bem-sucedida
   acontece.

Publicação **sob demanda** apenas — decidir *quando* ou *se* uma piece deve ser publicada
(`scheduled_for`, regras de aprovação/entitlement) é o motor de regras do sub-projeto 4, que ainda
não existe. Esta fase só sabe executar uma publicação já decidida por uma chamada explícita de API.

## Objetivo desta fase

Dar ao módulo de conteúdo a capacidade de publicar uma `ContentPiece` aprovada em uma ou mais contas
sociais já cadastradas, com execução assíncrona rastreável, retry operacional sem bloquear workers,
proteção contra publicação concorrente duplicada, e taxonomia de erro consistente com o resto do
módulo.

## Princípios arquiteturais

- **Publish ≠ Schedule** — S3 executa uma publicação já decidida; decidir quando/se publicar é do
  S4. `ContentPiece.scheduled_for` permanece sem uso ativo nesta fase.
- **Piece × Conta, não Piece → Conta** — uma piece pode ser publicada em N contas; cada par
  `(piece, conta)` tem seu próprio ciclo de vida e resultado independente.
- **Sem fallback de destino** — diferente da geração (onde um provider incompatível cai para o
  próximo candidato), aqui não existe substituto: publicar no Instagram só pode ser feito pelo
  adapter do Instagram. Erro não-retryable é sempre terminal para aquele par.
- **Retry é infraestrutura operacional, não decisão de negócio** — o dispatcher só reexecuta
  publicações que já foram criadas por uma chamada explícita a `/publish`; ele nunca cria uma
  publicação nova por conta própria.
- **Nunca segurar um worker esperando o relógio** — backoff é persistido (`next_run_at`), não
  dormido. Um worker que bloqueia em `time.sleep()` por até 30s por causa de rate-limit de uma
  plataforma é exatamente o tipo de gargalo que o pool compartilhado existe para evitar.
- **Claim atômico, não claim por convenção** — com múltiplas réplicas do processo (ou múltiplos
  ticks concorrentes do dispatcher), duas execuções nunca podem pegar a mesma linha; isso é
  garantido pelo banco (`SELECT ... FOR UPDATE SKIP LOCKED`), não por lógica de aplicação.
- **`content_social_publications` é a única fonte de verdade** — `ContentPiece.status=posted` e
  `publication_summary` são conveniência denormalizada, nunca a origem do dado.

## Arquitetura

### Adapters por plataforma

Um módulo por rede em `app/services/content/publishers/`: `instagram.py`, `tiktok.py`,
`youtube.py`, `x.py`, `facebook.py`, `linkedin.py`, implementando uma interface comum definida em
`publishers/base.py`:

```
class PublisherAdapter:
    platform: str
    supported_piece_types: set[ContentPieceType]

    def check_compatibility(piece, asset) -> None
        # levanta PublicationError(unsupported_capability, ...) se o tipo/formato
        # da piece não é aceito por esta plataforma (ex: LinkedIn não aceita o
        # mesmo vídeo vertical que o Instagram Reels aceita)

    def publish(piece, asset, account, credentials) -> PublishResult
        # PublishResult(platform_post_id, platform_post_url)
        # levanta PublicationError classificado na taxonomia canônica
```

Cada adapter mapeia os erros da API oficial da plataforma (status HTTP, códigos de erro
proprietários) para a mesma taxonomia canônica usada na geração:
`rate_limit | transient | invalid_credentials | invalid_params | content_policy |
unsupported_capability` — implementada em `app/services/content/publish_errors.py` como
`PublicationErrorCode` (taxonomia própria, não reaproveita `GenerationErrorCode`: os dois domínios
compartilham a forma, não a instância — misturar as duas faria um `no_compatible_model` de geração
aparecer, sem sentido, em contexto de publicação). `rate_limit`/`transient` são retryable; os demais
são terminais para aquele par `(piece, conta)`.

`publish()` retorna assim que a plataforma confirma o recebimento do post (ex: Graph API retorna o
`media_id`) — não faz polling de processamento assíncrono da plataforma (ex: YouTube processando o
vídeo depois do upload). Ver Não-objetivos.

### Compatibilidade — fail-fast antes de criar qualquer linha

`check_compatibility` roda **na criação do pedido de publicação** (dentro de `POST
/content/pieces/{id}/publish`), não no dispatcher. Um par incompatível nunca chega a existir como
linha em `content_social_publications` — é rejeitado na resposta da própria chamada, com o motivo.
Isso evita criar um job fadado a falhar e deixa o erro visível imediatamente para quem chamou a API,
em vez de só aparecer depois numa consulta de status.

Credenciais são decriptadas via o mesmo `app/services/content/crypto.py` e o mesmo padrão de
injeção de credencial por-tenant já usado pelos generation providers.

### `ContentSocialPublication` — execução técnica

Uma linha por par `(content_piece_id, social_account_id)`, com `UNIQUE` nessa dupla — nunca existe
mais de uma linha para o mesmo par, mesmo depois de retry manual (ver "Idempotência prática"):

```
content_social_publications
  id, tenant_id, client_id, content_piece_id, social_account_id, platform,
  status (queued|running|retrying|succeeded|failed),
  attempt_count, max_attempts, publication_cycle,
  next_run_at (nullable),
  platform_post_id, platform_post_url,
  error_code, error_message,
  request_payload (jsonb — snapshot do que foi enviado ao adapter),
  created_at, updated_at, completed_at
```

`tenant_id`/`client_id` denormalizados na criação (deriváveis via
`piece → campaign → client → tenant`), mesmo racional do `GenerationJob`: query/observabilidade
direta sem join longo, sem risco de divergência porque é imutável desde a criação. `platform`
também denormalizado da conta, no mesmo espírito.

`request_payload` guarda só o snapshot do pedido atual — **não** acumula histórico de tentativas
(ver "Idempotência prática" sobre por que o reset é destrutivo por design). Se no futuro for preciso
auditar tentativa a tentativa (não só o estado atual), a extensão natural é uma tabela de eventos
`content_social_publication_events` — fora de escopo aqui, mas o desenho atual não impede acrescentá-
la depois sem migração destrutiva.

### Resumo denormalizado em `ContentPiece`

Duas colunas novas em `content_pieces`:

- **`publication_summary`** (jsonb, ex: `{"instagram": "succeeded", "tiktok": "failed"}`) — mapa
  `platform → status` da publicação mais recente daquele par para essa piece. Convém para listagem
  (não precisa de join com `content_social_publications` para mostrar "publicado em 2 de 3 redes"),
  mas nunca é lido como fonte de decisão — só `content_social_publications` é.
- **`posted_at`** (já existia) — passa a ser preenchido na primeira publicação bem-sucedida de
  qualquer plataforma para essa piece.

Ambas são atualizadas **na mesma transação** que grava o novo status da linha de publicação
correspondente, dentro do próprio serviço de publicação — nunca por trigger de banco nem por job
separado. Se a atualização da linha falhar, o resumo na piece não pode ter avançado sozinho.

`ContentPiece.status` transiciona para `posted` (com `posted_at`) na primeira publicação
bem-sucedida — falha de publicação em outras contas não reverte esse status nem move a piece para
`failed`; o detalhe de quem falhou fica só em `publication_summary`/`content_social_publications`.

### Dispatcher — claim atômico, sem bloquear worker em backoff

Um loop único (registrado em `application_lifespan`, com shutdown limpo — evitando repetir o achado
M11 do backlog de follow-up da geração, onde os executores da fase 2 nascem no import do módulo sem
hook de lifespan) roda em intervalo curto configurável
(`CONTENT_PUBLISH_DISPATCH_INTERVAL_SECONDS`, default indicativo 2s). A cada tick:

```sql
SELECT * FROM content_social_publications
WHERE status IN ('queued', 'retrying')
  AND (next_run_at IS NULL OR next_run_at <= now())
ORDER BY next_run_at NULLS FIRST
LIMIT :batch_size
FOR UPDATE SKIP LOCKED
```

`batch_size` é `CONTENT_PUBLISH_DISPATCH_BATCH_SIZE` (default indicativo: igual a
`CONTENT_PUBLISH_WORKERS`, para não capturar mais linhas do que o pool consegue processar no mesmo
tick).

executado numa transação que já marca as linhas capturadas como `running` antes de liberar o lock —
isso é o claim atômico: duas execuções concorrentes do dispatcher (dois ticks sobrepostos, ou duas
réplicas do processo) nunca pegam a mesma linha, porque `SKIP LOCKED` faz a segunda simplesmente
ignorar o que a primeira já travou. `POST /publish` só cria linhas em `queued`
(`next_run_at=null`, elegível já no próximo tick) — **nunca** submete direto ao pool. O dispatcher é
o único código que efetivamente chama um adapter; isso mantém uma única via de execução (nada de um
caminho para a primeira tentativa e outro para retry), então a garantia de claim atômico vale
igualmente para tentativa inicial e para retry.

Cada linha capturada é submetida ao pool compartilhado (`executor.submit`). Dentro do worker:

1. Adquire o `Semaphore` da plataforma daquela linha (bloqueio aqui é aceitável e esperado — é
   contenção curta pela duração de uma chamada HTTP real, não um `sleep` de backoff; ver seção
   seguinte).
2. Chama `adapter.publish(...)`.
3. **Sucesso** → `status=succeeded`, `platform_post_id`/`platform_post_url` gravados,
   `completed_at=now`, mais a atualização transacional de `publication_summary`/`posted_at` da
   piece.
4. **Erro retryable** (`rate_limit`/`transient`) e `attempt_count < max_attempts` → `status=retrying`,
   `attempt_count += 1`, `next_run_at = now + backoff_delay(attempt_count)` (reaproveita a função pura
   `backoff_delay` de `app/services/content/retry.py`, que já não faz I/O nem sleep — só calcula o
   atraso), `error_code`/`error_message` atualizados com o erro mais recente. O worker retorna
   **imediatamente** — nenhum `sleep()`, nenhuma nova tentativa inline. A linha só volta a ser
   elegível no próximo tick do dispatcher que encontrar `next_run_at <= now()`.
5. **Erro retryable esgotado** (`attempt_count >= max_attempts`) ou **erro não-retryable** →
   `status=failed`, `error_code`/`error_message` gravados, `completed_at=now`. Sem fallback de
   destino (ver Princípios).
6. Libera o `Semaphore` da plataforma.

### Pool compartilhado + semáforo por plataforma

Um único `ThreadPoolExecutor` (`CONTENT_PUBLISH_WORKERS`, tamanho compartilhado entre todas as
plataformas) — não seis pools dedicados. Concorrência por plataforma é controlada por um
`Semaphore` independente por `platform` (`CONTENT_PUBLISH_PLATFORM_CONCURRENCY`, default uniforme
nesta fase, ex: 2), mantido num dicionário `{platform: Semaphore(limit)}` na camada de despacho do
worker (passo 1 acima) — não no dispatcher. Uma plataforma congestionada ou em rate-limit segura, no
máximo, os workers que estão de fato tentando publicar nela; jobs de outras plataformas continuam
disputando normalmente a capacidade geral do pool, sem depender de infraestrutura de fila separada
por rede.

A estrutura já nasce pronta para configuração por adapter (limite de concorrência, `max_attempts`,
mapa de backoff) — nesta fase todos usam o mesmo valor default, mas trocar o default por plataforma
depois é mudar uma constante, não redesenhar a arquitetura de execução (dispatcher/claim/semáforo
permanecem os mesmos).

### Idempotência prática

`POST /content/pieces/{id}/publish` recebe uma lista de `social_account_id` e, para cada um, olha se
já existe linha para o par `(piece_id, social_account_id)`:

- **Não existe** → cria `status=queued`, `attempt_count=0`, `publication_cycle=1`.
- **Existe, `queued|running|retrying`** → retorna a linha existente como está, sem criar nada novo
  (chamada duplicada é no-op).
- **Existe, `succeeded`** → retorna indicando que já foi publicado; não republica.
- **Existe, `failed`** → funciona como **retry explícito** sobre a mesma linha: reseta
  `status=queued`, `attempt_count=0`, `error_code=null`, `error_message=null`, `next_run_at=null`,
  incrementa `publication_cycle`. O reset é destrutivo por design — o erro da tentativa anterior não
  fica retido depois que um novo ciclo começa explicitamente; se isso viola alguma necessidade de
  auditoria histórica no futuro, a extensão é a tabela de eventos citada acima, não guardar array de
  tentativas dentro de `request_payload`.

Isso cobre o requisito de idempotência por `(piece_id, social_account_id)` sem precisar de um
endpoint de retry separado: chamar `/publish` de novo para um par que falhou **é** o retry.

## Fluxo — API

- **`POST /content/pieces/{id}/publish`** — body `{social_account_ids: [...]}`. Autenticado via
  `content_auth.verify_tenant_token` (mesmo padrão do resto do módulo). Valida: piece existe e
  pertence ao tenant do token; `piece.status in (approved, posted)` (senão 409 — estado errado para
  publicar). `posted` precisa continuar elegível: é o próprio efeito colateral do primeiro sucesso
  desta fase, e uma piece já publicada em uma rede tem que poder ser publicada depois em outra via
  uma segunda chamada — só `draft`/`generating`/`pending_approval`/`rejected`/`failed` bloqueiam;
  cada `social_account_id` existe, pertence ao mesmo `client_id` da campanha da piece, e está
  `status=active` (senão 404/422). Para cada conta válida, roda `check_compatibility` e aplica a
  regra de idempotência acima. Resposta 202 com o resultado por conta (linha criada, já existente,
  ou rejeitada por incompatibilidade — parcial: uma conta incompatível não derruba as demais da
  mesma chamada).
- **`GET /content/pieces/{id}/publications`** — lista as linhas de `content_social_publications` da
  piece (status por plataforma), leitura simples, sem CRUD de publicação via API — linhas só nascem
  pelo fluxo de `/publish`.

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
  publication_summary (jsonb, nullable, default null — mapa platform → status)
  posted_at (já existia — passa a ser escrito de fato nesta fase)
```

## Escopo desta fase (P0)

- `content_social_publications` + migration Alembic + colunas novas em `content_pieces`.
- `PublicationErrorCode` + classificação de erro HTTP/plataforma (`publish_errors.py`).
- Adapters Instagram, TikTok, YouTube, X, Facebook e LinkedIn (`publish` + `check_compatibility`,
  chamadas reais às APIs oficiais), assumindo credencial/app já registrado pelo tenant em cada
  plataforma e cadastrado via `ContentSocialAccount`.
- Dispatcher com claim atômico (`FOR UPDATE SKIP LOCKED`), registrado em `application_lifespan`
  (start/shutdown limpo).
- Pool compartilhado + semáforo por plataforma, configuráveis
  (`CONTENT_PUBLISH_WORKERS`, `CONTENT_PUBLISH_PLATFORM_CONCURRENCY`,
  `CONTENT_PUBLISH_DISPATCH_INTERVAL_SECONDS`, `CONTENT_PUBLISH_DISPATCH_BATCH_SIZE`).
- `POST /content/pieces/{id}/publish` e `GET /content/pieces/{id}/publications`.
- Atualização transacional de `publication_summary`/`posted_at`/`status=posted` na piece.

## Não-objetivos (ficam para specs futuras)

**P1 — preparado, não implementado nesta fase:**
- `content_social_publication_events` (histórico por tentativa) — o desenho atual (`attempt_count`,
  `publication_cycle`, reset destrutivo em retry) não guarda histórico; a extensão é aditiva, sem
  migração destrutiva, se/quando a necessidade aparecer.
- Configuração de concorrência/`max_attempts` por plataforma (hoje um único default uniforme) — a
  estrutura já suporta, falta só o mecanismo de override.
- Polling de processamento assíncrono pós-upload de plataformas que processam em segundo plano (ex:
  YouTube) — `publish()` retorna no aceite do upload, não no fim do processamento.

**P2 — fora de escopo até haver sinal de necessidade:**
- Scheduling por `scheduled_for` ou qualquer motor de regras (auto-post vs. aprovação, limites de
  `entitlement_status`) — sub-projeto 4 inteiro.
- Reaproveitamento do `UploadPostService`/agregador legado — descartado pela decisão de adapters
  diretos.
- Edição ou exclusão de um post já publicado na plataforma.
- Circuit breaker por plataforma (além do semáforo de concorrência estático).
- Multi-réplica com balanceamento inteligente do dispatcher (hoje qualquer número de réplicas
  funciona corretamente graças ao `SKIP LOCKED`, mas sem otimização de distribuição de carga entre
  elas).

## Erros

Reaproveita `HttpException`. Casos novos: `piece.status` fora de `(approved, posted)` (409), conta social não
encontrada/de outro client (404), conta social inativa (422), incompatibilidade de plataforma
detectada em `check_compatibility` (422, retornado por conta dentro da resposta parcial de
`/publish`, não aborta as demais contas do pedido), publicação falhou após esgotar
`max_attempts`/erro não-retryable (`content_social_publications.status=failed`, não é erro de API —
a chamada original já retornou 202).

## Testes

Sem suíte obrigatória por padrão (convenção do projeto). Candidatos a teste pontual ao final:
classificação retryable/non-retryable de `PublicationErrorCode`, regra de idempotência prática
(criação/no-op/retry conforme status existente), claim atômico do dispatcher (duas capturas
concorrentes não pegam a mesma linha), e a atualização transacional de `publication_summary`/
`posted_at` — são as peças de lógica não-trivial desta fase.
