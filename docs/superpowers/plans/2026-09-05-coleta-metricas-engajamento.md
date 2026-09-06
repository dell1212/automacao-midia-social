# Coleta de Métricas de Engajamento Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect post-publish engagement telemetry (reach/impressions, likes, comments, shares) for the six publisher platforms and surface it as three tiles on the Analytics screen, replacing the two permanently-empty "not collected yet" tiles.

**Architecture:** A new `content_publication_insights` snapshot table (one row per publication per collection, failures included) is filled by a fourth pass in the existing `automation_scheduler` tick, using a new `fetch_insights` method on each `PublisherAdapter`. `ui_analytics.get_overview` aggregates the latest snapshot per publication into three new `AnalyticsTiles` fields, which the webui renders.

**Tech Stack:** Python 3 / FastAPI / SQLModel / SQLAlchemy / Alembic (backend), React / TypeScript / TanStack Query (webui), `unittest` + `unittest.mock` (tests).

**Spec:** `docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md` — this plan argues from that spec; read both.

## Global Constraints

- Scope is engagement only. Link clicks stay out — see the spec's Não-objetivos.
- Every new numeric field is `Optional`, and absence renders as `None`/`"—"`, never `0`. A rate with a zero denominator is `None`, not a division by zero.
- `AnalyticsTiles.success_rate` is removed from the tile row entirely. It is **not** deleted from `AccountPerformanceRead` — that field and the "Desempenho por conta" table column are untouched.
- `retry.run_with_retry` is **not reusable here** — it is hard-coded to catch `GenerationError` (the media-generation taxonomy in `app/services/content/errors.py`), not `PublicationError` (the publish taxonomy this feature uses, in `app/services/content/publish_errors.py`). A deliberate deviation from the spec's literal wording: Task 10 reimplements the same backoff *shape* using the pure `retry.backoff_delay` helper and `publish_errors.is_retryable`, which does work for `PublicationError`. Calling `run_with_retry` directly would silently skip every retry, since its `except GenerationError` clause never matches a `PublicationError`.
- Follow existing code style exactly: Portuguese in docstrings/comments that explain *why* (matching every file this plan touches), English identifiers, `unittest.TestCase` + `unittest.mock.patch`/`MagicMock` for tests, no new test framework or dependency.
- No behavior change to `publish()`/`check_compatibility()` on any adapter, to `_fill_campaign_calendars`, `_evaluate_pending_approvals`, or `_dispatch_scheduled_publications`.

---

## Task 1: `content_publication_insights` schema (model + migration)

**Files:**
- Create: `app/models/content_insights.py`
- Create: `alembic/versions/cec5f57485cd_add_content_publication_insights.py`

**Interfaces:**
- Produces: `ContentPublicationInsight` (SQLModel table class) with columns `id, tenant_id, client_id, content_piece_id, publication_id, social_account_id, platform, publication_cycle, collected_at, reach, impressions, likes, comments, shares, raw, error_code, error_message`. Every later task that touches insights imports this class from `app.models.content_insights`.

This is a pure schema task — there is no behavior to drive with a failing test, so it skips the TDD ceremony and instead verifies the schema creates cleanly (the same bar `ContentSocialPublication` and every other table in this codebase meet, none of which have a dedicated model test file).

- [ ] **Step 1: Write the model**

```python
# app/models/content_insights.py
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ContentPublicationInsight(SQLModel, table=True):
    """Um snapshot de engajamento por (publicação, coleta) — nunca sobrescrito.

    Um post publicado hoje continua acumulando curtida por dias; sobrescrever
    uma linha destruiria a resposta para "quando isso aconteceu". Uma coleta
    que falhou também vira linha, com as cinco métricas nulas e `error_code`
    preenchido — assim um token quebrado fica visível na mesma tabela em vez
    de virar silêncio, e "quando foi a última tentativa" não precisa de
    estado separado.

    Ver docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md.
    """

    __tablename__ = "content_publication_insights"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    publication_id: int = Field(
        foreign_key="content_social_publications.id", index=True
    )
    social_account_id: int = Field(
        foreign_key="content_social_accounts.id", index=True
    )
    platform: str
    # Espelha ContentSocialPublication.publication_cycle: republicar uma peça
    # gera um post novo na plataforma, e as métricas do post antigo não podem
    # se misturar com as do novo.
    publication_cycle: int
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    # Alcance (pessoas únicas) só existe de verdade no Instagram e no
    # Facebook. As outras quatro plataformas só publicam impressions (volume
    # de exibição, não de gente) — por isso as duas colunas são separadas e
    # nuláveis, nunca uma soma sob um rótulo só. Ver a tabela de métricas por
    # plataforma no design spec.
    reach: Optional[int] = None
    impressions: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    # A resposta como chegou. As APIs adicionam campo sem avisar; quando um
    # número parecer errado, isto é a única forma de saber se o bug é nosso
    # ou deles.
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))

    error_code: Optional[str] = None
    error_message: Optional[str] = None
```

- [ ] **Step 2: Verify the schema creates cleanly**

Run:
```bash
python3 -c "
from app.models.content_insights import ContentPublicationInsight
from app.models import content, content_publishing  # noqa: F401  (registram as tabelas referenciadas pelas FKs)
from sqlmodel import SQLModel, create_engine
engine = create_engine('sqlite://')
SQLModel.metadata.create_all(engine)
print('ok:', ContentPublicationInsight.__tablename__)
"
```
Expected: `ok: content_publication_insights`, no traceback.

- [ ] **Step 3: Write the migration**

Revision id `cec5f57485cd` was generated with Python's `secrets.token_hex(6)` ahead of time so this plan is self-contained (no `DATABASE_URL` needed to invent one via `alembic revision`). Current head is `b72e5d419a83` (`add_piece_targets`).

```python
# alembic/versions/cec5f57485cd_add_content_publication_insights.py
"""add content_publication_insights

Revision ID: cec5f57485cd
Revises: b72e5d419a83
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'cec5f57485cd'
down_revision = 'b72e5d419a83'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Um snapshot por (publicação, coleta) — nunca sobrescrito. Falha também
    # é linha: um erro de coleta grava métricas nulas com error_code
    # preenchido, então um token quebrado fica visível na mesma tabela em vez
    # de virar silêncio.
    op.create_table(
        'content_publication_insights',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('content_piece_id', sa.Integer(), nullable=False),
        sa.Column('publication_id', sa.Integer(), nullable=False),
        sa.Column('social_account_id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('publication_cycle', sa.Integer(), nullable=False),
        sa.Column('collected_at', sa.DateTime(), nullable=False),
        sa.Column('reach', sa.Integer(), nullable=True),
        sa.Column('impressions', sa.Integer(), nullable=True),
        sa.Column('likes', sa.Integer(), nullable=True),
        sa.Column('comments', sa.Integer(), nullable=True),
        sa.Column('shares', sa.Integer(), nullable=True),
        sa.Column('raw', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['content_tenants.id']),
        sa.ForeignKeyConstraint(['client_id'], ['content_clients.id']),
        sa.ForeignKeyConstraint(['content_piece_id'], ['content_pieces.id']),
        sa.ForeignKeyConstraint(
            ['publication_id'], ['content_social_publications.id']
        ),
        sa.ForeignKeyConstraint(
            ['social_account_id'], ['content_social_accounts.id']
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_content_publication_insights_tenant_id'),
        'content_publication_insights', ['tenant_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_client_id'),
        'content_publication_insights', ['client_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_content_piece_id'),
        'content_publication_insights', ['content_piece_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_publication_id'),
        'content_publication_insights', ['publication_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_social_account_id'),
        'content_publication_insights', ['social_account_id'],
    )
    # Composto: o worker de coleta lê "qual foi a última coleta desta
    # publicação" (publication_id, collected_at); a leitura do dashboard é
    # "toda coleta de um tenant numa janela" (tenant_id, collected_at). Um
    # índice ascendente também serve ORDER BY ... DESC — o Postgres escaneia
    # o B-tree pra trás sem custo extra, sem precisar de um índice DESC
    # explícito.
    op.create_index(
        'ix_content_publication_insights_pub_collected',
        'content_publication_insights', ['publication_id', 'collected_at'],
    )
    op.create_index(
        'ix_content_publication_insights_tenant_collected',
        'content_publication_insights', ['tenant_id', 'collected_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_content_publication_insights_tenant_collected',
        table_name='content_publication_insights',
    )
    op.drop_index(
        'ix_content_publication_insights_pub_collected',
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_social_account_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_publication_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_content_piece_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_client_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_tenant_id'),
        table_name='content_publication_insights',
    )
    op.drop_table('content_publication_insights')
```

- [ ] **Step 4: Verify the migration file is valid Python**

Run: `python3 -m py_compile alembic/versions/cec5f57485cd_add_content_publication_insights.py`
Expected: no output, exit code 0.

If a local Postgres is configured (`DATABASE_URL` set), also run `alembic upgrade head` and confirm `\d content_publication_insights` in `psql` shows all 17 columns and the 7 indexes. This step is optional — it requires infrastructure this plan does not assume is present.

- [ ] **Step 5: Commit**

```bash
git add app/models/content_insights.py alembic/versions/cec5f57485cd_add_content_publication_insights.py
git commit -m "feat(content): add content_publication_insights schema"
```

---

## Task 2: `InsightsResult` and the `fetch_insights` capability hook

**Files:**
- Modify: `app/services/content/publishers/base.py`

**Interfaces:**
- Consumes: nothing new (existing `get_json`, `PublicationError`, `PublicationErrorCode` in the same file).
- Produces: `InsightsResult` (frozen dataclass: `reach`, `impressions`, `likes`, `comments`, `shares` — all `Optional[int] = None` — and `raw: dict`), `PublisherAdapter.supports_insights: bool = False` class attribute, `PublisherAdapter.fetch_insights(self, publication, account, credentials: dict) -> InsightsResult` (concrete method, default raises `NotImplementedError`). All six adapter tasks (3–8) override both.

No test file for this task: it only adds a dataclass and a default method that six later tasks exercise directly. Verified by those six tasks' tests importing `InsightsResult` successfully.

- [ ] **Step 1: Add the import and the dataclass**

In `app/services/content/publishers/base.py`, change:

```python
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests

from app.models.content import ContentSocialAccount, ContentPiece
from app.models.content_generation import ContentAsset
from app.services.content.crypto import decrypt_credentials
from app.services.content.publish_errors import (
    PublicationError,
    PublicationErrorCode,
    classify_http_status,
)
```

to:

```python
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import requests

from app.models.content import ContentSocialAccount, ContentPiece
from app.models.content_generation import ContentAsset
from app.models.content_publishing import ContentSocialPublication
from app.services.content.crypto import decrypt_credentials
from app.services.content.publish_errors import (
    PublicationError,
    PublicationErrorCode,
    classify_http_status,
)
```

Then, right after the existing `PublishResult` dataclass (after its closing `platform_post_url` line, before `class PublisherAdapter(ABC):`), add:

```python
@dataclass(frozen=True)
class InsightsResult:
    """Uma coleta de engajamento bem-sucedida.

    Todo campo é None por padrão, não 0 — zero é um fato que a plataforma
    reportou, ausência não é. Nenhuma plataforma preenche as cinco: reach só
    existe no Instagram/Facebook, shares não existe no YouTube, e assim por
    diante. Ver a tabela de métricas por plataforma no design spec.
    """

    reach: Optional[int] = None
    impressions: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    raw: dict = field(default_factory=dict)
```

- [ ] **Step 2: Add the capability hook to `PublisherAdapter`**

Change:

```python
class PublisherAdapter(ABC):
    platform: str

    @abstractmethod
    def check_compatibility(self, piece: ContentPiece, asset: ContentAsset) -> None:
        ...

    @abstractmethod
    def publish(
        self,
        piece: ContentPiece,
        asset: ContentAsset,
        account: ContentSocialAccount,
        credentials: dict,
        # The copy to publish, already resolved (platform override → global →
        # generation_prompt fallback) and clamped to this platform's limit by
        # captions.resolve_for_platform. Adapters must publish this and never
        # reach for piece.generation_prompt: that field is the *image
        # generation* prompt, and publishing it was a live defect.
        caption: str = "",
    ) -> PublishResult:
        ...
```

to:

```python
class PublisherAdapter(ABC):
    platform: str
    # Overridden to True by the adapters that implement fetch_insights below.
    # The insights-collection pass checks this before ever calling
    # fetch_insights, so an adapter that never overrides it is simply
    # skipped rather than hitting the NotImplementedError default.
    supports_insights: bool = False

    @abstractmethod
    def check_compatibility(self, piece: ContentPiece, asset: ContentAsset) -> None:
        ...

    @abstractmethod
    def publish(
        self,
        piece: ContentPiece,
        asset: ContentAsset,
        account: ContentSocialAccount,
        credentials: dict,
        # The copy to publish, already resolved (platform override → global →
        # generation_prompt fallback) and clamped to this platform's limit by
        # captions.resolve_for_platform. Adapters must publish this and never
        # reach for piece.generation_prompt: that field is the *image
        # generation* prompt, and publishing it was a live defect.
        caption: str = "",
    ) -> PublishResult:
        ...

    def fetch_insights(
        self,
        publication: ContentSocialPublication,
        account: ContentSocialAccount,
        credentials: dict,
    ) -> InsightsResult:
        """Engagement telemetry for one already-published post.

        Not abstract: only the six platforms with supports_insights = True
        override this. Errors are raised as PublicationError with the same
        codes publish() uses, so the collection pass's retry/give-up logic
        needs no separate taxonomy.
        """
        raise NotImplementedError(f"{self.platform} does not support fetch_insights")
```

- [ ] **Step 3: Verify it imports and instantiates**

Run:
```bash
python3 -c "
from app.services.content.publishers.base import InsightsResult, PublisherAdapter
r = InsightsResult(likes=5)
print(r.likes, r.reach, r.raw)
print(PublisherAdapter.supports_insights)
"
```
Expected: `5 None {}` then `False`, no traceback.

- [ ] **Step 4: Run the full existing publisher test suite to confirm nothing broke**

Run: `python3 -m pytest test/services/test_content_publishers_base.py test/services/test_content_publishers_instagram.py test/services/test_content_publishers_facebook.py test/services/test_content_publishers_linkedin.py test/services/test_content_publishers_x.py test/services/test_content_publishers_tiktok.py -v`
Expected: all PASS (the import of `ContentSocialPublication` in `base.py` must not create a circular import — `content_publishing.py` has no dependency back on `publishers/`, so it will not).

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publishers/base.py
git commit -m "feat(content): add the fetch_insights capability hook to PublisherAdapter"
```

---

## Task 3: Instagram `fetch_insights`

**Files:**
- Modify: `app/services/content/publishers/instagram.py`
- Test: `test/services/test_content_publishers_instagram.py`

**Interfaces:**
- Consumes: `InsightsResult` from `app.services.content.publishers.base` (Task 2); `get_json` (already imported in this file).
- Produces: `InstagramAdapter.supports_insights = True`, `InstagramAdapter().fetch_insights(publication, account, credentials) -> InsightsResult`.

Instagram's media node (`GET /{media-id}?fields=like_count,comments_count`) gives likes/comments for any media type; reach is a separate call (`GET /{media-id}/insights?metric=reach`). No reliable share count exists across every IG media type (only Reels expose one, inconsistently), so `shares` stays `None`.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_publishers_instagram.py` (add `InsightsResult` to the existing import line from `base`, and add a `_publication` factory alongside `_piece`/`_asset`/`_account`):

```python
from app.services.content.publishers.base import InsightsResult
```

```python
def _publication(**overrides):
    base = dict(platform_post_id="17900000000000000")
    base.update(overrides)
    return MagicMock(**base)


class TestInstagramFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(InstagramAdapter.supports_insights)

    def test_maps_canonical_response(self):
        fields_response = {"id": "media-1", "like_count": 12, "comments_count": 3}
        insights_response = {"data": [{"name": "reach", "values": [{"value": 240}]}]}

        with patch(
            "app.services.content.publishers.instagram.get_json",
            side_effect=[fields_response, insights_response],
        ) as get_json:
            result = InstagramAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsInstance(result, InsightsResult)
        self.assertEqual(result.reach, 240)
        self.assertEqual(result.likes, 12)
        self.assertEqual(result.comments, 3)
        self.assertIsNone(result.shares)
        self.assertEqual(get_json.call_count, 2)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.instagram.get_json",
            side_effect=PublicationError(
                PublicationErrorCode.invalid_credentials, "no scope"
            ),
        ):
            with self.assertRaises(PublicationError) as ctx:
                InstagramAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_publishers_instagram.py -k FetchInsights -v`
Expected: FAIL — `AttributeError: 'InstagramAdapter' object has no attribute 'fetch_insights'` is inherited from the base default, so `test_declares_support` fails first (`supports_insights` is `False` by default) and the mapping test fails with `NotImplementedError`.

- [ ] **Step 3: Implement**

In `app/services/content/publishers/instagram.py`, after `check_compatibility` and before `publish`, or anywhere inside the class after `publish` — add at the end of the class body, before `register_adapter(InstagramAdapter())`:

```python
    supports_insights = True

    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        media_id = publication.platform_post_id

        fields = get_json(
            f"{_GRAPH_API_BASE}/{media_id}",
            params={
                "fields": "like_count,comments_count",
                "access_token": access_token,
            },
        )
        insights = get_json(
            f"{_GRAPH_API_BASE}/{media_id}/insights",
            params={"metric": "reach", "access_token": access_token},
        )
        reach = insights["data"][0]["values"][0]["value"]

        return InsightsResult(
            reach=reach,
            likes=fields.get("like_count"),
            comments=fields.get("comments_count"),
            # No share count is reliable across every IG media type (only
            # Reels expose one, inconsistently) — left None rather than
            # guessed.
            raw={"fields": fields, "insights": insights},
        )
```

Note `supports_insights = True` is a class-body assignment, placed as a class attribute alongside `platform = "instagram"` (move it there, right under `platform = "instagram"`, not inside a method).

Add `InsightsResult` to the existing import from `base`:

```python
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_json,
    post_form,
    register_adapter,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_publishers_instagram.py -v`
Expected: all PASS, including the pre-existing `TestInstagramCompatibility`/`TestInstagramPublish` classes (unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publishers/instagram.py test/services/test_content_publishers_instagram.py
git commit -m "feat(content): add Instagram fetch_insights"
```

---

## Task 4: Facebook `fetch_insights`

**Files:**
- Modify: `app/services/content/publishers/facebook.py`
- Test: `test/services/test_content_publishers_facebook.py`

**Interfaces:**
- Consumes: `InsightsResult` (Task 2).
- Produces: `FacebookAdapter.supports_insights = True`, `FacebookAdapter().fetch_insights(...)`.

Facebook's post node (`GET /{post-id}?fields=likes.summary(true),comments.summary(true),shares`) gives likes/comments/shares; reach is `GET /{post-id}/insights?metric=post_impressions_unique` — Facebook's one genuinely unique-people metric, alongside Instagram's `reach`.

- [ ] **Step 1: Write the failing tests**

The file already defines `_piece`/`_asset` locally (it does not import Instagram's). Append:

```python
from app.services.content.publishers.base import InsightsResult
```

This file has no `_account()` factory yet (unlike `test_content_publishers_instagram.py`) — add one alongside the new `_publication()`:

```python
def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="1234567890_987654321")
    base.update(overrides)
    return MagicMock(**base)


class TestFacebookFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(FacebookAdapter.supports_insights)

    def test_maps_canonical_response(self):
        fields = {
            "likes": {"summary": {"total_count": 20}},
            "comments": {"summary": {"total_count": 5}},
            "shares": {"count": 7},
        }
        insights = {
            "data": [
                {"name": "post_impressions_unique", "values": [{"value": 300}]}
            ]
        }

        with patch(
            "app.services.content.publishers.facebook.get_json",
            side_effect=[fields, insights],
        ) as get_json:
            result = FacebookAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertEqual(result.reach, 300)
        self.assertEqual(result.likes, 20)
        self.assertEqual(result.comments, 5)
        self.assertEqual(result.shares, 7)
        self.assertEqual(get_json.call_count, 2)

    def test_missing_shares_field_stays_none(self):
        fields = {
            "likes": {"summary": {"total_count": 4}},
            "comments": {"summary": {"total_count": 1}},
            # Facebook omits `shares` entirely on a post with zero shares —
            # it is not sent as {"count": 0}.
        }
        insights = {
            "data": [
                {"name": "post_impressions_unique", "values": [{"value": 50}]}
            ]
        }

        with patch(
            "app.services.content.publishers.facebook.get_json",
            side_effect=[fields, insights],
        ):
            result = FacebookAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsNone(result.shares)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.facebook.get_json",
            side_effect=PublicationError(PublicationErrorCode.rate_limit, "slow down"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                FacebookAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_publishers_facebook.py -k FetchInsights -v`
Expected: FAIL (`supports_insights` is `False`; `fetch_insights` raises `NotImplementedError`).

- [ ] **Step 3: Implement**

In `app/services/content/publishers/facebook.py`, add `get_json` to the existing import:

```python
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_json,
    post_form,
    register_adapter,
)
```

Add `supports_insights = True` right under `platform = "facebook"`, and add the method before `register_adapter(FacebookAdapter())`:

```python
    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        post_id = publication.platform_post_id

        fields = get_json(
            f"{_GRAPH_API_BASE}/{post_id}",
            params={
                "fields": "likes.summary(true),comments.summary(true),shares",
                "access_token": access_token,
            },
        )
        insights = get_json(
            f"{_GRAPH_API_BASE}/{post_id}/insights",
            params={"metric": "post_impressions_unique", "access_token": access_token},
        )
        reach = insights["data"][0]["values"][0]["value"]

        return InsightsResult(
            reach=reach,
            likes=fields.get("likes", {}).get("summary", {}).get("total_count"),
            comments=fields.get("comments", {}).get("summary", {}).get("total_count"),
            shares=fields.get("shares", {}).get("count"),
            raw={"fields": fields, "insights": insights},
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_publishers_facebook.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publishers/facebook.py test/services/test_content_publishers_facebook.py
git commit -m "feat(content): add Facebook fetch_insights"
```

---

## Task 5: LinkedIn `fetch_insights`

**Files:**
- Modify: `app/services/content/publishers/linkedin.py`
- Test: `test/services/test_content_publishers_linkedin.py`

**Interfaces:**
- Consumes: `InsightsResult` (Task 2).
- Produces: `LinkedInAdapter.supports_insights = True`, `LinkedInAdapter().fetch_insights(...)`.

LinkedIn has no unique-reach metric at the post level — `impressionCount` from `organizationalEntityShareStatistics` is the volume figure, which is why LinkedIn is one of the four platforms substituted into the reach tile as impressions. Likes/comments come from `GET /socialActions/{shareUrn}`.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_publishers_linkedin.py`:

```python
from app.services.content.publishers.base import InsightsResult
```

This file has no `_account()` factory yet — add one alongside the new `_publication()`:

```python
def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="urn:li:share:123")
    base.update(overrides)
    return MagicMock(**base)


class TestLinkedInFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(LinkedInAdapter.supports_insights)

    def test_maps_canonical_response(self):
        social_actions = {
            "likesSummary": {"totalLikes": 8},
            "commentsSummary": {"aggregatedTotalComments": 2},
        }
        statistics = {
            "results": {
                "urn:li:share:123": {
                    "totalShareStatistics": {
                        "impressionCount": 500,
                        "shareCount": 4,
                    }
                }
            }
        }

        with patch(
            "app.services.content.publishers.linkedin.get_json",
            side_effect=[social_actions, statistics],
        ) as get_json:
            result = LinkedInAdapter().fetch_insights(
                _publication(),
                _account(),
                {"access_token": "tok", "author_urn": "urn:li:organization:1"},
            )

        self.assertIsNone(result.reach)
        self.assertEqual(result.impressions, 500)
        self.assertEqual(result.likes, 8)
        self.assertEqual(result.comments, 2)
        self.assertEqual(result.shares, 4)
        self.assertEqual(get_json.call_count, 2)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.linkedin.get_json",
            side_effect=PublicationError(PublicationErrorCode.transient, "blip"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                LinkedInAdapter().fetch_insights(
                    _publication(),
                    _account(),
                    {"access_token": "tok", "author_urn": "urn:li:organization:1"},
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_publishers_linkedin.py -k FetchInsights -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `app/services/content/publishers/linkedin.py`, add `get_json` to the import and two new URL constants near `_REGISTER_UPLOAD_URL`/`_UGC_POSTS_URL`:

```python
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_bytes,
    get_json,
    post_json,
    raise_for_response,
    register_adapter,
)

_REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"
_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
_SOCIAL_ACTIONS_URL = "https://api.linkedin.com/v2/socialActions"
_SHARE_STATISTICS_URL = "https://api.linkedin.com/v2/organizationalEntityShareStatistics"
```

Add `supports_insights = True` under `platform = "linkedin"`, and add the method before `register_adapter(LinkedInAdapter())`:

```python
    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        author_urn = credentials["author_urn"]
        share_urn = publication.platform_post_id
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        social_actions = get_json(f"{_SOCIAL_ACTIONS_URL}/{share_urn}", headers=headers)
        statistics = get_json(
            _SHARE_STATISTICS_URL,
            params={
                "q": "organizationalEntity",
                "organizationalEntity": author_urn,
                "shares[0]": share_urn,
            },
            headers=headers,
        )
        stats_row = (
            statistics.get("results", {}).get(share_urn, {}).get("totalShareStatistics", {})
        )

        return InsightsResult(
            # LinkedIn's post-level API has no unique-reach metric —
            # impressionCount is the volume figure it publishes, which is
            # why reach stays None and this platform gets substituted.
            impressions=stats_row.get("impressionCount"),
            likes=social_actions.get("likesSummary", {}).get("totalLikes"),
            comments=social_actions.get("commentsSummary", {}).get(
                "aggregatedTotalComments"
            ),
            shares=stats_row.get("shareCount"),
            raw={"social_actions": social_actions, "statistics": statistics},
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_publishers_linkedin.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publishers/linkedin.py test/services/test_content_publishers_linkedin.py
git commit -m "feat(content): add LinkedIn fetch_insights"
```

---

## Task 6: X `fetch_insights`

**Files:**
- Modify: `app/services/content/publishers/x.py`
- Test: `test/services/test_content_publishers_x.py`

**Interfaces:**
- Consumes: `InsightsResult` (Task 2).
- Produces: `XAdapter.supports_insights = True`, `XAdapter().fetch_insights(...)`.

`GET /2/tweets/{id}?tweet.fields=public_metrics` returns `like_count`, `reply_count`, `retweet_count`, `quote_count`, `impression_count` in one call. X has no unique-reach metric; `impression_count` is the volume figure. `shares` is the sum of retweets and quote-tweets — both are a share of the original post.

- [ ] **Step 1: Write the failing tests**

The file already defines `_piece`/`_asset` locally. Append to `test/services/test_content_publishers_x.py`:

```python
from app.services.content.publishers.base import InsightsResult
```

This file has no `_account()` factory yet — add one alongside the new `_publication()`:

```python
def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="1700000000000000000")
    base.update(overrides)
    return MagicMock(**base)


class TestXFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(XAdapter.supports_insights)

    def test_maps_canonical_response(self):
        response = {
            "data": {
                "public_metrics": {
                    "like_count": 10,
                    "reply_count": 2,
                    "retweet_count": 3,
                    "quote_count": 1,
                    "impression_count": 700,
                }
            }
        }

        with patch(
            "app.services.content.publishers.x.get_json", return_value=response
        ) as get_json:
            result = XAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsNone(result.reach)
        self.assertEqual(result.impressions, 700)
        self.assertEqual(result.likes, 10)
        self.assertEqual(result.comments, 2)
        self.assertEqual(result.shares, 4)  # retweets + quote tweets
        get_json.assert_called_once()

    def test_no_retweet_or_quote_data_leaves_shares_none(self):
        response = {
            "data": {
                "public_metrics": {
                    "like_count": 1,
                    "reply_count": 0,
                    "impression_count": 20,
                }
            }
        }

        with patch(
            "app.services.content.publishers.x.get_json", return_value=response
        ):
            result = XAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsNone(result.shares)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.x.get_json",
            side_effect=PublicationError(
                PublicationErrorCode.invalid_credentials, "no scope"
            ),
        ):
            with self.assertRaises(PublicationError) as ctx:
                XAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_publishers_x.py -k FetchInsights -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `app/services/content/publishers/x.py`, add `get_json` to the import and a `_TWEETS_URL` constant is already present (reused):

```python
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_bytes,
    get_json,
    post_form,
    post_json,
    register_adapter,
)
```

Add `supports_insights = True` under `platform = "x"`, and the method before `register_adapter(XAdapter())`:

```python
    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        tweet_id = publication.platform_post_id

        response = get_json(
            f"{_TWEETS_URL}/{tweet_id}",
            params={"tweet.fields": "public_metrics"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        metrics = response["data"]["public_metrics"]
        retweets = metrics.get("retweet_count")
        quotes = metrics.get("quote_count")
        # X counts retweets and quote-tweets separately; both are a share of
        # the original post, so this adapter reports their sum. None only
        # when the API returns neither field at all.
        shares = None if retweets is None and quotes is None else (retweets or 0) + (quotes or 0)

        return InsightsResult(
            # X's public API has no unique-reach metric — impression_count is
            # the volume figure, which is why reach stays None here.
            impressions=metrics.get("impression_count"),
            likes=metrics.get("like_count"),
            comments=metrics.get("reply_count"),
            shares=shares,
            raw=response,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_publishers_x.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publishers/x.py test/services/test_content_publishers_x.py
git commit -m "feat(content): add X fetch_insights"
```

---

## Task 7: TikTok `fetch_insights`

**Files:**
- Modify: `app/services/content/publishers/tiktok.py`
- Test: `test/services/test_content_publishers_tiktok.py`

**Interfaces:**
- Consumes: `InsightsResult` (Task 2).
- Produces: `TikTokAdapter.supports_insights = True`, `TikTokAdapter().fetch_insights(...)`.

`POST /v2/video/query/?fields=like_count,comment_count,share_count,view_count` with `{"filters": {"video_ids": [id]}}` returns `data.videos[0]`. No unique-reach metric; `view_count` is the volume figure.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_publishers_tiktok.py`:

```python
from app.services.content.publishers.base import InsightsResult
```

This file has no `_account()` factory yet — add one alongside the new `_publication()`:

```python
def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="v-1")
    base.update(overrides)
    return MagicMock(**base)


class TestTikTokFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(TikTokAdapter.supports_insights)

    def test_maps_canonical_response(self):
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "videos": [
                    {
                        "like_count": 40,
                        "comment_count": 5,
                        "share_count": 2,
                        "view_count": 900,
                    }
                ]
            }
        }

        with patch(
            "app.services.content.publishers.tiktok.post_json", return_value=response
        ) as post_json:
            result = TikTokAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsNone(result.reach)
        self.assertEqual(result.impressions, 900)
        self.assertEqual(result.likes, 40)
        self.assertEqual(result.comments, 5)
        self.assertEqual(result.shares, 2)
        post_json.assert_called_once()

    def test_no_video_returned_is_invalid_params(self):
        response = MagicMock()
        response.json.return_value = {"data": {"videos": []}}

        with patch(
            "app.services.content.publishers.tiktok.post_json", return_value=response
        ):
            with self.assertRaises(PublicationError) as ctx:
                TikTokAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.tiktok.post_json",
            side_effect=PublicationError(PublicationErrorCode.rate_limit, "slow down"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                TikTokAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_publishers_tiktok.py -k FetchInsights -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `app/services/content/publishers/tiktok.py`, add `InsightsResult` to the import and a new URL constant:

```python
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    post_json,
    register_adapter,
)

_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
_QUERY_VIDEOS_URL = "https://open.tiktokapis.com/v2/video/query/"
```

Add `supports_insights = True` under `platform = "tiktok"`, and the method before `register_adapter(TikTokAdapter())`:

```python
    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        video_id = publication.platform_post_id
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        response = post_json(
            f"{_QUERY_VIDEOS_URL}?fields=like_count,comment_count,share_count,view_count",
            {"filters": {"video_ids": [video_id]}},
            headers=headers,
        ).json()
        videos = response["data"]["videos"]
        if not videos:
            raise PublicationError(
                PublicationErrorCode.invalid_params,
                f"TikTok returned no video for id {video_id}",
            )
        video = videos[0]

        return InsightsResult(
            # No unique-reach metric in this API — view_count is the volume
            # figure, which is why reach stays None here.
            impressions=video.get("view_count"),
            likes=video.get("like_count"),
            comments=video.get("comment_count"),
            shares=video.get("share_count"),
            raw=response,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_publishers_tiktok.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publishers/tiktok.py test/services/test_content_publishers_tiktok.py
git commit -m "feat(content): add TikTok fetch_insights"
```

---

## Task 8: YouTube `fetch_insights`

**Files:**
- Modify: `app/services/content/publishers/youtube.py`
- Test: `test/services/test_content_publishers_youtube.py` (new — no test file exists for this adapter yet)

**Interfaces:**
- Consumes: `InsightsResult` (Task 2).
- Produces: `YouTubeAdapter.supports_insights = True`, `YouTubeAdapter().fetch_insights(...)`.

`GET /youtube/v3/videos?part=statistics&id={id}` returns `items[0].statistics` with `viewCount`/`likeCount`/`commentCount` **as strings** (a real quirk of this API — cast to `int`). No share count and no unique-reach metric in the Data API v3.

- [ ] **Step 1: Write the failing tests**

There is no existing test file for the YouTube adapter. Create `test/services/test_content_publishers_youtube.py`, matching `test_content_publishers_facebook.py`'s structure (compatibility class + fetch-insights class; no publish test is required by this task — `publish()` is unchanged and untested today, which is out of scope to backfill):

```python
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import InsightsResult
from app.services.content.publishers.youtube import YouTubeAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.video, generation_prompt="a dog")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.mp4"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="yt-1")
    base.update(overrides)
    return MagicMock(**base)


class TestYouTubeCompatibility(unittest.TestCase):
    def test_video_is_compatible(self):
        YouTubeAdapter().check_compatibility(_piece(type=ContentPieceType.video), _asset())

    def test_image_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            YouTubeAdapter().check_compatibility(_piece(type=ContentPieceType.image), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestYouTubeFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(YouTubeAdapter.supports_insights)

    def test_maps_canonical_response(self):
        response = {
            "items": [
                {
                    "statistics": {
                        "viewCount": "1500",
                        "likeCount": "80",
                        "commentCount": "12",
                    }
                }
            ]
        }

        with patch(
            "app.services.content.publishers.youtube.get_json", return_value=response
        ) as get_json:
            result = YouTubeAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsInstance(result, InsightsResult)
        self.assertIsNone(result.reach)
        self.assertEqual(result.impressions, 1500)
        self.assertEqual(result.likes, 80)
        self.assertEqual(result.comments, 12)
        self.assertIsNone(result.shares)
        get_json.assert_called_once()

    def test_no_items_is_invalid_params(self):
        with patch(
            "app.services.content.publishers.youtube.get_json",
            return_value={"items": []},
        ):
            with self.assertRaises(PublicationError) as ctx:
                YouTubeAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.youtube.get_json",
            side_effect=PublicationError(PublicationErrorCode.transient, "blip"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                YouTubeAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_publishers_youtube.py -v`
Expected: the two compatibility tests PASS (unchanged existing behavior); the three `FetchInsights` tests FAIL.

- [ ] **Step 3: Implement**

In `app/services/content/publishers/youtube.py`, add `get_json` to the import and a new URL constant:

```python
from app.services.content.publishers.base import (
    PublisherAdapter,
    PublishResult,
    InsightsResult,
    get_bytes,
    get_json,
    raise_for_response,
    register_adapter,
)

_UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?uploadType=multipart&part=snippet,status"
)
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
```

Add `supports_insights = True` under `platform = "youtube"`, and the method before `register_adapter(YouTubeAdapter())`:

```python
    def fetch_insights(self, publication, account, credentials) -> InsightsResult:
        access_token = credentials["access_token"]
        video_id = publication.platform_post_id

        response = get_json(
            _VIDEOS_URL,
            params={"part": "statistics", "id": video_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        items = response.get("items") or []
        if not items:
            raise PublicationError(
                PublicationErrorCode.invalid_params,
                f"YouTube returned no video for id {video_id}",
            )
        statistics = items[0]["statistics"]

        return InsightsResult(
            # No share count and no unique-reach metric in the YouTube Data
            # API v3 — viewCount is the only volume figure it publishes.
            # Every count field comes back as a string, a real quirk of this
            # API, hence the int() casts.
            impressions=int(statistics["viewCount"]) if "viewCount" in statistics else None,
            likes=int(statistics["likeCount"]) if "likeCount" in statistics else None,
            comments=(
                int(statistics["commentCount"]) if "commentCount" in statistics else None
            ),
            raw=response,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_publishers_youtube.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/publishers/youtube.py test/services/test_content_publishers_youtube.py
git commit -m "feat(content): add YouTube fetch_insights and its first test file"
```

---

## Task 9: `due_for_collection` — the collection cadence

**Files:**
- Create: `app/services/content/insights_collection.py`
- Test: `test/services/test_content_insights_collection.py`

**Interfaces:**
- Produces: `due_for_collection(*, completed_at: datetime, last_collected_at: Optional[datetime], now: datetime) -> bool`. Task 11 (the pass) calls this directly.

Pure function — decreasing cadence anchored on `completed_at`: 6h through 48h, 24h through 7 days, 72h through 14 days, then never again.

- [ ] **Step 1: Write the failing tests**

Create `test/services/test_content_insights_collection.py`:

```python
import unittest
from datetime import datetime, timedelta

from app.services.content.insights_collection import due_for_collection


class TestDueForCollection(unittest.TestCase):
    def test_never_collected_within_first_window_is_due(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=1)

        self.assertTrue(
            due_for_collection(completed_at=completed_at, last_collected_at=None, now=now)
        )

    def test_collected_recently_within_six_hour_band_is_not_due(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=10)
        last_collected_at = now - timedelta(minutes=10)

        self.assertFalse(
            due_for_collection(
                completed_at=completed_at, last_collected_at=last_collected_at, now=now
            )
        )

    def test_collected_exactly_one_interval_ago_is_due(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=10)  # inside the 6h band
        last_collected_at = now - timedelta(hours=6)

        self.assertTrue(
            due_for_collection(
                completed_at=completed_at, last_collected_at=last_collected_at, now=now
            )
        )

    def test_at_exactly_48_hours_still_uses_the_six_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=48)

        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=5, minutes=59),
                now=now,
            )
        )
        self.assertTrue(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=6),
                now=now,
            )
        )

    def test_just_past_48_hours_uses_the_24_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=48, minutes=1)

        # Only 6h since the last collection — not due yet in the 24h band.
        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=6),
                now=now,
            )
        )

    def test_at_exactly_7_days_still_uses_the_24_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=7)

        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=23, minutes=59),
                now=now,
            )
        )

    def test_just_past_7_days_uses_the_72_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=7, minutes=1)

        # Only 25h since the last collection — not due yet in the 72h band.
        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=25),
                now=now,
            )
        )

    def test_at_exactly_14_days_is_still_eligible(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=14)

        self.assertTrue(
            due_for_collection(completed_at=completed_at, last_collected_at=None, now=now)
        )

    def test_just_past_14_days_is_never_due_again(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=14, minutes=1)

        self.assertFalse(
            due_for_collection(completed_at=completed_at, last_collected_at=None, now=now)
        )
        # Even a stale last_collected_at can't make a post past the window due.
        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(days=10),
                now=now,
            )
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_insights_collection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.content.insights_collection'`.

- [ ] **Step 3: Implement**

Create `app/services/content/insights_collection.py`:

```python
"""Passe 4 do automation_scheduler: coleta de engajamento pós-publicação.

Ver docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md.

due_for_collection é a única lógica de agendamento e é pura: nada além dos
próprios snapshots de content_publication_insights é persistido para decidir
quando recoletar — a decisão é sempre derivada de completed_at e do
collected_at mais recente já gravado.
"""
from datetime import datetime, timedelta
from typing import Optional

# Cadência decrescente: quase todo engajamento acontece nos primeiros dias.
# Cada tupla é (fim da janela, intervalo dentro dela), checadas em ordem —
# a primeira janela em que a idade do post cabe decide o intervalo.
INSIGHTS_WINDOW_DAYS = 14

_CADENCE = (
    (timedelta(hours=48), timedelta(hours=6)),
    (timedelta(days=7), timedelta(hours=24)),
    (timedelta(days=INSIGHTS_WINDOW_DAYS), timedelta(hours=72)),
)


def due_for_collection(
    *,
    completed_at: datetime,
    last_collected_at: Optional[datetime],
    now: datetime,
) -> bool:
    """Se uma publicação deve ser recoletada agora.

    completed_at é quando o post foi ao ar; last_collected_at é a última vez
    que uma coleta (sucesso ou erro) foi tentada, ou None se nunca foi.
    """
    age = now - completed_at
    interval = None
    for window, band_interval in _CADENCE:
        if age <= window:
            interval = band_interval
            break
    if interval is None:
        return False
    if last_collected_at is None:
        return True
    return now - last_collected_at >= interval
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_insights_collection.py -v`
Expected: all 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/insights_collection.py test/services/test_content_insights_collection.py
git commit -m "feat(content): add due_for_collection, the insights collection cadence"
```

---

## Task 10: `_fetch_insights_with_retry` — retrying only what a retry can fix

**Files:**
- Modify: `app/services/content/insights_collection.py`
- Modify: `test/services/test_content_insights_collection.py`

**Interfaces:**
- Consumes: `retry.MAX_ATTEMPTS`, `retry.backoff_delay` (`app.services.content.retry`, unmodified); `PublicationError`, `is_retryable` (`app.services.content.publish_errors`, unmodified).
- Produces: `_fetch_insights_with_retry(adapter, publication, account, credentials) -> InsightsResult`. Task 11 (the pass) calls this instead of `adapter.fetch_insights(...)` directly.

`retry.run_with_retry` cannot be reused (see Global Constraints — it only catches `GenerationError`). This reimplements the same backoff shape for `PublicationError`, reusing the pure `backoff_delay` helper and the publish taxonomy's own `is_retryable`.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_insights_collection.py`:

```python
from unittest.mock import MagicMock, patch

from app.services.content import insights_collection, retry
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import InsightsResult


class TestFetchInsightsWithRetry(unittest.TestCase):
    def test_returns_result_on_first_success(self):
        adapter = MagicMock()
        adapter.fetch_insights.return_value = InsightsResult(likes=1)

        with patch("app.services.content.insights_collection.time.sleep") as sleep:
            result = insights_collection._fetch_insights_with_retry(
                adapter, MagicMock(), MagicMock(), {}
            )

        self.assertEqual(result.likes, 1)
        sleep.assert_not_called()

    def test_retries_transient_then_succeeds(self):
        adapter = MagicMock()
        adapter.fetch_insights.side_effect = [
            PublicationError(PublicationErrorCode.transient, "blip"),
            InsightsResult(likes=2),
        ]

        with patch("app.services.content.insights_collection.time.sleep") as sleep:
            result = insights_collection._fetch_insights_with_retry(
                adapter, MagicMock(), MagicMock(), {}
            )

        self.assertEqual(result.likes, 2)
        sleep.assert_called_once()

    def test_non_retryable_raises_immediately_without_sleeping(self):
        adapter = MagicMock()
        adapter.fetch_insights.side_effect = PublicationError(
            PublicationErrorCode.invalid_credentials, "no scope"
        )

        with patch("app.services.content.insights_collection.time.sleep") as sleep:
            with self.assertRaises(PublicationError) as ctx:
                insights_collection._fetch_insights_with_retry(
                    adapter, MagicMock(), MagicMock(), {}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)
        sleep.assert_not_called()
        self.assertEqual(adapter.fetch_insights.call_count, 1)

    def test_retryable_exhausted_raises_last_error(self):
        adapter = MagicMock()
        adapter.fetch_insights.side_effect = PublicationError(
            PublicationErrorCode.rate_limit, "slow down"
        )

        with patch("app.services.content.insights_collection.time.sleep"):
            with self.assertRaises(PublicationError) as ctx:
                insights_collection._fetch_insights_with_retry(
                    adapter, MagicMock(), MagicMock(), {}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)
        self.assertEqual(adapter.fetch_insights.call_count, retry.MAX_ATTEMPTS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_insights_collection.py -k FetchInsightsWithRetry -v`
Expected: FAIL with `AttributeError: module 'app.services.content.insights_collection' has no attribute '_fetch_insights_with_retry'`.

- [ ] **Step 3: Implement**

In `app/services/content/insights_collection.py`, add imports and the function. Change the top of the file to:

```python
"""Passe 4 do automation_scheduler: coleta de engajamento pós-publicação.

Ver docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md.

due_for_collection é a única lógica de agendamento e é pura: nada além dos
próprios snapshots de content_publication_insights é persistido para decidir
quando recoletar — a decisão é sempre derivada de completed_at e do
collected_at mais recente já gravado.

retry.run_with_retry não serve aqui: está amarrado a GenerationError (a
taxonomia de geração de mídia em app/services/content/errors.py), não a
PublicationError (a taxonomia de publicação, usada por este passe).
_fetch_insights_with_retry reimplementa a mesma forma de backoff
reaproveitando a função pura retry.backoff_delay e o is_retryable da própria
taxonomia de publicação.
"""
import time
from datetime import datetime, timedelta
from typing import Optional

from app.services.content import retry
from app.services.content.publish_errors import PublicationError, is_retryable
from app.services.content.publishers.base import InsightsResult
```

Then, after `due_for_collection`, add:

```python
def _fetch_insights_with_retry(adapter, publication, account, credentials) -> InsightsResult:
    """Repete só as falhas que dependem do momento (rate_limit/transient),
    dentro deste tick. Esgotando as tentativas, ou diante de uma falha
    não-retryable, propaga — quem chama grava o snapshot de erro."""
    last_error: Optional[PublicationError] = None
    for attempt in range(1, retry.MAX_ATTEMPTS + 1):
        try:
            return adapter.fetch_insights(publication, account, credentials)
        except PublicationError as error:
            last_error = error
            if not is_retryable(error.code) or attempt == retry.MAX_ATTEMPTS:
                raise
            time.sleep(retry.backoff_delay(attempt))
    raise last_error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_insights_collection.py -v`
Expected: all 13 PASS (9 from Task 9 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add app/services/content/insights_collection.py test/services/test_content_insights_collection.py
git commit -m "feat(content): add the PublicationError-aware retry wrapper for insights collection"
```

---

## Task 11: `collect_publication_insights` — the pass, and wiring it into the scheduler

**Files:**
- Modify: `app/services/content/insights_collection.py`
- Modify: `app/services/content/automation_scheduler.py`
- Modify: `test/services/test_content_insights_collection.py`

**Interfaces:**
- Consumes: `due_for_collection`, `_fetch_insights_with_retry` (Task 9/10, same file); `get_adapter`, `load_credentials` (`app.services.content.publishers.base`, unmodified); `ContentPublicationInsight` (Task 1); `ContentSocialPublication`, `PublicationStatus` (`app.models.content_publishing`, unmodified); `ContentSocialAccount` (`app.models.content`, unmodified).
- Produces: `collect_publication_insights(session: Session, *, batch_limit: int) -> None`. `automation_scheduler._tick` calls this as its fourth pass, exactly like the other three.

Same shape as the other three passes: one query for eligible rows, a per-row `try/except Exception` so one bad row can't sink the batch, `session.commit()` per row. The one addition specific to this pass: a `PublicationError` from the actual fetch is caught separately and turned into a recorded error snapshot — that is the expected, designed failure mode (see the spec's Degradação section), not a bug to swallow into the generic catch-all.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_insights_collection.py`. This follows `test_content_automation_scheduler.py`'s own integration-test fixture shape exactly (real sqlite in-memory engine, `SQLModel.metadata.create_all`):

```python
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import content_insights  # noqa: F401  (registra a tabela no metadata)
from app.models.content import ContentClient, ContentSocialAccount, ContentTenant
from app.models.content_insights import ContentPublicationInsight
from app.models.content_publishing import ContentSocialPublication, PublicationStatus


class TestCollectPublicationInsights(unittest.TestCase):
    def _session(self):
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        session = Session(engine)
        tenant = ContentTenant(
            owner_user_id="u1", name="T", slug="t", api_token_hash="h"
        )
        session.add(tenant)
        session.commit()
        client = ContentClient(tenant_id=tenant.id, name="C")
        session.add(client)
        session.commit()
        account = ContentSocialAccount(
            client_id=client.id,
            platform="instagram",
            external_account_id="ig-1",
            credentials_encrypted="irrelevant-for-this-test",
        )
        session.add(account)
        session.commit()
        publication = ContentSocialPublication(
            tenant_id=tenant.id,
            client_id=client.id,
            content_piece_id=1,
            social_account_id=account.id,
            platform="instagram",
            status=PublicationStatus.succeeded,
            platform_post_id="media-1",
            publication_cycle=1,
            completed_at=datetime.utcnow() - timedelta(hours=1),
        )
        session.add(publication)
        session.commit()
        return session, publication, account

    def _fake_adapter(self, *, supports_insights=True, fetch_result=None, fetch_error=None):
        adapter = MagicMock()
        adapter.supports_insights = supports_insights
        if fetch_error is not None:
            adapter.fetch_insights.side_effect = fetch_error
        else:
            adapter.fetch_insights.return_value = fetch_result or InsightsResult(likes=5)
        return adapter

    def test_successful_collection_writes_a_snapshot(self):
        session, publication, account = self._session()
        adapter = self._fake_adapter(
            fetch_result=InsightsResult(reach=100, likes=5, comments=1, shares=0)
        )

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            with patch.object(insights_collection, "load_credentials", return_value={}):
                insights_collection.collect_publication_insights(session, batch_limit=50)

        rows = session.exec(select(ContentPublicationInsight)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].publication_id, publication.id)
        self.assertEqual(rows[0].reach, 100)
        self.assertEqual(rows[0].likes, 5)
        self.assertIsNone(rows[0].error_code)

    def test_fetch_failure_writes_an_error_snapshot_not_a_crash(self):
        session, publication, account = self._session()
        adapter = self._fake_adapter(
            fetch_error=PublicationError(
                PublicationErrorCode.invalid_credentials, "missing scope"
            )
        )

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            with patch.object(insights_collection, "load_credentials", return_value={}):
                with patch.object(insights_collection.time, "sleep"):
                    insights_collection.collect_publication_insights(session, batch_limit=50)

        rows = session.exec(select(ContentPublicationInsight)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].error_code, "invalid_credentials")
        self.assertIsNone(rows[0].reach)
        self.assertIsNone(rows[0].likes)

    def test_platform_without_insights_support_is_skipped(self):
        session, publication, account = self._session()
        adapter = self._fake_adapter(supports_insights=False)

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            insights_collection.collect_publication_insights(session, batch_limit=50)

        adapter.fetch_insights.assert_not_called()
        self.assertEqual(session.exec(select(ContentPublicationInsight)).all(), [])

    def test_publication_not_yet_due_is_skipped(self):
        session, publication, account = self._session()
        # A snapshot collected 10 minutes ago, well inside the 6h band for a
        # 1-hour-old post — the next collection is not due yet.
        session.add(
            ContentPublicationInsight(
                tenant_id=publication.tenant_id,
                client_id=publication.client_id,
                content_piece_id=publication.content_piece_id,
                publication_id=publication.id,
                social_account_id=account.id,
                platform="instagram",
                publication_cycle=1,
                collected_at=datetime.utcnow() - timedelta(minutes=10),
                likes=1,
            )
        )
        session.commit()
        adapter = self._fake_adapter()

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            insights_collection.collect_publication_insights(session, batch_limit=50)

        adapter.fetch_insights.assert_not_called()
        self.assertEqual(len(session.exec(select(ContentPublicationInsight)).all()), 1)
```

Add `from datetime import datetime, timedelta` to the test file's imports if not already present from Task 9 (it is — reuse it), and add `from app.services.content.publish_errors import PublicationError, PublicationErrorCode` and `from app.services.content.publishers.base import InsightsResult` if not already present from Task 10 (they are).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_insights_collection.py -k CollectPublicationInsights -v`
Expected: FAIL with `AttributeError: module 'app.services.content.insights_collection' has no attribute 'collect_publication_insights'`.

- [ ] **Step 3: Implement**

In `app/services/content/insights_collection.py`, add imports (extend the existing import block):

```python
from loguru import logger
from sqlalchemy import func
from sqlmodel import Session, select

from app.models.content import ContentSocialAccount
from app.models.content_insights import ContentPublicationInsight
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content.publishers.base import get_adapter, load_credentials
```

(`InsightsResult` is already imported from Task 10 — keep it.)

Then, after `_fetch_insights_with_retry`, add:

```python
def collect_publication_insights(session: Session, *, batch_limit: int) -> None:
    """Passe 4: recoleta engajamento das publicações bem-sucedidas dos
    últimos 14 dias, respeitando a cadência de due_for_collection.

    Mesmo formato dos outros três passes: uma query pelas linhas elegíveis,
    cada item isolado em seu próprio try/except Exception (um item ruim não
    pode derrubar o passe inteiro), commit por item. A diferença específica
    deste passe: um PublicationError vindo da própria coleta é capturado à
    parte e vira um snapshot de erro gravado — é o modo de falha esperado e
    desenhado (ver a seção Degradação do design spec), não um bug pra
    engolir no catch-all genérico.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=INSIGHTS_WINDOW_DAYS)
    publications = session.exec(
        select(ContentSocialPublication)
        .where(
            ContentSocialPublication.status == PublicationStatus.succeeded,
            ContentSocialPublication.platform_post_id.is_not(None),
            ContentSocialPublication.completed_at.is_not(None),
            ContentSocialPublication.completed_at >= cutoff,
        )
        .order_by(ContentSocialPublication.id)
        .limit(batch_limit)
    ).all()

    for publication in publications:
        try:
            adapter = get_adapter(publication.platform)
            if not adapter.supports_insights:
                continue

            last_collected_at = session.exec(
                select(func.max(ContentPublicationInsight.collected_at)).where(
                    ContentPublicationInsight.publication_id == publication.id
                )
            ).one()
            if not due_for_collection(
                completed_at=publication.completed_at,
                last_collected_at=last_collected_at,
                now=now,
            ):
                continue

            account = session.get(ContentSocialAccount, publication.social_account_id)
            if account is None:
                continue
            credentials = load_credentials(account)

            try:
                result = _fetch_insights_with_retry(
                    adapter, publication, account, credentials
                )
            except PublicationError as error:
                session.add(
                    ContentPublicationInsight(
                        tenant_id=publication.tenant_id,
                        client_id=publication.client_id,
                        content_piece_id=publication.content_piece_id,
                        publication_id=publication.id,
                        social_account_id=publication.social_account_id,
                        platform=publication.platform,
                        publication_cycle=publication.publication_cycle,
                        collected_at=now,
                        error_code=error.code.value,
                        error_message=error.message,
                    )
                )
                session.commit()
                continue

            session.add(
                ContentPublicationInsight(
                    tenant_id=publication.tenant_id,
                    client_id=publication.client_id,
                    content_piece_id=publication.content_piece_id,
                    publication_id=publication.id,
                    social_account_id=publication.social_account_id,
                    platform=publication.platform,
                    publication_cycle=publication.publication_cycle,
                    collected_at=now,
                    reach=result.reach,
                    impressions=result.impressions,
                    likes=result.likes,
                    comments=result.comments,
                    shares=result.shares,
                    raw=result.raw,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.exception(
                f"publication {getattr(publication, 'id', None)}: insights collection failed"
            )
            continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_insights_collection.py -v`
Expected: all PASS (13 from Tasks 9–10 + 4 new = 17).

- [ ] **Step 5: Wire the pass into the scheduler**

In `app/services/content/automation_scheduler.py`, add one import near the other `from app.services.content import ...` lines:

```python
from app.services.content import insights_collection
```

Then in `_tick()`, change:

```python
    for name, pass_fn in (
        ("generation", _fill_campaign_calendars),
        ("approval", _evaluate_pending_approvals),
        ("publish_dispatch", _dispatch_scheduled_publications),
    ):
```

to:

```python
    for name, pass_fn in (
        ("generation", _fill_campaign_calendars),
        ("approval", _evaluate_pending_approvals),
        ("publish_dispatch", _dispatch_scheduled_publications),
        ("insights_collection", insights_collection.collect_publication_insights),
    ):
```

- [ ] **Step 6: Run the full scheduler test suite to confirm nothing broke**

Run: `python3 -m pytest test/services/test_content_automation_scheduler.py test/services/test_content_automation_scheduler_integration.py test/services/test_content_insights_collection.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/content/insights_collection.py app/services/content/automation_scheduler.py test/services/test_content_insights_collection.py
git commit -m "feat(content): add the insights-collection pass as the scheduler's fourth pass"
```

---

## Task 12: `AnalyticsTiles` reshape and the `ui_analytics` aggregation

**Files:**
- Modify: `app/models/content_analytics.py`
- Modify: `app/services/content/ui_analytics.py`
- Test: `test/services/test_content_ui_analytics.py` (new)

**Interfaces:**
- Consumes: `ContentPublicationInsight` (Task 1).
- Produces: `AnalyticsTiles` with fields `published, scheduled, failed, reach, interactions, engagement_rate, reach_substituted_accounts` (`success_rate` removed from this model only — `AccountPerformanceRead.success_rate` is untouched). `get_overview(...)` populates the new fields.

The aggregation is two pure helpers (`_pick_latest`, `_engagement_tiles`) plus a thin DB-query wrapper (`_latest_insight_by_publication`), matching this module's existing style: date/hour bucketing already happens in Python rather than SQL because "the volumes here are small" — same reasoning applies here. This is the codebase's first test file for `ui_analytics.py`; it covers only what this task adds, not a retroactive backfill of the pre-existing untested aggregation.

- [ ] **Step 1: Write the failing tests**

Create `test/services/test_content_ui_analytics.py`:

```python
import unittest
from datetime import datetime

from app.models.content_insights import ContentPublicationInsight
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content import ui_analytics


def _publication(id_, social_account_id=1):
    return ContentSocialPublication(
        id=id_,
        tenant_id=1,
        client_id=1,
        content_piece_id=1,
        social_account_id=social_account_id,
        platform="instagram",
        status=PublicationStatus.succeeded,
        publication_cycle=1,
    )


def _insight(publication_id, collected_at, **overrides):
    base = dict(
        tenant_id=1,
        client_id=1,
        content_piece_id=1,
        publication_id=publication_id,
        social_account_id=1,
        platform="instagram",
        publication_cycle=1,
        collected_at=collected_at,
    )
    base.update(overrides)
    return ContentPublicationInsight(**base)


class TestPickLatest(unittest.TestCase):
    def test_keeps_only_the_most_recent_row_per_publication(self):
        rows = [
            _insight(1, datetime(2026, 1, 1), likes=1),
            _insight(1, datetime(2026, 1, 3), likes=3),
            _insight(1, datetime(2026, 1, 2), likes=2),
            _insight(2, datetime(2026, 1, 1), likes=10),
        ]

        latest = ui_analytics._pick_latest(rows)

        self.assertEqual(len(latest), 2)
        self.assertEqual(latest[1].likes, 3)
        self.assertEqual(latest[2].likes, 10)

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(ui_analytics._pick_latest([]), {})


class TestEngagementTiles(unittest.TestCase):
    def test_no_snapshots_returns_all_none(self):
        totals = ui_analytics._engagement_tiles([_publication(1)], {})

        self.assertIsNone(totals.reach)
        self.assertIsNone(totals.interactions)
        self.assertIsNone(totals.engagement_rate)
        self.assertEqual(totals.reach_substituted_accounts, 0)

    def test_sums_reach_and_interactions_across_publications(self):
        pub1, pub2 = _publication(1, social_account_id=1), _publication(2, social_account_id=2)
        latest = {
            1: _insight(1, datetime(2026, 1, 1), reach=100, likes=5, comments=1, shares=0),
            2: _insight(2, datetime(2026, 1, 1), reach=50, likes=2, comments=0, shares=1),
        }

        totals = ui_analytics._engagement_tiles([pub1, pub2], latest)

        self.assertEqual(totals.reach, 150)
        self.assertEqual(totals.interactions, 9)
        self.assertEqual(totals.engagement_rate, round(9 / 150, 4))
        self.assertEqual(totals.reach_substituted_accounts, 0)

    def test_missing_reach_substitutes_impressions_and_counts_the_account(self):
        pub1, pub2 = _publication(1, social_account_id=1), _publication(2, social_account_id=2)
        latest = {
            # Instagram: real reach.
            1: _insight(1, datetime(2026, 1, 1), reach=100, likes=1),
            # LinkedIn-shaped: no reach, only impressions.
            2: _insight(2, datetime(2026, 1, 1), impressions=400, likes=2),
        }

        totals = ui_analytics._engagement_tiles([pub1, pub2], latest)

        self.assertEqual(totals.reach, 500)
        self.assertEqual(totals.reach_substituted_accounts, 1)

    def test_zero_reach_does_not_divide_by_zero(self):
        pub1 = _publication(1)
        latest = {1: _insight(1, datetime(2026, 1, 1), reach=0, likes=3)}

        totals = ui_analytics._engagement_tiles([pub1], latest)

        self.assertEqual(totals.reach, 0)
        self.assertEqual(totals.interactions, 3)
        self.assertIsNone(totals.engagement_rate)

    def test_publication_with_no_snapshot_is_ignored(self):
        pub1, pub2 = _publication(1), _publication(2)
        latest = {1: _insight(1, datetime(2026, 1, 1), reach=10, likes=1)}

        totals = ui_analytics._engagement_tiles([pub1, pub2], latest)

        self.assertEqual(totals.reach, 10)
        self.assertEqual(totals.interactions, 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_ui_analytics.py -v`
Expected: FAIL with `AttributeError: module 'app.services.content.ui_analytics' has no attribute '_pick_latest'` (and `_engagement_tiles`).

- [ ] **Step 3: Update `AnalyticsTiles`**

In `app/models/content_analytics.py`, change:

```python
class AnalyticsTiles(BaseModel):
    published: int
    scheduled: int
    failed: int
    # None when nothing resolved in the window — a rate over zero attempts is
    # not 0%, it is unknown, and rendering it as 0% would read as failure.
    success_rate: Optional[float]
    # Null on purpose, not zero: this system has never collected post-publish
    # telemetry. The UI renders these as "not collected yet".
    link_clicks: Optional[int] = None
    engagement: Optional[int] = None
```

to:

```python
class AnalyticsTiles(BaseModel):
    published: int
    scheduled: int
    failed: int
    # Reach (unique people) only exists on Instagram/Facebook; the other
    # four platforms only publish impressions (exposure volume, not people).
    # None when no publication in the window has a snapshot with any metric
    # yet — not zero, which would read as "the campaign got zero reach"
    # instead of "nothing collected yet".
    reach: Optional[int] = None
    interactions: Optional[int] = None
    # None whenever reach is unknown or sums to zero — a rate over zero reach
    # is not 0%, it is undefined.
    engagement_rate: Optional[float] = None
    # How many distinct social accounts in this window had their reach
    # substituted by impressions, because their platform has no unique-reach
    # metric. Feeds the reach tile's hint so the substitution stays visible
    # rather than silently blending into one number.
    reach_substituted_accounts: int = 0
```

- [ ] **Step 4: Implement the aggregation**

In `app/services/content/ui_analytics.py`, update the module docstring (it currently claims both link_clicks and engagement are absent — only link clicks remain out of scope now):

```python
"""Aggregates for the analytics dashboard.

Everything here is computed from tables that already exist. Link clicks are
still absent rather than faked — they need a URL shortener with a public
redirect route this system does not have (Instagram feed and TikTok have no
clickable link at all, and only Facebook/LinkedIn report clicks even when
one exists), which is a separate decision. Engagement (reach, interactions,
rate) IS collected, by the automation_scheduler's insights_collection pass.

Two substitutions the reference cannot make, because it does not generate the
media it publishes: generation cost (real money, from ContentGenerationJob)
and the auto-approval rate (how much of the pipeline runs without a human).
"""
```

Add imports (extend the existing block):

```python
from dataclasses import dataclass

from sqlmodel import Session, func, or_, select
```

(replacing the existing `from sqlmodel import Session, func, select` line — `or_` is added, `dataclass` is new).

```python
from app.models.content_insights import ContentPublicationInsight
```

(add alongside the other `from app.models.content_...` imports).

After `_publications_in_range` and before `get_overview`, add:

```python
@dataclass(frozen=True)
class _EngagementTotals:
    reach: Optional[int]
    interactions: Optional[int]
    engagement_rate: Optional[float]
    reach_substituted_accounts: int


def _pick_latest(
    rows: List[ContentPublicationInsight],
) -> Dict[int, ContentPublicationInsight]:
    """De várias linhas (publicações e timestamps misturados), mantém só a
    mais recentemente coletada por publication_id — somar todas contaria a
    mesma curtida quinze vezes."""
    latest: Dict[int, ContentPublicationInsight] = {}
    for row in rows:
        current = latest.get(row.publication_id)
        if current is None or row.collected_at > current.collected_at:
            latest[row.publication_id] = row
    return latest


def _latest_insight_by_publication(
    session: Session, publication_ids: List[int]
) -> Dict[int, ContentPublicationInsight]:
    if not publication_ids:
        return {}
    rows = session.exec(
        select(ContentPublicationInsight).where(
            ContentPublicationInsight.publication_id.in_(publication_ids),
            # A row with every metric null is a recorded failure, not data —
            # ignoring it here is what keeps a broken token from silently
            # zeroing out engagement instead of just not contributing.
            or_(
                ContentPublicationInsight.reach.is_not(None),
                ContentPublicationInsight.impressions.is_not(None),
                ContentPublicationInsight.likes.is_not(None),
                ContentPublicationInsight.comments.is_not(None),
                ContentPublicationInsight.shares.is_not(None),
            ),
        )
    ).all()
    return _pick_latest(rows)


def _engagement_tiles(
    succeeded: List[ContentSocialPublication],
    latest_by_publication: Dict[int, ContentPublicationInsight],
) -> _EngagementTotals:
    reach_total = 0
    reach_present = False
    substituted_accounts: set = set()
    interactions_total = 0
    interactions_present = False

    for publication in succeeded:
        snapshot = latest_by_publication.get(publication.id)
        if snapshot is None:
            continue

        if snapshot.reach is not None:
            reach_total += snapshot.reach
            reach_present = True
        elif snapshot.impressions is not None:
            reach_total += snapshot.impressions
            reach_present = True
            substituted_accounts.add(publication.social_account_id)

        if (
            snapshot.likes is not None
            or snapshot.comments is not None
            or snapshot.shares is not None
        ):
            interactions_total += (
                (snapshot.likes or 0) + (snapshot.comments or 0) + (snapshot.shares or 0)
            )
            interactions_present = True

    return _EngagementTotals(
        reach=reach_total if reach_present else None,
        interactions=interactions_total if interactions_present else None,
        engagement_rate=(
            round(interactions_total / reach_total, 4)
            if reach_present and reach_total and interactions_present
            else None
        ),
        reach_substituted_accounts=len(substituted_accounts),
    )
```

Then, in `get_overview`, replace:

```python
    tiles = AnalyticsTiles(
        published=len(succeeded),
        scheduled=int(scheduled or 0),
        failed=len(failed),
        success_rate=round(len(succeeded) / resolved, 4) if resolved else None,
        # Not collected yet — see the module docstring.
        link_clicks=None,
        engagement=None,
    )
```

with:

```python
    engagement = _engagement_tiles(
        succeeded,
        _latest_insight_by_publication(
            session, [p.id for p in succeeded if p.id is not None]
        ),
    )
    tiles = AnalyticsTiles(
        published=len(succeeded),
        scheduled=int(scheduled or 0),
        failed=len(failed),
        reach=engagement.reach,
        interactions=engagement.interactions,
        engagement_rate=engagement.engagement_rate,
        reach_substituted_accounts=engagement.reach_substituted_accounts,
    )
```

Note `resolved` (`len(succeeded) + len(failed)`) is still computed a few lines above this block for nothing now that `success_rate` is gone from `tiles` — leave that line as-is; it is dead in this function only if nothing else reads it. Check: grep confirms `resolved` is used nowhere else in `get_overview` after this edit, so delete the now-unused line `resolved = len(succeeded) + len(failed)` too.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_ui_analytics.py -v`
Expected: all 7 PASS.

- [ ] **Step 6: Run the controller layer to confirm the response model still matches**

Run: `python3 -m pytest test/services/test_content_ui.py -v`
Expected: all PASS (this file does not test `/content/ui/analytics/overview` today — confirm with `grep -n analytics test/services/test_content_ui.py`; if it returns nothing, this step is just a regression guard on unrelated content-UI tests, which must stay green).

- [ ] **Step 7: Commit**

```bash
git add app/models/content_analytics.py app/services/content/ui_analytics.py test/services/test_content_ui_analytics.py
git commit -m "feat(content): aggregate engagement into three new Analytics tiles"
```

---

## Task 13: The Analytics screen — three tiles, not two empty ones

**Files:**
- Modify: `webui/src/pages/Analytics.tsx`
- Modify: `webui/src/components/charts/Charts.tsx`

**Interfaces:**
- Consumes: the new `AnalyticsTiles` shape from Task 12 (`reach`, `interactions`, `engagement_rate`, `reach_substituted_accounts`; `success_rate` and `link_clicks`/`engagement` gone).
- Produces: no new exports — this is the leaf of the chain.

No test runner is configured for `webui/` (`package.json` has `dev`/`build`/`lint`/`preview` only). Verification here is `npm run build` (type-checks via `tsc -b`) and `npm run lint`, which is exactly how the four-screen migration and the UI-backlog fixes earlier in this project were verified.

- [ ] **Step 1: Update the `Overview` TypeScript interface**

In `webui/src/pages/Analytics.tsx`, change:

```ts
interface Overview {
  tiles: {
    published: number;
    scheduled: number;
    failed: number;
    success_rate: number | null;
    link_clicks: number | null;
    engagement: number | null;
  };
```

to:

```ts
interface Overview {
  tiles: {
    published: number;
    scheduled: number;
    failed: number;
    reach: number | null;
    interactions: number | null;
    engagement_rate: number | null;
    reach_substituted_accounts: number;
  };
```

(the rest of the interface — `throughput`, `platform_mix`, `cadence_by_hour`, `account_performance`, `window` — is unchanged; `account_performance[].success_rate` stays exactly as it is).

- [ ] **Step 2: Add a count formatter and a reach hint next to the existing `pct` helper**

Change:

```ts
function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}
```

to:

```ts
function pct(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function count(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("pt-BR");
}

function reachHint(substitutedAccounts: number): string | undefined {
  if (substitutedAccounts === 0) return undefined;
  return substitutedAccounts === 1
    ? "1 conta sem alcance — usando impressões"
    : `${substitutedAccounts} contas sem alcance — usando impressões`;
}
```

- [ ] **Step 3: Replace the three tiles**

Change:

```tsx
            <StatTile label="Publicadas" value={String(data.tiles.published)} />
            <StatTile label="Agendadas" value={String(data.tiles.scheduled)} />
            <StatTile label="Falhas" value={String(data.tiles.failed)} />
            <StatTile label="Taxa de sucesso" value={pct(data.tiles.success_rate)} />
            {/* Present but empty, not omitted: keeping the six-tile grid says
                these exist and are not collected yet, where dropping them
                would just look like they were never part of the product. */}
            <StatTile
              label="Cliques em links"
              value="—"
              hint="ainda não coletado"
              unavailable
            />
            <StatTile
              label="Engajamento"
              value="—"
              hint="ainda não coletado"
              unavailable
            />
```

to:

```tsx
            <StatTile label="Publicadas" value={String(data.tiles.published)} />
            <StatTile label="Agendadas" value={String(data.tiles.scheduled)} />
            <StatTile label="Falhas" value={String(data.tiles.failed)} />
            {/* Alcance → Interações → Taxa de engajamento: distribuição,
                volume, qualidade. O hint aparece só quando alguma conta
                nesta janela não tem alcance de verdade (LinkedIn, X, TikTok,
                YouTube) e entrou como impressões — a substituição fica
                visível em vez de virar mentira silenciosa. */}
            <StatTile
              label="Alcance"
              value={count(data.tiles.reach)}
              hint={reachHint(data.tiles.reach_substituted_accounts)}
            />
            <StatTile label="Interações" value={count(data.tiles.interactions)} />
            <StatTile
              label="Taxa de engajamento"
              value={pct(data.tiles.engagement_rate)}
            />
```

- [ ] **Step 4: Remove the now-dead `unavailable` prop from `StatTile`**

In `webui/src/components/charts/Charts.tsx`, change:

```tsx
export function StatTile({
  label,
  value,
  hint,
  unavailable,
}: {
  label: string;
  value: string;
  hint?: string;
  /** Renders the tile as present-but-empty. Used for the two metrics this
   * system has never collected — dropping them would hide the gap. */
  unavailable?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 px-3 py-2.5 border-r border-[var(--border)] last:border-r-0",
        unavailable && "opacity-60",
      )}
    >
      <span className="text-[22px] leading-none font-semibold tracking-tight text-[var(--text-h)]">
        {unavailable ? "—" : value}
      </span>
      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--text)]">
        {label}
      </span>
      {hint ? <span className="text-[10px] text-[var(--text)]">{hint}</span> : null}
    </div>
  );
}
```

to:

```tsx
export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1 px-3 py-2.5 border-r border-[var(--border)] last:border-r-0">
      <span className="text-[22px] leading-none font-semibold tracking-tight text-[var(--text-h)]">
        {value}
      </span>
      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--text)]">
        {label}
      </span>
      {hint ? <span className="text-[10px] text-[var(--text)]">{hint}</span> : null}
    </div>
  );
}
```

- [ ] **Step 5: Build and lint**

Run:
```bash
cd webui && npm run build && npm run lint
```
Expected: build succeeds (no TypeScript errors — every remaining reference to `data.tiles.success_rate`/`link_clicks`/`engagement`/`unavailable` must be gone, or `tsc -b` fails the build); lint shows the same 9 pre-existing warnings as before this task (all `react(only-export-components)`/`react(set-state-in-effect)` in unrelated files), zero new ones.

- [ ] **Step 6: Commit**

```bash
cd .. && git add webui/src/pages/Analytics.tsx webui/src/components/charts/Charts.tsx
git commit -m "feat(webui): replace the two empty Analytics tiles with reach/interactions/engagement rate"
```

---

## Self-Review Notes

- **Spec coverage:** every section of the design spec maps to a task — schema (Task 1), the `fetch_insights` capability hook (Task 2), all six adapters (Tasks 3–8), the cadence (Task 9), the retry wrapper (Task 10), the pass and scheduler wiring (Task 11), the aggregation and `AnalyticsTiles` reshape (Task 12), the screen (Task 13). The spec's Não-objetivos (shortener, account-health screen, engagement-over-time chart, retention/expurgo, account metrics) have deliberately no task — confirmed absent by design, not by oversight.
- **The `run_with_retry` correction** is called out once in Global Constraints and again at Task 10 — it is the one place this plan's approach differs from the spec's literal wording, and it differs because the literal wording would produce code that silently never retries (a `except GenerationError` clause can't catch a `PublicationError`).
- **Type/name consistency checked:** `InsightsResult` (Task 2) is the return type of every adapter's `fetch_insights` (Tasks 3–8), the return type of `_fetch_insights_with_retry` (Task 10), and the source of the five metric fields written onto `ContentPublicationInsight` in Task 11 — same five names (`reach`, `impressions`, `likes`, `comments`, `shares`) throughout. `due_for_collection`'s keyword-only signature (`completed_at`, `last_collected_at`, `now`) is identical between its definition (Task 9) and its one call site (Task 11). `AnalyticsTiles`'s four new field names (Task 12) match exactly what `Analytics.tsx` reads (Task 13): `reach`, `interactions`, `engagement_rate`, `reach_substituted_accounts`.
