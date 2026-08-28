# Motor de Geração Estendido (+ Imagens) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao módulo de conteúdo a capacidade de gerar imagem, áudio e vídeo por IA — com provedores configuráveis por tenant, seleção de modelo por capability, retry/fallback classificado, e rastreabilidade completa (jobs, assets, custo).

**Architecture:** `ContentPiece` (conteúdo) fica separado de `ContentGenerationJob` (execução técnica). Um Capability Engine escolhe o par `(provider, model)` compatível com os requisitos do pedido a partir de um catálogo global em YAML, e o orquestrador executa com retry classificado e fallback entre candidatos. Cada job bem-sucedido faz upload no Supabase Storage e registra um `ContentAsset`.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLAlchemy, Alembic, Postgres (Supabase), `requests`, Pillow (via moviepy), PyYAML, `cryptography` (Fernet), pytest + unittest.

**Spec:** [docs/superpowers/specs/2026-08-27-motor-geracao-imagens-design.md](../specs/2026-08-27-motor-geracao-imagens-design.md)

## Global Constraints

- **Idioma:** código, comentários, docstrings e mensagens de commit em **inglês**. (Comentários explicativos em chinês existem no código legado herdado do MoneyPrinterTurbo — não replicar; escrever em inglês.)
- **Testes:** este projeto **não escreve testes por padrão**. Escreva testes **somente** nas Tasks 2, 3, 4, 5 e 15, que cobrem as peças de lógica pura não-trivial nomeadas na spec (validação do catálogo, capability matching, classificação retryable/non-retryable, derivação de policy, idempotência). Nas demais tasks, o passo de verificação é execução manual/smoke — **não** adicione arquivos de teste nelas.
- **Estilo de teste:** `unittest.TestCase` em `test/services/test_<modulo>.py`, executado via `pytest`. Sem I/O real de rede ou banco nos testes — use `unittest.mock`.
- **Segredos:** nunca logar credencial, API key, token ou header de autorização. Ao logar erro de request, use o padrão de redação já existente em `app/services/material.py` (`_redact_secret`, `_redact_request_error`).
- **Segredos em config:** credenciais de provider nunca vão para `config.toml` — só para o banco (criptografadas com Fernet) ou variável de ambiente.
- **Enums Postgres:** cada coluna enum usa um `name=` **único** no banco. Nunca reutilize o mesmo `name` em duas colunas — o Alembic tenta criar o tipo duas vezes e a migration quebra.
- **Convenção de tabela:** toda tabela nova é prefixada `content_` (o `alembic/env.py` filtra por esse prefixo; tabela sem o prefixo é ignorada pelo autogenerate).
- **Roteador:** todo controller novo usa `new_router(dependencies=[Depends(content_auth.verify_tenant_token)])` de `app/controllers/v1/base.py` e é registrado em `app/router.py`.
- **Fase:** implementar **apenas** o P0 da spec. Circuit breaker, policy enforcement, validação técnica de asset, workflow engine genérico e worker externo estão fora de escopo — não implemente por conta própria.
- **Commits:** um commit por task, mensagem no formato Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

---

## File Structure

**Criados:**

| Arquivo | Responsabilidade |
|---|---|
| `app/models/content_generation.py` | Entidades e DTOs da execução de geração (provider, job, asset, avatar) |
| `app/services/content/models_catalog.yaml` | Catálogo global de modelos e capacidades |
| `app/services/content/catalog.py` | Carrega, valida e consulta o catálogo |
| `app/services/content/capability.py` | Capability Engine: requisitos → candidatos `(provider, model)` |
| `app/services/content/errors.py` | Taxonomia canônica de erro de geração |
| `app/services/content/retry.py` | Retry Policy: backoff exponencial com jitter |
| `app/services/content/policy.py` | Regulated Content Policy Gate (derivação estática) |
| `app/services/content/storage.py` | Upload para Supabase Storage |
| `app/services/content/image_ops.py` | Normalização de aspect ratio (Pillow) |
| `app/services/content/composition.py` | Mux de narração no vídeo gerado (moviepy) |
| `app/services/content/providers/base.py` | `GeneratedAsset` + contrato dos adapters |
| `app/services/content/providers/wavespeed.py` | Adapter WaveSpeed (image + video) |
| `app/services/content/providers/falai.py` | Adapter fal.ai (image + video) |
| `app/services/content/providers/gemini.py` | Adapter Gemini (image + video) |
| `app/services/content/providers/elevenlabs.py` | Adapter ElevenLabs (voice) |
| `app/services/content/providers/__init__.py` | Registry: resolve provider → adapter |
| `app/services/content/generation_providers.py` | CRUD de `ContentGenerationProvider` |
| `app/services/content/avatars.py` | CRUD de `ContentAvatar` |
| `app/services/content/jobs.py` | Persistência e transições de `ContentGenerationJob` |
| `app/services/content/assets.py` | Persistência de `ContentAsset` |
| `app/services/content/orchestrator.py` | Executa **um** job: capability → retry/fallback → adapter → upload → asset |
| `app/services/content/pipeline.py` | Grafo de jobs por `type` de piece + pools de thread |
| `app/controllers/v1/content/providers.py` | CRUD HTTP de provedores |
| `app/controllers/v1/content/avatars.py` | CRUD HTTP de avatares |
| `app/controllers/v1/content/models.py` | `GET /content/models` |

**Modificados:**

| Arquivo | Mudança |
|---|---|
| `app/models/content.py` | Novas colunas em `ContentPiece` + enums `ContentCategory`/`RiskLevel` + DTO de criação |
| `app/services/content/pieces.py` | `create_piece` com idempotência |
| `app/controllers/v1/content/pieces.py` | `POST /content/pieces` + `GET /content/pieces/{id}/jobs` |
| `app/router.py` | Registra routers novos |
| `alembic/env.py` | Importa `app.models.content_generation` |
| `app/services/material.py` | `generate_videos_wavespeed` aceita credencial injetada |
| `requirements.txt` / `pyproject.toml` | Adiciona `pillow` explícito |

---

## Task 1: Modelo de dados e migration

**Files:**
- Create: `app/models/content_generation.py`
- Modify: `app/models/content.py` (adicionar enums e colunas em `ContentPiece`)
- Modify: `alembic/env.py:11`
- Create: `alembic/versions/<hash>_add_generation_engine_tables.py` (via autogenerate)

**Interfaces:**
- Consumes: nada (primeira task).
- Produces: `GenerationKind`, `GenerationProviderName`, `GenerationJobStatus`, `ContentAssetType`, `ContentCategory`, `RiskLevel`, `ContentGenerationProvider`, `ContentGenerationJob`, `ContentAsset`, `ContentAvatar`; colunas novas em `ContentPiece`.

- [ ] **Step 1: Criar `app/models/content_generation.py`**

```python
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


class GenerationKind(str, Enum):
    image = "image"
    video = "video"
    voice = "voice"


class GenerationProviderName(str, Enum):
    wavespeed = "wavespeed"
    falai = "falai"
    gemini = "gemini"
    elevenlabs = "elevenlabs"


class GenerationJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    retrying = "retrying"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"


class ContentAssetType(str, Enum):
    image = "image"
    audio = "audio"
    video = "video"
    thumbnail = "thumbnail"
    subtitle = "subtitle"


# --- Tables ----------------------------------------------------------------


class ContentGenerationProvider(SQLModel, table=True):
    __tablename__ = "content_generation_providers"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    kind: GenerationKind = Field(
        sa_column=Column(SAEnum(GenerationKind, name="content_generation_provider_kind"))
    )
    provider: GenerationProviderName = Field(
        sa_column=Column(
            SAEnum(GenerationProviderName, name="content_generation_provider_name")
        )
    )
    credentials_encrypted: str
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    priority: int = Field(default=0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentAvatar(SQLModel, table=True):
    __tablename__ = "content_avatars"

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    name: str
    reference_image_url: str
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentGenerationJob(SQLModel, table=True):
    __tablename__ = "content_generation_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    kind: GenerationKind = Field(
        sa_column=Column(SAEnum(GenerationKind, name="content_generation_job_kind"))
    )
    status: GenerationJobStatus = Field(
        default=GenerationJobStatus.queued,
        sa_column=Column(
            SAEnum(GenerationJobStatus, name="content_generation_job_status")
        ),
    )
    provider: Optional[str] = None
    model: Optional[str] = None
    request_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    response_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
    attempt_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    input_units: Optional[float] = None
    output_units: Optional[float] = None
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    currency: Optional[str] = None
    duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ContentAsset(SQLModel, table=True):
    __tablename__ = "content_assets"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    generation_job_id: Optional[int] = Field(
        default=None, foreign_key="content_generation_jobs.id", index=True
    )
    type: ContentAssetType = Field(
        sa_column=Column(SAEnum(ContentAssetType, name="content_asset_type"))
    )
    url: str
    storage_path: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    is_intermediate: bool = Field(default=False)
    asset_metadata: dict = Field(
        default_factory=dict, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- DTOs ------------------------------------------------------------------


class GenerationProviderCreate(BaseModel):
    kind: GenerationKind
    provider: GenerationProviderName
    credentials: str
    config: dict = {}
    priority: int = 0


class GenerationProviderRead(BaseModel):
    id: int
    tenant_id: int
    kind: GenerationKind
    provider: GenerationProviderName
    config: dict
    priority: int
    is_active: bool
    created_at: datetime


class AvatarCreate(BaseModel):
    client_id: int
    name: str
    reference_image_url: str
    voice_provider: Optional[str] = None
    voice_id: Optional[str] = None


class AvatarRead(BaseModel):
    id: int
    client_id: int
    name: str
    reference_image_url: str
    voice_provider: Optional[str]
    voice_id: Optional[str]
    created_at: datetime


class GenerationJobRead(BaseModel):
    id: int
    content_piece_id: int
    kind: GenerationKind
    status: GenerationJobStatus
    provider: Optional[str]
    model: Optional[str]
    attempt_count: int
    retry_count: int
    estimated_cost: Optional[float]
    actual_cost: Optional[float]
    currency: Optional[str]
    duration_ms: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class ModelRead(BaseModel):
    provider: str
    kind: str
    model_id: str
    name: str
    supported_ratios: list[str]
    supported_resolutions: list[str]
    max_duration: Optional[int]
```

Nota sobre `asset_metadata`: o nome da coluna no banco é `metadata`, mas `metadata` é atributo reservado do SQLAlchemy `DeclarativeBase` — por isso o atributo Python é `asset_metadata` e o `Column("metadata", JSON)` faz o mapeamento.

- [ ] **Step 2: Adicionar enums de policy em `app/models/content.py`**

Insira logo após a classe `ApprovalAction` (linha 34), antes do comentário `# --- Tabelas ---`:

```python
class ContentCategory(str, Enum):
    medical = "medical"
    pharmaceutical = "pharmaceutical"
    financial = "financial"
    insurance = "insurance"
    legal = "legal"
    alcohol = "alcohol"
    gambling = "gambling"
    political = "political"
    regulated_product = "regulated_product"


class RiskLevel(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"
```

- [ ] **Step 3: Adicionar colunas novas em `ContentPiece`**

Em `app/models/content.py`, dentro da classe `ContentPiece`, insira antes de `created_at`:

```python
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = Field(default=None, foreign_key="content_avatars.id")
    source_image_piece_id: Optional[int] = Field(
        default=None, foreign_key="content_pieces.id"
    )
    voice_id: Optional[str] = None
    is_synthetic_media: bool = Field(default=False)
    content_category: Optional[ContentCategory] = Field(
        default=None,
        sa_column=Column(SAEnum(ContentCategory, name="content_category")),
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.none,
        sa_column=Column(
            SAEnum(RiskLevel, name="content_risk_level"),
            nullable=False,
            server_default="none",
        ),
    )
    requires_human_review: bool = Field(default=False)
    policy_version: str = Field(default="v1")
```

- [ ] **Step 4: Adicionar `generating` ao `ContentPieceStatus`**

Em `app/models/content.py`, na classe `ContentPieceStatus`, adicione como primeiro membro depois de `draft`:

```python
    generating = "generating"
```

- [ ] **Step 5: Estender `ContentPieceRead` e criar `ContentPieceCreate`**

Substitua a classe `ContentPieceRead` no fim de `app/models/content.py` por:

```python
class ContentPieceCreate(BaseModel):
    campaign_id: int
    type: ContentPieceType
    idempotency_key: str
    is_synthetic_media: bool
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = None
    source_image_piece_id: Optional[int] = None
    voice_id: Optional[str] = None
    content_category: Optional[ContentCategory] = None
    aspect_ratio: str = "9:16"
    resolution: Optional[str] = None
    duration: Optional[int] = None


class ContentPieceRead(BaseModel):
    id: int
    campaign_id: int
    type: ContentPieceType
    status: ContentPieceStatus
    asset_url: Optional[str]
    generation_prompt: Optional[str]
    avatar_id: Optional[int]
    source_image_piece_id: Optional[int]
    voice_id: Optional[str]
    is_synthetic_media: bool
    content_category: Optional[ContentCategory]
    risk_level: RiskLevel
    requires_human_review: bool
    policy_version: str
    scheduled_for: Optional[datetime]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 6: Garantir que os dois módulos de model carregam juntos**

`ContentPiece.avatar_id` referencia `content_avatars.id`, que vive no módulo novo. SQLAlchemy resolve FK por nome de tabela na configuração do mapper: se só um dos dois módulos tiver sido importado, a configuração falha com `NoReferencedTableError`. Como `content_generation.py` não importa `content.py`, não há ciclo — basta o pacote carregar os dois.

Escreva `app/models/__init__.py` (hoje vazio) com:

```python
# Both model modules must load together: content_pieces.avatar_id references
# content_avatars, which lives in content_generation.
from app.models import content, content_generation  # noqa: F401
```

- [ ] **Step 7: Registrar o módulo novo no Alembic**

Em `alembic/env.py`, logo abaixo da linha 11:

```python
import app.models.content_generation  # noqa: E402,F401  (registers generation tables)
```

- [ ] **Step 8: Gerar a migration**

```bash
alembic revision --autogenerate -m "add generation engine tables"
```

- [ ] **Step 9: Revisar a migration gerada**

Abra o arquivo criado em `alembic/versions/` e confirme:
- Cria as 4 tabelas: `content_generation_providers`, `content_avatars`, `content_generation_jobs`, `content_assets`.
- Adiciona as 9 colunas novas em `content_pieces`.
- Cada `sa.Enum(...)` tem um `name=` distinto. Se dois `sa.Enum` compartilharem `name`, corrija os `name=` no model e regenere.
- A ordem de `op.create_table` cria `content_avatars` **antes** de qualquer `add_column` que referencie `content_avatars.id`. Se não, mova a chamada.
- `risk_level`, `requires_human_review`, `policy_version` e `is_synthetic_media` são `nullable=False` com `server_default` (`'none'`, `false`, `'v1'`, `false` respectivamente) — sem `server_default` o `ALTER TABLE` falha se a tabela tiver linhas.

- [ ] **Step 10: Aplicar a migration**

```bash
alembic upgrade head
```
Expected: termina sem erro, imprimindo `Running upgrade 60a7421f3570 -> <hash>`.

- [ ] **Step 11: Verificar o schema no banco**

```bash
python3 -c "
import re, psycopg
url = re.search(r'DATABASE_URL=(.+)', open('.env').read()).group(1).strip().strip('\"').replace('postgresql+psycopg://','postgresql://')
with psycopg.connect(url) as conn, conn.cursor() as cur:
    for t in ['content_generation_providers','content_avatars','content_generation_jobs','content_assets']:
        cur.execute(f'SELECT count(*) FROM {t}')
        print(t, 'OK', cur.fetchone()[0])
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='content_pieces' ORDER BY ordinal_position\")
    print([r[0] for r in cur.fetchall()])
"
```
Expected: as 4 tabelas com contagem `0`, e a lista de colunas de `content_pieces` incluindo `generation_prompt`, `avatar_id`, `source_image_piece_id`, `voice_id`, `is_synthetic_media`, `content_category`, `risk_level`, `requires_human_review`, `policy_version`.

- [ ] **Step 12: Commit**

```bash
git add app/models/ alembic/env.py alembic/versions/
git commit -m "feat(content): add generation engine tables and policy columns"
```

---

## Task 2: Catálogo de modelos (YAML + loader + endpoint)

**Files:**
- Create: `app/services/content/models_catalog.yaml`
- Create: `app/services/content/catalog.py`
- Create: `app/controllers/v1/content/models.py`
- Create: `test/services/test_content_catalog.py`
- Modify: `app/router.py`

**Interfaces:**
- Consumes: `ModelRead` (Task 1).
- Produces: `ModelEntry` (dataclass), `ModelCatalogError`, `load_catalog(path=None) -> tuple[ModelEntry, ...]`, `get_catalog() -> tuple[ModelEntry, ...]`, `list_models(*, provider=None, kind=None) -> list[ModelEntry]`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `test/services/test_content_catalog.py`:

```python
import os
import tempfile
import unittest

from app.services.content import catalog

_VALID_ENTRY = """
- provider: wavespeed
  kind: video
  model_id: bytedance/seedance-2.0-fast/text-to-video
  name: Seedance 2.0 Fast
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: true
  supports_image_to_video: true
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9"]
  supported_resolutions: ["720p", "1080p"]
  max_duration: 15
  cost_config:
    unit: second
    price: 0.05
    currency: USD
"""


def _write(content):
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    handle.write(content)
    handle.close()
    return handle.name


class TestLoadCatalog(unittest.TestCase):
    def tearDown(self):
        catalog.get_catalog.cache_clear()

    def test_loads_valid_entry(self):
        path = _write(_VALID_ENTRY)
        try:
            entries = catalog.load_catalog(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].provider, "wavespeed")
        self.assertEqual(entries[0].supported_ratios, ("9:16", "16:9"))
        self.assertEqual(entries[0].max_duration, 15)

    def test_missing_required_field_raises(self):
        path = _write(_VALID_ENTRY.replace("  model_id: bytedance", "  other: bytedance"))
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)

    def test_duplicate_model_id_for_same_provider_raises(self):
        path = _write(_VALID_ENTRY + _VALID_ENTRY)
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)

    def test_unknown_kind_raises(self):
        path = _write(_VALID_ENTRY.replace("kind: video", "kind: hologram"))
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)

    def test_non_list_root_raises(self):
        path = _write("provider: wavespeed\n")
        try:
            with self.assertRaises(catalog.ModelCatalogError):
                catalog.load_catalog(path)
        finally:
            os.unlink(path)


class TestListModels(unittest.TestCase):
    def tearDown(self):
        catalog.get_catalog.cache_clear()

    def test_bundled_catalog_loads_and_filters(self):
        video_models = catalog.list_models(kind="video")
        voice_models = catalog.list_models(kind="voice")

        self.assertTrue(video_models)
        self.assertTrue(voice_models)
        self.assertTrue(all(m.kind == "video" for m in video_models))
        self.assertTrue(all(m.kind == "voice" for m in voice_models))

    def test_filters_by_provider(self):
        models = catalog.list_models(provider="elevenlabs")

        self.assertTrue(models)
        self.assertTrue(all(m.provider == "elevenlabs" for m in models))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `pytest test/services/test_content_catalog.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.content.catalog'`.

- [ ] **Step 3: Criar o catálogo YAML**

Crie `app/services/content/models_catalog.yaml`:

```yaml
# Global model catalog. Capabilities are intrinsic to each model and identical
# for every tenant, so this file is platform-owned configuration, not schema.
# Adding a model is a one-entry change here; no migration needed.

# --- WaveSpeed -------------------------------------------------------------
- provider: wavespeed
  kind: image
  model_id: bytedance/seedream-v4
  name: Seedream v4
  is_active: true
  supports_text_to_image: true
  supports_image_to_image: true
  supports_text_to_video: false
  supports_image_to_video: false
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9", "1:1", "4:5"]
  supported_resolutions: ["1024", "2048"]
  max_duration: null
  cost_config:
    unit: image
    price: 0.03
    currency: USD

- provider: wavespeed
  kind: video
  model_id: bytedance/seedance-2.0-fast/text-to-video
  name: Seedance 2.0 Fast (text-to-video)
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: true
  supports_image_to_video: false
  supports_reference_image: false
  supports_avatar: false
  supported_ratios: ["9:16", "16:9", "1:1"]
  supported_resolutions: ["720p", "1080p"]
  max_duration: 15
  cost_config:
    unit: second
    price: 0.05
    currency: USD

- provider: wavespeed
  kind: video
  model_id: bytedance/seedance-2.0-fast/image-to-video
  name: Seedance 2.0 Fast (image-to-video)
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: false
  supports_image_to_video: true
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9", "1:1"]
  supported_resolutions: ["720p", "1080p"]
  max_duration: 15
  cost_config:
    unit: second
    price: 0.06
    currency: USD

# --- fal.ai ----------------------------------------------------------------
- provider: falai
  kind: image
  model_id: fal-ai/flux/dev
  name: FLUX.1 [dev]
  is_active: true
  supports_text_to_image: true
  supports_image_to_image: true
  supports_text_to_video: false
  supports_image_to_video: false
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9", "1:1", "4:5"]
  supported_resolutions: ["1024"]
  max_duration: null
  cost_config:
    unit: image
    price: 0.025
    currency: USD

- provider: falai
  kind: video
  model_id: fal-ai/kling-video/v2/master/text-to-video
  name: Kling 2.0 Master (text-to-video)
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: true
  supports_image_to_video: false
  supports_reference_image: false
  supports_avatar: false
  supported_ratios: ["9:16", "16:9", "1:1"]
  supported_resolutions: ["720p", "1080p"]
  max_duration: 10
  cost_config:
    unit: second
    price: 0.09
    currency: USD

- provider: falai
  kind: video
  model_id: fal-ai/kling-video/v2/master/image-to-video
  name: Kling 2.0 Master (image-to-video)
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: false
  supports_image_to_video: true
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9", "1:1"]
  supported_resolutions: ["720p", "1080p"]
  max_duration: 10
  cost_config:
    unit: second
    price: 0.10
    currency: USD

# --- Gemini ----------------------------------------------------------------
- provider: gemini
  kind: image
  model_id: gemini-3-pro-image
  name: Gemini 3 Pro Image
  is_active: true
  supports_text_to_image: true
  supports_image_to_image: true
  supports_text_to_video: false
  supports_image_to_video: false
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9", "1:1", "4:5"]
  supported_resolutions: ["1024", "2048"]
  max_duration: null
  cost_config:
    unit: image
    price: 0.04
    currency: USD

- provider: gemini
  kind: video
  model_id: veo-3.1-generate-preview
  name: Veo 3.1
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: true
  supports_image_to_video: true
  supports_reference_image: true
  supports_avatar: false
  supported_ratios: ["9:16", "16:9"]
  supported_resolutions: ["720p", "1080p"]
  max_duration: 8
  cost_config:
    unit: second
    price: 0.35
    currency: USD

# --- ElevenLabs ------------------------------------------------------------
- provider: elevenlabs
  kind: voice
  model_id: eleven_multilingual_v2
  name: Eleven Multilingual v2
  is_active: true
  supports_text_to_image: false
  supports_image_to_image: false
  supports_text_to_video: false
  supports_image_to_video: false
  supports_reference_image: false
  supports_avatar: true
  supported_ratios: []
  supported_resolutions: []
  max_duration: null
  cost_config:
    unit: character
    price: 0.00018
    currency: USD
```

Nota: os `model_id` e preços acima são o ponto de partida. Confira contra a documentação vigente de cada provider antes de usar em produção e ajuste — é um arquivo de configuração, mudar não exige migration.

- [ ] **Step 4: Implementar o loader**

Crie `app/services/content/catalog.py`:

```python
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

import yaml

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "models_catalog.yaml")

_VALID_KINDS = frozenset({"image", "video", "voice"})

_REQUIRED_FIELDS = (
    "provider",
    "kind",
    "model_id",
    "name",
    "is_active",
    "supports_text_to_image",
    "supports_image_to_image",
    "supports_text_to_video",
    "supports_image_to_video",
    "supports_reference_image",
    "supports_avatar",
    "supported_ratios",
    "supported_resolutions",
    "max_duration",
    "cost_config",
)


class ModelCatalogError(RuntimeError):
    """The model catalog file is missing, unreadable, or malformed.

    Raised at import/boot time on purpose: a broken catalog must fail loudly
    on startup instead of silently producing "no compatible model" at the
    first paid generation.
    """


@dataclass(frozen=True)
class ModelEntry:
    provider: str
    kind: str
    model_id: str
    name: str
    is_active: bool
    supports_text_to_image: bool
    supports_image_to_image: bool
    supports_text_to_video: bool
    supports_image_to_video: bool
    supports_reference_image: bool
    supports_avatar: bool
    supported_ratios: tuple[str, ...]
    supported_resolutions: tuple[str, ...]
    max_duration: Optional[int]
    cost_config: dict


def _build_entry(raw: Any, index: int) -> ModelEntry:
    if not isinstance(raw, dict):
        raise ModelCatalogError(f"catalog entry #{index} is not a mapping")

    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ModelCatalogError(
            f"catalog entry #{index} is missing required fields: {', '.join(missing)}"
        )

    kind = str(raw["kind"])
    if kind not in _VALID_KINDS:
        raise ModelCatalogError(
            f"catalog entry #{index} has unknown kind {kind!r} "
            f"(expected one of {sorted(_VALID_KINDS)})"
        )

    max_duration = raw["max_duration"]
    if max_duration is not None:
        try:
            max_duration = int(max_duration)
        except (TypeError, ValueError) as exc:
            raise ModelCatalogError(
                f"catalog entry #{index} has a non-numeric max_duration"
            ) from exc

    return ModelEntry(
        provider=str(raw["provider"]),
        kind=kind,
        model_id=str(raw["model_id"]),
        name=str(raw["name"]),
        is_active=bool(raw["is_active"]),
        supports_text_to_image=bool(raw["supports_text_to_image"]),
        supports_image_to_image=bool(raw["supports_image_to_image"]),
        supports_text_to_video=bool(raw["supports_text_to_video"]),
        supports_image_to_video=bool(raw["supports_image_to_video"]),
        supports_reference_image=bool(raw["supports_reference_image"]),
        supports_avatar=bool(raw["supports_avatar"]),
        supported_ratios=tuple(str(item) for item in raw["supported_ratios"] or ()),
        supported_resolutions=tuple(
            str(item) for item in raw["supported_resolutions"] or ()
        ),
        max_duration=max_duration,
        cost_config=dict(raw["cost_config"] or {}),
    )


def load_catalog(path: Optional[str] = None) -> tuple[ModelEntry, ...]:
    """Read and validate the catalog file. Never cached — see get_catalog."""
    target = path or _CATALOG_PATH
    try:
        with open(target, "r", encoding="utf-8") as handle:
            raw_entries = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise ModelCatalogError(f"model catalog not found at {target}") from exc
    except yaml.YAMLError as exc:
        raise ModelCatalogError(f"model catalog at {target} is not valid YAML") from exc

    if not isinstance(raw_entries, list):
        raise ModelCatalogError(
            f"model catalog at {target} must be a list of model entries"
        )

    entries = tuple(
        _build_entry(raw, index) for index, raw in enumerate(raw_entries)
    )

    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry.provider, entry.model_id)
        if key in seen:
            raise ModelCatalogError(
                f"duplicate model_id {entry.model_id!r} for provider {entry.provider!r}"
            )
        seen.add(key)

    return entries


@lru_cache(maxsize=1)
def get_catalog() -> tuple[ModelEntry, ...]:
    return load_catalog()


def list_models(
    *, provider: Optional[str] = None, kind: Optional[str] = None
) -> list[ModelEntry]:
    entries = get_catalog()
    return [
        entry
        for entry in entries
        if entry.is_active
        and (provider is None or entry.provider == provider)
        and (kind is None or entry.kind == kind)
    ]
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `pytest test/services/test_content_catalog.py -v`
Expected: PASS (7 testes).

- [ ] **Step 6: Adicionar o boot check em `app/asgi.py`**

Em `app/asgi.py`, dentro de `application_lifespan`, logo após `logger.info("startup event")`, adicione:

```python
    # Fail fast on a malformed model catalog: a broken entry must break boot,
    # not the first paid generation call.
    from app.services.content.catalog import get_catalog

    get_catalog()
    logger.info("content model catalog loaded")
```

O import fica dentro da função, seguindo o padrão já usado no mesmo bloco (`from app.services import task as task_service`), que evita import pesado no topo do módulo.

- [ ] **Step 7: Criar o controller `GET /content/models`**

Crie `app/controllers/v1/content/models.py`:

```python
from typing import Optional

from fastapi import Depends

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.models.content import ContentTenant
from app.models.content_generation import ModelRead
from app.services.content import catalog

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.get("/content/models", response_model=list[ModelRead])
def list_models(
    provider: Optional[str] = None,
    kind: Optional[str] = None,
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    entries = catalog.list_models(provider=provider, kind=kind)
    return [
        ModelRead(
            provider=entry.provider,
            kind=entry.kind,
            model_id=entry.model_id,
            name=entry.name,
            supported_ratios=list(entry.supported_ratios),
            supported_resolutions=list(entry.supported_resolutions),
            max_duration=entry.max_duration,
        )
        for entry in entries
    ]
```

- [ ] **Step 8: Registrar o router**

Em `app/router.py`, adicione `models` à lista de imports de `app.controllers.v1.content` (mantendo a ordem alfabética) e, no bloco `# v1 content`, adicione:

```python
root_api_router.include_router(models.router)
```

- [ ] **Step 9: Verificar o endpoint**

```bash
python3 -c "
from fastapi.testclient import TestClient
from app.asgi import app
routes = [r.path for r in app.routes if 'models' in r.path]
print(routes)
"
```
Expected: imprime `['/api/v1/content/models']`.

- [ ] **Step 10: Commit**

```bash
git add app/services/content/catalog.py app/services/content/models_catalog.yaml app/controllers/v1/content/models.py app/router.py app/asgi.py test/services/test_content_catalog.py
git commit -m "feat(content): add validated global model catalog and models endpoint"
```

---

## Task 3: Capability Engine

**Files:**
- Create: `app/services/content/capability.py`
- Create: `test/services/test_content_capability.py`

**Interfaces:**
- Consumes: `ModelEntry`, `list_models` (Task 2); `ContentGenerationProvider` (Task 1).
- Produces: `GenerationMode` (Enum), `GenerationRequirements` (dataclass), `Candidate` (dataclass), `model_supports(entry, requirements) -> bool`, `select_candidates(session, *, tenant_id, requirements) -> list[Candidate]`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `test/services/test_content_capability.py`:

```python
import unittest
from unittest.mock import MagicMock

from app.services.content import capability
from app.services.content.catalog import ModelEntry


def _entry(**overrides):
    base = dict(
        provider="wavespeed",
        kind="video",
        model_id="m1",
        name="M1",
        is_active=True,
        supports_text_to_image=False,
        supports_image_to_image=False,
        supports_text_to_video=True,
        supports_image_to_video=True,
        supports_reference_image=True,
        supports_avatar=False,
        supported_ratios=("9:16", "16:9"),
        supported_resolutions=("720p", "1080p"),
        max_duration=15,
        cost_config={},
    )
    base.update(overrides)
    return ModelEntry(**base)


def _requirements(**overrides):
    base = dict(
        kind="video",
        mode=capability.GenerationMode.image_to_video,
        aspect_ratio="9:16",
        resolution="1080p",
        duration=8,
        needs_reference_image=True,
    )
    base.update(overrides)
    return capability.GenerationRequirements(**base)


class TestModelSupports(unittest.TestCase):
    def test_matching_model_is_supported(self):
        self.assertTrue(capability.model_supports(_entry(), _requirements()))

    def test_wrong_kind_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(kind="image"), _requirements())
        )

    def test_inactive_model_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(is_active=False), _requirements())
        )

    def test_mode_not_supported_is_rejected(self):
        entry = _entry(supports_image_to_video=False)

        self.assertFalse(capability.model_supports(entry, _requirements()))

    def test_unsupported_ratio_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(), _requirements(aspect_ratio="4:5"))
        )

    def test_unsupported_resolution_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(), _requirements(resolution="4k"))
        )

    def test_duration_above_max_is_rejected(self):
        self.assertFalse(
            capability.model_supports(_entry(), _requirements(duration=30))
        )

    def test_duration_equal_to_max_is_accepted(self):
        self.assertTrue(
            capability.model_supports(_entry(), _requirements(duration=15))
        )

    def test_reference_image_requirement_is_enforced(self):
        entry = _entry(supports_reference_image=False)

        self.assertFalse(capability.model_supports(entry, _requirements()))

    def test_empty_constraint_lists_are_treated_as_unconstrained(self):
        entry = _entry(supported_ratios=(), supported_resolutions=(), max_duration=None)

        self.assertTrue(capability.model_supports(entry, _requirements()))

    def test_unset_requirement_does_not_constrain(self):
        requirements = _requirements(aspect_ratio=None, resolution=None, duration=None)

        self.assertTrue(capability.model_supports(_entry(), requirements))


class TestSelectCandidates(unittest.TestCase):
    def _session_with(self, providers):
        session = MagicMock()
        session.exec.return_value.all.return_value = providers
        return session

    def test_orders_by_provider_priority(self):
        low = MagicMock(id=1, provider="wavespeed", priority=10, config={})
        high = MagicMock(id=2, provider="gemini", priority=1, config={})
        session = self._session_with([low, high])

        catalog_entries = {
            "wavespeed": [_entry(provider="wavespeed", model_id="ws-1")],
            "gemini": [_entry(provider="gemini", model_id="gm-1")],
        }

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: catalog_entries[provider],
        )

        self.assertEqual([c.model_id for c in candidates], ["gm-1", "ws-1"])

    def test_incompatible_models_are_dropped(self):
        provider_row = MagicMock(id=1, provider="wavespeed", priority=0, config={})
        session = self._session_with([provider_row])

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: [
                _entry(model_id="bad", supports_image_to_video=False),
                _entry(model_id="good"),
            ],
        )

        self.assertEqual([c.model_id for c in candidates], ["good"])

    def test_no_providers_yields_no_candidates(self):
        session = self._session_with([])

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: [_entry()],
        )

        self.assertEqual(candidates, [])

    def test_config_model_allowlist_filters_candidates(self):
        provider_row = MagicMock(
            id=1, provider="wavespeed", priority=0, config={"allowed_models": ["good"]}
        )
        session = self._session_with([provider_row])

        candidates = capability.select_candidates(
            session,
            tenant_id=1,
            requirements=_requirements(),
            catalog_lookup=lambda provider, kind: [
                _entry(model_id="good"),
                _entry(model_id="other"),
            ],
        )

        self.assertEqual([c.model_id for c in candidates], ["good"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `pytest test/services/test_content_capability.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.content.capability'`.

- [ ] **Step 3: Implementar o Capability Engine**

Crie `app/services/content/capability.py`:

```python
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

from sqlmodel import Session, select

from app.models.content_generation import ContentGenerationProvider
from app.services.content.catalog import ModelEntry, list_models


class GenerationMode(str, Enum):
    text_to_image = "text_to_image"
    image_to_image = "image_to_image"
    text_to_video = "text_to_video"
    image_to_video = "image_to_video"
    voice = "voice"


_MODE_SUPPORT_ATTRIBUTE = {
    GenerationMode.text_to_image: "supports_text_to_image",
    GenerationMode.image_to_image: "supports_image_to_image",
    GenerationMode.text_to_video: "supports_text_to_video",
    GenerationMode.image_to_video: "supports_image_to_video",
}


@dataclass(frozen=True)
class GenerationRequirements:
    kind: str
    mode: GenerationMode
    aspect_ratio: Optional[str] = None
    resolution: Optional[str] = None
    duration: Optional[int] = None
    needs_reference_image: bool = False
    needs_avatar: bool = False


@dataclass(frozen=True)
class Candidate:
    provider: str
    model_id: str
    priority: int
    provider_row_id: int


def model_supports(entry: ModelEntry, requirements: GenerationRequirements) -> bool:
    """Whether a catalog model can satisfy this request.

    Empty capability lists in the catalog mean "unconstrained", and unset
    requirement fields mean "caller does not care" — both sides default to
    permissive so a model is only rejected on a real conflict.
    """
    if not entry.is_active or entry.kind != requirements.kind:
        return False

    support_attribute = _MODE_SUPPORT_ATTRIBUTE.get(requirements.mode)
    if support_attribute is not None and not getattr(entry, support_attribute):
        return False

    if requirements.needs_reference_image and not entry.supports_reference_image:
        return False

    if requirements.needs_avatar and not entry.supports_avatar:
        return False

    if (
        requirements.aspect_ratio
        and entry.supported_ratios
        and requirements.aspect_ratio not in entry.supported_ratios
    ):
        return False

    if (
        requirements.resolution
        and entry.supported_resolutions
        and requirements.resolution not in entry.supported_resolutions
    ):
        return False

    if (
        requirements.duration is not None
        and entry.max_duration is not None
        and requirements.duration > entry.max_duration
    ):
        return False

    return True


def _default_catalog_lookup(provider: str, kind: str) -> Sequence[ModelEntry]:
    return list_models(provider=provider, kind=kind)


def select_candidates(
    session: Session,
    *,
    tenant_id: int,
    requirements: GenerationRequirements,
    catalog_lookup: Optional[Callable[[str, str], Sequence[ModelEntry]]] = None,
) -> list[Candidate]:
    """Resolve the ordered list of (provider, model) pairs to try.

    Capability comes first: priority only breaks ties among models that can
    actually satisfy the request. A high-priority provider whose models do not
    support the requested mode/ratio/duration is simply not a candidate.
    """
    lookup = catalog_lookup or _default_catalog_lookup

    provider_rows = list(
        session.exec(
            select(ContentGenerationProvider).where(
                ContentGenerationProvider.tenant_id == tenant_id,
                ContentGenerationProvider.kind == requirements.kind,
                ContentGenerationProvider.is_active == True,  # noqa: E712
            )
        ).all()
    )

    candidates: list[Candidate] = []
    for row in sorted(provider_rows, key=lambda item: item.priority):
        allowed = (row.config or {}).get("allowed_models")
        for entry in lookup(row.provider, requirements.kind):
            if allowed and entry.model_id not in allowed:
                continue
            if not model_supports(entry, requirements):
                continue
            candidates.append(
                Candidate(
                    provider=row.provider,
                    model_id=entry.model_id,
                    priority=row.priority,
                    provider_row_id=row.id,
                )
            )

    return candidates
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pytest test/services/test_content_capability.py -v`
Expected: PASS (15 testes).

- [ ] **Step 5: Commit**

```bash
git add app/services/content/capability.py test/services/test_content_capability.py
git commit -m "feat(content): add capability engine for provider and model selection"
```

---

## Task 4: Taxonomia de erro e Retry Policy

**Files:**
- Create: `app/services/content/errors.py`
- Create: `app/services/content/retry.py`
- Create: `test/services/test_content_retry.py`

**Interfaces:**
- Consumes: nada.
- Produces: `GenerationErrorCode` (Enum), `GenerationError` (Exception com `.code`/`.message`), `is_retryable(code) -> bool`, `classify_http_status(status) -> GenerationErrorCode`, `backoff_delay(attempt, random_fn=...) -> float`, `run_with_retry(operation, *, on_attempt=None) -> Any`, constante `MAX_ATTEMPTS`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `test/services/test_content_retry.py`:

```python
import unittest
from unittest.mock import patch

from app.services.content import retry
from app.services.content.errors import (
    GenerationError,
    GenerationErrorCode,
    classify_http_status,
    is_retryable,
)


class TestErrorClassification(unittest.TestCase):
    def test_rate_limit_is_retryable(self):
        self.assertTrue(is_retryable(GenerationErrorCode.rate_limit))

    def test_transient_is_retryable(self):
        self.assertTrue(is_retryable(GenerationErrorCode.transient))

    def test_timeout_is_retryable(self):
        self.assertTrue(is_retryable(GenerationErrorCode.timeout))

    def test_invalid_credentials_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.invalid_credentials))

    def test_invalid_params_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.invalid_params))

    def test_content_policy_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.content_policy))

    def test_unsupported_capability_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.unsupported_capability))

    def test_unknown_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.unknown))

    def test_http_429_maps_to_rate_limit(self):
        self.assertEqual(classify_http_status(429), GenerationErrorCode.rate_limit)

    def test_http_5xx_maps_to_transient(self):
        self.assertEqual(classify_http_status(503), GenerationErrorCode.transient)

    def test_http_401_maps_to_invalid_credentials(self):
        self.assertEqual(
            classify_http_status(401), GenerationErrorCode.invalid_credentials
        )

    def test_http_403_maps_to_invalid_credentials(self):
        self.assertEqual(
            classify_http_status(403), GenerationErrorCode.invalid_credentials
        )

    def test_http_400_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(400), GenerationErrorCode.invalid_params)

    def test_http_422_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(422), GenerationErrorCode.invalid_params)


class TestBackoffDelay(unittest.TestCase):
    def test_grows_exponentially(self):
        first = retry.backoff_delay(1, random_fn=lambda: 0.0)
        second = retry.backoff_delay(2, random_fn=lambda: 0.0)
        third = retry.backoff_delay(3, random_fn=lambda: 0.0)

        self.assertEqual(first, retry.BACKOFF_BASE_SECONDS)
        self.assertEqual(second, retry.BACKOFF_BASE_SECONDS * retry.BACKOFF_MULTIPLIER)
        self.assertEqual(
            third, retry.BACKOFF_BASE_SECONDS * retry.BACKOFF_MULTIPLIER**2
        )

    def test_is_capped_at_max_backoff(self):
        self.assertLessEqual(
            retry.backoff_delay(20, random_fn=lambda: 1.0),
            retry.MAX_BACKOFF_SECONDS * (1 + retry.JITTER_RATIO),
        )

    def test_jitter_widens_the_delay(self):
        without = retry.backoff_delay(1, random_fn=lambda: 0.0)
        with_jitter = retry.backoff_delay(1, random_fn=lambda: 1.0)

        self.assertGreater(with_jitter, without)


class TestRunWithRetry(unittest.TestCase):
    def test_returns_result_without_retrying_on_success(self):
        calls = []

        def operation():
            calls.append(1)
            return "ok"

        with patch.object(retry.time, "sleep"):
            result = retry.run_with_retry(operation)

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_retryable_error_up_to_max_attempts(self):
        calls = []

        def operation():
            calls.append(1)
            raise GenerationError(GenerationErrorCode.transient, "boom")

        with patch.object(retry.time, "sleep"):
            with self.assertRaises(GenerationError):
                retry.run_with_retry(operation)

        self.assertEqual(len(calls), retry.MAX_ATTEMPTS)

    def test_does_not_retry_non_retryable_error(self):
        calls = []

        def operation():
            calls.append(1)
            raise GenerationError(GenerationErrorCode.invalid_params, "bad")

        with patch.object(retry.time, "sleep"):
            with self.assertRaises(GenerationError):
                retry.run_with_retry(operation)

        self.assertEqual(len(calls), 1)

    def test_succeeds_after_a_retryable_failure(self):
        calls = []

        def operation():
            calls.append(1)
            if len(calls) == 1:
                raise GenerationError(GenerationErrorCode.rate_limit, "slow down")
            return "ok"

        with patch.object(retry.time, "sleep"):
            result = retry.run_with_retry(operation)

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)

    def test_reports_each_attempt(self):
        attempts = []

        def operation():
            raise GenerationError(GenerationErrorCode.transient, "boom")

        with patch.object(retry.time, "sleep"):
            with self.assertRaises(GenerationError):
                retry.run_with_retry(operation, on_attempt=attempts.append)

        self.assertEqual(attempts, list(range(1, retry.MAX_ATTEMPTS + 1)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `pytest test/services/test_content_retry.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.content.retry'`.

- [ ] **Step 3: Implementar a taxonomia de erro**

Crie `app/services/content/errors.py`:

```python
from enum import Enum


class GenerationErrorCode(str, Enum):
    rate_limit = "rate_limit"
    transient = "transient"
    timeout = "timeout"
    invalid_credentials = "invalid_credentials"
    invalid_params = "invalid_params"
    content_policy = "content_policy"
    unsupported_capability = "unsupported_capability"
    no_compatible_model = "no_compatible_model"
    unknown = "unknown"


# Retrying only helps when the failure is about the moment, not the request.
# A bad credential or a rejected prompt fails identically on every attempt, so
# retrying it just burns time and, on paid endpoints, money.
RETRYABLE_ERROR_CODES = frozenset(
    {
        GenerationErrorCode.rate_limit,
        GenerationErrorCode.transient,
        GenerationErrorCode.timeout,
    }
)


class GenerationError(Exception):
    """A provider call failed, classified into the canonical taxonomy."""

    def __init__(self, code: GenerationErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def is_retryable(code: GenerationErrorCode) -> bool:
    return code in RETRYABLE_ERROR_CODES


def classify_http_status(status_code: int) -> GenerationErrorCode:
    if status_code == 429:
        return GenerationErrorCode.rate_limit
    if status_code >= 500:
        return GenerationErrorCode.transient
    if status_code in (401, 403):
        return GenerationErrorCode.invalid_credentials
    if status_code in (400, 404, 422):
        return GenerationErrorCode.invalid_params
    return GenerationErrorCode.unknown
```

- [ ] **Step 4: Implementar a Retry Policy**

Crie `app/services/content/retry.py`:

```python
import random
import time
from typing import Callable, Optional, TypeVar

from loguru import logger

from app.services.content.errors import GenerationError, is_retryable

T = TypeVar("T")

# Tuned for paid provider endpoints: a short burst of retries absorbs rate
# limits and blips without keeping a worker thread parked for minutes. Not
# tenant-configurable in this phase — see the spec's Retry Policy section.
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0
MAX_BACKOFF_SECONDS = 30.0
JITTER_RATIO = 0.25


def backoff_delay(attempt: int, *, random_fn: Callable[[], float] = random.random) -> float:
    """Exponential backoff with jitter. `attempt` is 1-based."""
    raw = BACKOFF_BASE_SECONDS * (BACKOFF_MULTIPLIER ** max(attempt - 1, 0))
    capped = min(raw, MAX_BACKOFF_SECONDS)
    return capped * (1 + JITTER_RATIO * random_fn())


def run_with_retry(
    operation: Callable[[], T],
    *,
    on_attempt: Optional[Callable[[int], None]] = None,
) -> T:
    """Run `operation`, retrying only errors classified as retryable.

    Raises the last GenerationError when attempts run out, so the caller can
    decide whether to fall back to the next provider candidate.
    """
    last_error: Optional[GenerationError] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if on_attempt is not None:
            on_attempt(attempt)
        try:
            return operation()
        except GenerationError as error:
            last_error = error
            if not is_retryable(error.code):
                raise
            if attempt == MAX_ATTEMPTS:
                break
            delay = backoff_delay(attempt)
            logger.warning(
                f"generation attempt {attempt}/{MAX_ATTEMPTS} failed "
                f"({error.code.value}), retrying in {delay:.1f}s"
            )
            time.sleep(delay)

    raise last_error
```

- [ ] **Step 5: Rodar os testes e confirmar que passam**

Run: `pytest test/services/test_content_retry.py -v`
Expected: PASS (22 testes).

- [ ] **Step 6: Commit**

```bash
git add app/services/content/errors.py app/services/content/retry.py test/services/test_content_retry.py
git commit -m "feat(content): add generation error taxonomy and retry policy"
```

---

## Task 5: Regulated Content Policy Gate

**Files:**
- Create: `app/services/content/policy.py`
- Create: `test/services/test_content_policy.py`

**Interfaces:**
- Consumes: `ContentCategory`, `RiskLevel` (Task 1).
- Produces: `POLICY_VERSION` (str), `PolicyClassification` (dataclass com `risk_level`, `requires_human_review`, `policy_version`), `risk_for_category(category) -> RiskLevel`, `classify(category) -> PolicyClassification`.

- [ ] **Step 1: Escrever o teste que falha**

Crie `test/services/test_content_policy.py`:

```python
import unittest

from app.models.content import ContentCategory, RiskLevel
from app.services.content import policy


class TestRiskForCategory(unittest.TestCase):
    def test_none_category_is_no_risk(self):
        self.assertEqual(policy.risk_for_category(None), RiskLevel.none)

    def test_medical_is_high_risk(self):
        self.assertEqual(
            policy.risk_for_category(ContentCategory.medical), RiskLevel.high
        )

    def test_pharmaceutical_is_high_risk(self):
        self.assertEqual(
            policy.risk_for_category(ContentCategory.pharmaceutical), RiskLevel.high
        )

    def test_financial_is_medium_risk(self):
        self.assertEqual(
            policy.risk_for_category(ContentCategory.financial), RiskLevel.medium
        )

    def test_every_category_has_a_mapping(self):
        for category in ContentCategory:
            self.assertIsInstance(policy.risk_for_category(category), RiskLevel)

    def test_no_category_maps_to_none_risk(self):
        # `none` is reserved for "no declared category" so the absence of a
        # declaration stays distinguishable from a declared low-risk niche.
        for category in ContentCategory:
            self.assertNotEqual(policy.risk_for_category(category), RiskLevel.none)


class TestClassify(unittest.TestCase):
    def test_high_risk_requires_human_review(self):
        result = policy.classify(ContentCategory.medical)

        self.assertEqual(result.risk_level, RiskLevel.high)
        self.assertTrue(result.requires_human_review)
        self.assertEqual(result.policy_version, policy.POLICY_VERSION)

    def test_medium_risk_does_not_require_human_review(self):
        result = policy.classify(ContentCategory.financial)

        self.assertEqual(result.risk_level, RiskLevel.medium)
        self.assertFalse(result.requires_human_review)

    def test_absent_category_is_inert(self):
        result = policy.classify(None)

        self.assertEqual(result.risk_level, RiskLevel.none)
        self.assertFalse(result.requires_human_review)
        self.assertEqual(result.policy_version, policy.POLICY_VERSION)

    def test_is_deterministic(self):
        self.assertEqual(
            policy.classify(ContentCategory.gambling),
            policy.classify(ContentCategory.gambling),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `pytest test/services/test_content_policy.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.services.content.policy'`.

- [ ] **Step 3: Implementar o Policy Gate**

Crie `app/services/content/policy.py`:

```python
from dataclasses import dataclass
from typing import Optional

from app.models.content import ContentCategory, RiskLevel

# Bump this whenever _CATEGORY_RISK changes. Pieces keep the version they were
# classified under, so an updated table never silently reclassifies history.
POLICY_VERSION = "v1"

# Static, deterministic, no external call and no AI. Risk here reflects how
# tightly the niche is regulated in advertising, not the quality of any
# specific piece — classification, never enforcement.
_CATEGORY_RISK: dict[ContentCategory, RiskLevel] = {
    ContentCategory.medical: RiskLevel.high,
    ContentCategory.pharmaceutical: RiskLevel.high,
    ContentCategory.gambling: RiskLevel.high,
    ContentCategory.political: RiskLevel.high,
    ContentCategory.financial: RiskLevel.medium,
    ContentCategory.insurance: RiskLevel.medium,
    ContentCategory.legal: RiskLevel.medium,
    ContentCategory.alcohol: RiskLevel.medium,
    ContentCategory.regulated_product: RiskLevel.medium,
}


@dataclass(frozen=True)
class PolicyClassification:
    risk_level: RiskLevel
    requires_human_review: bool
    policy_version: str


def risk_for_category(category: Optional[ContentCategory]) -> RiskLevel:
    if category is None:
        return RiskLevel.none
    return _CATEGORY_RISK.get(category, RiskLevel.medium)


def classify(category: Optional[ContentCategory]) -> PolicyClassification:
    """Derive the policy fields persisted on a ContentPiece at creation time.

    This phase records only. Nothing here blocks generation, upload or
    publishing — `requires_human_review` exists so a future policy engine can
    read it without a migration.
    """
    risk = risk_for_category(category)
    return PolicyClassification(
        risk_level=risk,
        requires_human_review=risk == RiskLevel.high,
        policy_version=POLICY_VERSION,
    )
```

Nota sobre o fallback `RiskLevel.medium` em `risk_for_category`: uma categoria nova adicionada ao enum sem entrada no mapa cai em `medium`, não em `none` — o padrão seguro é tratar o desconhecido como regulado, não como irrestrito.

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pytest test/services/test_content_policy.py -v`
Expected: PASS (10 testes).

- [ ] **Step 5: Commit**

```bash
git add app/services/content/policy.py test/services/test_content_policy.py
git commit -m "feat(content): add regulated content policy classification"
```

---

## Task 6: Upload para Supabase Storage

**Files:**
- Create: `app/services/content/storage.py`
- Modify: `config.example.toml` (documentar as env vars)

**Interfaces:**
- Consumes: nada.
- Produces: `StorageError`, `UploadedObject` (dataclass com `url`, `storage_path`, `size_bytes`), `upload_bytes(*, tenant_id, content_piece_id, filename, data, content_type) -> UploadedObject`.

- [ ] **Step 1: Implementar o client de storage**

Crie `app/services/content/storage.py`:

```python
import os
from dataclasses import dataclass
from uuid import uuid4

import requests
from loguru import logger

_SUPABASE_URL_ENV = "SUPABASE_URL"
_SUPABASE_SERVICE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"
_BUCKET_ENV = "CONTENT_STORAGE_BUCKET"
_DEFAULT_BUCKET = "content-assets"

_UPLOAD_TIMEOUT = (30, 300)


class StorageError(RuntimeError):
    """Uploading a generated artifact to Supabase Storage failed."""


@dataclass(frozen=True)
class UploadedObject:
    url: str
    storage_path: str
    size_bytes: int


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise StorageError(f"{name} is not set")
    return value


def _bucket() -> str:
    return os.environ.get(_BUCKET_ENV) or _DEFAULT_BUCKET


def upload_bytes(
    *,
    tenant_id: int,
    content_piece_id: int,
    filename: str,
    data: bytes,
    content_type: str,
) -> UploadedObject:
    """Upload one generated artifact and return its public URL.

    The path is prefixed by tenant so a future storage-level policy can scope
    access per tenant without moving objects around.
    """
    base_url = _require_env(_SUPABASE_URL_ENV).rstrip("/")
    service_key = _require_env(_SUPABASE_SERVICE_KEY_ENV)
    bucket = _bucket()

    safe_name = os.path.basename(filename).replace(" ", "-")
    storage_path = f"{tenant_id}/{content_piece_id}/{uuid4().hex}-{safe_name}"
    endpoint = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"

    try:
        response = requests.post(
            endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {service_key}",
                "Content-Type": content_type,
                "x-upsert": "false",
            },
            timeout=_UPLOAD_TIMEOUT,
        )
    except requests.RequestException as exc:
        # The service key can appear in a request exception's string form.
        raise StorageError(
            f"storage upload request failed for {storage_path}"
        ) from exc

    if response.status_code >= 400:
        raise StorageError(
            f"storage upload rejected for {storage_path}: "
            f"status={response.status_code}"
        )

    public_url = f"{base_url}/storage/v1/object/public/{bucket}/{storage_path}"
    logger.info(f"uploaded generated asset to storage: path={storage_path}")
    return UploadedObject(
        url=public_url, storage_path=storage_path, size_bytes=len(data)
    )
```

- [ ] **Step 2: Documentar as variáveis de ambiente**

Adicione ao fim de `config.example.toml`:

```toml
# Content module — Supabase Storage for generated artifacts.
# These are secrets and must be set as environment variables, never here:
#   SUPABASE_URL=https://<project-ref>.supabase.co
#   SUPABASE_SERVICE_ROLE_KEY=<service role key>
#   CONTENT_STORAGE_BUCKET=content-assets   # optional, defaults to content-assets
```

- [ ] **Step 3: Criar o bucket no Supabase**

No painel do Supabase, em Storage, crie um bucket público chamado `content-assets` (ou o nome definido em `CONTENT_STORAGE_BUCKET`).

- [ ] **Step 4: Verificar upload real**

```bash
python3 -c "
from app.services.content import storage
result = storage.upload_bytes(
    tenant_id=0, content_piece_id=0, filename='smoke.txt',
    data=b'hello', content_type='text/plain',
)
print(result)
"
```
Expected: imprime um `UploadedObject` com `size_bytes=5` e uma URL acessível. Se falhar com `StorageError: SUPABASE_URL is not set`, exporte as variáveis primeiro.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/storage.py config.example.toml
git commit -m "feat(content): add supabase storage upload for generated assets"
```

---

## Task 7: Contrato de adapter + adapter WaveSpeed

**Files:**
- Create: `app/services/content/providers/__init__.py`
- Create: `app/services/content/providers/base.py`
- Create: `app/services/content/providers/wavespeed.py`

**Interfaces:**
- Consumes: `GenerationError`, `GenerationErrorCode`, `classify_http_status` (Task 4).
- Produces: `GeneratedAsset` (dataclass), `get_adapter(provider) -> module`, `generate(*, provider, kind, api_key, model_id, **params) -> GeneratedAsset`, `validate_credentials(*, provider, api_key) -> None`; e no módulo wavespeed: `generate_image(...)`, `generate_video(...)`, `validate_credentials(api_key)`.

**Contrato de timeout (vale para todos os adapters, Tasks 7-9):** toda função `generate_*` aceita `poll_timeout: Optional[float] = None` como parâmetro **nomeado explícito**, nunca via `**extra` — `**extra` é encaminhado ao payload do provider, e um campo desconhecido lá vira `invalid_params`. É esse parâmetro que permite ao orquestrador impor o timeout por `kind` sem precisar abandonar uma thread bloqueada.

- [ ] **Step 1: Criar o contrato base**

Crie `app/services/content/providers/base.py`:

```python
from dataclasses import dataclass, field
from typing import Optional

import requests

from app.services.content.errors import (
    GenerationError,
    GenerationErrorCode,
    classify_http_status,
)

# Providers that submit a job and poll for it need a ceiling; the orchestrator
# enforces a per-kind timeout above this, so this is only a safety net.
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_SUBMIT_TIMEOUT = (30, 60)
DEFAULT_DOWNLOAD_TIMEOUT = (30, 300)


@dataclass(frozen=True)
class GeneratedAsset:
    """One artifact returned by a provider, already downloaded into memory."""

    data: bytes
    mime_type: str
    filename: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    input_units: Optional[float] = None
    output_units: Optional[float] = None
    actual_cost: Optional[float] = None
    currency: Optional[str] = None
    raw_metadata: dict = field(default_factory=dict)


def raise_for_response(response: requests.Response, *, provider: str) -> None:
    """Translate an HTTP error response into the canonical taxonomy.

    Never include the response body verbatim in the message: provider errors
    sometimes echo the request, which can carry the API key.
    """
    if response.status_code < 400:
        return
    code = classify_http_status(response.status_code)
    raise GenerationError(
        code, f"{provider} request failed with status {response.status_code}"
    )


def wrap_request_exception(exc: Exception, *, provider: str) -> GenerationError:
    """Network-level failures are transient by definition."""
    if isinstance(exc, requests.exceptions.Timeout):
        return GenerationError(
            GenerationErrorCode.timeout, f"{provider} request timed out"
        )
    if isinstance(exc, requests.RequestException):
        return GenerationError(
            GenerationErrorCode.transient, f"{provider} request failed: {type(exc).__name__}"
        )
    return GenerationError(
        GenerationErrorCode.unknown, f"{provider} request raised {type(exc).__name__}"
    )


def download_asset(
    url: str, *, provider: str, filename: str, mime_type: str
) -> GeneratedAsset:
    try:
        response = requests.get(url, timeout=DEFAULT_DOWNLOAD_TIMEOUT)
    except Exception as exc:
        raise wrap_request_exception(exc, provider=provider) from exc

    raise_for_response(response, provider=provider)
    return GeneratedAsset(
        data=response.content,
        mime_type=response.headers.get("Content-Type", mime_type),
        filename=filename,
    )
```

- [ ] **Step 2: Implementar o adapter WaveSpeed**

Crie `app/services/content/providers/wavespeed.py`:

```python
import time
from typing import Any, Optional

import requests
from loguru import logger

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers.base import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_SUBMIT_TIMEOUT,
    GeneratedAsset,
    download_asset,
    raise_for_response,
    wrap_request_exception,
)

API_BASE_URL = "https://api.wavespeed.ai/api/v3"
_SUCCESS_STATUSES = frozenset({"completed", "succeeded"})
_FAILURE_STATUSES = frozenset({"failed", "cancelled", "timeout"})
_MAX_POLL_SECONDS = 900.0


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _submit(api_key: str, model_id: str, payload: dict) -> str:
    """Submit a prediction and return its id.

    A submission is never retried inside the adapter: the request may already
    have created a billable task upstream, and resending would double-charge.
    The retry policy above only re-runs whole attempts that failed before a
    task existed.
    """
    endpoint = f"{API_BASE_URL}/{model_id.strip('/')}"
    try:
        response = requests.post(
            endpoint, json=payload, headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="wavespeed") from exc

    raise_for_response(response, provider="wavespeed")
    body = response.json()
    prediction_id = (body.get("data") or {}).get("id")
    if not prediction_id:
        raise GenerationError(
            GenerationErrorCode.unknown, "wavespeed response has no prediction id"
        )
    return prediction_id


def _poll(api_key: str, prediction_id: str, poll_timeout: Optional[float] = None) -> dict:
    deadline = time.monotonic() + (poll_timeout or _MAX_POLL_SECONDS)
    endpoint = f"{API_BASE_URL}/predictions/{prediction_id}/result"

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                endpoint, headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
            )
        except Exception as exc:
            raise wrap_request_exception(exc, provider="wavespeed") from exc

        raise_for_response(response, provider="wavespeed")
        data = response.json().get("data") or {}
        status = str(data.get("status", "")).lower()

        if status in _SUCCESS_STATUSES:
            return data
        if status in _FAILURE_STATUSES:
            raise GenerationError(
                GenerationErrorCode.content_policy
                if "policy" in str(data.get("error", "")).lower()
                else GenerationErrorCode.unknown,
                f"wavespeed prediction {prediction_id} ended as {status}",
            )
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

    raise GenerationError(
        GenerationErrorCode.timeout,
        f"wavespeed prediction {prediction_id} did not finish in time",
    )


def _first_output_url(data: dict) -> str:
    outputs = data.get("outputs") or []
    if not outputs:
        raise GenerationError(
            GenerationErrorCode.unknown, "wavespeed prediction returned no outputs"
        )
    return outputs[0]


def generate_image(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    aspect_ratio: Optional[str] = None,
    source_image_url: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    payload: dict = {"prompt": prompt}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if source_image_url:
        payload["image"] = source_image_url
    payload.update(extra)

    logger.info(f"generating image on wavespeed: model={model_id}")
    prediction_id = _submit(api_key, model_id, payload)
    data = _poll(api_key, prediction_id, poll_timeout)
    asset = download_asset(
        _first_output_url(data),
        provider="wavespeed",
        filename=f"{prediction_id}.png",
        mime_type="image/png",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        output_units=1,
        raw_metadata={"prediction_id": prediction_id},
    )


def generate_video(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    source_image_url: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    duration: Optional[int] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    payload: dict = {"prompt": prompt}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if duration:
        payload["duration"] = int(duration)
    if source_image_url:
        payload["image"] = source_image_url
    payload.update(extra)

    logger.info(f"generating video on wavespeed: model={model_id}")
    prediction_id = _submit(api_key, model_id, payload)
    data = _poll(api_key, prediction_id, poll_timeout)
    asset = download_asset(
        _first_output_url(data),
        provider="wavespeed",
        filename=f"{prediction_id}.mp4",
        mime_type="video/mp4",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        duration=float(duration) if duration else None,
        output_units=float(duration) if duration else None,
        raw_metadata={"prediction_id": prediction_id},
    )


def validate_credentials(api_key: str) -> None:
    """Cheap authenticated call, used when a tenant registers the provider."""
    try:
        response = requests.get(
            f"{API_BASE_URL}/balance",
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="wavespeed") from exc

    if response.status_code in (401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials, "wavespeed rejected the API key"
        )
```

- [ ] **Step 3: Criar o registry de adapters**

Crie `app/services/content/providers/__init__.py`:

```python
from types import ModuleType
from typing import Any

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers import wavespeed
from app.services.content.providers.base import GeneratedAsset

_ADAPTERS: dict[str, ModuleType] = {
    "wavespeed": wavespeed,
}

_KIND_TO_FUNCTION = {
    "image": "generate_image",
    "video": "generate_video",
    "voice": "generate_voice",
}


def get_adapter(provider: str) -> ModuleType:
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise GenerationError(
            GenerationErrorCode.unsupported_capability,
            f"no adapter registered for provider {provider!r}",
        )
    return adapter


def generate(
    *, provider: str, kind: str, api_key: str, model_id: str, **params: Any
) -> GeneratedAsset:
    adapter = get_adapter(provider)
    function_name = _KIND_TO_FUNCTION.get(kind)
    function = getattr(adapter, function_name, None) if function_name else None
    if function is None:
        raise GenerationError(
            GenerationErrorCode.unsupported_capability,
            f"provider {provider!r} does not support kind {kind!r}",
        )
    return function(api_key=api_key, model_id=model_id, **params)


def validate_credentials(*, provider: str, api_key: str) -> None:
    adapter = get_adapter(provider)
    validator = getattr(adapter, "validate_credentials", None)
    if validator is None:
        return
    validator(api_key)
```

- [ ] **Step 4: Verificar que o registry resolve**

```bash
python3 -c "
from app.services.content import providers
print(providers.get_adapter('wavespeed').__name__)
try:
    providers.generate(provider='wavespeed', kind='voice', api_key='x', model_id='y', text='z')
except Exception as exc:
    print(type(exc).__name__, exc)
"
```
Expected: imprime `app.services.content.providers.wavespeed` e depois `GenerationError provider 'wavespeed' does not support kind 'voice'`.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/providers/
git commit -m "feat(content): add provider adapter contract and wavespeed adapter"
```

---

## Task 8: Adapters fal.ai e Gemini

**Files:**
- Create: `app/services/content/providers/falai.py`
- Create: `app/services/content/providers/gemini.py`
- Modify: `app/services/content/providers/__init__.py`

**Interfaces:**
- Consumes: `GeneratedAsset`, `download_asset`, `raise_for_response`, `wrap_request_exception` (Task 7).
- Produces: `falai.generate_image/generate_video/validate_credentials`, `gemini.generate_image/generate_video/validate_credentials`, ambos registrados em `_ADAPTERS`.

- [ ] **Step 1: Implementar o adapter fal.ai**

Crie `app/services/content/providers/falai.py`:

```python
import time
from typing import Any, Optional

import requests
from loguru import logger

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers.base import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_SUBMIT_TIMEOUT,
    GeneratedAsset,
    download_asset,
    raise_for_response,
    wrap_request_exception,
)

QUEUE_BASE_URL = "https://queue.fal.run"
_MAX_POLL_SECONDS = 900.0


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Key {api_key}"}


def _submit(api_key: str, model_id: str, payload: dict) -> tuple[str, str]:
    """Submit to the fal queue; returns (status_url, response_url)."""
    try:
        response = requests.post(
            f"{QUEUE_BASE_URL}/{model_id.strip('/')}",
            json=payload,
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="falai") from exc

    raise_for_response(response, provider="falai")
    body = response.json()
    status_url = body.get("status_url")
    response_url = body.get("response_url")
    if not status_url or not response_url:
        raise GenerationError(
            GenerationErrorCode.unknown, "falai response is missing queue urls"
        )
    return status_url, response_url


def _poll(
    api_key: str,
    status_url: str,
    response_url: str,
    poll_timeout: Optional[float] = None,
) -> dict:
    deadline = time.monotonic() + (poll_timeout or _MAX_POLL_SECONDS)

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                status_url, headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
            )
        except Exception as exc:
            raise wrap_request_exception(exc, provider="falai") from exc

        raise_for_response(response, provider="falai")
        status = str(response.json().get("status", "")).upper()

        if status == "COMPLETED":
            try:
                result = requests.get(
                    response_url,
                    headers=_headers(api_key),
                    timeout=DEFAULT_SUBMIT_TIMEOUT,
                )
            except Exception as exc:
                raise wrap_request_exception(exc, provider="falai") from exc
            raise_for_response(result, provider="falai")
            return result.json()
        if status in ("FAILED", "CANCELLED"):
            raise GenerationError(
                GenerationErrorCode.unknown, f"falai request ended as {status}"
            )
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

    raise GenerationError(
        GenerationErrorCode.timeout, "falai request did not finish in time"
    )


def _extract_url(result: dict, key: str) -> str:
    node = result.get(key)
    if isinstance(node, dict) and node.get("url"):
        return node["url"]
    if isinstance(node, list) and node and isinstance(node[0], dict):
        url = node[0].get("url")
        if url:
            return url
    raise GenerationError(
        GenerationErrorCode.unknown, f"falai result has no {key} url"
    )


def generate_image(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    aspect_ratio: Optional[str] = None,
    source_image_url: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    payload: dict = {"prompt": prompt}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if source_image_url:
        payload["image_url"] = source_image_url
    payload.update(extra)

    logger.info(f"generating image on falai: model={model_id}")
    status_url, response_url = _submit(api_key, model_id, payload)
    result = _poll(api_key, status_url, response_url, poll_timeout)
    asset = download_asset(
        _extract_url(result, "images"),
        provider="falai",
        filename="falai-image.png",
        mime_type="image/png",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        output_units=1,
        raw_metadata={"seed": result.get("seed")},
    )


def generate_video(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    source_image_url: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    duration: Optional[int] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    payload: dict = {"prompt": prompt}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if duration:
        payload["duration"] = str(int(duration))
    if source_image_url:
        payload["image_url"] = source_image_url
    payload.update(extra)

    logger.info(f"generating video on falai: model={model_id}")
    status_url, response_url = _submit(api_key, model_id, payload)
    result = _poll(api_key, status_url, response_url, poll_timeout)
    asset = download_asset(
        _extract_url(result, "video"),
        provider="falai",
        filename="falai-video.mp4",
        mime_type="video/mp4",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        duration=float(duration) if duration else None,
        output_units=float(duration) if duration else None,
        raw_metadata={"seed": result.get("seed")},
    )


def validate_credentials(api_key: str) -> None:
    try:
        response = requests.get(
            "https://rest.alpha.fal.ai/tokens/",
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="falai") from exc

    if response.status_code in (401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials, "falai rejected the API key"
        )
```

- [ ] **Step 2: Implementar o adapter Gemini**

Crie `app/services/content/providers/gemini.py`:

```python
import base64
import time
from typing import Any, Optional

import requests
from loguru import logger

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers.base import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_SUBMIT_TIMEOUT,
    GeneratedAsset,
    raise_for_response,
    wrap_request_exception,
)

API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_MAX_POLL_SECONDS = 900.0


def _headers(api_key: str) -> dict:
    return {"x-goog-api-key": api_key, "Content-Type": "application/json"}


def _post(api_key: str, path: str, payload: dict) -> dict:
    try:
        response = requests.post(
            f"{API_BASE_URL}/{path}",
            json=payload,
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="gemini") from exc

    raise_for_response(response, provider="gemini")
    return response.json()


def generate_image(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    aspect_ratio: Optional[str] = None,
    source_image_url: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    parts: list[dict] = [{"text": prompt}]
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    if aspect_ratio:
        payload["generationConfig"]["imageConfig"] = {"aspectRatio": aspect_ratio}

    logger.info(f"generating image on gemini: model={model_id}")
    body = _post(api_key, f"models/{model_id}:generateContent", payload)

    candidates = body.get("candidates") or []
    for candidate in candidates:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return GeneratedAsset(
                    data=base64.b64decode(inline["data"]),
                    mime_type=inline.get("mimeType", "image/png"),
                    filename="gemini-image.png",
                    output_units=1,
                )

    finish_reason = candidates[0].get("finishReason") if candidates else None
    if finish_reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
        raise GenerationError(
            GenerationErrorCode.content_policy,
            f"gemini refused the request: {finish_reason}",
        )
    raise GenerationError(
        GenerationErrorCode.unknown, "gemini response contains no image data"
    )


def generate_video(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    source_image_url: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    duration: Optional[int] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    instance: dict = {"prompt": prompt}
    if source_image_url:
        instance["image"] = {"gcsUri": source_image_url}

    parameters: dict = {}
    if aspect_ratio:
        parameters["aspectRatio"] = aspect_ratio
    if duration:
        parameters["durationSeconds"] = int(duration)

    logger.info(f"generating video on gemini: model={model_id}")
    operation = _post(
        api_key,
        f"models/{model_id}:predictLongRunning",
        {"instances": [instance], "parameters": parameters},
    )
    operation_name = operation.get("name")
    if not operation_name:
        raise GenerationError(
            GenerationErrorCode.unknown, "gemini response has no operation name"
        )

    deadline = time.monotonic() + (poll_timeout or _MAX_POLL_SECONDS)
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{API_BASE_URL}/{operation_name}",
                headers=_headers(api_key),
                timeout=DEFAULT_SUBMIT_TIMEOUT,
            )
        except Exception as exc:
            raise wrap_request_exception(exc, provider="gemini") from exc

        raise_for_response(response, provider="gemini")
        body = response.json()

        if body.get("done"):
            if body.get("error"):
                raise GenerationError(
                    GenerationErrorCode.unknown,
                    f"gemini operation failed with code {body['error'].get('code')}",
                )
            samples = (
                (body.get("response") or {}).get("generateVideoResponse", {})
            ).get("generatedSamples") or []
            for sample in samples:
                encoded = (sample.get("video") or {}).get("bytesBase64Encoded")
                if encoded:
                    return GeneratedAsset(
                        data=base64.b64decode(encoded),
                        mime_type="video/mp4",
                        filename="gemini-video.mp4",
                        duration=float(duration) if duration else None,
                        output_units=float(duration) if duration else None,
                    )
            raise GenerationError(
                GenerationErrorCode.unknown, "gemini operation returned no video data"
            )
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

    raise GenerationError(
        GenerationErrorCode.timeout, "gemini operation did not finish in time"
    )


def validate_credentials(api_key: str) -> None:
    try:
        response = requests.get(
            f"{API_BASE_URL}/models", headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="gemini") from exc

    if response.status_code in (400, 401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials, "gemini rejected the API key"
        )
```

- [ ] **Step 3: Registrar os adapters**

Em `app/services/content/providers/__init__.py`, atualize o import e o dicionário:

```python
from app.services.content.providers import falai, gemini, wavespeed

_ADAPTERS: dict[str, ModuleType] = {
    "wavespeed": wavespeed,
    "falai": falai,
    "gemini": gemini,
}
```

- [ ] **Step 4: Verificar que os adapters resolvem**

```bash
python3 -c "
from app.services.content import providers
for name in ('wavespeed', 'falai', 'gemini'):
    adapter = providers.get_adapter(name)
    print(name, hasattr(adapter, 'generate_image'), hasattr(adapter, 'generate_video'))
"
```
Expected: três linhas com `True True`.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/providers/
git commit -m "feat(content): add falai and gemini generation adapters"
```

---

## Task 9: Adapter ElevenLabs (voz)

**Files:**
- Create: `app/services/content/providers/elevenlabs.py`
- Modify: `app/services/content/providers/__init__.py`

**Interfaces:**
- Consumes: `GeneratedAsset`, `raise_for_response`, `wrap_request_exception` (Task 7).
- Produces: `elevenlabs.generate_voice(*, api_key, model_id, text, voice_id, **extra) -> GeneratedAsset`, `elevenlabs.validate_credentials(api_key)`.

- [ ] **Step 1: Implementar o adapter**

Crie `app/services/content/providers/elevenlabs.py`:

```python
from typing import Any, Optional

import requests
from loguru import logger

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers.base import (
    DEFAULT_DOWNLOAD_TIMEOUT,
    DEFAULT_SUBMIT_TIMEOUT,
    GeneratedAsset,
    raise_for_response,
    wrap_request_exception,
)

API_BASE_URL = "https://api.elevenlabs.io/v1"


def _headers(api_key: str) -> dict:
    return {"xi-api-key": api_key, "Content-Type": "application/json"}


def generate_voice(
    *,
    api_key: str,
    model_id: str,
    text: str,
    voice_id: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    """Text-to-speech. Synchronous — ElevenLabs streams the audio back.

    `poll_timeout` is accepted for interface parity with the polling providers
    and used as the read timeout; there is no queue to poll here.
    """
    if not voice_id:
        raise GenerationError(
            GenerationErrorCode.invalid_params,
            "elevenlabs requires a voice_id",
        )

    payload: dict = {"text": text, "model_id": model_id}
    voice_settings = extra.get("voice_settings")
    if voice_settings:
        payload["voice_settings"] = voice_settings

    logger.info(f"generating voice on elevenlabs: model={model_id}")
    try:
        response = requests.post(
            f"{API_BASE_URL}/text-to-speech/{voice_id}",
            json=payload,
            headers=_headers(api_key),
            timeout=(30, poll_timeout or DEFAULT_DOWNLOAD_TIMEOUT[1]),
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="elevenlabs") from exc

    raise_for_response(response, provider="elevenlabs")
    return GeneratedAsset(
        data=response.content,
        mime_type=response.headers.get("Content-Type", "audio/mpeg"),
        filename=f"{voice_id}.mp3",
        input_units=float(len(text)),
        raw_metadata={"voice_id": voice_id},
    )


def validate_credentials(api_key: str) -> None:
    try:
        response = requests.get(
            f"{API_BASE_URL}/user",
            headers={"xi-api-key": api_key},
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="elevenlabs") from exc

    if response.status_code in (401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials,
            "elevenlabs rejected the API key",
        )
```

- [ ] **Step 2: Registrar o adapter**

Em `app/services/content/providers/__init__.py`:

```python
from app.services.content.providers import elevenlabs, falai, gemini, wavespeed

_ADAPTERS: dict[str, ModuleType] = {
    "wavespeed": wavespeed,
    "falai": falai,
    "gemini": gemini,
    "elevenlabs": elevenlabs,
}
```

- [ ] **Step 3: Verificar**

```bash
python3 -c "
from app.services.content import providers
adapter = providers.get_adapter('elevenlabs')
print(hasattr(adapter, 'generate_voice'), hasattr(adapter, 'generate_image'))
"
```
Expected: `True False`.

- [ ] **Step 4: Commit**

```bash
git add app/services/content/providers/
git commit -m "feat(content): add elevenlabs voice adapter"
```

---

## Task 10: CRUD de provedores por tenant

**Files:**
- Create: `app/services/content/generation_providers.py`
- Create: `app/controllers/v1/content/providers.py`
- Modify: `app/router.py`

**Interfaces:**
- Consumes: `ContentGenerationProvider`, `GenerationProviderCreate/Read` (Task 1); `encrypt_credentials` (existente); `providers.validate_credentials` (Task 7-9).
- Produces: `create_generation_provider(session, *, tenant_id, kind, provider, credentials, config, priority) -> ContentGenerationProvider`, `list_generation_providers(session, *, tenant_id, kind=None) -> list`, `get_generation_provider(session, *, tenant_id, provider_id) -> Optional`, `deactivate_generation_provider(session, *, tenant_id, provider_id) -> Optional`, `decrypt_provider_credentials(row) -> str`.

- [ ] **Step 1: Implementar o service**

Crie `app/services/content/generation_providers.py`:

```python
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content_generation import (
    ContentGenerationProvider,
    GenerationKind,
    GenerationProviderName,
)
from app.services.content.crypto import decrypt_credentials, encrypt_credentials


def create_generation_provider(
    session: Session,
    *,
    tenant_id: int,
    kind: GenerationKind,
    provider: GenerationProviderName,
    credentials: str,
    config: Optional[dict] = None,
    priority: int = 0,
) -> ContentGenerationProvider:
    row = ContentGenerationProvider(
        tenant_id=tenant_id,
        kind=kind,
        provider=provider,
        credentials_encrypted=encrypt_credentials(credentials),
        config=config or {},
        priority=priority,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_generation_providers(
    session: Session, *, tenant_id: int, kind: Optional[GenerationKind] = None
) -> List[ContentGenerationProvider]:
    statement = select(ContentGenerationProvider).where(
        ContentGenerationProvider.tenant_id == tenant_id
    )
    if kind is not None:
        statement = statement.where(ContentGenerationProvider.kind == kind)
    return list(session.exec(statement).all())


def get_generation_provider(
    session: Session, *, tenant_id: int, provider_id: int
) -> Optional[ContentGenerationProvider]:
    return session.exec(
        select(ContentGenerationProvider).where(
            ContentGenerationProvider.id == provider_id,
            ContentGenerationProvider.tenant_id == tenant_id,
        )
    ).first()


def deactivate_generation_provider(
    session: Session, *, tenant_id: int, provider_id: int
) -> Optional[ContentGenerationProvider]:
    """Soft delete: jobs already executed reference this row's provider name."""
    row = get_generation_provider(
        session, tenant_id=tenant_id, provider_id=provider_id
    )
    if row is None:
        return None
    row.is_active = False
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def has_active_provider(
    session: Session, *, tenant_id: int, kind: GenerationKind
) -> bool:
    return bool(
        session.exec(
            select(ContentGenerationProvider).where(
                ContentGenerationProvider.tenant_id == tenant_id,
                ContentGenerationProvider.kind == kind,
                ContentGenerationProvider.is_active == True,  # noqa: E712
            )
        ).first()
    )


def decrypt_provider_credentials(row: ContentGenerationProvider) -> str:
    return decrypt_credentials(row.credentials_encrypted)
```

- [ ] **Step 2: Implementar o controller**

Crie `app/controllers/v1/content/providers.py`:

```python
from typing import Optional

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentTenant
from app.models.content_generation import (
    GenerationKind,
    GenerationProviderCreate,
    GenerationProviderRead,
)
from app.services.content import audit
from app.services.content import generation_providers as providers_service
from app.services.content import providers as provider_adapters
from app.services.content.errors import GenerationError

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/providers", response_model=GenerationProviderRead, status_code=201)
def create_provider(
    payload: GenerationProviderCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    # Validate before persisting: a bad key should fail at registration time,
    # not silently at the tenant's first paid generation.
    try:
        provider_adapters.validate_credentials(
            provider=payload.provider.value, api_key=payload.credentials
        )
    except GenerationError as error:
        raise HTTPException(status_code=422, detail=error.message)

    row = providers_service.create_generation_provider(
        session,
        tenant_id=tenant.id,
        kind=payload.kind,
        provider=payload.provider,
        credentials=payload.credentials,
        config=payload.config,
        priority=payload.priority,
    )
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return row


@router.get("/content/providers", response_model=list[GenerationProviderRead])
def list_providers(
    kind: Optional[GenerationKind] = None,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return providers_service.list_generation_providers(
        session, tenant_id=tenant.id, kind=kind
    )


@router.delete("/content/providers/{provider_id}", response_model=GenerationProviderRead)
def deactivate_provider(
    provider_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    row = providers_service.deactivate_generation_provider(
        session, tenant_id=tenant.id, provider_id=provider_id
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Generation provider not found")
    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="generation_provider",
        entity_id=row.id,
        action="deactivated",
        actor=f"tenant:{tenant.id}",
    )
    return row
```

- [ ] **Step 3: Registrar o router**

Em `app/router.py`, adicione `providers` aos imports de `app.controllers.v1.content` e:

```python
root_api_router.include_router(providers.router)
```

- [ ] **Step 4: Verificar as rotas**

```bash
python3 -c "
from app.asgi import app
print(sorted({r.path for r in app.routes if 'providers' in r.path}))
"
```
Expected: `['/api/v1/content/providers', '/api/v1/content/providers/{provider_id}']`.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/generation_providers.py app/controllers/v1/content/providers.py app/router.py
git commit -m "feat(content): add per-tenant generation provider crud"
```

---

## Task 11: CRUD de avatares

**Files:**
- Create: `app/services/content/avatars.py`
- Create: `app/controllers/v1/content/avatars.py`
- Modify: `app/router.py`

**Interfaces:**
- Consumes: `ContentAvatar`, `AvatarCreate/Read` (Task 1); `get_client` (existente em `app/services/content/clients.py`).
- Produces: `create_avatar(session, *, tenant_id, client_id, name, reference_image_url, voice_provider, voice_id) -> Optional[ContentAvatar]`, `list_avatars(session, *, tenant_id, client_id) -> list`, `get_avatar(session, *, tenant_id, avatar_id) -> Optional[ContentAvatar]`.

- [ ] **Step 1: Implementar o service**

Crie `app/services/content/avatars.py`:

```python
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentClient
from app.models.content_generation import ContentAvatar
from app.services.content.clients import get_client


def create_avatar(
    session: Session,
    *,
    tenant_id: int,
    client_id: int,
    name: str,
    reference_image_url: str,
    voice_provider: Optional[str] = None,
    voice_id: Optional[str] = None,
) -> Optional[ContentAvatar]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return None
    avatar = ContentAvatar(
        client_id=client_id,
        name=name,
        reference_image_url=reference_image_url,
        voice_provider=voice_provider,
        voice_id=voice_id,
    )
    session.add(avatar)
    session.commit()
    session.refresh(avatar)
    return avatar


def list_avatars(
    session: Session, *, tenant_id: int, client_id: int
) -> List[ContentAvatar]:
    if get_client(session, tenant_id=tenant_id, client_id=client_id) is None:
        return []
    return list(
        session.exec(
            select(ContentAvatar).where(ContentAvatar.client_id == client_id)
        ).all()
    )


def get_avatar(
    session: Session, *, tenant_id: int, avatar_id: int
) -> Optional[ContentAvatar]:
    """Tenant-scoped lookup: an avatar of another tenant must read as absent."""
    return session.exec(
        select(ContentAvatar)
        .join(ContentClient, ContentClient.id == ContentAvatar.client_id)
        .where(ContentAvatar.id == avatar_id, ContentClient.tenant_id == tenant_id)
    ).first()
```

- [ ] **Step 2: Implementar o controller**

Crie `app/controllers/v1/content/avatars.py`:

```python
from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import ContentTenant
from app.models.content_generation import AvatarCreate, AvatarRead
from app.services.content import audit
from app.services.content import avatars as avatars_service

router = new_router(dependencies=[Depends(content_auth.verify_tenant_token)])


@router.post("/content/avatars", response_model=AvatarRead, status_code=201)
def create_avatar(
    payload: AvatarCreate,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    avatar = avatars_service.create_avatar(
        session,
        tenant_id=tenant.id,
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
        tenant_id=tenant.id,
        entity_type="avatar",
        entity_id=avatar.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return avatar


@router.get("/content/clients/{client_id}/avatars", response_model=list[AvatarRead])
def list_avatars(
    client_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    return avatars_service.list_avatars(
        session, tenant_id=tenant.id, client_id=client_id
    )


@router.get("/content/avatars/{avatar_id}", response_model=AvatarRead)
def get_avatar(
    avatar_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    avatar = avatars_service.get_avatar(
        session, tenant_id=tenant.id, avatar_id=avatar_id
    )
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    return avatar
```

- [ ] **Step 3: Registrar o router**

Em `app/router.py`, adicione `avatars` aos imports e:

```python
root_api_router.include_router(avatars.router)
```

- [ ] **Step 4: Verificar as rotas**

```bash
python3 -c "
from app.asgi import app
print(sorted({r.path for r in app.routes if 'avatar' in r.path}))
"
```
Expected: `['/api/v1/content/avatars', '/api/v1/content/avatars/{avatar_id}', '/api/v1/content/clients/{client_id}/avatars']`.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/avatars.py app/controllers/v1/content/avatars.py app/router.py
git commit -m "feat(content): add avatar crud"
```

---

## Task 12: Normalização de aspect ratio

**Files:**
- Create: `app/services/content/image_ops.py`
- Modify: `requirements.txt`, `pyproject.toml`

**Interfaces:**
- Consumes: nada.
- Produces: `RATIO_FRACTIONS` (dict), `CROP_TOLERANCE` (float), `parse_ratio(ratio) -> Optional[float]`, `normalize_to_ratio(data, target_ratio) -> tuple[bytes, int, int]`.

- [ ] **Step 1: Declarar Pillow como dependência direta**

Pillow já chega ao ambiente como dependência transitiva de `moviepy`, mas este módulo o usa diretamente — declare-o para que uma futura mudança no moviepy não quebre o build silenciosamente.

Em `requirements.txt`, adicione (mantendo a ordem alfabética das linhas ao redor):
```
pillow==11.3.0
```

Em `pyproject.toml`, na lista `dependencies`, adicione:
```
    "pillow==11.3.0",
```

- [ ] **Step 2: Implementar a normalização**

Crie `app/services/content/image_ops.py`:

```python
import io
from typing import Optional

from loguru import logger
from PIL import Image

# Ratios the catalog can request. Values are width / height.
RATIO_FRACTIONS: dict[str, float] = {
    "9:16": 9 / 16,
    "16:9": 16 / 9,
    "1:1": 1.0,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
}

# Above this much cropping the subject (usually a face) starts leaving the
# frame, so pad instead of cutting.
CROP_TOLERANCE = 0.15

_PAD_COLOR = (18, 18, 18)


def parse_ratio(ratio: Optional[str]) -> Optional[float]:
    if not ratio:
        return None
    known = RATIO_FRACTIONS.get(ratio)
    if known is not None:
        return known
    if ":" in ratio:
        width, _, height = ratio.partition(":")
        try:
            return float(width) / float(height)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


def normalize_to_ratio(data: bytes, target_ratio: Optional[str]) -> tuple[bytes, int, int]:
    """Reshape an image to `target_ratio` without distorting it.

    An avatar's reference image is registered once and reused across output
    formats, so a 1:1 portrait feeding a 9:16 video is the common case. Sending
    it raw makes image-to-video providers stretch or reject the frame. Small
    mismatches are center-cropped; larger ones are padded, which keeps the
    subject intact at the cost of neutral bars.

    Returns (image_bytes, width, height). Input is returned untouched when the
    ratio already matches or cannot be parsed.
    """
    target = parse_ratio(target_ratio)
    if target is None:
        return data, 0, 0

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        width, height = image.size
        current = width / height

        if abs(current - target) < 0.01:
            return data, width, height

        crop_loss = abs(current - target) / max(current, target)

        if crop_loss <= CROP_TOLERANCE:
            if current > target:
                new_width = int(round(height * target))
                left = (width - new_width) // 2
                box = (left, 0, left + new_width, height)
            else:
                new_height = int(round(width / target))
                top = (height - new_height) // 2
                box = (0, top, width, top + new_height)
            result = image.crop(box)
            logger.info(
                f"normalized base image by cropping to {target_ratio}: "
                f"{width}x{height} -> {result.size[0]}x{result.size[1]}"
            )
        else:
            if current > target:
                canvas_width, canvas_height = width, int(round(width / target))
            else:
                canvas_width, canvas_height = int(round(height * target)), height
            result = Image.new("RGB", (canvas_width, canvas_height), _PAD_COLOR)
            result.paste(
                image,
                ((canvas_width - width) // 2, (canvas_height - height) // 2),
            )
            logger.info(
                f"normalized base image by padding to {target_ratio}: "
                f"{width}x{height} -> {canvas_width}x{canvas_height}"
            )

        buffer = io.BytesIO()
        result.save(buffer, format="PNG")
        return buffer.getvalue(), result.size[0], result.size[1]
```

- [ ] **Step 3: Verificar o comportamento**

Os três casos abaixo exercitam os três caminhos: pad (diferença grande), crop (diferença dentro da tolerância) e passagem direta (ratio já correto).

```bash
python3 -c "
import io
from PIL import Image
from app.services.content import image_ops

def encode(size):
    buffer = io.BytesIO()
    Image.new('RGB', size).save(buffer, format='PNG')
    return buffer.getvalue()

square = encode((1024, 1024))

data, w, h = image_ops.normalize_to_ratio(square, '9:16')
print('1024x1024 -> 9:16 (pad):', w, h, round(w/h, 3))

data, w, h = image_ops.normalize_to_ratio(encode((1000, 1100)), '1:1')
print('1000x1100 -> 1:1 (crop):', w, h, round(w/h, 3))

data, w, h = image_ops.normalize_to_ratio(square, '1:1')
print('1024x1024 -> 1:1 (unchanged):', w, h, data is square)
"
```
Expected:
```
1024x1024 -> 9:16 (pad): 1024 1820 0.563
1000x1100 -> 1:1 (crop): 1000 1000 1.0
1024x1024 -> 1:1 (unchanged): 1024 1024 True
```

O `True` na última linha importa: o caminho "já está no ratio certo" tem que devolver o **mesmo objeto** de bytes recebido, porque é assim que `_normalized_base_image` (Task 14) detecta que não há nada para reenviar ao Storage.

- [ ] **Step 4: Commit**

```bash
git add app/services/content/image_ops.py requirements.txt pyproject.toml
git commit -m "feat(content): add aspect ratio normalization for base images"
```

---

## Task 13: Persistência de jobs/assets e orquestrador

**Files:**
- Create: `app/services/content/jobs.py`
- Create: `app/services/content/assets.py`
- Create: `app/services/content/orchestrator.py`

**Interfaces:**
- Consumes: `ContentGenerationJob`, `ContentAsset`, `GenerationJobStatus`, `ContentAssetType` (Task 1); `select_candidates`, `GenerationRequirements` (Task 3); `run_with_retry`, `GenerationError`, `GenerationErrorCode` (Task 4); `upload_bytes`, `UploadedObject` (Task 6); `providers.generate` (Tasks 7-9); `get_generation_provider`, `decrypt_provider_credentials` (Task 10); `catalog.list_models` (Task 2).
- Produces:
  - `jobs.create_job(session, *, tenant_id, client_id, content_piece_id, kind, request_payload) -> ContentGenerationJob`
  - `jobs.mark_running(session, job) -> None`, `jobs.mark_completed(session, job, **fields) -> None`, `jobs.mark_failed(session, job, *, error_code, error_message, status=GenerationJobStatus.failed) -> None`
  - `jobs.list_jobs_for_piece(session, *, tenant_id, piece_id) -> list[ContentGenerationJob]`
  - `assets.create_asset(session, *, job, asset_type, uploaded, provider, model, mime_type, width, height, duration, is_intermediate) -> ContentAsset`
  - `orchestrator.estimate_cost(provider, model_id, *, units) -> tuple[Optional[float], Optional[str]]`
  - `orchestrator.run_job(session, *, job, requirements, params, asset_type, timeout_seconds=None, is_intermediate=False) -> Optional[ContentAsset]`

- [ ] **Step 1: Implementar a persistência de jobs**

Crie `app/services/content/jobs.py`:

```python
from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient, ContentPiece
from app.models.content_generation import (
    ContentGenerationJob,
    GenerationJobStatus,
    GenerationKind,
)


def create_job(
    session: Session,
    *,
    tenant_id: int,
    client_id: int,
    content_piece_id: int,
    kind: GenerationKind,
    request_payload: dict,
) -> ContentGenerationJob:
    job = ContentGenerationJob(
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=content_piece_id,
        kind=kind,
        status=GenerationJobStatus.queued,
        request_payload=request_payload,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def mark_running(session: Session, job: ContentGenerationJob) -> None:
    job.status = GenerationJobStatus.running
    job.started_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def mark_completed(
    session: Session,
    job: ContentGenerationJob,
    *,
    provider: str,
    model: str,
    response_metadata: Optional[dict] = None,
    input_units: Optional[float] = None,
    output_units: Optional[float] = None,
    estimated_cost: Optional[float] = None,
    actual_cost: Optional[float] = None,
    currency: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    job.status = GenerationJobStatus.completed
    job.provider = provider
    job.model = model
    job.response_metadata = response_metadata or {}
    job.input_units = input_units
    job.output_units = output_units
    job.estimated_cost = estimated_cost
    job.actual_cost = actual_cost
    job.currency = currency
    job.duration_ms = duration_ms
    job.completed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def mark_failed(
    session: Session,
    job: ContentGenerationJob,
    *,
    error_code: str,
    error_message: str,
    status: GenerationJobStatus = GenerationJobStatus.failed,
) -> None:
    job.status = status
    job.error_code = error_code
    job.error_message = error_message
    job.failed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def record_attempt(
    session: Session, job: ContentGenerationJob, *, attempt: int, provider: str, model: str
) -> None:
    job.attempt_count += 1
    if attempt > 1:
        job.retry_count += 1
        job.status = GenerationJobStatus.retrying
    job.provider = provider
    job.model = model
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


def is_still_running(session: Session, job_id: int) -> bool:
    """Guard against a late provider response overwriting a settled job.

    A result that arrives after the job timed out must be dropped, not written.
    """
    current = session.get(ContentGenerationJob, job_id)
    return current is not None and current.status in (
        GenerationJobStatus.running,
        GenerationJobStatus.retrying,
    )


def list_jobs_for_piece(
    session: Session, *, tenant_id: int, piece_id: int
) -> List[ContentGenerationJob]:
    return list(
        session.exec(
            select(ContentGenerationJob)
            .join(ContentPiece, ContentPiece.id == ContentGenerationJob.content_piece_id)
            .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
            .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
            .where(
                ContentGenerationJob.content_piece_id == piece_id,
                ContentClient.tenant_id == tenant_id,
            )
            .order_by(ContentGenerationJob.id)
        ).all()
    )
```

- [ ] **Step 2: Implementar a persistência de assets**

Crie `app/services/content/assets.py`:

```python
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content_generation import (
    ContentAsset,
    ContentAssetType,
    ContentGenerationJob,
)
from app.services.content.storage import UploadedObject


def create_asset(
    session: Session,
    *,
    job: ContentGenerationJob,
    asset_type: ContentAssetType,
    uploaded: UploadedObject,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    mime_type: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[float] = None,
    is_intermediate: bool = False,
) -> ContentAsset:
    asset = ContentAsset(
        tenant_id=job.tenant_id,
        client_id=job.client_id,
        content_piece_id=job.content_piece_id,
        generation_job_id=job.id,
        type=asset_type,
        url=uploaded.url,
        storage_path=uploaded.storage_path,
        mime_type=mime_type,
        size_bytes=uploaded.size_bytes,
        width=width or None,
        height=height or None,
        duration=duration,
        provider=provider,
        model=model,
        is_intermediate=is_intermediate,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def list_assets_for_piece(
    session: Session, *, content_piece_id: int
) -> List[ContentAsset]:
    return list(
        session.exec(
            select(ContentAsset)
            .where(ContentAsset.content_piece_id == content_piece_id)
            .order_by(ContentAsset.id)
        ).all()
    )
```

- [ ] **Step 3: Implementar o orquestrador**

Crie `app/services/content/orchestrator.py`:

```python
import time
from typing import Optional

from loguru import logger
from sqlmodel import Session

from app.models.content_generation import (
    ContentAsset,
    ContentAssetType,
    ContentGenerationJob,
    GenerationJobStatus,
)
from app.services.content import assets as assets_service
from app.services.content import jobs as jobs_service
from app.services.content import providers as provider_adapters
from app.services.content.capability import GenerationRequirements, select_candidates
from app.services.content.catalog import list_models
from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.generation_providers import (
    decrypt_provider_credentials,
    get_generation_provider,
)
from app.services.content.retry import run_with_retry
from app.services.content.storage import StorageError, upload_bytes


def estimate_cost(
    provider: str, model_id: str, *, units: Optional[float]
) -> tuple[Optional[float], Optional[str]]:
    """Estimate the spend of one generation from the catalog's cost_config."""
    if units is None:
        return None, None
    for entry in list_models(provider=provider):
        if entry.model_id != model_id:
            continue
        price = entry.cost_config.get("price")
        currency = entry.cost_config.get("currency")
        if price is None:
            return None, currency
        return round(float(price) * float(units), 6), currency
    return None, None


def run_job(
    session: Session,
    *,
    job: ContentGenerationJob,
    requirements: GenerationRequirements,
    params: dict,
    asset_type: ContentAssetType,
    timeout_seconds: Optional[float] = None,
    is_intermediate: bool = False,
) -> Optional[ContentAsset]:
    """Execute one generation job end to end.

    Walks the capability-ordered candidate list: retryable failures re-run the
    same (provider, model) per the retry policy; non-retryable ones move
    straight to the next candidate, since insisting would fail identically.
    Returns the created asset, or None when every candidate is exhausted (the
    job is marked failed in that case).

    `timeout_seconds` is pushed down into each adapter's poll deadline rather
    than enforced by abandoning a worker thread — a thread left polling a paid
    provider is exactly the leak the per-kind pools exist to prevent.
    """
    candidates = select_candidates(
        session, tenant_id=job.tenant_id, requirements=requirements
    )
    if not candidates:
        jobs_service.mark_failed(
            session,
            job,
            error_code=GenerationErrorCode.no_compatible_model.value,
            error_message=(
                f"no active provider/model satisfies kind={requirements.kind} "
                f"mode={requirements.mode.value}"
            ),
        )
        return None

    jobs_service.mark_running(session, job)
    last_error: Optional[GenerationError] = None

    for candidate in candidates:
        provider_row = get_generation_provider(
            session, tenant_id=job.tenant_id, provider_id=candidate.provider_row_id
        )
        if provider_row is None:
            continue

        api_key = decrypt_provider_credentials(provider_row)
        started = time.monotonic()

        def attempt():
            return provider_adapters.generate(
                provider=candidate.provider,
                kind=requirements.kind,
                api_key=api_key,
                model_id=candidate.model_id,
                poll_timeout=timeout_seconds,
                **params,
            )

        try:
            generated = run_with_retry(
                attempt,
                on_attempt=lambda number: jobs_service.record_attempt(
                    session,
                    job,
                    attempt=number,
                    provider=candidate.provider,
                    model=candidate.model_id,
                ),
            )
        except GenerationError as error:
            last_error = error
            logger.warning(
                f"generation job {job.id} failed on "
                f"{candidate.provider}/{candidate.model_id}: {error.code.value}"
            )
            continue

        if not jobs_service.is_still_running(session, job.id):
            # The job was already settled (timeout) while the provider was
            # still working. Drop the late result instead of resurrecting it.
            logger.warning(
                f"discarding late result for generation job {job.id} "
                f"(status is no longer running)"
            )
            return None

        try:
            uploaded = upload_bytes(
                tenant_id=job.tenant_id,
                content_piece_id=job.content_piece_id,
                filename=generated.filename,
                data=generated.data,
                content_type=generated.mime_type,
            )
        except StorageError as error:
            jobs_service.mark_failed(
                session,
                job,
                error_code=GenerationErrorCode.unknown.value,
                error_message=str(error),
            )
            return None

        units = generated.output_units or generated.input_units
        estimated, currency = estimate_cost(
            candidate.provider, candidate.model_id, units=units
        )

        jobs_service.mark_completed(
            session,
            job,
            provider=candidate.provider,
            model=candidate.model_id,
            response_metadata=generated.raw_metadata,
            input_units=generated.input_units,
            output_units=generated.output_units,
            estimated_cost=estimated,
            actual_cost=generated.actual_cost,
            currency=generated.currency or currency,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

        asset = assets_service.create_asset(
            session,
            job=job,
            asset_type=asset_type,
            uploaded=uploaded,
            provider=candidate.provider,
            model=candidate.model_id,
            mime_type=generated.mime_type,
            width=generated.width,
            height=generated.height,
            duration=generated.duration,
            is_intermediate=is_intermediate,
        )
        logger.info(
            f"generation job {job.id} completed on "
            f"{candidate.provider}/{candidate.model_id}, asset={asset.id}"
        )
        return asset

    jobs_service.mark_failed(
        session,
        job,
        error_code=(last_error.code.value if last_error else GenerationErrorCode.unknown.value),
        error_message=(
            last_error.message if last_error else "all provider candidates failed"
        ),
        status=(
            GenerationJobStatus.timeout
            if last_error and last_error.code == GenerationErrorCode.timeout
            else GenerationJobStatus.failed
        ),
    )
    return None
```

- [ ] **Step 4: Verificar que os módulos importam e o fallback é exercido**

```bash
python3 -c "
from unittest.mock import MagicMock, patch
from app.services.content import orchestrator
from app.services.content.capability import Candidate, GenerationMode, GenerationRequirements
from app.services.content.errors import GenerationError, GenerationErrorCode
from app.models.content_generation import ContentAssetType

job = MagicMock(id=1, tenant_id=1, client_id=1, content_piece_id=1)
requirements = GenerationRequirements(kind='image', mode=GenerationMode.text_to_image)

with patch.object(orchestrator, 'select_candidates', return_value=[]):
    with patch.object(orchestrator.jobs_service, 'mark_failed') as mark_failed:
        result = orchestrator.run_job(
            MagicMock(), job=job, requirements=requirements,
            params={'prompt': 'x'}, asset_type=ContentAssetType.image,
        )
print('no candidates ->', result, mark_failed.call_args.kwargs['error_code'])
"
```
Expected: `no candidates -> None no_compatible_model`.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/jobs.py app/services/content/assets.py app/services/content/orchestrator.py
git commit -m "feat(content): add generation job orchestration with capability fallback"
```

---

## Task 14: Pipeline por tipo de peça e pools de execução

**Files:**
- Create: `app/services/content/composition.py`
- Create: `app/services/content/pipeline.py`

**Interfaces:**
- Consumes: `orchestrator.run_job` (Task 13); `jobs.create_job` (Task 13); `assets.list_assets_for_piece` (Task 13); `normalize_to_ratio` (Task 12); `avatars.get_avatar` (Task 11); `GenerationRequirements`, `GenerationMode` (Task 3); `upload_bytes` (Task 6); `audit.write_audit_log` (existente).
- Produces: `composition.mux_narration(video_bytes, audio_bytes) -> Optional[bytes]`, `schedule_piece(piece_id, *, piece_type, aspect_ratio="9:16", resolution=None, duration=None) -> bool`, `KIND_TIMEOUT_SECONDS` (dict).

**Design notes — leia antes de codar:**

1. **Um pool por tipo de peça, sem submit aninhado.** `schedule_piece` roteia a peça inteira para o pool que corresponde ao seu `type`: `image`/`audio` vão para o pool rápido, `video` para o pool de vídeo. Submeter o job de vídeo a um segundo pool a partir de uma thread do pool rápido não resolveria nada — a thread rápida ficaria bloqueada esperando o resultado, que é exatamente a inanição que a separação de pools existe para evitar.
2. **Uma `Session` por thread.** `Session` do SQLAlchemy **não** é thread-safe. Cada execução de peça abre a sua própria sessão e a usa do começo ao fim, dentro de uma única thread. Nunca passe uma `Session` para outra thread.
3. **Timeout empurrado para baixo, não imposto por abandono.** O timeout por `kind` vai como `timeout_seconds` para `run_job`, que o repassa ao `poll_timeout` do adapter. Nada de `future.result(timeout=...)`: abandonar o future deixaria a thread continuar fazendo polling num provider pago, sem ninguém para colher o resultado.
4. **Parâmetros de request não moram na peça.** `aspect_ratio`, `resolution` e `duration` são parâmetros do pedido, não atributos da `ContentPiece` — eles chegam por argumento em `schedule_piece` e descem pelo grafo de jobs.
5. **Composição própria, não `video.generate_video`.** A spec pede reaproveitar o merge de `app/services/video.py`, mas `generate_video()` exige um `VideoParams` e arrasta legendas, BGM e redimensionamento de aspecto — tudo fora do escopo aqui. O que este módulo precisa é só um mux de narração; ele usa o mesmo moviepy/ffmpeg por baixo, num módulo próprio e pequeno.

- [ ] **Step 1: Implementar a composição de narração**

Crie `app/services/content/composition.py`:

```python
import os
import tempfile
from typing import Optional

from loguru import logger


def mux_narration(video_bytes: bytes, audio_bytes: bytes) -> Optional[bytes]:
    """Replace a generated video's audio track with the narration.

    Duration mismatch is resolved by trimming to the shorter of the two: a
    video that outlasts the narration ends in silence, and narration that
    outlasts the video is cut. Extending either one is a creative decision the
    generation engine has no basis to make.

    Returns None on any failure — the caller keeps the silent video rather
    than failing the whole piece.
    """
    from moviepy import AudioFileClip, VideoFileClip

    video_path = audio_path = output_path = None
    video_clip = audio_clip = composed = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
            handle.write(video_bytes)
            video_path = handle.name
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(audio_bytes)
            audio_path = handle.name
        output_path = tempfile.mktemp(suffix=".mp4")

        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)
        duration = min(video_clip.duration, audio_clip.duration)

        composed = video_clip.subclipped(0, duration).with_audio(
            audio_clip.subclipped(0, duration)
        )
        composed.write_videofile(
            output_path, codec="libx264", audio_codec="aac", logger=None
        )

        with open(output_path, "rb") as handle:
            return handle.read()
    except Exception as exc:  # noqa: BLE001 - composition is best-effort
        logger.warning(f"could not mux narration into generated video: {exc}")
        return None
    finally:
        for clip in (composed, audio_clip, video_clip):
            if clip is not None:
                try:
                    clip.close()
                except Exception:  # noqa: BLE001
                    pass
        for path in (video_path, audio_path, output_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
```

Nota sobre a API do moviepy: este projeto usa moviepy 2.x, cuja API é `subclipped()` / `with_audio()`. Em 1.x os nomes eram `subclip()` / `set_audio()`, que **não existem** na versão instalada — se encontrar esses nomes em algum código antigo, não copie.

- [ ] **Step 2: Implementar o pipeline**

Crie `app/services/content/pipeline.py`:

```python
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import requests
from loguru import logger
from sqlmodel import Session

from app.db import get_engine
from app.models.content import (
    ContentCampaign,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentPieceType,
)
from app.models.content_generation import ContentAssetType, GenerationKind
from app.services.content import assets as assets_service
from app.services.content import audit
from app.services.content import avatars as avatars_service
from app.services.content import jobs as jobs_service
from app.services.content import orchestrator
from app.services.content.capability import GenerationMode, GenerationRequirements
from app.services.content.composition import mux_narration
from app.services.content.image_ops import normalize_to_ratio
from app.services.content.storage import StorageError, upload_bytes

# Image and voice calls return in seconds; video polling parks a thread for
# minutes. Separate pools keep a burst of video work from starving everything
# else, mirroring how _cross_post_executor is bounded in app/services/task.py.
# A piece runs entirely inside the pool matching its type — never split across
# pools, or the fast thread would just block waiting on the video one.
_FAST_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.environ.get("CONTENT_FAST_WORKERS", 4)),
    thread_name_prefix="mpt-content-fast",
)
_VIDEO_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.environ.get("CONTENT_VIDEO_WORKERS", 2)),
    thread_name_prefix="mpt-content-video",
)
_PENDING_SLOTS = threading.BoundedSemaphore(
    int(os.environ.get("CONTENT_MAX_PENDING_PIECES", 20))
)

KIND_TIMEOUT_SECONDS: dict[GenerationKind, int] = {
    GenerationKind.image: 60,
    GenerationKind.voice: 60,
    GenerationKind.video: 600,
}

_FETCH_TIMEOUT = (30, 120)


def schedule_piece(
    piece_id: int,
    *,
    piece_type: ContentPieceType,
    aspect_ratio: str = "9:16",
    resolution: Optional[str] = None,
    duration: Optional[int] = None,
) -> bool:
    """Queue a piece's generation graph. False when the queue is saturated.

    A saturated queue is not an error: the piece stays in `generating` and the
    caller's request still succeeds, which is why the semaphore is acquired
    without blocking.
    """
    if not _PENDING_SLOTS.acquire(blocking=False):
        logger.warning(
            f"content generation queue is full; piece {piece_id} stays queued"
        )
        return False

    def runner():
        try:
            _run_piece(
                piece_id,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration=duration,
            )
        finally:
            _PENDING_SLOTS.release()

    executor = (
        _VIDEO_EXECUTOR if piece_type == ContentPieceType.video else _FAST_EXECUTOR
    )
    executor.submit(runner)
    return True


def _run_piece(
    piece_id: int,
    *,
    aspect_ratio: str,
    resolution: Optional[str],
    duration: Optional[int],
) -> None:
    """Own one piece from queued to settled, in a single thread and session."""
    with Session(get_engine()) as session:
        piece = session.get(ContentPiece, piece_id)
        if piece is None:
            logger.error(f"generation pipeline: piece {piece_id} not found")
            return

        campaign = session.get(ContentCampaign, piece.campaign_id)
        client = session.get(ContentClient, campaign.client_id) if campaign else None
        if client is None:
            logger.error(
                f"generation pipeline: could not resolve tenant for piece {piece_id}"
            )
            return

        tenant_id = client.tenant_id
        client_id = client.id

        try:
            if piece.type == ContentPieceType.image:
                asset_url = _run_image_piece(
                    session,
                    piece,
                    tenant_id=tenant_id,
                    client_id=client_id,
                    aspect_ratio=aspect_ratio,
                )
            elif piece.type == ContentPieceType.audio:
                asset_url = _run_audio_piece(
                    session, piece, tenant_id=tenant_id, client_id=client_id
                )
            else:
                asset_url = _run_video_piece(
                    session,
                    piece,
                    tenant_id=tenant_id,
                    client_id=client_id,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    duration=duration,
                )
        except Exception as exc:  # noqa: BLE001 - a piece must never stay stuck
            logger.exception(f"generation pipeline crashed for piece {piece_id}: {exc}")
            asset_url = None

        _finalize(session, piece, asset_url=asset_url, tenant_id=tenant_id)


def _finalize(
    session: Session,
    piece: ContentPiece,
    *,
    asset_url: Optional[str],
    tenant_id: int,
) -> None:
    piece.status = (
        ContentPieceStatus.pending_approval if asset_url else ContentPieceStatus.failed
    )
    piece.asset_url = asset_url
    piece.updated_at = datetime.utcnow()
    session.add(piece)
    session.commit()

    audit.write_audit_log(
        session,
        tenant_id=tenant_id,
        entity_type="content_piece",
        entity_id=piece.id,
        action="generated" if asset_url else "generation_failed",
        actor="system:generation",
    )


def _run_image_piece(
    session: Session,
    piece: ContentPiece,
    *,
    tenant_id: int,
    client_id: int,
    aspect_ratio: str,
) -> Optional[str]:
    if piece.avatar_id and not piece.generation_prompt:
        # Reusing the avatar's own image: no provider call, no job, no cost.
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant_id, avatar_id=piece.avatar_id
        )
        return avatar.reference_image_url if avatar else None

    params = {"prompt": piece.generation_prompt, "aspect_ratio": aspect_ratio}
    job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.image,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=job,
        requirements=GenerationRequirements(
            kind=GenerationKind.image.value,
            mode=GenerationMode.text_to_image,
            aspect_ratio=aspect_ratio,
        ),
        params=params,
        asset_type=ContentAssetType.image,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.image],
    )
    return asset.url if asset else None


def _run_audio_piece(
    session: Session, piece: ContentPiece, *, tenant_id: int, client_id: int
) -> Optional[str]:
    voice_id = _resolve_voice_id(session, piece, tenant_id=tenant_id)
    params = {"text": piece.generation_prompt, "voice_id": voice_id}
    job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.voice,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=job,
        requirements=GenerationRequirements(
            kind=GenerationKind.voice.value, mode=GenerationMode.voice
        ),
        params=params,
        asset_type=ContentAssetType.audio,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.voice],
    )
    return asset.url if asset else None


def _run_video_piece(
    session: Session,
    piece: ContentPiece,
    *,
    tenant_id: int,
    client_id: int,
    aspect_ratio: str,
    resolution: Optional[str],
    duration: Optional[int],
) -> Optional[str]:
    base_image_url = _resolve_base_image(
        session,
        piece,
        tenant_id=tenant_id,
        client_id=client_id,
        aspect_ratio=aspect_ratio,
    )
    if base_image_url:
        base_image_url = _normalized_base_image(
            piece,
            tenant_id=tenant_id,
            base_image_url=base_image_url,
            aspect_ratio=aspect_ratio,
        )

    narration_asset = None
    voice_id = _resolve_voice_id(session, piece, tenant_id=tenant_id)
    if voice_id:
        voice_params = {"text": piece.generation_prompt, "voice_id": voice_id}
        voice_job = jobs_service.create_job(
            session,
            tenant_id=tenant_id,
            client_id=client_id,
            content_piece_id=piece.id,
            kind=GenerationKind.voice,
            request_payload=voice_params,
        )
        narration_asset = orchestrator.run_job(
            session,
            job=voice_job,
            requirements=GenerationRequirements(
                kind=GenerationKind.voice.value, mode=GenerationMode.voice
            ),
            params=voice_params,
            asset_type=ContentAssetType.audio,
            timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.voice],
            is_intermediate=True,
        )

    mode = (
        GenerationMode.image_to_video if base_image_url else GenerationMode.text_to_video
    )
    params: dict = {"prompt": piece.generation_prompt, "aspect_ratio": aspect_ratio}
    if duration:
        params["duration"] = duration
    if base_image_url:
        params["source_image_url"] = base_image_url

    video_job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.video,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=video_job,
        requirements=GenerationRequirements(
            kind=GenerationKind.video.value,
            mode=mode,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            needs_reference_image=bool(base_image_url),
        ),
        params=params,
        asset_type=ContentAssetType.video,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.video],
        # The raw provider video is intermediate whenever narration will be
        # muxed on top of it; the composed file becomes the piece's asset.
        is_intermediate=narration_asset is not None,
    )
    if asset is None:
        return None
    if narration_asset is None:
        return asset.url

    composed_url = _compose_with_narration(
        piece,
        tenant_id=tenant_id,
        video_url=asset.url,
        narration_url=narration_asset.url,
    )
    if composed_url is None:
        # Composition failed: ship the silent video rather than the whole
        # piece. Undo the intermediate flag so the piece still points at a
        # non-intermediate asset.
        asset.is_intermediate = False
        session.add(asset)
        session.commit()
        return asset.url
    return composed_url


def _resolve_base_image(
    session: Session,
    piece: ContentPiece,
    *,
    tenant_id: int,
    client_id: int,
    aspect_ratio: str,
) -> Optional[str]:
    """Pick the image the video will animate, in the spec's precedence order.

    avatar -> source image piece -> newly generated image. Returns None when
    none applies, which makes the video a text-to-video generation.
    """
    if piece.avatar_id:
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant_id, avatar_id=piece.avatar_id
        )
        if avatar is not None:
            return avatar.reference_image_url

    if piece.source_image_piece_id:
        for asset in assets_service.list_assets_for_piece(
            session, content_piece_id=piece.source_image_piece_id
        ):
            if asset.type == ContentAssetType.image and not asset.is_intermediate:
                return asset.url

    params = {"prompt": piece.generation_prompt, "aspect_ratio": aspect_ratio}
    job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.image,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=job,
        requirements=GenerationRequirements(
            kind=GenerationKind.image.value,
            mode=GenerationMode.text_to_image,
            aspect_ratio=aspect_ratio,
        ),
        params=params,
        asset_type=ContentAssetType.image,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.image],
        is_intermediate=True,
    )
    return asset.url if asset else None


def _normalized_base_image(
    piece: ContentPiece,
    *,
    tenant_id: int,
    base_image_url: str,
    aspect_ratio: str,
) -> str:
    """Crop/pad the base image to the video's ratio and re-upload it.

    An avatar's reference image is registered once and reused across output
    formats, so a square portrait feeding a 9:16 video is the common case.
    The normalized file is what the provider actually receives, so it is
    persisted rather than discarded. Any failure here degrades to the original
    URL: a slightly off-ratio frame beats failing the whole piece.
    """
    try:
        response = requests.get(base_image_url, timeout=_FETCH_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - normalization is best-effort
        logger.warning(f"could not fetch base image for normalization: {exc}")
        return base_image_url

    original = response.content
    data, width, _height = normalize_to_ratio(original, aspect_ratio)
    if data is original or not width:
        # Ratio already matched (or was unparseable): nothing to upload.
        return base_image_url

    try:
        uploaded = upload_bytes(
            tenant_id=tenant_id,
            content_piece_id=piece.id,
            filename="base-normalized.png",
            data=data,
            content_type="image/png",
        )
    except StorageError as exc:
        logger.warning(f"could not upload normalized base image: {exc}")
        return base_image_url

    return uploaded.url


def _compose_with_narration(
    piece: ContentPiece,
    *,
    tenant_id: int,
    video_url: str,
    narration_url: str,
) -> Optional[str]:
    """Mux the narration onto the generated video and upload the result."""
    try:
        video_response = requests.get(video_url, timeout=_FETCH_TIMEOUT)
        video_response.raise_for_status()
        audio_response = requests.get(narration_url, timeout=_FETCH_TIMEOUT)
        audio_response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - composition is best-effort
        logger.warning(f"could not fetch assets for composition: {exc}")
        return None

    composed = mux_narration(video_response.content, audio_response.content)
    if composed is None:
        return None

    try:
        uploaded = upload_bytes(
            tenant_id=tenant_id,
            content_piece_id=piece.id,
            filename="composed.mp4",
            data=composed,
            content_type="video/mp4",
        )
    except StorageError as exc:
        logger.warning(f"could not upload composed video: {exc}")
        return None

    logger.info(f"composed narration into video for piece {piece.id}")
    return uploaded.url


def _resolve_voice_id(
    session: Session, piece: ContentPiece, *, tenant_id: int
) -> Optional[str]:
    """Explicit voice wins over the avatar's, so a piece can override it."""
    if piece.voice_id:
        return piece.voice_id
    if piece.avatar_id:
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant_id, avatar_id=piece.avatar_id
        )
        if avatar is not None:
            return avatar.voice_id
    return None
```

Nota: `_normalized_base_image` não registra o asset normalizado em `content_assets` porque ele não vem de um `GenerationJob` — `create_asset` exige um job. O arquivo fica no Storage e a URL entra no `request_payload` do job de vídeo, então continua auditável por ali.

- [ ] **Step 3: Verificar que o módulo importa e os pools estão dimensionados**

```bash
python3 -c "
from app.services.content import pipeline
from app.models.content import ContentPieceType
print('fast workers:', pipeline._FAST_EXECUTOR._max_workers)
print('video workers:', pipeline._VIDEO_EXECUTOR._max_workers)
print('timeouts:', {k.value: v for k, v in pipeline.KIND_TIMEOUT_SECONDS.items()})
"
```
Expected:
```
fast workers: 4
video workers: 2
timeouts: {'image': 60, 'voice': 60, 'video': 600}
```

- [ ] **Step 4: Verificar o roteamento por pool e a saturação da fila**

```bash
python3 -c "
from unittest.mock import patch
from app.models.content import ContentPieceType
from app.services.content import pipeline

with patch.object(pipeline, '_run_piece'):
    with patch.object(pipeline._VIDEO_EXECUTOR, 'submit') as video_submit:
        with patch.object(pipeline._FAST_EXECUTOR, 'submit') as fast_submit:
            pipeline.schedule_piece(1, piece_type=ContentPieceType.video)
            pipeline.schedule_piece(2, piece_type=ContentPieceType.image)
            print('video pool used:', video_submit.call_count)
            print('fast pool used:', fast_submit.call_count)

# Saturated queue must refuse without raising.
import threading
pipeline._PENDING_SLOTS = threading.BoundedSemaphore(1)
with patch.object(pipeline, '_run_piece'):
    with patch.object(pipeline._FAST_EXECUTOR, 'submit'):
        first = pipeline.schedule_piece(3, piece_type=ContentPieceType.image)
        second = pipeline.schedule_piece(4, piece_type=ContentPieceType.image)
print('first accepted:', first, '| second refused:', second)
"
```
Expected:
```
video pool used: 1
fast pool used: 1
first accepted: True | second refused: False
```

- [ ] **Step 5: Commit**

```bash
git add app/services/content/pipeline.py app/services/content/composition.py
git commit -m "feat(content): add generation pipeline with per-type executor pools"
```

---
## Task 15: `POST /content/pieces` e leitura de jobs

**Files:**
- Modify: `app/services/content/pieces.py`
- Modify: `app/controllers/v1/content/pieces.py`
- Create: `test/services/test_content_pieces.py`

**Interfaces:**
- Consumes: `ContentPieceCreate/Read` (Task 1); `classify` (Task 5); `has_active_provider` (Task 10); `get_avatar` (Task 11); `schedule_piece` (Task 14); `jobs.list_jobs_for_piece` (Task 13).
- Produces: `find_by_idempotency_key(session, *, campaign_id, idempotency_key) -> Optional[ContentPiece]`, `required_kinds_for(payload) -> list[GenerationKind]`, `create_piece(session, *, tenant_id, payload) -> tuple[ContentPiece, bool]` (o `bool` é `created`: `False` quando a `idempotency_key` já existia).

- [ ] **Step 1: Escrever o teste que falha**

Crie `test/services/test_content_pieces.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentCategory, ContentPieceType, RiskLevel
from app.models.content_generation import GenerationKind
from app.services.content import pieces as pieces_service


def _payload(**overrides):
    base = dict(
        campaign_id=1,
        type=ContentPieceType.image,
        idempotency_key="key-1",
        is_synthetic_media=True,
        generation_prompt="a cat",
        avatar_id=None,
        source_image_piece_id=None,
        voice_id=None,
        content_category=None,
        aspect_ratio="9:16",
        resolution=None,
        duration=None,
    )
    base.update(overrides)
    return MagicMock(**base)


class TestRequiredKinds(unittest.TestCase):
    def test_image_with_prompt_needs_image_provider(self):
        self.assertEqual(
            pieces_service.required_kinds_for(_payload()), [GenerationKind.image]
        )

    def test_image_from_avatar_without_prompt_needs_nothing(self):
        payload = _payload(generation_prompt=None, avatar_id=7)

        self.assertEqual(pieces_service.required_kinds_for(payload), [])

    def test_audio_needs_voice_provider(self):
        payload = _payload(type=ContentPieceType.audio)

        self.assertEqual(pieces_service.required_kinds_for(payload), [GenerationKind.voice])

    def test_video_from_prompt_needs_image_and_video(self):
        payload = _payload(type=ContentPieceType.video)

        self.assertEqual(
            pieces_service.required_kinds_for(payload),
            [GenerationKind.video, GenerationKind.image],
        )

    def test_video_from_avatar_with_voice_needs_video_and_voice(self):
        payload = _payload(type=ContentPieceType.video, avatar_id=7, voice_id="v1")

        self.assertEqual(
            pieces_service.required_kinds_for(payload),
            [GenerationKind.video, GenerationKind.voice],
        )

    def test_video_from_source_image_does_not_need_image_provider(self):
        payload = _payload(type=ContentPieceType.video, source_image_piece_id=3)

        self.assertEqual(
            pieces_service.required_kinds_for(payload), [GenerationKind.video]
        )


class TestCreatePieceIdempotency(unittest.TestCase):
    def test_existing_key_returns_the_same_piece_without_new_work(self):
        existing = MagicMock(id=42)
        session = MagicMock()

        with patch.object(
            pieces_service, "find_by_idempotency_key", return_value=existing
        ):
            with patch.object(pieces_service, "schedule_piece") as schedule:
                result, created = pieces_service.create_piece(
                    session, tenant_id=1, payload=_payload()
                )

        self.assertIs(result, existing)
        self.assertFalse(created)
        schedule.assert_not_called()
        session.add.assert_not_called()

    def test_new_key_creates_and_schedules(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece") as schedule:
                result, created = pieces_service.create_piece(
                    session, tenant_id=1, payload=_payload()
                )

        self.assertTrue(created)
        session.add.assert_called_once()
        schedule.assert_called_once()


class TestCreatePiecePolicy(unittest.TestCase):
    def test_medical_category_is_classified_as_high_risk(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece"):
                piece, _ = pieces_service.create_piece(
                    session,
                    tenant_id=1,
                    payload=_payload(content_category=ContentCategory.medical),
                )

        self.assertEqual(piece.risk_level, RiskLevel.high)
        self.assertTrue(piece.requires_human_review)
        self.assertEqual(piece.policy_version, "v1")

    def test_absent_category_is_inert(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece"):
                piece, _ = pieces_service.create_piece(
                    session, tenant_id=1, payload=_payload()
                )

        self.assertEqual(piece.risk_level, RiskLevel.none)
        self.assertFalse(piece.requires_human_review)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

Run: `pytest test/services/test_content_pieces.py -v`
Expected: FAIL com `AttributeError: module 'app.services.content.pieces' has no attribute 'required_kinds_for'`.

- [ ] **Step 3: Estender o service de pieces**

Adicione ao fim de `app/services/content/pieces.py` (mantendo o que já existe):

```python
from datetime import datetime

from app.models.content import ContentPieceStatus, ContentPieceType
from app.models.content_generation import GenerationKind
from app.services.content.pipeline import schedule_piece
from app.services.content.policy import classify


def find_by_idempotency_key(
    session: Session, *, campaign_id: int, idempotency_key: str
) -> Optional[ContentPiece]:
    return session.exec(
        select(ContentPiece).where(
            ContentPiece.campaign_id == campaign_id,
            ContentPiece.idempotency_key == idempotency_key,
        )
    ).first()


def required_kinds_for(payload) -> List[GenerationKind]:
    """Which provider kinds this request will actually need.

    Coarse check only — it answers "does the tenant have a provider at all",
    not "is there a compatible model", which the capability engine resolves
    per job at run time.
    """
    if payload.type == ContentPieceType.image:
        if payload.avatar_id and not payload.generation_prompt:
            return []
        return [GenerationKind.image]

    if payload.type == ContentPieceType.audio:
        return [GenerationKind.voice]

    kinds = [GenerationKind.video]
    needs_generated_base = not payload.avatar_id and not payload.source_image_piece_id
    if needs_generated_base:
        kinds.append(GenerationKind.image)
    if payload.voice_id or payload.avatar_id:
        kinds.append(GenerationKind.voice)
    return kinds


def create_piece(session: Session, *, tenant_id: int, payload) -> tuple[ContentPiece, bool]:
    """Create a piece and kick off its generation.

    Returns (piece, created). `created` is False when the idempotency key
    already produced a piece — the caller must not schedule new work in that
    case, since every generation call is billable.
    """
    existing = find_by_idempotency_key(
        session,
        campaign_id=payload.campaign_id,
        idempotency_key=payload.idempotency_key,
    )
    if existing is not None:
        return existing, False

    classification = classify(payload.content_category)

    piece = ContentPiece(
        campaign_id=payload.campaign_id,
        type=payload.type,
        status=ContentPieceStatus.generating,
        generation_prompt=payload.generation_prompt,
        avatar_id=payload.avatar_id,
        source_image_piece_id=payload.source_image_piece_id,
        voice_id=payload.voice_id,
        is_synthetic_media=payload.is_synthetic_media,
        content_category=payload.content_category,
        risk_level=classification.risk_level,
        requires_human_review=classification.requires_human_review,
        policy_version=classification.policy_version,
        idempotency_key=payload.idempotency_key,
        updated_at=datetime.utcnow(),
    )
    session.add(piece)
    session.commit()
    session.refresh(piece)

    # Request parameters live on the call, not on the row: aspect_ratio and
    # friends describe this generation, not the piece itself.
    schedule_piece(
        piece.id,
        piece_type=payload.type,
        aspect_ratio=payload.aspect_ratio,
        resolution=payload.resolution,
        duration=payload.duration,
    )
    return piece, True
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

Run: `pytest test/services/test_content_pieces.py -v`
Expected: PASS (10 testes).

- [ ] **Step 5: Adicionar os endpoints**

Em `app/controllers/v1/content/pieces.py`, substitua os imports do topo por:

```python
from fastapi import Depends, HTTPException, Response
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import (
    ContentPieceCreate,
    ContentPieceRead,
    ContentPieceType,
    ContentTenant,
)
from app.models.content_generation import GenerationJobRead
from app.services.content import audit
from app.services.content import avatars as avatars_service
from app.services.content import jobs as jobs_service
from app.services.content import pieces as pieces_service
from app.services.content.campaigns import get_campaign
from app.services.content.generation_providers import has_active_provider
```

E adicione, antes dos handlers `GET` existentes:

```python
@router.post("/content/pieces", response_model=ContentPieceRead, status_code=202)
def create_piece(
    payload: ContentPieceCreate,
    response: Response,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    if get_campaign(session, tenant_id=tenant.id, campaign_id=payload.campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if payload.type in (ContentPieceType.audio, ContentPieceType.video):
        if not payload.generation_prompt:
            raise HTTPException(
                status_code=422,
                detail=f"generation_prompt is required for type {payload.type.value}",
            )
    elif not payload.generation_prompt and not payload.avatar_id:
        raise HTTPException(
            status_code=422,
            detail="image pieces require generation_prompt or avatar_id",
        )

    if payload.avatar_id is not None:
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant.id, avatar_id=payload.avatar_id
        )
        if avatar is None:
            raise HTTPException(status_code=404, detail="Avatar not found")

    if payload.source_image_piece_id is not None:
        source = pieces_service.get_piece(
            session, tenant_id=tenant.id, piece_id=payload.source_image_piece_id
        )
        if source is None:
            raise HTTPException(status_code=404, detail="Source image piece not found")

    for kind in pieces_service.required_kinds_for(payload):
        if not has_active_provider(session, tenant_id=tenant.id, kind=kind):
            raise HTTPException(
                status_code=422,
                detail=f"no active {kind.value} provider configured for this tenant",
            )

    piece, created = pieces_service.create_piece(
        session, tenant_id=tenant.id, payload=payload
    )
    if not created:
        # Idempotent replay: the piece already exists and its generation was
        # already paid for. Return it as-is instead of generating again.
        response.status_code = 200
        return piece

    audit.write_audit_log(
        session,
        tenant_id=tenant.id,
        entity_type="content_piece",
        entity_id=piece.id,
        action="created",
        actor=f"tenant:{tenant.id}",
    )
    return piece


@router.get("/content/pieces/{piece_id}/jobs", response_model=list[GenerationJobRead])
def list_piece_jobs(
    piece_id: int,
    session: Session = Depends(get_session),
    tenant: ContentTenant = Depends(content_auth.verify_tenant_token),
):
    if pieces_service.get_piece(session, tenant_id=tenant.id, piece_id=piece_id) is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return jobs_service.list_jobs_for_piece(
        session, tenant_id=tenant.id, piece_id=piece_id
    )
```

- [ ] **Step 6: Verificar as rotas**

```bash
python3 -c "
from app.asgi import app
print(sorted({(r.path, tuple(sorted(r.methods))) for r in app.routes if 'pieces' in r.path}))
"
```
Expected: inclui `('/api/v1/content/pieces', ('POST',))` e `('/api/v1/content/pieces/{piece_id}/jobs', ('GET',))`.

- [ ] **Step 7: Rodar a suíte de conteúdo inteira**

Run: `pytest test/services/test_content_catalog.py test/services/test_content_capability.py test/services/test_content_retry.py test/services/test_content_policy.py test/services/test_content_pieces.py test/services/test_content_auth.py test/services/test_content_crypto.py -v`
Expected: PASS, sem falhas.

- [ ] **Step 8: Commit**

```bash
git add app/services/content/pieces.py app/controllers/v1/content/pieces.py test/services/test_content_pieces.py
git commit -m "feat(content): add content piece creation with idempotency and policy gate"
```

---

## Task 16: Credencial de WaveSpeed por tenant no pipeline legado

**Files:**
- Modify: `app/services/material.py:698-712`

**Interfaces:**
- Consumes: nada novo.
- Produces: `generate_videos_wavespeed(..., api_key: Optional[str] = None)` — assinatura retrocompatível.

- [ ] **Step 1: Aceitar credencial injetada**

Em `app/services/material.py`, na função `generate_videos_wavespeed` (linha ~698), altere a assinatura e a resolução da chave.

Assinatura — de:
```python
def generate_videos_wavespeed(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
```
para:
```python
def generate_videos_wavespeed(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
    api_key: Optional[str] = None,
) -> List[MaterialInfo]:
```

Resolução da chave — de:
```python
    api_key = get_api_key("wavespeed_api_keys")
```
para:
```python
    # The content module resolves credentials per tenant and passes them in;
    # the legacy standalone pipeline keeps falling back to the global config.
    api_key = api_key or get_api_key("wavespeed_api_keys")
```

Confirme que `Optional` já está importado no topo do arquivo (o módulo usa `from typing import ...`); se não estiver, adicione-o ao import existente.

- [ ] **Step 2: Verificar que o comportamento legado não mudou**

Run: `pytest test/services/test_material.py -v -k wavespeed`
Expected: PASS — todos os testes existentes de WaveSpeed continuam verdes, já que `api_key` é opcional e o fallback é o comportamento anterior.

- [ ] **Step 3: Rodar a suíte completa**

Run: `pytest test/ -q`
Expected: PASS. Se algum teste pré-existente falhar, corrija antes de commitar — esta task não pode regredir o pipeline legado.

- [ ] **Step 4: Commit**

```bash
git add app/services/material.py
git commit -m "feat(content): allow per-tenant credential injection in wavespeed generation"
```

---

## Verificação final (após todas as tasks)

- [ ] **Smoke test ponta a ponta**

Com `DATABASE_URL`, `CONTENT_MODULE_ENCRYPTION_KEY`, `CONTENT_ADMIN_TOKEN`, `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` exportados, e o servidor rodando (`python main.py`):

```bash
# 1. Criar tenant (guarde o api_token retornado)
curl -s -X POST localhost:8080/api/v1/content/tenants \
  -H "X-Admin-Token: $CONTENT_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"owner_user_id":"u1","name":"Smoke Agency","slug":"smoke"}'

# 2. Cadastrar um provider de imagem (TOKEN = api_token do passo 1)
curl -s -X POST localhost:8080/api/v1/content/providers \
  -H "X-Tenant-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"image","provider":"falai","credentials":"'"$FAL_KEY"'","priority":0}'

# 3. Criar client e campaign (anote os ids retornados)
curl -s -X POST localhost:8080/api/v1/content/clients \
  -H "X-Tenant-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Smoke Client"}'

curl -s -X POST localhost:8080/api/v1/content/campaigns \
  -H "X-Tenant-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"client_id":1,"name":"Smoke Campaign","horizon_days":7}'

# 4. Criar a piece (CAMPAIGN_ID = id do passo anterior)
curl -s -X POST localhost:8080/api/v1/content/pieces \
  -H "X-Tenant-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"campaign_id":1,"type":"image","idempotency_key":"smoke-1",
       "is_synthetic_media":true,"generation_prompt":"a red bicycle",
       "content_category":"medical","aspect_ratio":"9:16"}'
```
Expected: HTTP 202, piece com `status="generating"`, `risk_level="high"`, `requires_human_review=true`, `policy_version="v1"`.

- [ ] **Verificar idempotência**

Repita a chamada do passo 4 com a mesma `idempotency_key`.
Expected: HTTP **200** (não 202), a mesma piece, e **nenhum** job novo em `GET /content/pieces/{id}/jobs`.

- [ ] **Verificar a conclusão da geração**

```bash
curl -s localhost:8080/api/v1/content/pieces/1 -H "X-Tenant-Token: $TOKEN"
curl -s localhost:8080/api/v1/content/pieces/1/jobs -H "X-Tenant-Token: $TOKEN"
```
Expected: após alguns segundos, `status="pending_approval"` com `asset_url` preenchido, e um job `status="completed"` com `provider`, `model`, `estimated_cost` e `duration_ms` populados.

- [ ] **Limpar os dados do smoke test**

```bash
python3 -c "
import re, psycopg
url = re.search(r'DATABASE_URL=(.+)', open('.env').read()).group(1).strip().strip('\"').replace('postgresql+psycopg://','postgresql://')
with psycopg.connect(url) as conn, conn.cursor() as cur:
    for table in ['content_assets','content_generation_jobs','content_pieces','content_approval_rules','content_campaigns','content_avatars','content_social_accounts','content_generation_providers','content_clients','content_audit_logs','content_tenants']:
        cur.execute(f'DELETE FROM {table}')
        print(table, cur.rowcount)
    conn.commit()
"
```
