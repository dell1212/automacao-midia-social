# UI de revisão e aprovação (fase 5a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a JWT-based user session (inherited from a future "app mãe", embedded via iframe) and a React review/approval screen so a human at an agency can see pending content pieces, preview their media, and approve/reject them — without touching any of the four already-shipped sub-projects.

**Architecture:** Backend gets one new, additive auth dependency (`verify_user_session`, RS256 JWT) and six new routes under `/v1/content/ui/...` that reuse the existing services (`pieces`, `campaigns`, `publications`, `storage`) — no existing route or auth mechanism changes. Frontend is a standalone Vite + React + TypeScript SPA in `webui/`, built to run inside an `<iframe>`, that receives its session token via `postMessage` and talks only to the new `/ui/...` routes.

**Tech Stack:** Backend: FastAPI, SQLModel, PyJWT (new dependency) + `cryptography` (already present) for RS256. Frontend: React 18, Vite, TypeScript, react-router-dom, @tanstack/react-query.

**Spec:** [docs/superpowers/specs/2026-08-29-ui-revisao-aprovacao-design.md](../specs/2026-08-29-ui-revisao-aprovacao-design.md)

## Global Constraints

- Session token algorithm: RS256 only (no HS256 fallback) — app mãe holds the private key, this module holds only `CONTENT_UI_JWT_PUBLIC_KEY` (env, PEM).
- `verify_user_session` fails closed: missing/malformed/expired/badly-signed token → `401`; unconfigured public key → `500` (same fail-closed pattern as `verify_admin_token`).
- Roles are exactly `"admin"` and `"member"` — any other value in the `role` claim is an invalid token (`401`), not a third role.
- No existing route, service function signature, or auth dependency (`verify_tenant_token`, `verify_admin_token`) may change behavior. All new backend surface lives in new files or additive function parameters with defaults.
- Session token is held in memory only on the frontend (`useState`/context) — never `localStorage`/`sessionStorage`.
- Backend re-checks role on every mutating `/ui/...` route — the frontend disabling a button is UX only, never the actual guard.
- Signed URLs (`storage.create_signed_url`) are generated only for `/ui/pieces/{id}` responses; no existing upload/fetch path in `pipeline.py`/`orchestrator.py`/`publish_dispatcher.py` changes.
- Backend tasks follow TDD (test-first, matches existing `test/services/test_content_*.py` convention — `unittest.TestCase` + `MagicMock` sessions, run via `python3 -m pytest`). Frontend tasks have no automated test suite (project convention: no tests by default) — each frontend task ends with a manual verification step instead.

---

### Task 1: `verify_user_session` + `require_role` (JWT auth)

**Files:**
- Modify: `requirements.txt`
- Modify: `app/controllers/content_auth.py`
- Modify: `test/services/test_content_auth.py`
- Modify: `config.example.toml`

**Interfaces:**
- Consumes: nothing new (uses existing `ContentTenant`, `EntitlementStatus` from `app.models.content`, existing `get_session` from `app.db`).
- Produces: `content_auth.UserSession` (dataclass: `tenant: ContentTenant`, `user_id: str`, `role: str`, `name: Optional[str]`), `content_auth.verify_user_session(authorization, session) -> UserSession`, `content_auth.require_role(user_session: UserSession, role: str) -> None`. Task 6 (`ui.py` controller) depends on all three.

- [ ] **Step 1: Add PyJWT to requirements**

Edit `requirements.txt`, add this line near `cryptography==43.0.3`:

```
PyJWT==2.13.0
```

Install it:

```bash
pip install PyJWT==2.13.0
```

- [ ] **Step 2: Write the failing tests**

Append to `test/services/test_content_auth.py` (add these imports at the top, alongside the existing ones):

```python
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
```

Add this helper near the top of the file, after the existing `_session_returning` helper:

```python
def _generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem
```

Append these test classes at the end of the file, before `if __name__ == "__main__":`:

```python
class TestVerifyUserSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_pem, cls.public_pem = _generate_rsa_keypair()
        cls.other_private_pem, _ = _generate_rsa_keypair()

    def _token(self, private_pem=None, **claim_overrides):
        claims = {
            "tenant_id": 1,
            "user_id": "user-1",
            "role": "admin",
            "name": "Ana",
            "exp": int(time.time()) + 3600,
        }
        claims.update(claim_overrides)
        return jwt.encode(claims, private_pem or self.private_pem, algorithm="RS256")

    def _tenant(self, status=EntitlementStatus.active):
        return ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=status,
        )

    def _session_returning_tenant(self, tenant):
        session = MagicMock()
        session.get.return_value = tenant
        return session

    def test_missing_header_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=None, session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_non_bearer_header_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization="Token abc", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_public_key_env_fails_closed_with_500(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {self._token()}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 500)

    def test_wrong_signature_is_rejected(self):
        token = self._token(private_pem=self.other_private_pem)
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_is_rejected(self):
        token = self._token(exp=int(time.time()) - 60)
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_tenant_id_claim_is_rejected(self):
        claims = {
            "user_id": "user-1",
            "role": "admin",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(claims, self.private_pem, algorithm="RS256")
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invalid_role_claim_is_rejected(self):
        token = self._token(role="superadmin")
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_tenant_is_rejected(self):
        token = self._token()
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}",
                    session=self._session_returning_tenant(None),
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_inactive_tenant_is_rejected_with_403(self):
        token = self._token()
        tenant = self._tenant(status=EntitlementStatus.inactive)
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}",
                    session=self._session_returning_tenant(tenant),
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_valid_token_returns_user_session(self):
        token = self._token()
        tenant = self._tenant()
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            result = content_auth.verify_user_session(
                authorization=f"Bearer {token}",
                session=self._session_returning_tenant(tenant),
            )
        self.assertIs(result.tenant, tenant)
        self.assertEqual(result.user_id, "user-1")
        self.assertEqual(result.role, "admin")
        self.assertEqual(result.name, "Ana")


class TestRequireRole(unittest.TestCase):
    def test_matching_role_passes(self):
        session = content_auth.UserSession(
            tenant=MagicMock(), user_id="u1", role="admin", name=None
        )
        content_auth.require_role(session, "admin")  # does not raise

    def test_mismatched_role_raises_403(self):
        session = content_auth.UserSession(
            tenant=MagicMock(), user_id="u1", role="member", name=None
        )
        with self.assertRaises(HTTPException) as ctx:
            content_auth.require_role(session, "admin")
        self.assertEqual(ctx.exception.status_code, 403)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_auth.py -v`
Expected: FAIL — `AttributeError: module 'app.controllers.content_auth' has no attribute 'verify_user_session'` (and related for `UserSession`/`require_role`).

- [ ] **Step 4: Implement `verify_user_session` and `require_role`**

Edit `app/controllers/content_auth.py`. Add imports at the top (after the existing ones):

```python
from dataclasses import dataclass

import jwt
```

Add this constant near `_ADMIN_TOKEN_ENV`:

```python
_UI_JWT_PUBLIC_KEY_ENV = "CONTENT_UI_JWT_PUBLIC_KEY"
_VALID_ROLES = {"admin", "member"}
```

Append at the end of the file:

```python
@dataclass(frozen=True)
class UserSession:
    tenant: ContentTenant
    user_id: str
    role: str
    name: Optional[str]


def verify_user_session(
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> UserSession:
    """Validates the RS256 session JWT the parent app hands the iframe.

    Additive to verify_tenant_token/verify_admin_token — used only by the
    new /v1/content/ui/... routes. Fails closed like verify_admin_token:
    an unconfigured public key is a 500, not an open door.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[len("Bearer ") :]

    public_key = os.environ.get(_UI_JWT_PUBLIC_KEY_ENV)
    if not public_key:
        raise HTTPException(
            status_code=500,
            detail=f"{_UI_JWT_PUBLIC_KEY_ENV} is not configured on the server",
        )

    try:
        claims = jwt.decode(token, public_key, algorithms=["RS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid session token")

    tenant_id = claims.get("tenant_id")
    user_id = claims.get("user_id")
    role = claims.get("role")
    if tenant_id is None or not user_id or role not in _VALID_ROLES:
        raise HTTPException(status_code=401, detail="Invalid session token")

    tenant = session.get(ContentTenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid session token")

    if tenant.entitlement_status == EntitlementStatus.inactive:
        raise HTTPException(status_code=403, detail="Tenant is not entitled")

    return UserSession(tenant=tenant, user_id=str(user_id), role=role, name=claims.get("name"))


def require_role(user_session: UserSession, role: str) -> None:
    if user_session.role != role:
        raise HTTPException(status_code=403, detail=f"Requires role '{role}'")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_auth.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 6: Document the new env var**

Edit `config.example.toml`, add after the `CONTENT_AUTOMATION_*` block (after the line documenting `CONTENT_AUTOMATION_BATCH_SIZE`):

```toml

# Content module — UI session auth (sub-project 5a).
# This is a secret and must be set as an environment variable, never here:
#   CONTENT_UI_JWT_PUBLIC_KEY=<RS256 public key, PEM format>   # required for /v1/content/ui/... routes
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/controllers/content_auth.py test/services/test_content_auth.py config.example.toml
git commit -m "feat(content): add JWT user-session auth for the UI module

verify_user_session validates an RS256 token handed to the iframe by a
future parent app, additive to the existing tenant/admin token auth.
require_role gates admin-only actions. Neither existing dependency
changes behavior."
```

---

### Task 2: `list_pieces` status filter

**Files:**
- Modify: `app/services/content/pieces.py`
- Modify: `test/services/test_content_pieces.py`

**Interfaces:**
- Consumes: `ContentPieceStatus` (already defined in `app.models.content`).
- Produces: `pieces_service.list_pieces(session, *, tenant_id, campaign_id, status=None)` — `status` is a new optional keyword-only-by-convention parameter (existing callers pass no `status`, unaffected). Task 6 (`ui.py`) calls this with a `status` value.

**Context:** `pieces.py` currently has a second, mid-file `from app.models.content import ContentPieceStatus, ContentPieceType` (after `get_piece`, before `find_by_idempotency_key`) — that import runs *after* `list_pieces` is already defined, so referencing `ContentPieceStatus` in `list_pieces`'s signature today would raise `NameError` at import time. This task consolidates the imports at the top of the file as part of adding the parameter — a mechanical, same-imports move, not a rewrite.

- [ ] **Step 1: Write the failing test**

Add this test class to `test/services/test_content_pieces.py`, after `TestRequiredKinds` (add `from app.models.content import ContentPieceStatus` to the existing imports at the top if not already present — it is not, currently only `ContentCategory, ContentPieceType, RiskLevel` are imported):

```python
class TestListPieces(unittest.TestCase):
    def test_returns_empty_list_when_campaign_not_found(self):
        session = MagicMock()

        with patch.object(pieces_service, "get_campaign", return_value=None):
            result = pieces_service.list_pieces(session, tenant_id=1, campaign_id=99)

        self.assertEqual(result, [])

    def test_no_status_filters_by_campaign_only(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["piece-a", "piece-b"]

        with patch.object(pieces_service, "get_campaign", return_value=MagicMock()):
            result = pieces_service.list_pieces(session, tenant_id=1, campaign_id=1)

        self.assertEqual(result, ["piece-a", "piece-b"])
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("CAMPAIGN_ID = 1", compiled)
        self.assertNotIn("STATUS", compiled)

    def test_status_filter_is_applied_when_given(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["piece-a"]

        with patch.object(pieces_service, "get_campaign", return_value=MagicMock()):
            result = pieces_service.list_pieces(
                session,
                tenant_id=1,
                campaign_id=1,
                status=ContentPieceStatus.pending_approval,
            )

        self.assertEqual(result, ["piece-a"])
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("CAMPAIGN_ID = 1", compiled)
        self.assertIn("STATUS = 'PENDING_APPROVAL'", compiled)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/services/test_content_pieces.py -v`
Expected: FAIL — `TypeError: list_pieces() got an unexpected keyword argument 'status'` (third test) and the first two currently pass by accident since they don't touch `status` yet; run to confirm the third fails.

- [ ] **Step 3: Consolidate imports and add the `status` parameter**

Replace the top of `app/services/content/pieces.py` (from the first line through the `find_by_idempotency_key`'s preceding import block) — i.e. everything from `from typing import List, Optional` through the `from app.services.content.policy import classify` line just before `def find_by_idempotency_key` — with:

```python
from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select, update

from app.models.content import (
    ContentCampaign,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentPieceType,
)
from app.models.content_generation import GenerationKind
from app.services.content import audit
from app.services.content.campaigns import get_campaign
from app.services.content.pipeline import schedule_piece
from app.services.content.policy import classify


def list_pieces(
    session: Session,
    *,
    tenant_id: int,
    campaign_id: int,
    status: Optional[ContentPieceStatus] = None,
) -> List[ContentPiece]:
    if get_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id) is None:
        return []
    statement = select(ContentPiece).where(ContentPiece.campaign_id == campaign_id)
    if status is not None:
        statement = statement.where(ContentPiece.status == status)
    return list(session.exec(statement).all())


def get_piece(session: Session, *, tenant_id: int, piece_id: int) -> Optional[ContentPiece]:
    return session.exec(
        select(ContentPiece)
        .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(ContentPiece.id == piece_id, ContentClient.tenant_id == tenant_id)
    ).first()
```

Leave everything from `def find_by_idempotency_key` onward untouched — the old mid-file import block (the duplicate `from datetime import datetime` / `from app.models.content import ContentPieceStatus, ContentPieceType` / etc. lines that used to sit between `get_piece` and `find_by_idempotency_key`) is deleted since it's now redundant with the consolidated top-of-file imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_pieces.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add app/services/content/pieces.py test/services/test_content_pieces.py
git commit -m "feat(content): add optional status filter to list_pieces

Consolidates pieces.py's split import blocks at the top of the file as
part of the change — ContentPieceStatus is now imported before
list_pieces references it in its signature."
```

---

### Task 3: `list_campaigns_for_tenant`

**Files:**
- Modify: `app/services/content/campaigns.py`
- Create: `test/services/test_content_campaigns.py`

**Interfaces:**
- Consumes: `ContentCampaign`, `ContentClient` (already imported in `campaigns.py`).
- Produces: `campaigns_service.list_campaigns_for_tenant(session, *, tenant_id) -> List[ContentCampaign]`. Task 6 (`ui.py`) calls this for `GET /ui/campaigns`.

- [ ] **Step 1: Write the failing test**

Create `test/services/test_content_campaigns.py`:

```python
import unittest
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.services.content import campaigns as campaigns_service


class TestListCampaignsForTenant(unittest.TestCase):
    def test_returns_campaigns_across_clients(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["campaign-a", "campaign-b"]

        result = campaigns_service.list_campaigns_for_tenant(session, tenant_id=1)

        self.assertEqual(result, ["campaign-a", "campaign-b"])
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("TENANT_ID = 1", compiled)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test/services/test_content_campaigns.py -v`
Expected: FAIL — `AttributeError: module 'app.services.content.campaigns' has no attribute 'list_campaigns_for_tenant'`.

- [ ] **Step 3: Implement it**

Append to `app/services/content/campaigns.py`:

```python
def list_campaigns_for_tenant(session: Session, *, tenant_id: int) -> List[ContentCampaign]:
    return list(
        session.exec(
            select(ContentCampaign)
            .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
            .where(ContentClient.tenant_id == tenant_id)
        ).all()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest test/services/test_content_campaigns.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/campaigns.py test/services/test_content_campaigns.py
git commit -m "feat(content): add list_campaigns_for_tenant for the UI campaign filter"
```

---

### Task 4: `storage.create_signed_url`

**Files:**
- Modify: `app/services/content/storage.py`
- Create: `test/services/test_content_storage.py`

**Interfaces:**
- Consumes: nothing new (`requests`, `_require_env`, `_bucket`, `StorageError` already exist in `storage.py`).
- Produces: `storage.create_signed_url(storage_path: str, *, expires_in: int = 600) -> str`. Task 5 (`ui_pieces.get_piece_detail`) calls this per asset.

- [ ] **Step 1: Write the failing tests**

Create `test/services/test_content_storage.py`:

```python
import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.content import storage


_ENV = {
    "SUPABASE_URL": "https://proj.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-key",
}


class TestCreateSignedUrl(unittest.TestCase):
    def test_returns_full_signed_url_on_success(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "signedURL": "/object/sign/content-assets/1/2/file.png?token=abc"
        }

        with patch.dict(os.environ, _ENV):
            with patch.object(storage.requests, "post", return_value=response) as mock_post:
                result = storage.create_signed_url("1/2/file.png", expires_in=600)

        self.assertEqual(
            result,
            "https://proj.supabase.co/storage/v1/object/sign/content-assets/1/2/file.png?token=abc",
        )
        mock_post.assert_called_once()
        called_url = mock_post.call_args.args[0]
        self.assertEqual(
            called_url,
            "https://proj.supabase.co/storage/v1/object/sign/content-assets/1/2/file.png",
        )
        self.assertEqual(mock_post.call_args.kwargs["json"], {"expiresIn": 600})

    def test_raises_storage_error_on_http_error(self):
        response = MagicMock(status_code=403)

        with patch.dict(os.environ, _ENV):
            with patch.object(storage.requests, "post", return_value=response):
                with self.assertRaises(storage.StorageError):
                    storage.create_signed_url("1/2/file.png")

    def test_raises_storage_error_when_response_missing_signed_url(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {}

        with patch.dict(os.environ, _ENV):
            with patch.object(storage.requests, "post", return_value=response):
                with self.assertRaises(storage.StorageError):
                    storage.create_signed_url("1/2/file.png")

    def test_raises_storage_error_when_service_key_missing(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://proj.supabase.co"}, clear=True):
            with self.assertRaises(storage.StorageError):
                storage.create_signed_url("1/2/file.png")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest test/services/test_content_storage.py -v`
Expected: FAIL — `AttributeError: module 'app.services.content.storage' has no attribute 'create_signed_url'`.

- [ ] **Step 3: Implement it**

Append to `app/services/content/storage.py`:

```python
def create_signed_url(storage_path: str, *, expires_in: int = 600) -> str:
    """Signs a storage_path for temporary UI access.

    Uploads and the pipeline/publish paths keep using the public URL
    persisted on ContentAsset.url — this is only for what the review UI
    hands to the browser, generated fresh on every call (no caching, the
    default 10-minute TTL is already short enough).
    """
    base_url = _require_env(_SUPABASE_URL_ENV).rstrip("/")
    service_key = _require_env(_SUPABASE_SERVICE_KEY_ENV)
    bucket = _bucket()
    endpoint = f"{base_url}/storage/v1/object/sign/{bucket}/{storage_path}"

    try:
        response = requests.post(
            endpoint,
            json={"expiresIn": expires_in},
            headers={"Authorization": f"Bearer {service_key}"},
            timeout=_UPLOAD_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageError(f"storage sign request failed for {storage_path}") from exc

    if response.status_code >= 400:
        raise StorageError(
            f"storage sign rejected for {storage_path}: status={response.status_code}"
        )

    signed_url = response.json().get("signedURL")
    if not signed_url:
        raise StorageError(f"storage sign response missing signedURL for {storage_path}")

    return f"{base_url}/storage/v1{signed_url}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_storage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/content/storage.py test/services/test_content_storage.py
git commit -m "feat(content): add create_signed_url for UI asset previews

No change to upload_bytes or any existing consumer of the public URL —
this is additive, used only by the new UI piece-detail endpoint."
```

---

### Task 5: `content_ui` response models + `ui_pieces.get_piece_detail`

**Files:**
- Create: `app/models/content_ui.py`
- Create: `app/services/content/ui_pieces.py`
- Create: `test/services/test_content_ui_pieces.py`

**Interfaces:**
- Consumes: `ContentAssetType` (`app.models.content_generation`), `PublicationRead` (`app.models.content_publishing`), `pieces_service.get_piece` (Task 2's module, unchanged signature), `assets_service.list_assets_for_piece` (`app.services.content.assets`, existing), `publications_service.list_publications_for_piece` (`app.services.content.publications`, existing), `storage.create_signed_url` (Task 4).
- Produces: `content_ui.UserSessionRead`, `content_ui.PieceAssetRead`, `content_ui.PieceDetailRead` (Pydantic `BaseModel`s); `ui_pieces.get_piece_detail(session, *, tenant_id, piece_id) -> Optional[PieceDetailRead]`. Task 6 (`ui.py` controller) uses all of these.

- [ ] **Step 1: Create the response models (no test — plain data classes)**

Create `app/models/content_ui.py`:

```python
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.models.content import ApprovalAction, ContentCategory, ContentPieceStatus, ContentPieceType, RiskLevel
from app.models.content_generation import ContentAssetType
from app.models.content_publishing import PublicationRead


class UserSessionRead(BaseModel):
    tenant_id: int
    tenant_name: str
    user_id: str
    role: str
    name: Optional[str]


class PieceAssetRead(BaseModel):
    type: ContentAssetType
    signed_url: str
    mime_type: Optional[str]
    width: Optional[int]
    height: Optional[int]
    duration: Optional[float]


class PieceDetailRead(BaseModel):
    id: int
    campaign_id: int
    type: ContentPieceType
    status: ContentPieceStatus
    generation_prompt: Optional[str]
    avatar_id: Optional[int]
    is_synthetic_media: bool
    content_category: Optional[ContentCategory]
    risk_level: RiskLevel
    requires_human_review: bool
    policy_version: str
    scheduled_for: Optional[datetime]
    approval_action: Optional[ApprovalAction]
    approved_at: Optional[datetime]
    posted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    assets: List[PieceAssetRead]
    publications: List[PublicationRead]
```

- [ ] **Step 2: Write the failing test for `get_piece_detail`**

Create `test/services/test_content_ui_pieces.py`:

```python
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceStatus, ContentPieceType, RiskLevel
from app.models.content_generation import ContentAssetType
from app.models.content_publishing import PublicationStatus
from app.services.content import ui_pieces


def _piece(**overrides):
    base = dict(
        id=10,
        campaign_id=1,
        type=ContentPieceType.image,
        status=ContentPieceStatus.pending_approval,
        generation_prompt="a cat",
        avatar_id=None,
        is_synthetic_media=True,
        content_category=None,
        risk_level=RiskLevel.none,
        requires_human_review=False,
        policy_version="v1",
        scheduled_for=None,
        approval_action=None,
        approved_at=None,
        posted_at=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return MagicMock(**base)


def _asset(**overrides):
    base = dict(
        type=ContentAssetType.image,
        storage_path="1/10/file.png",
        mime_type="image/png",
        width=1024,
        height=1024,
        duration=None,
        is_intermediate=False,
    )
    base.update(overrides)
    return MagicMock(**base)


def _publication(**overrides):
    base = dict(
        id=1,
        content_piece_id=10,
        social_account_id=1,
        platform="instagram",
        status=PublicationStatus.succeeded,
        attempt_count=1,
        max_attempts=3,
        publication_cycle=1,
        platform_post_id="p1",
        platform_post_url="https://instagram.com/p/1",
        error_code=None,
        error_message=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return MagicMock(**base)


class TestGetPieceDetail(unittest.TestCase):
    def test_returns_none_when_piece_not_found(self):
        session = MagicMock()

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=None):
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=99)

        self.assertIsNone(result)

    def test_excludes_intermediate_assets_and_signs_the_rest(self):
        session = MagicMock()
        piece = _piece()
        final_asset = _asset()
        intermediate_asset = _asset(storage_path="1/10/intermediate.png", is_intermediate=True)

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=piece), \
             patch.object(
                 ui_pieces.assets_service,
                 "list_assets_for_piece",
                 return_value=[intermediate_asset, final_asset],
             ), \
             patch.object(
                 ui_pieces.publications_service, "list_publications_for_piece", return_value=[]
             ), \
             patch.object(
                 ui_pieces.storage, "create_signed_url", return_value="https://signed/file.png"
             ) as mock_sign:
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=10)

        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].signed_url, "https://signed/file.png")
        mock_sign.assert_called_once_with("1/10/file.png")

    def test_includes_publications(self):
        session = MagicMock()
        piece = _piece()
        publication = _publication()

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=piece), \
             patch.object(ui_pieces.assets_service, "list_assets_for_piece", return_value=[]), \
             patch.object(
                 ui_pieces.publications_service,
                 "list_publications_for_piece",
                 return_value=[publication],
             ), \
             patch.object(ui_pieces.storage, "create_signed_url"):
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=10)

        self.assertEqual(len(result.publications), 1)
        self.assertEqual(result.publications[0].platform, "instagram")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest test/services/test_content_ui_pieces.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.content.ui_pieces'`.

- [ ] **Step 4: Implement `get_piece_detail`**

Create `app/services/content/ui_pieces.py`:

```python
from typing import Optional

from sqlmodel import Session

from app.models.content_publishing import PublicationRead
from app.models.content_ui import PieceAssetRead, PieceDetailRead
from app.services.content import assets as assets_service
from app.services.content import pieces as pieces_service
from app.services.content import publications as publications_service
from app.services.content import storage


def get_piece_detail(
    session: Session, *, tenant_id: int, piece_id: int
) -> Optional[PieceDetailRead]:
    piece = pieces_service.get_piece(session, tenant_id=tenant_id, piece_id=piece_id)
    if piece is None:
        return None

    assets = [
        PieceAssetRead(
            type=asset.type,
            signed_url=storage.create_signed_url(asset.storage_path),
            mime_type=asset.mime_type,
            width=asset.width,
            height=asset.height,
            duration=asset.duration,
        )
        for asset in assets_service.list_assets_for_piece(session, content_piece_id=piece.id)
        if not asset.is_intermediate
    ]

    publications = [
        PublicationRead.model_validate(publication, from_attributes=True)
        for publication in publications_service.list_publications_for_piece(
            session, content_piece_id=piece.id
        )
    ]

    return PieceDetailRead(
        id=piece.id,
        campaign_id=piece.campaign_id,
        type=piece.type,
        status=piece.status,
        generation_prompt=piece.generation_prompt,
        avatar_id=piece.avatar_id,
        is_synthetic_media=piece.is_synthetic_media,
        content_category=piece.content_category,
        risk_level=piece.risk_level,
        requires_human_review=piece.requires_human_review,
        policy_version=piece.policy_version,
        scheduled_for=piece.scheduled_for,
        approval_action=piece.approval_action,
        approved_at=piece.approved_at,
        posted_at=piece.posted_at,
        created_at=piece.created_at,
        updated_at=piece.updated_at,
        assets=assets,
        publications=publications,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest test/services/test_content_ui_pieces.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/models/content_ui.py app/services/content/ui_pieces.py test/services/test_content_ui_pieces.py
git commit -m "feat(content): add get_piece_detail composing assets (signed URLs) and publications for the UI"
```

---

### Task 6: `/v1/content/ui/...` controller

**Files:**
- Create: `app/controllers/v1/content/ui.py`
- Modify: `app/router.py`

**Interfaces:**
- Consumes: `content_auth.verify_user_session`, `content_auth.UserSession`, `content_auth.require_role` (Task 1); `pieces_service.list_pieces`, `.get_piece`, `.approve_piece`, `.reject_piece` (Task 2 / existing); `campaigns_service.list_campaigns_for_tenant` (Task 3); `ui_pieces_service.get_piece_detail` (Task 5); `content_ui.UserSessionRead`, `.PieceDetailRead` (Task 5); `CampaignRead`, `ContentPieceRead`, `ContentPieceStatus` (existing, `app.models.content`); `audit.write_audit_log` (existing).
- Produces: the six `/v1/content/ui/...` routes the frontend (Tasks 7-10) calls.

- [ ] **Step 1: Implement the controller**

Create `app/controllers/v1/content/ui.py`:

```python
from typing import Optional

from fastapi import Depends, HTTPException
from sqlmodel import Session

from app.controllers import content_auth
from app.controllers.v1.base import new_router
from app.db import get_session
from app.models.content import CampaignRead, ContentPieceRead, ContentPieceStatus
from app.models.content_ui import PieceDetailRead, UserSessionRead
from app.services.content import audit
from app.services.content import campaigns as campaigns_service
from app.services.content import pieces as pieces_service
from app.services.content import ui_pieces as ui_pieces_service

router = new_router(dependencies=[Depends(content_auth.verify_user_session)])


@router.get("/content/ui/session", response_model=UserSessionRead)
def get_session_info(
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return UserSessionRead(
        tenant_id=user_session.tenant.id,
        tenant_name=user_session.tenant.name,
        user_id=user_session.user_id,
        role=user_session.role,
        name=user_session.name,
    )


@router.get("/content/ui/campaigns", response_model=list[CampaignRead])
def list_campaigns(
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return campaigns_service.list_campaigns_for_tenant(
        session, tenant_id=user_session.tenant.id
    )


@router.get("/content/ui/pieces", response_model=list[ContentPieceRead])
def list_pieces(
    campaign_id: int,
    status: Optional[ContentPieceStatus] = None,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    return pieces_service.list_pieces(
        session,
        tenant_id=user_session.tenant.id,
        campaign_id=campaign_id,
        status=status,
    )


@router.get("/content/ui/pieces/{piece_id}", response_model=PieceDetailRead)
def get_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    detail = ui_pieces_service.get_piece_detail(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Content piece not found")
    return detail


@router.post("/content/ui/pieces/{piece_id}/approve", response_model=ContentPieceRead)
def approve_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.approve_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to approve, got '{piece.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="approved",
        actor=f"user:{user_session.user_id}",
    )
    return updated


@router.post("/content/ui/pieces/{piece_id}/reject", response_model=ContentPieceRead)
def reject_piece(
    piece_id: int,
    session: Session = Depends(get_session),
    user_session: content_auth.UserSession = Depends(content_auth.verify_user_session),
):
    content_auth.require_role(user_session, "admin")

    piece = pieces_service.get_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if piece is None:
        raise HTTPException(status_code=404, detail="Content piece not found")

    updated = pieces_service.reject_piece(
        session, tenant_id=user_session.tenant.id, piece_id=piece_id
    )
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail=f"Piece must be pending_approval to reject, got '{piece.status.value}'",
        )

    audit.write_audit_log(
        session,
        tenant_id=user_session.tenant.id,
        entity_type="content_piece",
        entity_id=piece_id,
        action="rejected",
        actor=f"user:{user_session.user_id}",
    )
    return updated
```

- [ ] **Step 2: Register the router**

Read `app/router.py` first to see the exact existing import block and registration pattern (`from app.controllers.v1.content import (...)` and the corresponding `app.include_router(...)` calls) — add `ui` to that import tuple and add its `include_router` call in the same style as the other content routers (e.g. `pieces`, `publications`).

- [ ] **Step 3: Verify the app imports cleanly and the routes are wired**

Run:

```bash
python3 -c "from app.main import app; paths = sorted(r.path for r in app.routes if 'ui' in r.path); print(paths)"
```

Expected output includes all six new paths:
```
['/api/v1/content/ui/campaigns', '/api/v1/content/ui/pieces', '/api/v1/content/ui/pieces/{piece_id}', '/api/v1/content/ui/pieces/{piece_id}/approve', '/api/v1/content/ui/pieces/{piece_id}/reject', '/api/v1/content/ui/session']
```

(Adjust the expected list if `new_router`'s `/api/v1` prefix or path ordering differs from what you observe — the point of this step is confirming no import error and all six routes are present, not matching this exact string.)

- [ ] **Step 4: Run the full content test suite**

Run: `python3 -m pytest test/services/ -k content -v`
Expected: PASS — every content test, old and new, green.

- [ ] **Step 5: Commit**

```bash
git add app/controllers/v1/content/ui.py app/router.py
git commit -m "feat(content): add /v1/content/ui/... routes for the review/approval UI

Session, campaigns, pieces list/detail, approve/reject — all behind
verify_user_session, approve/reject additionally gated to role=admin.
No existing /v1/content/... route changes."
```

---

### Task 7: `webui/` scaffold + `apiClient`

**Files:**
- Create: `webui/` (Vite + React + TS project, generated)
- Create: `webui/src/lib/apiClient.ts`
- Create: `webui/.env.example`

**Interfaces:**
- Produces: `apiClient.get<T>(path: string): Promise<T>`, `apiClient.post<T>(path: string): Promise<T>`, `apiClient.setToken(token: string | null): void`, `class ApiError extends Error { status: number }`. Tasks 8-10 import all of these.

- [ ] **Step 1: Scaffold the Vite project**

```bash
cd /Users/gilbertomacbook/projeto-mosaic-automacao
npm create vite@latest webui -- --template react-ts
cd webui
npm install
npm install react-router-dom @tanstack/react-query
```

- [ ] **Step 2: Remove Vite's default demo content**

Delete the contents of `webui/src/App.css` (leave the file empty — Task 10 adds real styles) and remove the counter demo from `webui/src/App.tsx` (Task 10 replaces it entirely).

- [ ] **Step 3: Create the env example**

Create `webui/.env.example`:

```
VITE_PARENT_ORIGIN=https://app-mae.example.com
VITE_API_BASE_URL=/api/v1
```

- [ ] **Step 4: Create the API client**

Create `webui/src/lib/apiClient.ts`:

```typescript
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let currentToken: string | null = null;

export function setToken(token: string | null): void {
  currentToken = token;
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(currentToken ? { Authorization: `Bearer ${currentToken}` } : {}),
      "Content-Type": "application/json",
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
  post: <T>(path: string): Promise<T> => request<T>(path, { method: "POST" }),
  setToken,
};
```

- [ ] **Step 5: Verify the project builds**

```bash
cd webui
npm run build
```

Expected: build succeeds (Vite prints `✓ built in ...`), no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/gilbertomacbook/projeto-mosaic-automacao
git add webui/
git commit -m "feat(webui): scaffold Vite + React + TS project with a typed API client"
```

---

### Task 8: `SessionProvider`

**Files:**
- Create: `webui/src/context/SessionProvider.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 7).
- Produces: `<SessionProvider>` component, `useSession()` hook returning `{ status: "waiting" | "loading" | "ready" | "error", session: UserSessionRead | null, canApprove: () => boolean }`. Tasks 9-10 use `useSession()`.

- [ ] **Step 1: Implement the provider**

Create `webui/src/context/SessionProvider.tsx`:

```tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { apiClient, setToken } from "../lib/apiClient";

interface UserSessionRead {
  tenant_id: number;
  tenant_name: string;
  user_id: string;
  role: "admin" | "member";
  name: string | null;
}

type SessionStatus = "waiting" | "loading" | "ready" | "error";

interface SessionContextValue {
  status: SessionStatus;
  session: UserSessionRead | null;
  canApprove: () => boolean;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

const PARENT_ORIGIN = import.meta.env.VITE_PARENT_ORIGIN as string | undefined;
const WAIT_TIMEOUT_MS = 15000;

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("waiting");
  const [session, setSession] = useState<UserSessionRead | null>(null);

  useEffect(() => {
    const timeout = setTimeout(() => {
      setStatus((current) => (current === "waiting" ? "error" : current));
    }, WAIT_TIMEOUT_MS);

    async function handleMessage(event: MessageEvent) {
      if (PARENT_ORIGIN && event.origin !== PARENT_ORIGIN) return;
      if (event.data?.type !== "session" || typeof event.data.token !== "string") return;

      clearTimeout(timeout);
      setStatus("loading");
      setToken(event.data.token);

      try {
        const result = await apiClient.get<UserSessionRead>("/content/ui/session");
        setSession(result);
        setStatus("ready");
      } catch {
        setStatus("error");
      }
    }

    window.addEventListener("message", handleMessage);
    window.parent.postMessage({ type: "ready" }, PARENT_ORIGIN ?? "*");

    return () => {
      window.removeEventListener("message", handleMessage);
      clearTimeout(timeout);
    };
  }, []);

  const canApprove = () => session?.role === "admin";

  return (
    <SessionContext.Provider value={{ status, session, canApprove }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used within a SessionProvider");
  return context;
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd webui
npm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/gilbertomacbook/projeto-mosaic-automacao
git add webui/src/context/SessionProvider.tsx
git commit -m "feat(webui): add SessionProvider — postMessage session intake + role check"
```

---

### Task 9: `PieceQueue` page

**Files:**
- Create: `webui/src/pages/PieceQueue.tsx`
- Create: `webui/src/lib/types.ts`

**Interfaces:**
- Consumes: `apiClient` (Task 7), `useSession` (Task 8).
- Produces: `<PieceQueue>` component (route `/`), shared types `ContentPieceStatus`, `ContentPieceSummary`, `Campaign` in `webui/src/lib/types.ts`. Task 10 imports the same types.

- [ ] **Step 1: Add shared types**

Create `webui/src/lib/types.ts`:

```typescript
export type ContentPieceStatus =
  | "draft"
  | "generating"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "posted"
  | "failed";

export interface Campaign {
  id: number;
  client_id: number;
  name: string;
  horizon_days: number;
  status: string;
  created_at: string;
}

export interface ContentPieceSummary {
  id: number;
  campaign_id: number;
  type: "video" | "image" | "audio";
  status: ContentPieceStatus;
  generation_prompt: string | null;
  scheduled_for: string | null;
  posted_at: string | null;
  created_at: string;
}
```

- [ ] **Step 2: Implement the page**

Create `webui/src/pages/PieceQueue.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiClient } from "../lib/apiClient";
import { Campaign, ContentPieceStatus, ContentPieceSummary } from "../lib/types";

const TABS: { label: string; value: ContentPieceStatus }[] = [
  { label: "Aguardando revisão", value: "pending_approval" },
  { label: "Aprovadas", value: "approved" },
  { label: "Rejeitadas", value: "rejected" },
  { label: "Publicadas", value: "posted" },
  { label: "Falhas", value: "failed" },
];

export function PieceQueue() {
  const [status, setStatus] = useState<ContentPieceStatus>("pending_approval");
  const [campaignId, setCampaignId] = useState<number | null>(null);

  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => apiClient.get<Campaign[]>("/content/ui/campaigns"),
  });

  const activeCampaignId = campaignId ?? campaigns.data?.[0]?.id ?? null;

  const pieces = useQuery({
    queryKey: ["pieces", activeCampaignId, status],
    queryFn: () =>
      apiClient.get<ContentPieceSummary[]>(
        `/content/ui/pieces?campaign_id=${activeCampaignId}&status=${status}`
      ),
    enabled: activeCampaignId !== null,
  });

  return (
    <div>
      <select
        value={activeCampaignId ?? ""}
        onChange={(event) => setCampaignId(Number(event.target.value))}
      >
        {campaigns.data?.map((campaign) => (
          <option key={campaign.id} value={campaign.id}>
            {campaign.name}
          </option>
        ))}
      </select>

      <nav>
        {TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setStatus(tab.value)}
            aria-current={status === tab.value}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {pieces.isLoading && <p>Carregando...</p>}
      {pieces.isError && <p>Erro ao carregar. Tente novamente.</p>}

      <ul>
        {pieces.data?.map((piece) => (
          <li key={piece.id}>
            <Link to={`/pieces/${piece.id}`}>
              #{piece.id} — {piece.type} — {piece.generation_prompt ?? "(sem prompt)"}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Verify it compiles**

```bash
cd webui
npm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/gilbertomacbook/projeto-mosaic-automacao
git add webui/src/pages/PieceQueue.tsx webui/src/lib/types.ts
git commit -m "feat(webui): add PieceQueue page with status tabs and campaign filter"
```

---

### Task 10: `PieceDetail` page + routing + manual verification

**Files:**
- Create: `webui/src/pages/PieceDetail.tsx`
- Modify: `webui/src/App.tsx`
- Modify: `webui/src/main.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 7), `useSession` (Task 8), `ContentPieceStatus` (Task 9's `types.ts`).
- Produces: `<PieceDetail>` component (route `/pieces/:id`), the wired `<App>` with both routes behind `<SessionProvider>`.

- [ ] **Step 1: Add shared response types for the detail payload**

Append to `webui/src/lib/types.ts`:

```typescript
export interface PieceAsset {
  type: "image" | "audio" | "video" | "thumbnail" | "subtitle";
  signed_url: string;
  mime_type: string | null;
  width: number | null;
  height: number | null;
  duration: number | null;
}

export interface Publication {
  id: number;
  social_account_id: number;
  platform: string;
  status: "queued" | "running" | "retrying" | "succeeded" | "failed";
  platform_post_url: string | null;
  error_message: string | null;
}

export interface PieceDetail extends ContentPieceSummary {
  avatar_id: number | null;
  is_synthetic_media: boolean;
  content_category: string | null;
  risk_level: string;
  requires_human_review: boolean;
  assets: PieceAsset[];
  publications: Publication[];
}
```

- [ ] **Step 2: Implement the page**

Create `webui/src/pages/PieceDetail.tsx`:

```tsx
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { apiClient, ApiError } from "../lib/apiClient";
import { useSession } from "../context/SessionProvider";
import { PieceDetail as PieceDetailType } from "../lib/types";

export function PieceDetail() {
  const { id } = useParams<{ id: string }>();
  const { canApprove } = useSession();
  const queryClient = useQueryClient();

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

  if (detail.isLoading) return <p>Carregando...</p>;
  if (detail.isError) return <p>Erro ao carregar esta peça.</p>;
  if (!detail.data) return null;

  const piece = detail.data;
  const canDecide = canApprove() && piece.status === "pending_approval";
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

- [ ] **Step 3: Wire routing**

Replace the contents of `webui/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SessionProvider, useSession } from "./context/SessionProvider";
import { PieceQueue } from "./pages/PieceQueue";
import { PieceDetail } from "./pages/PieceDetail";

function Gate({ children }: { children: React.ReactNode }) {
  const { status } = useSession();

  if (status === "waiting") return <p>Aguardando sessão do app mãe...</p>;
  if (status === "loading") return <p>Validando sessão...</p>;
  if (status === "error") return <p>Sessão expirada ou inválida. Feche e reabra este painel.</p>;

  return <>{children}</>;
}

export function App() {
  return (
    <SessionProvider>
      <Gate>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<PieceQueue />} />
            <Route path="/pieces/:id" element={<PieceDetail />} />
          </Routes>
        </BrowserRouter>
      </Gate>
    </SessionProvider>
  );
}
```

Replace the contents of `webui/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";

const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
```

- [ ] **Step 4: Verify the project builds**

```bash
cd webui
npm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 5: Manual verification end-to-end**

This is the checklist from the spec's "Testes" section — run it now that both frontend and backend exist:

1. Start the backend: `python3 -m app.main` (or however this repo normally starts the FastAPI server — check `README.md` if unsure), with `CONTENT_UI_JWT_PUBLIC_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` set in the environment.
2. Start the frontend dev server: `cd webui && npm run dev`.
3. Build a tiny local HTML harness (outside the repo, e.g. in `/tmp`) that embeds `http://localhost:5173` in an `<iframe>` and, on load, `postMessage`s a JWT signed with a locally-generated RSA key pair (matching `CONTENT_UI_JWT_PUBLIC_KEY`) containing `tenant_id`/`user_id`/`role`/`exp` for a real tenant seeded in the dev database.
4. Confirm: the SPA leaves the "aguardando sessão" state once the token arrives; the queue loads pieces filtered by the default tab; switching tabs refetches; opening a piece shows its media via the signed URL (confirm the URL is short-lived by inspecting the query string, not by waiting out the TTL); approving/rejecting a `pending_approval` piece works and the piece disappears from the current tab; re-running the harness with `role: "member"` shows the buttons disabled with a tooltip and a direct `POST` to `/approve` still returns `403`.

- [ ] **Step 6: Commit**

```bash
cd /Users/gilbertomacbook/projeto-mosaic-automacao
git add webui/src/pages/PieceDetail.tsx webui/src/App.tsx webui/src/main.tsx webui/src/lib/types.ts
git commit -m "feat(webui): add PieceDetail page, wire routing behind SessionProvider"
```

---
