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
