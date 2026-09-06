import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import asgi
from app.controllers import content_auth
from app.db import get_session
from app.models.content import ContentTenant, EntitlementStatus

PATCH_URL = "/api/v1/content/tenants/5/entitlement"


def _tenant(status=EntitlementStatus.trial):
    return ContentTenant(
        id=5,
        owner_user_id="u1",
        name="AccioLyMind",
        slug="acciolymind",
        api_token_hash="hash",
        entitlement_status=status,
    )


class SetEntitlementRouteTestCase(unittest.TestCase):
    """Exercises PATCH .../entitlement through the real app: real admin-token
    dependency wiring, real Pydantic validation, real response_model."""

    def setUp(self):
        self.client = TestClient(asgi.app)
        asgi.app.dependency_overrides[content_auth.verify_admin_token] = lambda: None
        asgi.app.dependency_overrides[get_session] = lambda: MagicMock()

    def tearDown(self):
        asgi.app.dependency_overrides.clear()

    def test_sets_entitlement_and_returns_new_state(self):
        tenant = _tenant(EntitlementStatus.active)
        with patch(
            "app.controllers.v1.content.tenants.tenants_service.set_entitlement",
            return_value=(tenant, EntitlementStatus.trial),
        ), patch("app.controllers.v1.content.tenants.audit.write_audit_log"):
            response = self.client.patch(
                PATCH_URL, json={"entitlement_status": "active"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"tenant_id": 5, "entitlement_status": "active"}
        )

    def test_writes_audit_log_with_the_transition(self):
        tenant = _tenant(EntitlementStatus.inactive)
        with patch(
            "app.controllers.v1.content.tenants.tenants_service.set_entitlement",
            return_value=(tenant, EntitlementStatus.active),
        ), patch(
            "app.controllers.v1.content.tenants.audit.write_audit_log"
        ) as write_audit_log:
            self.client.patch(PATCH_URL, json={"entitlement_status": "inactive"})

        kwargs = write_audit_log.call_args.kwargs
        self.assertEqual(kwargs["tenant_id"], 5)
        self.assertEqual(kwargs["entity_type"], "tenant")
        self.assertEqual(kwargs["entity_id"], 5)
        self.assertEqual(kwargs["action"], "entitlement_changed")
        self.assertEqual(kwargs["actor"], "admin")
        self.assertEqual(kwargs["details"], {"from": "active", "to": "inactive"})

    def test_unknown_tenant_is_404_and_writes_no_audit_log(self):
        with patch(
            "app.controllers.v1.content.tenants.tenants_service.set_entitlement",
            return_value=None,
        ), patch(
            "app.controllers.v1.content.tenants.audit.write_audit_log"
        ) as write_audit_log:
            response = self.client.patch(
                PATCH_URL, json={"entitlement_status": "active"}
            )

        self.assertEqual(response.status_code, 404)
        write_audit_log.assert_not_called()

    def test_value_outside_the_enum_is_rejected(self):
        with patch(
            "app.controllers.v1.content.tenants.tenants_service.set_entitlement"
        ) as set_entitlement:
            response = self.client.patch(
                PATCH_URL, json={"entitlement_status": "premium"}
            )

        # This app installs a RequestValidationError handler that answers 400
        # (app/asgi.py) instead of FastAPI's default 422.
        self.assertIn(response.status_code, (400, 422))
        set_entitlement.assert_not_called()

    def test_missing_body_is_rejected(self):
        with patch(
            "app.controllers.v1.content.tenants.tenants_service.set_entitlement"
        ) as set_entitlement:
            response = self.client.patch(PATCH_URL, json={})

        self.assertIn(response.status_code, (400, 422))
        set_entitlement.assert_not_called()


class SetEntitlementAuthTestCase(unittest.TestCase):
    """The route must inherit the router-level verify_admin_token dependency.
    No override here: the real dependency runs, and with no CONTENT_ADMIN_TOKEN
    in the environment it fails closed."""

    def setUp(self):
        self.client = TestClient(asgi.app, raise_server_exceptions=False)
        asgi.app.dependency_overrides[get_session] = lambda: MagicMock()

    def tearDown(self):
        asgi.app.dependency_overrides.clear()

    def test_unconfigured_admin_token_fails_closed(self):
        # An empty value is the falsy case verify_admin_token treats as
        # unconfigured, and patch.dict restores whatever was there before.
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": ""}):
            response = self.client.patch(
                PATCH_URL, json={"entitlement_status": "active"}
            )
        self.assertEqual(response.status_code, 500)

    def test_wrong_admin_token_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": "right-token"}):
            response = self.client.patch(
                PATCH_URL,
                json={"entitlement_status": "active"},
                headers={"X-Admin-Token": "wrong-token"},
            )
        self.assertEqual(response.status_code, 401)


class SetEntitlementServiceTestCase(unittest.TestCase):
    def test_persists_the_new_status_and_returns_the_previous_one(self):
        from app.services.content import tenants as tenants_service

        tenant = _tenant(EntitlementStatus.trial)
        session = MagicMock()
        session.get.return_value = tenant

        result = tenants_service.set_entitlement(
            session, tenant_id=5, entitlement_status=EntitlementStatus.active
        )

        self.assertIsNotNone(result)
        updated, previous = result
        self.assertEqual(previous, EntitlementStatus.trial)
        self.assertEqual(updated.entitlement_status, EntitlementStatus.active)
        session.add.assert_called_once_with(tenant)
        session.commit.assert_called_once()

    def test_returns_none_for_unknown_tenant_without_writing(self):
        from app.services.content import tenants as tenants_service

        session = MagicMock()
        session.get.return_value = None

        result = tenants_service.set_entitlement(
            session, tenant_id=999, entitlement_status=EntitlementStatus.active
        )

        self.assertIsNone(result)
        session.add.assert_not_called()
        session.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
