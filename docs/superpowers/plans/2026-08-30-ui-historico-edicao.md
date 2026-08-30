# UI de Histórico e Edição Manual (fase 5c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing `ContentAuditLog` for reading (a history tab per piece + a tenant-wide feed) and let an admin manually correct a `ContentPiece` — its metadata and/or its primary asset — after generation, with every correction and every status reversal explicitly traceable in the audit log.

**Architecture:** Two new read/write surfaces bolt onto the existing 5a router (`app/controllers/v1/content/ui.py`): `GET /content/ui/audit-log` (generic, filterable) and `PATCH /content/ui/pieces/{id}` / `POST /content/ui/pieces/{id}/asset` (admin-only, both gated by the same "not posted" rule and both reverting `approved`/`rejected` back to `pending_approval`). `ContentAuditLog` gains a `details` JSON column (not `metadata` — that name is reserved by SQLAlchemy's Declarative API) carrying a `{field: {before, after}}` diff, written by the same conditional-UPDATE pattern `approve_piece`/`reject_piece` already use. The frontend adds an edit form, an asset-upload form, and a shared `AuditLogList` component (null-safe on `details`) reused by both the piece's history tab and a new `/history` feed page.

**Tech Stack:** FastAPI + SQLModel (Postgres), Alembic migrations, React 19 + TypeScript + Vite + TanStack Query, Python `unittest` (HTTP-layer via `fastapi.testclient.TestClient` + `dependency_overrides`, service-layer via `unittest.mock.MagicMock` sessions).

**Spec:** `docs/superpowers/specs/2026-08-30-ui-historico-edicao-design.md`

## Global Constraints

- Toda rota de escrita (`PATCH`/`POST asset`) exige `role == "admin"`, checado no backend via `content_auth.require_role` — nunca só no frontend.
- Toda leitura/escrita filtra por `tenant_id` da sessão; um `id` de outro tenant responde 404, nunca 200 nem 403.
- Edição (`PATCH` ou `POST asset`) é permitida em qualquer status de `ContentPiece` exceto `posted` (409 nesse caso).
- Editar uma peça `approved`/`rejected` reverte o status para `pending_approval` e limpa `approved_at`; essa reversão entra explicitamente em `details["status"]` do mesmo evento de audit log — nunca fica implícita só no banco.
- A coluna nova em `ContentAuditLog` chama-se `details`, nunca `metadata` (nome reservado pela Declarative API do SQLAlchemy/SQLModel).
- Frontend: qualquer componente que renderiza uma entrada de audit log **precisa** tratar `entry.details === null` sem quebrar (histórico anterior ao 5c foi gravado sem esse campo).
- Sem testes automatizados de frontend (convenção do projeto) — tasks de frontend usam `cd webui && npm run build` (`tsc -b && vite build`) como gate, mais validação manual na task final.

---

### Task 1: `ContentAuditLog.details` — migration, model, `write_audit_log`, `list_audit_log`

**Files:**
- Create: `alembic/versions/c9f4e2a7b1d5_add_details_to_audit_log.py`
- Modify: `app/models/content.py:197-206` (`ContentAuditLog`)
- Modify: `app/services/content/audit.py`
- Test: `test/services/test_content_audit.py`

**Interfaces:**
- Produces: `audit.write_audit_log(session, *, tenant_id, entity_type, entity_id, action, actor, details: Optional[dict] = None) -> ContentAuditLog` (existing signature, additive param). `audit.list_audit_log(session, *, tenant_id, entity_type: Optional[str] = None, entity_id: Optional[int] = None, limit: int = 50, offset: int = 0) -> List[ContentAuditLog]`.

- [ ] **Step 1: Write the failing tests**

```python
# test/services/test_content_audit.py
import unittest
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.services.content import audit


class TestWriteAuditLog(unittest.TestCase):
    def test_details_defaults_to_none(self):
        session = MagicMock()

        entry = audit.write_audit_log(
            session,
            tenant_id=1,
            entity_type="content_piece",
            entity_id=10,
            action="approved",
            actor="user:u1",
        )

        self.assertIsNone(entry.details)
        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_details_is_persisted_when_given(self):
        session = MagicMock()
        details = {"generation_prompt": {"before": "a cat", "after": "a dog"}}

        entry = audit.write_audit_log(
            session,
            tenant_id=1,
            entity_type="content_piece",
            entity_id=10,
            action="edited",
            actor="user:u1",
            details=details,
        )

        self.assertEqual(entry.details, details)


class TestListAuditLog(unittest.TestCase):
    def test_filters_by_tenant_entity_type_and_entity_id(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["row"]

        result = audit.list_audit_log(
            session, tenant_id=1, entity_type="content_piece", entity_id=10
        )

        self.assertEqual(result, ["row"])
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("TENANT_ID = 1", compiled)
        self.assertIn("ENTITY_TYPE = 'CONTENT_PIECE'", compiled)
        self.assertIn("ENTITY_ID = 10", compiled)

    def test_defaults_to_tenant_only_filter(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = []

        audit.list_audit_log(session, tenant_id=1)

        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("TENANT_ID = 1", compiled)
        self.assertNotIn("ENTITY_TYPE", compiled)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_audit.py -v`
Expected: FAIL — `write_audit_log()` doesn't accept `details`, `list_audit_log` doesn't exist.

- [ ] **Step 3: Add the `details` column to the model**

In `app/models/content.py`, replace the `ContentAuditLog` table (currently lines 197-206):

```python
class ContentAuditLog(SQLModel, table=True):
    __tablename__ = "content_audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    entity_type: str
    entity_id: int
    action: str
    actor: str
    details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

(`JSON`/`Column` are already imported at the top of `content.py`.)

- [ ] **Step 4: Write the migration**

```python
# alembic/versions/c9f4e2a7b1d5_add_details_to_audit_log.py
"""add details to audit log

Revision ID: c9f4e2a7b1d5
Revises: a7d3f8c1b2e9
Create Date: 2026-08-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9f4e2a7b1d5'
down_revision = 'a7d3f8c1b2e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'content_audit_logs',
        sa.Column('details', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('content_audit_logs', 'details')
```

- [ ] **Step 5: Implement `write_audit_log` and `list_audit_log`**

Replace the full contents of `app/services/content/audit.py`:

```python
from typing import List, Optional

from sqlmodel import Session, select

from app.models.content import ContentAuditLog


def write_audit_log(
    session: Session,
    *,
    tenant_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str,
    details: Optional[dict] = None,
) -> ContentAuditLog:
    entry = ContentAuditLog(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        details=details,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_audit_log(
    session: Session,
    *,
    tenant_id: int,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[ContentAuditLog]:
    query = select(ContentAuditLog).where(ContentAuditLog.tenant_id == tenant_id)
    if entity_type is not None:
        query = query.where(ContentAuditLog.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(ContentAuditLog.entity_id == entity_id)
    query = query.order_by(ContentAuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(session.exec(query).all())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_audit.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/c9f4e2a7b1d5_add_details_to_audit_log.py app/models/content.py app/services/content/audit.py test/services/test_content_audit.py
git commit -m "feat(content): add details column and list_audit_log to the audit trail"
```

---

### Task 2: `GET /content/ui/audit-log` route

**Files:**
- Create: `test/services/test_content_ui.py`
- Modify: `app/models/content_ui.py` (add `AuditLogEntryRead`)
- Modify: `app/controllers/v1/content/ui.py`

**Interfaces:**
- Consumes: `audit.list_audit_log` (Task 1).
- Produces: `AuditLogEntryRead` DTO; route `GET /api/v1/content/ui/audit-log`.

- [ ] **Step 1: Write the failing test**

```python
# test/services/test_content_ui.py
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import asgi
from app.controllers import content_auth
from app.db import get_session
from app.models.content import ContentAuditLog, ContentPieceStatus, ContentPieceType, ContentTenant, EntitlementStatus


def _tenant():
    return ContentTenant(
        id=1,
        owner_user_id="u1",
        name="Acme",
        slug="acme",
        api_token_hash="hash",
        entitlement_status=EntitlementStatus.active,
    )


def _user_session(role):
    return content_auth.UserSession(
        tenant=_tenant(), user_id="user-1", role=role, name="Test User"
    )


class UITestCase(unittest.TestCase):
    """Same wiring as UIConfigTestCase in test_content_ui_config.py, for the
    routes in ui.py (session/pieces/audit-log)."""

    role = "admin"

    def setUp(self):
        self.client = TestClient(asgi.app)
        asgi.app.dependency_overrides[content_auth.verify_user_session] = (
            lambda: _user_session(self.role)
        )
        asgi.app.dependency_overrides[get_session] = lambda: MagicMock()

    def tearDown(self):
        asgi.app.dependency_overrides.clear()


def _log_entry(**overrides):
    base = dict(
        id=1,
        tenant_id=1,
        entity_type="content_piece",
        entity_id=10,
        action="edited",
        actor="user:user-1",
        details={"generation_prompt": {"before": "a cat", "after": "a dog"}},
        created_at=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return ContentAuditLog(**base)


class TestListAuditLogRoute(UITestCase):
    role = "member"  # read is open to both roles; member is the stricter case

    def test_returns_entries_from_the_service(self):
        with patch(
            "app.services.content.audit.list_audit_log",
            return_value=[_log_entry()],
        ) as mock_list:
            response = self.client.get(
                "/api/v1/content/ui/audit-log?entity_type=content_piece&entity_id=10"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["action"], "edited")
        self.assertEqual(
            body[0]["details"]["generation_prompt"], {"before": "a cat", "after": "a dog"}
        )
        mock_list.assert_called_once_with(
            unittest.mock.ANY,
            tenant_id=1,
            entity_type="content_piece",
            entity_id=10,
            limit=50,
            offset=0,
        )

    def test_null_details_serializes_as_null(self):
        with patch(
            "app.services.content.audit.list_audit_log",
            return_value=[_log_entry(details=None, action="approved")],
        ):
            response = self.client.get("/api/v1/content/ui/audit-log")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()[0]["details"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/services/test_content_ui.py -v`
Expected: FAIL — `/content/ui/audit-log` doesn't exist (404).

- [ ] **Step 3: Add the `AuditLogEntryRead` DTO**

In `app/models/content_ui.py`, add after `PieceAssetRead` (currently ends at line 26):

```python
class AuditLogEntryRead(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    actor: str
    details: Optional[dict]
    created_at: datetime
```

- [ ] **Step 4: Add the route**

In `app/controllers/v1/content/ui.py`, replace the existing
`from app.models.content_ui import PieceDetailRead, UserSessionRead` line with:

```python
from app.models.content_ui import AuditLogEntryRead, PieceDetailRead, UserSessionRead
```

(`from app.services.content import audit` is already imported in this file — it's
what `approve_piece`/`reject_piece` use today — no change needed there.)

```python
@router.get("/content/ui/audit-log", response_model=list[AuditLogEntryRead])
def list_audit_log(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return audit.list_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest test/services/test_content_ui.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add test/services/test_content_ui.py app/models/content_ui.py app/controllers/v1/content/ui.py
git commit -m "feat(content): add GET /content/ui/audit-log"
```

---

### Task 3: `pieces_service.update_piece` and `mark_asset_replaced`

**Files:**
- Modify: `app/services/content/pieces.py`
- Test: `test/services/test_content_pieces.py`

**Interfaces:**
- Produces: `pieces_service.update_piece(session, *, tenant_id, piece_id, generation_prompt=None, avatar_id=None, voice_id=None, content_category=None, risk_level=None, scheduled_for=None) -> Optional[tuple[ContentPiece, dict]]`. Returns `None` when the piece doesn't exist or is/became `posted`. Otherwise `(updated_piece, diff)` where `diff` is `{field: {"before": ..., "after": ...}}`, including a `"status"` entry when `approved`/`rejected` was reverted to `pending_approval`.
- Produces: `pieces_service.mark_asset_replaced(session, *, tenant_id, piece_id) -> Optional[tuple[ContentPiece, dict]]` — same `None`/`posted` semantics as `update_piece`, but never changes a `ContentPiece` field directly (Task 6's route uses it for the asset-replace endpoint's status-only side effect). `diff` is `{}` unless the piece was `approved`/`rejected`, in which case it's just the `"status"` entry.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_pieces.py`:

```python
class TestUpdatePiece(unittest.TestCase):
    def test_returns_none_when_piece_not_found(self):
        session = MagicMock()

        with patch.object(pieces_service, "get_piece", return_value=None):
            result = pieces_service.update_piece(
                session, tenant_id=1, piece_id=99, generation_prompt="new"
            )

        self.assertIsNone(result)

    def test_diffs_only_changed_fields(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.draft,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session,
                tenant_id=1,
                piece_id=10,
                generation_prompt="a cat",  # unchanged — must not appear in diff
                risk_level=RiskLevel.high,
            )

        self.assertIsNotNone(result)
        updated, diff = result
        self.assertIs(updated, piece)
        self.assertEqual(
            diff, {"risk_level": {"before": "none", "after": "high"}}
        )
        self.assertNotIn("status", diff)

    def test_reverts_approved_to_pending_approval_and_logs_it(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.approved,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session, tenant_id=1, piece_id=10, generation_prompt="a dog"
            )

        updated, diff = result
        self.assertEqual(
            diff["status"], {"before": "approved", "after": "pending_approval"}
        )
        self.assertEqual(
            diff["generation_prompt"], {"before": "a cat", "after": "a dog"}
        )

    def test_returns_none_when_posted_concurrently(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.pending_approval,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 0

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session, tenant_id=1, piece_id=10, generation_prompt="a dog"
            )

        self.assertIsNone(result)
        session.refresh.assert_not_called()

    def test_where_clause_excludes_posted(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.draft,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            pieces_service.update_piece(
                session, tenant_id=1, piece_id=10, generation_prompt="a dog"
            )

        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("STATUS != 'POSTED'", compiled)
        self.assertIn("ID = 10", compiled)


class TestMarkAssetReplaced(unittest.TestCase):
    def test_returns_none_when_piece_not_found(self):
        session = MagicMock()

        with patch.object(pieces_service, "get_piece", return_value=None):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=99)

        self.assertIsNone(result)

    def test_no_diff_when_piece_not_in_decided_state(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.draft)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        self.assertIsNotNone(result)
        updated, diff = result
        self.assertIs(updated, piece)
        self.assertEqual(diff, {})

    def test_reverts_approved_to_pending_approval_and_logs_it(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.approved)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        updated, diff = result
        self.assertEqual(
            diff["status"], {"before": "approved", "after": "pending_approval"}
        )

    def test_returns_none_when_posted_concurrently(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.pending_approval)
        session = MagicMock()
        session.exec.return_value.rowcount = 0

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        self.assertIsNone(result)
        session.refresh.assert_not_called()

    def test_where_clause_excludes_posted(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.draft)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("STATUS != 'POSTED'", compiled)
        self.assertIn("ID = 10", compiled)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_pieces.py -v -k "UpdatePiece or MarkAssetReplaced"`
Expected: FAIL — `update_piece` and `mark_asset_replaced` don't exist.

- [ ] **Step 3: Implement**

Add `from enum import Enum` to the top-of-file imports (next to
`from datetime import datetime`), and add `ContentCategory, RiskLevel` to the
existing `from app.models.content import (...)` block so it reads:

```python
from app.models.content import (
    ContentCampaign,
    ContentCategory,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentPieceType,
    RiskLevel,
)
```

Append to `app/services/content/pieces.py` (after `reject_piece`, which ends the file today):

```python
def _serialize_for_log(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _status_reset_for_edit(piece: ContentPiece) -> tuple[dict, dict]:
    """An edit to an approved/rejected piece reverts it to pending_approval —
    a manual correction can't silently stay 'approved'. Returns
    (values_for_update, diff_for_audit_log); both empty when the piece isn't
    currently in a decided state.
    """
    if piece.status not in (ContentPieceStatus.approved, ContentPieceStatus.rejected):
        return {}, {}
    values = {"status": ContentPieceStatus.pending_approval, "approved_at": None}
    diff = {
        "status": {
            "before": piece.status.value,
            "after": ContentPieceStatus.pending_approval.value,
        }
    }
    return values, diff


def _conditional_edit(session: Session, *, piece_id: int, values: dict) -> bool:
    """UPDATE guardado: só aplica se a piece não estiver posted.

    Mesmo princípio de _conditional_transition, mas a guarda é 'não postada'
    em vez de 'pending_approval' — edição manual é permitida em qualquer
    status anterior a posted.
    """
    result = session.exec(
        update(ContentPiece)
        .where(
            ContentPiece.id == piece_id,
            ContentPiece.status != ContentPieceStatus.posted,
        )
        .values(**values)
    )
    session.commit()
    return result.rowcount > 0


def update_piece(
    session: Session,
    *,
    tenant_id: int,
    piece_id: int,
    generation_prompt: Optional[str] = None,
    avatar_id: Optional[int] = None,
    voice_id: Optional[str] = None,
    content_category: Optional[ContentCategory] = None,
    risk_level: Optional[RiskLevel] = None,
    scheduled_for: Optional[datetime] = None,
) -> Optional[tuple[ContentPiece, dict]]:
    piece = get_piece(session, tenant_id=tenant_id, piece_id=piece_id)
    if piece is None:
        return None

    changes = {
        "generation_prompt": generation_prompt,
        "avatar_id": avatar_id,
        "voice_id": voice_id,
        "content_category": content_category,
        "risk_level": risk_level,
        "scheduled_for": scheduled_for,
    }
    values = {"updated_at": datetime.utcnow()}
    diff = {}
    for field, new_value in changes.items():
        if new_value is None:
            continue
        old_value = getattr(piece, field)
        if old_value != new_value:
            diff[field] = {
                "before": _serialize_for_log(old_value),
                "after": _serialize_for_log(new_value),
            }
            values[field] = new_value

    reset_values, reset_diff = _status_reset_for_edit(piece)
    values.update(reset_values)
    diff.update(reset_diff)

    applied = _conditional_edit(session, piece_id=piece_id, values=values)
    if not applied:
        return None
    session.refresh(piece)
    return piece, diff


def mark_asset_replaced(
    session: Session, *, tenant_id: int, piece_id: int
) -> Optional[tuple[ContentPiece, dict]]:
    """Bumps updated_at and applies the same approved/rejected -> pending_approval
    reset as update_piece, for the asset-replace endpoint — it doesn't change
    any ContentPiece column directly, so it has no field diff of its own.
    """
    piece = get_piece(session, tenant_id=tenant_id, piece_id=piece_id)
    if piece is None:
        return None
    values = {"updated_at": datetime.utcnow()}
    reset_values, diff = _status_reset_for_edit(piece)
    values.update(reset_values)
    applied = _conditional_edit(session, piece_id=piece_id, values=values)
    if not applied:
        return None
    session.refresh(piece)
    return piece, diff
```

Note: `mark_asset_replaced` is implemented and tested here too (not in Task 5,
which only touches `assets.py`) since it shares `_status_reset_for_edit`/
`_conditional_edit` with `update_piece` — keeping both in one place avoids
defining `_conditional_edit` twice. Task 6 later consumes it (mocked, for the
route-level test) — its own behavior is covered by `TestMarkAssetReplaced`
above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_pieces.py -v -k "UpdatePiece or MarkAssetReplaced"`
Expected: PASS (10 tests: 5 for `update_piece`, 5 for `mark_asset_replaced`).

- [ ] **Step 5: Commit**

```bash
git add app/services/content/pieces.py test/services/test_content_pieces.py
git commit -m "feat(content): add pieces_service.update_piece and mark_asset_replaced"
```

---

### Task 4: `PATCH /content/ui/pieces/{id}` route

**Files:**
- Modify: `app/models/content.py` (add `PieceUpdate`)
- Modify: `app/controllers/v1/content/ui.py`
- Modify: `test/services/test_content_ui.py`

**Interfaces:**
- Consumes: `pieces_service.update_piece`, `pieces_service.get_piece` (Task 3), `avatars_service.get_avatar` (existing), `audit.write_audit_log` (Task 1).
- Produces: route `PATCH /api/v1/content/ui/pieces/{piece_id}` → `ContentPieceRead`.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_ui.py`:

```python
from app.models.content import ContentPiece


def _piece(**overrides):
    base = dict(
        id=10,
        campaign_id=1,
        type=ContentPieceType.image,
        status=ContentPieceStatus.draft,
        asset_url=None,
        generation_prompt="a cat",
        avatar_id=None,
        source_image_piece_id=None,
        voice_id=None,
        is_synthetic_media=False,
        content_category=None,
        risk_level="none",
        requires_human_review=False,
        policy_version="v1",
        scheduled_for=None,
        posted_at=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        approval_action=None,
        approved_at=None,
        is_autogenerated=False,
    )
    base.update(overrides)
    return ContentPiece(**base)


class TestUpdatePieceRoute(UITestCase):
    role = "member"

    def test_member_gets_403(self):
        response = self.client.patch(
            "/api/v1/content/ui/pieces/10", json={"generation_prompt": "a dog"}
        )
        self.assertEqual(response.status_code, 403)


class TestUpdatePieceRouteAsAdmin(UITestCase):
    role = "admin"

    def test_not_found_is_404(self):
        with patch("app.services.content.pieces.get_piece", return_value=None):
            response = self.client.patch(
                "/api/v1/content/ui/pieces/999", json={"generation_prompt": "a dog"}
            )
        self.assertEqual(response.status_code, 404)

    def test_posted_piece_is_409(self):
        piece = _piece(status=ContentPieceStatus.posted)
        with patch("app.services.content.pieces.get_piece", return_value=piece):
            response = self.client.patch(
                "/api/v1/content/ui/pieces/10", json={"generation_prompt": "a dog"}
            )
        self.assertEqual(response.status_code, 409)

    def test_cross_tenant_avatar_is_422(self):
        piece = _piece()
        with patch("app.services.content.pieces.get_piece", return_value=piece), patch(
            "app.services.content.avatars.get_avatar", return_value=None
        ):
            response = self.client.patch(
                "/api/v1/content/ui/pieces/10", json={"avatar_id": 999}
            )
        self.assertEqual(response.status_code, 422)

    def test_successful_edit_writes_audit_log_with_diff(self):
        piece = _piece()
        updated = _piece(generation_prompt="a dog")
        with patch(
            "app.services.content.pieces.get_piece", return_value=piece
        ), patch(
            "app.services.content.pieces.update_piece",
            return_value=(updated, {"generation_prompt": {"before": "a cat", "after": "a dog"}}),
        ), patch(
            "app.services.content.audit.write_audit_log"
        ) as mock_log:
            response = self.client.patch(
                "/api/v1/content/ui/pieces/10", json={"generation_prompt": "a dog"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["generation_prompt"], "a dog")
        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args.kwargs["action"], "edited")
        self.assertEqual(
            mock_log.call_args.kwargs["details"],
            {"generation_prompt": {"before": "a cat", "after": "a dog"}},
        )

    def test_no_op_edit_does_not_write_audit_log(self):
        piece = _piece()
        with patch(
            "app.services.content.pieces.get_piece", return_value=piece
        ), patch(
            "app.services.content.pieces.update_piece", return_value=(piece, {})
        ), patch(
            "app.services.content.audit.write_audit_log"
        ) as mock_log:
            response = self.client.patch("/api/v1/content/ui/pieces/10", json={})

        self.assertEqual(response.status_code, 200)
        mock_log.assert_not_called()
```

Also update the top-of-file import in `test/services/test_content_ui.py` to add
`ContentPiece` (needed by the new `_piece()` helper below) — it must keep
`ContentAuditLog` too, since `TestListAuditLogRoute` (Task 2) still uses it:

```python
from app.models.content import (
    ContentAuditLog,
    ContentPiece,
    ContentPieceStatus,
    ContentPieceType,
    ContentTenant,
    EntitlementStatus,
)
```

(replaces the single-line import from Task 2.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_ui.py -v -k UpdatePieceRoute`
Expected: FAIL — route doesn't exist (405/404).

- [ ] **Step 3: Add the `PieceUpdate` DTO**

In `app/models/content.py`, add after `ContentPieceRead` (currently ends at line 384):

```python
class PieceUpdate(BaseModel):
    generation_prompt: Optional[str] = None
    avatar_id: Optional[int] = None
    voice_id: Optional[str] = None
    content_category: Optional[ContentCategory] = None
    risk_level: Optional[RiskLevel] = None
    scheduled_for: Optional[datetime] = None
```

- [ ] **Step 4: Add the route**

In `app/controllers/v1/content/ui.py`, replace the existing
`from app.models.content import ContentPieceRead, ContentPieceStatus` line with:

```python
from app.models.content import ContentPieceRead, ContentPieceStatus, PieceUpdate
```

and add a new import line next to the other `from app.services.content import ...` lines:

```python
from app.services.content import avatars as avatars_service
```

Add the route (after `get_piece`, before `approve_piece` — order doesn't matter functionally, but keeps read/write routes grouped):

```python
@router.patch("/content/ui/pieces/{piece_id}", response_model=ContentPieceRead)
def update_piece(
    piece_id: int,
    payload: PieceUpdate,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to edit"
        )

    if payload.avatar_id is not None and avatars_service.get_avatar(
        session, tenant_id=user_session.tenant.id, avatar_id=payload.avatar_id
    ) is None:
        raise HTTPException(status_code=422, detail="avatar_id not found in this tenant")

    result = pieces_service.update_piece(
        session,
        tenant_id=user_session.tenant.id,
        piece_id=piece_id,
        generation_prompt=payload.generation_prompt,
        avatar_id=payload.avatar_id,
        voice_id=payload.voice_id,
        content_category=payload.content_category,
        risk_level=payload.risk_level,
        scheduled_for=payload.scheduled_for,
    )
    if result is None:
        raise HTTPException(
            status_code=409, detail="Piece became 'posted' before the edit was applied"
        )
    updated, diff = result

    if diff:
        audit.write_audit_log(
            session,
            tenant_id=user_session.tenant.id,
            entity_type="content_piece",
            entity_id=piece_id,
            action="edited",
            actor=f"user:{user_session.user_id}",
            details=diff,
        )
    return updated
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_ui.py -v`
Expected: PASS (all tests in the file so far).

- [ ] **Step 6: Commit**

```bash
git add app/models/content.py app/controllers/v1/content/ui.py test/services/test_content_ui.py
git commit -m "feat(content): add PATCH /content/ui/pieces/{id} for manual metadata edits"
```

---

### Task 5: `assets_service.archive_assets_of_type` + `create_manual_asset`

**Files:**
- Modify: `app/services/content/assets.py`
- Test: `test/services/test_content_assets.py` (create if it doesn't exist — check first with `ls test/services/test_content_assets.py`)

**Interfaces:**
- Produces: `assets_service.archive_assets_of_type(session, *, content_piece_id, asset_type) -> List[ContentAsset]` (returns the assets it just archived). `assets_service.create_manual_asset(session, *, tenant_id, client_id, content_piece_id, asset_type, uploaded: UploadedObject, mime_type=None) -> ContentAsset`.

- [ ] **Step 1: Check for an existing test file**

Run: `ls test/services/test_content_assets.py 2>&1`

If it exists, read it first and append to it instead of overwriting — match its existing fixtures/imports.

- [ ] **Step 2: Write the failing tests**

```python
# test/services/test_content_assets.py (new, or appended if it already exists)
import unittest
from unittest.mock import MagicMock

from app.models.content_generation import ContentAssetType
from app.services.content import assets as assets_service
from app.services.content.storage import UploadedObject


class TestArchiveAssetsOfType(unittest.TestCase):
    def test_marks_matching_non_intermediate_assets_as_intermediate(self):
        asset = MagicMock(is_intermediate=False)
        session = MagicMock()
        session.exec.return_value.all.return_value = [asset]

        result = assets_service.archive_assets_of_type(
            session, content_piece_id=10, asset_type=ContentAssetType.video
        )

        self.assertEqual(result, [asset])
        self.assertTrue(asset.is_intermediate)
        session.commit.assert_called_once()

    def test_no_matching_assets_returns_empty_list(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = []

        result = assets_service.archive_assets_of_type(
            session, content_piece_id=10, asset_type=ContentAssetType.video
        )

        self.assertEqual(result, [])


class TestCreateManualAsset(unittest.TestCase):
    def test_creates_asset_without_a_generation_job(self):
        session = MagicMock()
        uploaded = UploadedObject(
            url="https://x/1/10/file.mp4", storage_path="1/10/file.mp4", size_bytes=1024
        )

        asset = assets_service.create_manual_asset(
            session,
            tenant_id=1,
            client_id=2,
            content_piece_id=10,
            asset_type=ContentAssetType.video,
            uploaded=uploaded,
            mime_type="video/mp4",
        )

        self.assertIsNone(asset.generation_job_id)
        self.assertEqual(asset.storage_path, "1/10/file.mp4")
        self.assertFalse(asset.is_intermediate)
        session.add.assert_called_once()
        session.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_assets.py -v`
Expected: FAIL — neither function exists yet.

- [ ] **Step 4: Implement**

Append to `app/services/content/assets.py`:

```python
def archive_assets_of_type(
    session: Session, *, content_piece_id: int, asset_type: ContentAssetType
) -> List[ContentAsset]:
    """Marks the current non-intermediate asset(s) of this type as
    intermediate — get_piece_detail already filters those out of the UI, so
    this is how a manually-replaced asset stops showing up without deleting
    the old file (keeps it recoverable, matches how pipeline intermediates
    already work).
    """
    assets = list(
        session.exec(
            select(ContentAsset).where(
                ContentAsset.content_piece_id == content_piece_id,
                ContentAsset.type == asset_type,
                ContentAsset.is_intermediate == False,  # noqa: E712
            )
        ).all()
    )
    for asset in assets:
        asset.is_intermediate = True
        session.add(asset)
    session.commit()
    return assets


def create_manual_asset(
    session: Session,
    *,
    tenant_id: int,
    client_id: int,
    content_piece_id: int,
    asset_type: ContentAssetType,
    uploaded: UploadedObject,
    mime_type: Optional[str] = None,
) -> ContentAsset:
    """Like create_asset, but for an admin's manual upload rather than a
    pipeline job — there's no ContentGenerationJob to pull tenant/client ids
    from, so they're passed directly and generation_job_id stays None
    (already nullable on the model).
    """
    asset = ContentAsset(
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=content_piece_id,
        generation_job_id=None,
        type=asset_type,
        url=uploaded.url,
        storage_path=uploaded.storage_path,
        mime_type=mime_type,
        size_bytes=uploaded.size_bytes,
        is_intermediate=False,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
```

`select` and `Optional`/`List` are already imported at the top of `assets.py`; `ContentAssetType` is already imported too.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_assets.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add app/services/content/assets.py test/services/test_content_assets.py
git commit -m "feat(content): add archive_assets_of_type and create_manual_asset"
```

---

### Task 6: `POST /content/ui/pieces/{id}/asset` route

**Files:**
- Modify: `app/controllers/v1/content/ui.py`
- Modify: `test/services/test_content_ui.py`

**Interfaces:**
- Consumes: `pieces_service.get_piece`, `pieces_service.mark_asset_replaced` (Task 3), `assets_service.archive_assets_of_type`, `assets_service.create_manual_asset` (Task 5), `campaigns_service.get_campaign` (existing), `storage.upload_bytes` (existing), `audit.write_audit_log` (Task 1).
- Produces: route `POST /api/v1/content/ui/pieces/{piece_id}/asset` → `ContentPieceRead`.

- [ ] **Step 1: Write the failing tests**

Append to `test/services/test_content_ui.py`:

```python
from app.models.content_generation import ContentAssetType
from app.services.content.storage import UploadedObject


class TestReplaceAssetRoute(UITestCase):
    role = "member"

    def test_member_gets_403(self):
        response = self.client.post(
            "/api/v1/content/ui/pieces/10/asset",
            data={"type": "image"},
            files={"file": ("photo.png", b"binarydata", "image/png")},
        )
        self.assertEqual(response.status_code, 403)


class TestReplaceAssetRouteAsAdmin(UITestCase):
    role = "admin"

    def test_not_found_is_404(self):
        with patch("app.services.content.pieces.get_piece", return_value=None):
            response = self.client.post(
                "/api/v1/content/ui/pieces/999/asset",
                data={"type": "image"},
                files={"file": ("photo.png", b"binarydata", "image/png")},
            )
        self.assertEqual(response.status_code, 404)

    def test_posted_piece_is_409(self):
        piece = _piece(status=ContentPieceStatus.posted)
        with patch("app.services.content.pieces.get_piece", return_value=piece):
            response = self.client.post(
                "/api/v1/content/ui/pieces/10/asset",
                data={"type": "image"},
                files={"file": ("photo.png", b"binarydata", "image/png")},
            )
        self.assertEqual(response.status_code, 409)

    def test_type_mismatch_is_422(self):
        piece = _piece(type=ContentPieceType.image)
        with patch("app.services.content.pieces.get_piece", return_value=piece):
            response = self.client.post(
                "/api/v1/content/ui/pieces/10/asset",
                data={"type": "video"},
                files={"file": ("clip.mp4", b"binarydata", "video/mp4")},
            )
        self.assertEqual(response.status_code, 422)

    def test_successful_replace_archives_old_asset_and_logs_it(self):
        piece = _piece(type=ContentPieceType.image)
        old_asset = MagicMock(storage_path="1/10/old.png")
        new_asset = MagicMock(storage_path="1/10/new.png")
        campaign = MagicMock(client_id=2)
        updated = _piece(type=ContentPieceType.image)
        uploaded = UploadedObject(
            url="https://x/1/10/new.png", storage_path="1/10/new.png", size_bytes=10
        )

        with patch(
            "app.services.content.pieces.get_piece", return_value=piece
        ), patch(
            "app.services.content.campaigns.get_campaign", return_value=campaign
        ), patch(
            "app.services.content.storage.upload_bytes", return_value=uploaded
        ), patch(
            "app.services.content.assets.archive_assets_of_type",
            return_value=[old_asset],
        ), patch(
            "app.services.content.assets.create_manual_asset", return_value=new_asset
        ), patch(
            "app.services.content.pieces.mark_asset_replaced",
            return_value=(updated, {}),
        ), patch(
            "app.services.content.audit.write_audit_log"
        ) as mock_log:
            response = self.client.post(
                "/api/v1/content/ui/pieces/10/asset",
                data={"type": "image"},
                files={"file": ("photo.png", b"binarydata", "image/png")},
            )

        self.assertEqual(response.status_code, 200)
        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args.kwargs["action"], "asset_replaced")
        self.assertEqual(
            mock_log.call_args.kwargs["details"]["asset"],
            {"before": "1/10/old.png", "after": "1/10/new.png"},
        )

    def test_reverted_status_is_merged_into_the_same_log_entry(self):
        piece = _piece(type=ContentPieceType.image, status=ContentPieceStatus.approved)
        campaign = MagicMock(client_id=2)
        updated = _piece(type=ContentPieceType.image, status=ContentPieceStatus.pending_approval)
        uploaded = UploadedObject(
            url="https://x/1/10/new.png", storage_path="1/10/new.png", size_bytes=10
        )
        status_diff = {"status": {"before": "approved", "after": "pending_approval"}}

        with patch(
            "app.services.content.pieces.get_piece", return_value=piece
        ), patch(
            "app.services.content.campaigns.get_campaign", return_value=campaign
        ), patch(
            "app.services.content.storage.upload_bytes", return_value=uploaded
        ), patch(
            "app.services.content.assets.archive_assets_of_type", return_value=[]
        ), patch(
            "app.services.content.assets.create_manual_asset",
            return_value=MagicMock(storage_path="1/10/new.png"),
        ), patch(
            "app.services.content.pieces.mark_asset_replaced",
            return_value=(updated, status_diff),
        ), patch(
            "app.services.content.audit.write_audit_log"
        ) as mock_log:
            response = self.client.post(
                "/api/v1/content/ui/pieces/10/asset",
                data={"type": "image"},
                files={"file": ("photo.png", b"binarydata", "image/png")},
            )

        self.assertEqual(response.status_code, 200)
        details = mock_log.call_args.kwargs["details"]
        self.assertEqual(details["status"], status_diff["status"])
        self.assertIn("asset", details)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_ui.py -v -k ReplaceAsset`
Expected: FAIL — route doesn't exist.

- [ ] **Step 3: Add the route**

In `app/controllers/v1/content/ui.py`, replace the existing
`from fastapi import Depends, HTTPException` line with:

```python
from fastapi import Depends, File, Form, HTTPException, UploadFile
```

and add new import lines next to the other `from app.services.content import ...`/
`from app.models... import ...` lines:

```python
from app.models.content_generation import ContentAssetType
from app.services.content import assets as assets_service
from app.services.content import campaigns as campaigns_service
from app.services.content import storage
```

Add the route:

```python
@router.post("/content/ui/pieces/{piece_id}/asset", response_model=ContentPieceRead)
async def replace_piece_asset(
    piece_id: int,
    type: ContentAssetType = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    if piece.status == ContentPieceStatus.posted:
        raise HTTPException(
            status_code=409, detail="Piece must not be 'posted' to replace its asset"
        )
    if type.value != piece.type.value:
        raise HTTPException(
            status_code=422,
            detail=f"asset type '{type.value}' does not match piece type '{piece.type.value}'",
        )

    campaign = campaigns_service.get_campaign(
        session, tenant_id=user_session.tenant.id, campaign_id=piece.campaign_id
    )

    data = await file.read()
    uploaded = storage.upload_bytes(
        tenant_id=user_session.tenant.id,
        content_piece_id=piece_id,
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type or "application/octet-stream",
    )

    archived = assets_service.archive_assets_of_type(
        session, content_piece_id=piece_id, asset_type=type
    )
    new_asset = assets_service.create_manual_asset(
        session,
        tenant_id=user_session.tenant.id,
        client_id=campaign.client_id,
        content_piece_id=piece_id,
        asset_type=type,
        uploaded=uploaded,
        mime_type=file.content_type,
    )

    result = pieces_service.mark_asset_replaced(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if result is None:
        raise HTTPException(
            status_code=409, detail="Piece became 'posted' before the asset was replaced"
        )
    updated, diff = result

    diff["asset"] = {
        "before": archived[0].storage_path if archived else None,
        "after": new_asset.storage_path,
    }
    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="asset_replaced",
        actor=f"user:{user_session.user_id}",
        details=diff,
    )
    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_ui.py -v`
Expected: PASS (every test in the file).

- [ ] **Step 5: Run the full backend suite**

Run: `python3 -m pytest test/services/ -v`
Expected: PASS — no regressions in `ui_config`, `pieces`, `assets`, `avatars`, etc.

- [ ] **Step 6: Commit**

```bash
git add app/controllers/v1/content/ui.py test/services/test_content_ui.py
git commit -m "feat(content): add POST /content/ui/pieces/{id}/asset for manual asset replacement"
```

---

### Task 7: Frontend plumbing — `apiClient.uploadFile` + shared types

**Files:**
- Modify: `webui/src/lib/apiClient.ts`
- Modify: `webui/src/lib/types.ts`

**Interfaces:**
- Produces: `apiClient.uploadFile<T>(path: string, formData: FormData): Promise<T>`. Types `AuditLogEntry`, `PieceUpdatePayload`.

- [ ] **Step 1: Fix `request()` to not force JSON content-type on `FormData` bodies, and add `uploadFile`**

Replace the `request` function and `apiClient` export in `webui/src/lib/apiClient.ts`:

```typescript
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(currentToken ? { Authorization: `Bearer ${currentToken}` } : {}),
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string): Promise<T> => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string): Promise<T> => request<T>(path, { method: "DELETE" }),
  uploadFile: <T>(path: string, formData: FormData): Promise<T> =>
    request<T>(path, { method: "POST", body: formData }),
  setToken,
};
```

(browsers set the multipart boundary in `Content-Type` themselves when the body is a `FormData` and no `Content-Type` header is set explicitly — that's why `isFormData` skips it above.)

- [ ] **Step 2: Add the shared types**

Append to `webui/src/lib/types.ts`:

```typescript
export interface AuditLogEntry {
  id: number;
  entity_type: string;
  entity_id: number;
  action: string;
  actor: string;
  details: Record<string, { before: unknown; after: unknown }> | null;
  created_at: string;
}

export interface PieceUpdatePayload {
  generation_prompt?: string | null;
  avatar_id?: number | null;
  voice_id?: string | null;
  content_category?: string | null;
  risk_level?: string | null;
  scheduled_for?: string | null;
}
```

- [ ] **Step 3: Run the build**

Run: `cd webui && npm run build`
Expected: succeeds (`tsc -b` reports no type errors, `vite build` completes).

- [ ] **Step 4: Commit**

```bash
git add webui/src/lib/apiClient.ts webui/src/lib/types.ts
git commit -m "feat(webui): add apiClient.uploadFile and audit-log/piece-update types"
```

---

### Task 8: `PieceDetail.tsx` — formulário de edição de metadados

**Files:**
- Modify: `webui/src/pages/PieceDetail.tsx`

**Interfaces:**
- Consumes: `apiClient.patch` (existing), `PieceUpdatePayload` (Task 7), `RequireRole` (existing).

- [ ] **Step 1: Add the edit form, gated to admin, wired to `PATCH`**

In `webui/src/pages/PieceDetail.tsx`, add the import and state, and the mutation, and render the form. Full updated file:

```tsx
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { apiClient, ApiError } from "../lib/apiClient";
import { useSession } from "../context/SessionProvider";
import { RequireRole } from "../components/RequireRole";
import type { PieceDetail as PieceDetailType, PieceUpdatePayload } from "../lib/types";

export function PieceDetail() {
  const { id } = useParams<{ id: string }>();
  const { canApprove } = useSession();
  const queryClient = useQueryClient();

  const [generationPrompt, setGenerationPrompt] = useState("");
  const [riskLevel, setRiskLevel] = useState("");
  const [contentCategory, setContentCategory] = useState("");

  const detail = useQuery({
    queryKey: ["piece", id],
    queryFn: () => apiClient.get<PieceDetailType>(`/content/ui/pieces/${id}`),
  });

  const decide = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      apiClient.post(`/content/ui/pieces/${id}/${action}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["piece", id] });
      queryClient.invalidateQueries({ queryKey: ["pieces"] });
    },
  });

  const edit = useMutation({
    mutationFn: (payload: PieceUpdatePayload) =>
      apiClient.patch(`/content/ui/pieces/${id}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["piece", id] });
      queryClient.invalidateQueries({ queryKey: ["pieces"] });
      queryClient.invalidateQueries({ queryKey: ["audit-log", "content_piece", id] });
    },
  });

  if (detail.isLoading) return <p>Carregando...</p>;
  if (detail.isError) return <p>Erro ao carregar esta peça.</p>;
  if (!detail.data) return null;

  const piece = detail.data;
  const canDecide = canApprove() && piece.status === "pending_approval";
  const canEdit = canApprove() && piece.status !== "posted";
  const conflict = decide.error instanceof ApiError && decide.error.status === 409;

  return (
    <div>
      <h1>Peça #{piece.id}</h1>
      <p>Status: {piece.status}</p>
      <p>Prompt: {piece.generation_prompt ?? "(sem prompt)"}</p>
      <p>Categoria: {piece.content_category ?? "—"} · Risco: {piece.risk_level}</p>
      <p>Mídia sintética: {piece.is_synthetic_media ? "sim" : "não"}</p>

      {piece.assets.map((asset) => {
        if (asset.type === "video") {
          return <video key={asset.signed_url} src={asset.signed_url} controls />;
        }
        if (asset.type === "audio") {
          return <audio key={asset.signed_url} src={asset.signed_url} controls />;
        }
        return <img key={asset.signed_url} src={asset.signed_url} alt={`asset-${piece.id}`} />;
      })}

      <div>
        <button
          disabled={!canDecide || decide.isPending}
          title={!canDecide ? "Você não tem permissão para decidir esta peça" : undefined}
          onClick={() => decide.mutate("approve")}
        >
          Aprovar
        </button>
        <button
          disabled={!canDecide || decide.isPending}
          title={!canDecide ? "Você não tem permissão para decidir esta peça" : undefined}
          onClick={() => decide.mutate("reject")}
        >
          Rejeitar
        </button>
        {conflict && <p>Esta peça já foi decidida por outra pessoa.</p>}
      </div>

      <RequireRole role="admin" fallback={null}>
        <h2>Editar</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            edit.mutate({
              generation_prompt: generationPrompt || undefined,
              risk_level: riskLevel || undefined,
              content_category: contentCategory || undefined,
            });
          }}
        >
          <input
            value={generationPrompt}
            onChange={(event) => setGenerationPrompt(event.target.value)}
            placeholder="Novo prompt de geração"
          />
          <select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value)}>
            <option value="">Manter risco atual</option>
            <option value="none">Nenhum</option>
            <option value="low">Baixo</option>
            <option value="medium">Médio</option>
            <option value="high">Alto</option>
          </select>
          <input
            value={contentCategory}
            onChange={(event) => setContentCategory(event.target.value)}
            placeholder="Nova categoria (opcional)"
          />
          <button type="submit" disabled={!canEdit || edit.isPending}>
            Salvar edição
          </button>
        </form>
        {piece.status === "posted" && <p>Peça publicada — não pode mais ser editada.</p>}
      </RequireRole>

      <h2>Publicações</h2>
      <ul>
        {piece.publications.map((publication) => (
          <li key={publication.id}>
            {publication.platform}: {publication.status}
            {publication.error_message ? ` — ${publication.error_message}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Run the build**

Run: `cd webui && npm run build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add webui/src/pages/PieceDetail.tsx
git commit -m "feat(webui): add manual metadata edit form to PieceDetail"
```

---

### Task 9: `PieceDetail.tsx` — upload de asset substituto

**Files:**
- Modify: `webui/src/pages/PieceDetail.tsx`

**Interfaces:**
- Consumes: `apiClient.uploadFile` (Task 7).

- [ ] **Step 1: Add the file-replace form inside the existing admin `RequireRole` block**

In `webui/src/pages/PieceDetail.tsx`, add state and a mutation, then render the form right after the metadata-edit `</form>` and before the "posted" message (still inside the same `<RequireRole role="admin" fallback={null}>` block):

Add to the top of the component, alongside the other `useState` calls:

```tsx
const [assetFile, setAssetFile] = useState<File | null>(null);
```

Add alongside the `edit` mutation:

```tsx
const replaceAsset = useMutation({
  mutationFn: (file: File) => {
    const formData = new FormData();
    formData.append("type", piece!.type);
    formData.append("file", file);
    return apiClient.uploadFile(`/content/ui/pieces/${id}/asset`, formData);
  },
  onSuccess: () => {
    setAssetFile(null);
    queryClient.invalidateQueries({ queryKey: ["piece", id] });
    queryClient.invalidateQueries({ queryKey: ["pieces"] });
    queryClient.invalidateQueries({ queryKey: ["audit-log", "content_piece", id] });
  },
});
```

(`piece!` is safe here — this mutation is only ever invoked from inside the render path below, after the `if (!detail.data) return null;` guard, so `piece` is always defined by the time the button can be clicked.)

Render, right after the edit form's closing `</form>` and before the "posted" paragraph:

```tsx
<form
  onSubmit={(event) => {
    event.preventDefault();
    if (assetFile) replaceAsset.mutate(assetFile);
  }}
>
  <input
    type="file"
    onChange={(event) => setAssetFile(event.target.files?.[0] ?? null)}
  />
  <button type="submit" disabled={!canEdit || !assetFile || replaceAsset.isPending}>
    Substituir asset
  </button>
</form>
```

- [ ] **Step 2: Run the build**

Run: `cd webui && npm run build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add webui/src/pages/PieceDetail.tsx
git commit -m "feat(webui): add manual asset replacement to PieceDetail"
```

---

### Task 10: `AuditLogList` component + seção de histórico no `PieceDetail`

**Files:**
- Create: `webui/src/components/AuditLogList.tsx`
- Modify: `webui/src/pages/PieceDetail.tsx`

**Interfaces:**
- Produces: `AuditLogList({ entries: AuditLogEntry[] })` — the single place that reads `entry.details`, so the null-safety requirement is satisfied once and reused everywhere (Task 11 reuses it in `History.tsx`).

- [ ] **Step 1: Create the shared component**

```tsx
// webui/src/components/AuditLogList.tsx
import type { AuditLogEntry } from "../lib/types";

export function AuditLogList({ entries }: { entries: AuditLogEntry[] }) {
  if (entries.length === 0) {
    return <p>Nenhum evento registrado.</p>;
  }

  return (
    <ul>
      {entries.map((entry) => (
        <li key={entry.id}>
          <strong>{entry.action}</strong> por {entry.actor} em{" "}
          {new Date(entry.created_at).toLocaleString()}
          {/* Events recorded before the 5c history feature (approve/reject
              from 5a, all of 5b's config CRUD) have details === null — must
              render gracefully instead of reading .before/.after on null. */}
          {entry.details && (
            <ul>
              {Object.entries(entry.details).map(([field, change]) => (
                <li key={field}>
                  {field}: {String(change.before)} → {String(change.after)}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 2: Wire it into `PieceDetail.tsx`**

Add the import:

```tsx
import { AuditLogList } from "../components/AuditLogList";
import type { AuditLogEntry, PieceDetail as PieceDetailType, PieceUpdatePayload } from "../lib/types";
```

(replaces the existing type-only import line from Task 8.)

Add the query, alongside `detail`/`decide`/`edit`:

```tsx
const history = useQuery({
  queryKey: ["audit-log", "content_piece", id],
  queryFn: () =>
    apiClient.get<AuditLogEntry[]>(
      `/content/ui/audit-log?entity_type=content_piece&entity_id=${id}`
    ),
});
```

Render at the end of the component, after the "Publicações" `<ul>`:

```tsx
<h2>Histórico</h2>
{history.isLoading && <p>Carregando histórico...</p>}
{history.data && <AuditLogList entries={history.data} />}
```

- [ ] **Step 3: Run the build**

Run: `cd webui && npm run build`
Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add webui/src/components/AuditLogList.tsx webui/src/pages/PieceDetail.tsx
git commit -m "feat(webui): add history section to PieceDetail via shared AuditLogList"
```

---

### Task 11: `History.tsx` — feed geral, nav e rota

**Files:**
- Create: `webui/src/pages/History.tsx`
- Modify: `webui/src/components/ConfigNav.tsx`
- Modify: `webui/src/App.tsx`

**Interfaces:**
- Consumes: `AuditLogList` (Task 10), `apiClient.get`, `AuditLogEntry`.

- [ ] **Step 1: Create the feed page**

```tsx
// webui/src/pages/History.tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { AuditLogList } from "../components/AuditLogList";
import type { AuditLogEntry } from "../lib/types";

const ENTITY_TYPES = [
  { value: "", label: "Todos" },
  { value: "content_piece", label: "Peças" },
  { value: "content_client", label: "Clientes" },
  { value: "content_campaign", label: "Campanhas" },
  { value: "content_avatar", label: "Avatares" },
  { value: "content_social_account", label: "Contas sociais" },
  { value: "content_approval_rule", label: "Regras de aprovação" },
  { value: "content_generation_template", label: "Templates" },
  { value: "content_generation_provider", label: "Provedores" },
];

const PAGE_SIZE = 50;

export function History() {
  const [entityType, setEntityType] = useState("");
  const [offset, setOffset] = useState(0);

  const feed = useQuery({
    queryKey: ["audit-log", "feed", entityType, offset],
    queryFn: () =>
      apiClient.get<AuditLogEntry[]>(
        `/content/ui/audit-log?limit=${PAGE_SIZE}&offset=${offset}` +
          (entityType ? `&entity_type=${entityType}` : "")
      ),
  });

  return (
    <div>
      <h1>Histórico</h1>

      <select
        value={entityType}
        onChange={(event) => {
          setEntityType(event.target.value);
          setOffset(0);
        }}
      >
        {ENTITY_TYPES.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      {feed.isLoading && <p>Carregando...</p>}
      {feed.isError && <p>Erro ao carregar. Tente novamente.</p>}
      {feed.data && <AuditLogList entries={feed.data} />}

      <div>
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Anterior
        </button>
        <button
          disabled={(feed.data?.length ?? 0) < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          Próxima
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the nav link**

In `webui/src/components/ConfigNav.tsx`, add `"Histórico"` to `LINKS`:

```tsx
const LINKS = [
  { to: "/config/clients", label: "Clients" },
  { to: "/config/campaigns", label: "Campaigns" },
  { to: "/config/social-accounts", label: "Social Accounts" },
  { to: "/config/avatars", label: "Avatars" },
  { to: "/config/approval-rules", label: "Approval Rules" },
  { to: "/config/templates", label: "Templates" },
  { to: "/config/providers", label: "Providers" },
  { to: "/history", label: "Histórico" },
];
```

- [ ] **Step 3: Add the route**

In `webui/src/App.tsx`, add the import and route:

```tsx
import { History } from "./pages/History";
```

```tsx
<Route path="/history" element={<History />} />
```

(add it as the last `<Route>` inside `<Routes>`.)

- [ ] **Step 4: Run the build**

Run: `cd webui && npm run build`
Expected: succeeds.

- [ ] **Step 5: Commit**

```bash
git add webui/src/pages/History.tsx webui/src/components/ConfigNav.tsx webui/src/App.tsx
git commit -m "feat(webui): add tenant-wide history feed page"
```

---

### Task 12: Validação manual via `/run`

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend suite one more time**

Run: `python3 -m pytest test/services/ -v`
Expected: PASS, zero regressions across the whole content module.

- [ ] **Step 2: Run the Alembic migration against a real (or local) Postgres**

Run: `alembic upgrade head`
Expected: succeeds; `content_audit_logs` gains a nullable `details` column; existing rows read back with `details = NULL`.

- [ ] **Step 3: Launch the app and the SPA via `/run`**

Use the `run` skill to start the backend and `webui` dev server.

- [ ] **Step 4: Manual checklist as `admin`**

- Open a piece in `draft`/`pending_approval`/`failed`: edit `generation_prompt` and `risk_level`, save, confirm the piece's status is unchanged and the new values show up.
- Open an `approved` (or `rejected`) piece: edit any field, save, confirm the piece disappears from that tab and reappears under "Aguardando revisão" (`pending_approval`).
- On that same piece, open its "Histórico" section: confirm the edit entry shows both the field diff and `status: approved → pending_approval` in the same entry.
- Replace the asset on a piece: confirm the new asset renders and the old one no longer appears (but check via the API/DB that the old `ContentAsset` row still exists with `is_intermediate=true`).
- Try to edit or replace the asset of a `posted` piece: confirm both are blocked in the UI and the backend returns 409 if attempted directly.
- Open `/history`: confirm it lists events across entity types (pieces, clients, campaigns, etc.), confirm the `entity_type` filter works, confirm older entries (from 5a/5b, `details = null`) render without a diff section and without any console error.

- [ ] **Step 5: Manual checklist as `member`**

- Confirm the edit form and asset-upload form are not rendered on `PieceDetail`.
- Confirm `/history` and the piece's "Histórico" section are visible (read-only).
- Confirm a direct `PATCH`/`POST .../asset` call (e.g. via browser devtools or curl with the member's token) returns 403.

No commit for this task — it's a verification checkpoint. If any step fails, return to the relevant earlier task and fix it before considering 5c done.
