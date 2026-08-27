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
   múltiplos provedores e fallback por prioridade.
3. Introduz o conceito de **avatar** — uma identidade visual/vocal reutilizável (ex: um
   influenciador real ou fictício) associada a um client.
4. Fecha o ciclo de criação de `ContentPiece`, produzindo `image`, `audio` ou `video` de fato.

## Objetivo desta fase

Dar ao módulo de conteúdo a capacidade de gerar peças de conteúdo (imagem, áudio, vídeo) por IA,
com provedores plugáveis e configuráveis por tenant, incluindo suporte a avatares com voz clonada.

## Arquitetura

### Provedores por tenant

Nova tabela `content_generation_providers` — credenciais e configuração de cada provedor de IA que
um tenant contratou, com prioridade de fallback dentro do mesmo `kind`:

```
content_generation_providers
  id, tenant_id, kind (image|video|voice), provider (wavespeed|falai|gemini|elevenlabs),
  credentials_encrypted, config (jsonb — model id, voice settings, etc.),
  priority, is_active, created_at
```

Reaproveita o padrão de criptografia já existente (`app/services/content/crypto.py`, o mesmo usado
em `content_social_accounts`). Ao cadastrar um provedor (`POST /content/providers`), o backend faz
uma chamada de validação mínima contra a API do provedor antes de persistir — credencial inválida
falha na hora do cadastro, não na primeira geração real.

### Adapters

Interface única por `kind`:
- `generate_image(prompt, **params) -> GeneratedAsset`
- `generate_video(prompt, source_image_url=None, **params) -> GeneratedAsset` — `source_image_url`
  presente vira image-to-video, ausente vira text-to-video.
- `generate_voice(text, voice_id, **params) -> GeneratedAsset`

Um módulo por provedor em `app/services/content/providers/`:
- `wavespeed.py` — `generate_image`, `generate_video` (reaproveita client HTTP, retry e polling já
  escritos em `generate_videos_wavespeed`).
- `falai.py` — `generate_image`, `generate_video`.
- `gemini.py` — `generate_image`, `generate_video`.
- `elevenlabs.py` — `generate_voice`.

Nenhum provedor implementa os três `kind`s — cada adapter só expõe os métodos que o provedor de
fato suporta.

### Orquestrador de geração

`app/services/content/generation.py`: dado um tenant e um `kind`, resolve os provedores ativos
(`is_active=true`) ordenados por `priority` e tenta em cascata — mesmo espírito do fallback
Pexels→Pixabay→Coverr que já existe pra vídeo de estoque. Provedor sem crédito/erro/timeout → tenta
o próximo da lista. Todos falham → propaga falha pro chamador.

### Avatar

Identidade reutilizável (imagem de referência + voz), escopada ao **client** (não ao tenant) —
várias campanhas do mesmo client reusam o mesmo avatar para consistência visual e de voz entre
vídeos:

```
content_avatars
  id, client_id, name, reference_image_url, voice_provider, voice_id, created_at
```

`voice_provider`/`voice_id` apontam pra uma voz já cadastrada/clonada no ElevenLabs da conta do
tenant — o cadastro/clonagem da voz em si acontece direto na conta ElevenLabs do cliente, fora
desta API; aqui só se referencia o `voice_id` resultante.

### Composição de `ContentPiece`

`POST /content/pieces` passa a aceitar, além de `campaign_id` e `type`:
- `generation_prompt` (texto/ideia que descreve o que gerar)
- `avatar_id` (opcional)
- `source_image_piece_id` (opcional — reusa o `asset_url` de uma imagem já gerada como base)
- `voice_id` (opcional, independente de avatar — permite narração sem avatar associado)
- `is_synthetic_media` (obrigatório, booleano — ver seção "Disclosure de mídia sintética")
- `idempotency_key` (obrigatório — ver seção "Idempotência")

Validação por `type`: `audio` e `video` exigem `generation_prompt` não vazio (é o texto/ideia base
da narração ou do vídeo). `image` exige `generation_prompt` **ou** `avatar_id` (pelo menos um dos
dois, conforme a regra descrita abaixo). Falta de campo obrigatório pro `type` pedido → 422.

Orquestração por `type`:
- **image**: chama provedor `kind=image` com `generation_prompt` → upload no Supabase Storage →
  `ContentPiece.asset_url` preenchido. Se `avatar_id` informado e `generation_prompt` vazio, usa
  direto a `reference_image_url` do avatar (sem chamar provedor).
- **audio**: chama ElevenLabs (`kind=voice`) com `generation_prompt` como texto e a voz resolvida
  (`voice_id` explícito, ou a do `avatar_id`) → upload → `ContentPiece` publicável sozinho.
- **video**: resolve imagem-base (nesta ordem: `avatar.reference_image_url` se `avatar_id` sem
  `source_image_piece_id`; `source_image_piece_id.asset_url` se informado; senão gera uma nova via
  `kind=image` a partir de `generation_prompt`) → resolve narração (voz do avatar, `voice_id`
  explícito, ou nenhuma) → chama provedor `kind=video` (image-to-video com a imagem-base resolvida,
  ou text-to-video se nenhuma imagem-base se aplica) → se há narração, compõe áudio+vídeo
  reaproveitando as funções de merge já existentes em `app/services/video.py` (mesmo mecanismo que
  hoje junta trilha/legenda no pipeline legado).

## Fluxo assíncrono

Cada geração externa pode levar de segundos a minutos. Segue o padrão já validado em `task.py`
(`_schedule_cross_post`, execução em `ThreadPoolExecutor` em background) em vez da máquina de
estado Redis/Memory do pipeline de vídeo legado (feita pra um fluxo multi-etapas com polling de UI)
— aqui o estado já vive direto na linha do Postgres:

1. `POST /content/pieces` valida: campanha existe, tenant tem provedor ativo pro(s) `kind`(s)
   necessário(s) pelo `type` pedido (senão 422 antes de tentar gerar).
2. Cria a linha com `status=generating`, agenda a geração em background, retorna 202 com o
   `ContentPiece` criado.
3. Ao terminar: sucesso → upload do artefato, `asset_url` preenchido, `status=pending_approval`.
   Todos os provedores do fallback falharam ou o timeout do `kind` estourou → `status=failed` +
   linha em `content_audit_logs` com o motivo.
4. Timeout por `kind` é configurável (default indicativo: 60s pra `image`/`voice`, 10min pra
   `video`). Se um provedor responder depois do timeout já ter marcado a piece como `failed`, o
   resultado tardio é descartado (a rotina revalida o `status` atual da piece antes de escrever o
   resultado; se não estiver mais `generating`, é no-op) — evita sobrescrever um estado já
   finalizado.

## Idempotência

`idempotency_key` é obrigatório em `POST /content/pieces` (campo já previsto na Fundação, agora
usado de fato). Antes de criar qualquer coisa, o endpoint busca uma piece existente com a mesma
chave dentro do mesmo `campaign_id`:
- Existe → retorna a piece existente como está (200), **sem** disparar nova geração — protege
  contra retry de rede repetindo uma chamada de API paga.
- Não existe → segue o fluxo normal de criação (201/202 conforme o `type`).

## Disclosure de mídia sintética

`is_synthetic_media` é um campo obrigatório e **explícito**, definido por quem cria a piece — não
inferido pelo sistema a partir de haver ou não `avatar_id`/geração por IA. Quem monta o plano de
conteúdo (ex: 30 dias) decide dia a dia se aquela peça é declarada como IA-gerada ou não; o risco de
declarar incorretamente é do cliente, não da plataforma. O sistema só persiste e expõe o valor —
fica disponível pra fase 3 (motor de publicação) usar na hora de postar em cada rede.

## Modelo de dados — mudanças

```
content_generation_providers  (nova)
  id, tenant_id, kind (image|video|voice), provider (wavespeed|falai|gemini|elevenlabs),
  credentials_encrypted, config (jsonb), priority, is_active, created_at

content_avatars  (nova)
  id, client_id, name, reference_image_url, voice_provider, voice_id, created_at

content_pieces  (alterada — novas colunas)
  generation_prompt (text, nullable)
  avatar_id (FK content_avatars.id, nullable)
  source_image_piece_id (FK content_pieces.id, nullable — auto-referência)
  voice_id (text, nullable)
  is_synthetic_media (bool, not null)
```

`idempotency_key` já existia na Fundação como `unique` global; passa a ser obrigatório no create e a
lógica de dedup passa a olhar por `campaign_id` (a unicidade global no banco continua válida e
evita colisão entre campanhas).

## Escopo desta fase

- `content_generation_providers` + `content_avatars` + migrations Alembic + colunas novas em
  `content_pieces`.
- CRUD de provedores (`app/controllers/v1/content/providers.py`) com validação de credencial no
  create.
- CRUD de avatares (`app/controllers/v1/content/avatars.py`).
- Adapters WaveSpeed, fal.ai, Gemini (`generate_image` + `generate_video`) e ElevenLabs
  (`generate_voice`).
- Orquestrador de fallback por `kind`.
- `POST /content/pieces` funcional (cria + gera de fato), com idempotência, timeout por `kind` e
  disclosure de mídia sintética.
- Upload de artefatos gerados pro Supabase Storage (novo — hoje não existe integração com Storage
  no projeto).
- Migração de `generate_videos_wavespeed` (vídeo legado/global) pra buscar credenciais via
  `content_generation_providers` quando chamado no contexto do módulo de conteúdo.

## Não-objetivos (ficam para specs futuras)

- Controle de custo/limite de geração por tenant (ex: cap de gerações por `entitlement_status`) —
  fase 4 (automação e aprovação), que já vai lidar com regras/gating.
- Consistência visual do avatar entre cenas/vídeos diferentes — limitação inerente dos provedores
  (nem todos suportam referência de personagem consistente), não é algo resolvido em arquitetura
  aqui.
- Regenerar/versionar uma piece existente — pra gerar de novo, cria-se uma nova piece por ora.
- Política de retenção/limpeza de artefatos descartados no Supabase Storage.
- Clonagem de voz em si (cadastro da voz no ElevenLabs) — acontece fora desta API; aqui só se
  referencia um `voice_id` já existente.
- Integrações reais com redes sociais / postagem (fase 3) e motor de regras em runtime (fase 4).

## Erros

Reaproveita `HttpException` (`app/models/exception.py`). Casos novos: nenhum provedor ativo pro
`kind` exigido pelo `type` pedido (422), `source_image_piece_id`/`avatar_id`/`voice_id` inválido ou
de outro client (404/422), credencial de provedor inválida no cadastro (422), todos os provedores do
fallback falharam ou timeout (piece marcada `failed`, não é erro de API — o `POST` já retornou 202).

## Testes

Sem suíte obrigatória por padrão (convenção do projeto). Candidatos a teste pontual ao final,
seguindo o mesmo critério usado na Fundação (função crítica o bastante pra justificar): a lógica de
fallback do orquestrador (ordem, quando desiste) e a checagem de idempotência.
