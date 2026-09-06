# Design — Coleta de métricas de engajamento

> **Status:** Final / Aprovado para Implementação
> **Data:** 2026-09-05
> **Escopo:** backend (`app/`) + os tiles do topo de `webui/src/pages/Analytics.tsx`

## Contexto

`app/services/content/ui_analytics.py` computa tudo o que a tela de Analytics mostra a
partir de tabelas que já existem. Duas das seis métricas do topo são deliberadamente
`None`, e o docstring do módulo diz por quê:

> both need post-publish telemetry that this system has never collected (no shortener, no
> platform insights worker)

O resultado é o único vazio visível do produto: dois tiles marcados "ainda não coletado"
na tela principal de métricas. Esta spec constrói o *insights worker*. O encurtador fica
de fora — ver Não-objetivos.

### O que já existe e deve ser reusado

- **`PublisherAdapter`** (`publishers/base.py`) com `check_compatibility` e `publish`, seis
  implementações registradas, e `get_adapter(platform)`.
- **Taxonomia de erro de publicação** (`publish_errors.py`): `rate_limit`, `transient`,
  `invalid_credentials`, `invalid_params`, `content_policy`, `unsupported_capability`,
  mais `RETRYABLE_ERROR_CODES` e `classify_http_status`.
- **`retry.py`**: backoff exponencial com jitter, 3 tentativas.
- **`automation_scheduler`**: uma thread, um tick, três passes isolados, cada um em sessão
  própria. Um passe que estoura não impede os outros.
- **`ContentSocialPublication`**: já carrega `platform_post_id`, `completed_at`,
  `publication_cycle` e o status final da publicação. É o ponto de partida de toda coleta.

## Decisões de brainstorming

- **Só engajamento nesta rodada.** Cliques em link exigem encurtador próprio com rota
  pública de redirecionamento — Instagram feed e TikTok não têm link clicável, e só
  Facebook e LinkedIn reportam cliques. Fazer os dois dobraria o escopo e adicionaria uma
  superfície pública ao backend. O tile de cliques sai da tela em vez de continuar vazio.
- **Série de snapshots, não valor corrente.** Um post continua acumulando engajamento por
  dias. Sobrescrever uma linha destrói a resposta para "quando isso aconteceu", e o
  gráfico de engajamento no tempo é a evolução natural desta tela. Custa linhas; é o
  único desenho que não exige migração e recomeço depois.
- **Cadência decrescente, não fixa.** Intervalo constante gasta chamada em post velho,
  onde quase nada muda.
- **As seis plataformas, com capability declarada.** Simétrico com o publish, que já tem
  as seis. Assume o risco conhecido e explícito: sem credencial real disponível, os seis
  mapeamentos são verificados apenas contra resposta mockada — a mesma situação em que o
  motor de publicação vive desde que foi escrito.

## As métricas

### Alcance não é a mesma coisa nas seis plataformas

Alcance no sentido de *pessoas únicas* só existe no Instagram (`reach`) e no Facebook
(`post_impressions_unique`). As outras quatro reportam volume de exibição, não de gente:

| plataforma | campo de volume | é alcance? |
|---|---|---|
| Instagram | `reach` | sim |
| Facebook | `post_impressions_unique` | sim |
| LinkedIn | `impressionCount` | não |
| X | `impression_count` | não |
| TikTok | `view_count` | não |
| YouTube | `viewCount` | não |

Somar tudo sob o rótulo "Alcance" seria mentir por definição. `reach` e `impressions`
ficam em **colunas separadas e nuláveis**. O tile soma `reach` onde existe e `impressions`
onde não existe, e o `hint` do `StatTile` diz em quantas contas sociais houve
substituição. O mesmo número é o denominador da taxa, então tile e taxa nunca discordam
entre si.

### A fileira de tiles

| posição | hoje | passa a ser |
|---|---|---|
| 1–3 | Publicadas · Agendadas · Falhas | inalterado |
| 4 | Taxa de sucesso | **Alcance** |
| 5 | Cliques em links (vazio) | **Interações** |
| 6 | Engajamento (vazio) | **Taxa de engajamento** |

A hierarquia é Alcance → Interações → Taxa: distribuição, volume, qualidade.

- **Interações** = `likes + comments + shares`. Não inclui *saves* (só o Instagram tem) nem
  cliques (fora de escopo): incluí-los faria o número mudar de significado conforme o mix
  de plataformas da campanha.
- **Taxa de engajamento** = `interações ÷ alcance × 100`.

**Ausência não é zero, nos três.** Sem nenhum snapshot com métrica na janela, os três vêm
`None` e a tela renderiza "—", não "0" — do contrário uma campanha sem coleta ainda
pareceria uma campanha com zero engajamento. Pela mesma razão a taxa é `None` quando o
alcance somado é `0`, e não uma divisão por zero mascarada.

Os campos de `AnalyticsTiles` passam a ser `reach`, `interactions`, `engagement_rate` e
`reach_substituted_accounts` — este último é a contagem de **contas sociais distintas** na
janela cujo alcance entrou como impressões, e é o que alimenta o `hint` do tile.
- **"Taxa de sucesso" sai do topo.** O termo não deve aparecer na tela. O sinal não morre:
  `falhas` continua no tile 3 e a coluna "Taxa" continua em "Desempenho por conta".
  `success_rate` sai de `AnalyticsTiles` e **permanece** em `AccountPerformanceRead`.

## `content_publication_insights`

Uma linha por (publicação, coleta).

```
id                 pk
tenant_id          fk, index
client_id          fk, index
content_piece_id   fk, index
publication_id     fk, index
social_account_id  fk, index
platform           str
publication_cycle  int
collected_at       datetime
reach              int | null
impressions        int | null
likes              int | null
comments           int | null
shares             int | null
raw                JSON
error_code         str | null
error_message      str | null
```

Índices: `(publication_id, collected_at desc)` para o último snapshot, `(tenant_id,
collected_at)` para a janela.

**Colunas normalizadas *e* `raw`.** Sem as normalizadas, toda agregação vira parsing de
JSON. O `raw` guarda a resposta como chegou, porque as APIs adicionam campo sem avisar e
porque, quando um número parecer errado, é a única forma de saber se o bug é nosso ou
deles.

**`publication_cycle` acompanha o da publicação.** Republicar uma peça gera post novo na
plataforma; as métricas do post velho não podem se misturar com as do novo.

**Falha também é linha.** Erro na coleta grava snapshot com métricas nulas e `error_code`
preenchido. Assim "quando foi a última tentativa" não precisa de estado separado, e um
token quebrado fica visível na mesma tabela em vez de virar silêncio. A agregação ignora
linhas sem métrica.

**Nenhuma coluna nova em `content_social_publications`.** A publicação já tem `next_run_at`
para o retry de publicação; um `insights_next_at` misturaria dois ciclos de vida na mesma
linha, e a informação já está na tabela de snapshots.

## A coleta

### Cadência

Ancorada em `publication.completed_at`:

| idade do post | intervalo | coletas |
|---|---|---|
| 0–48h | 6h | 8 |
| 2–7 dias | 24h | 5 |
| 7–14 dias | 72h | 2 |
| > 14 dias | para | — |

~15 chamadas por publicação. Depois de 14 dias o custo de quota compra ruído.

A decisão é uma **função pura**:

```
due_for_collection(publication, last_collected_at, now) -> bool
```

Único lugar do agendamento, e trivialmente testável. Derivada a cada passe em vez de
persistida — os volumes aqui são pequenos, e o módulo de analytics já bucketiza em Python
pelo mesmo motivo.

### A costura nos adapters

No `PublisherAdapter`:

```python
supports_insights: bool = False

def fetch_insights(
    self, publication, account, credentials: dict
) -> InsightsResult: ...
```

`InsightsResult` é um dataclass congelado com `reach`, `impressions`, `likes`, `comments`,
`shares` (todos `Optional[int]`) e `raw: dict`. Cada adapter mapeia o que a sua API
publica; o que ela não publica fica `None`, nunca zero — zero é um fato, ausência não é.

Erros levantam `PublicationError` com os códigos que já existem, então
`RETRYABLE_ERROR_CODES` e `retry.py` valem sem adaptação.

### O passe

Quarto passe do `automation_scheduler`, ao lado de `generation`, `approval` e
`publish_dispatch`. Sem pool de threads próprio: é I/O em lote pequeno, como os outros
três. Elegibilidade: publicações `succeeded`, com `platform_post_id`, `completed_at`
dentro de 14 dias, adapter com `supports_insights`, e `due_for_collection` verdadeiro.

### Degradação

- **`rate_limit` / `transient`** → `run_with_retry` dentro da coleta. Esgotando, grava
  snapshot de erro e desiste **deste tick**; a próxima janela devida tenta de novo.
- **`invalid_credentials` / `invalid_params`** → grava snapshot de erro e **encerra a
  coleta daquela publicação**. Token sem `instagram_manage_insights` ou post apagado não
  se conserta sozinho; insistir queima 15 chamadas para receber o mesmo 403.

## A leitura

`ui_analytics.get_overview` passa a agregar sobre o **snapshot mais recente com métrica de
cada publicação** da janela. Somar todos os snapshots contaria a mesma curtida quinze
vezes — é a armadilha central desta feature e tem teste dedicado.

## Testes

Em ordem de valor:

1. **`due_for_collection`** — tabela de casos sobre a cadência, com as bordas exatas (48h,
   7d, 14d) e "já coletei há 10 minutos".
2. **Agregação** — o último-snapshot-por-publicação, e a substituição alcance→impressões
   incluindo o contador que alimenta o `hint`.
3. **Seis mapeamentos de adapter** — fixture de resposta canônica por API, saída
   normalizada asseverada. Única verificação possível sem credencial; é o que os seis
   testes de publish já fazem, no mesmo molde (`unittest` + `MagicMock`).
4. **O passe** — adapter falso e sessão em memória: escreve snapshot, registra falha, e
   para de coletar após erro não-retryável.

## Não-objetivos

- **Encurtador de links e o tile de cliques.** Decisão separada, tomada depois com dados
  reais de uso na mão.
- **Tela de saúde de conta.** Se uma conta inteira está com escopo faltando, todo post dela
  vira linha de erro e ninguém é avisado ativamente. O dado fica na tabela para uma tela
  futura; não construir isso agora é escolha consciente, não esquecimento.
- **Gráfico de engajamento no tempo.** A tabela de snapshots existe para permiti-lo, mas
  ele não entra nesta rodada.
- **Retenção / expurgo dos snapshots.** ~15 linhas por publicação não pressiona nada no
  horizonte visível.
- **Métricas de conta** (seguidores, crescimento). Escopo é performance de post.

## Riscos e pontos de atenção

- **Os seis mapeamentos não são verificáveis daqui.** Nenhuma credencial real disponível.
  Mesmo risco que o motor de publicação carrega desde que foi escrito, agora assumido de
  olhos abertos. O `raw` na tabela é o que torna o diagnóstico possível quando houver
  credencial.
- **Quota de API.** ~15 chamadas por publicação. Com muitas contas ativas isso escala
  linearmente e pode bater em rate limit — que é retryável e cai no backoff, mas vale
  medir antes de aumentar a janela ou a densidade.
- **`reach` vs `impressions` é uma decisão de produto disfarçada de detalhe técnico.** O
  `hint` do tile é o que impede a substituição de virar mentira silenciosa; se ele for
  removido numa rodada futura de polimento, a métrica perde a honestidade.
- **Permissões de insights são escopos separados do publish.** Um token que publica pode
  não ler métricas (`instagram_manage_insights`, `read_insights` no Facebook). Espere
  `invalid_credentials` em contas que hoje publicam bem.
