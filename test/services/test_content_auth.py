import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.controllers import content_auth
from app.models.content import ContentTenant, EntitlementStatus
from app.services.content.crypto import hash_api_token


def _session_returning(tenant):
    session = MagicMock()
    session.exec.return_value.first.return_value = tenant
    return session


class TestVerifyAdminToken(unittest.TestCase):
    def test_missing_env_fails_closed_with_500(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_admin_token(x_admin_token="anything")

        self.assertEqual(ctx.exception.status_code, 500)

    def test_missing_header_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": "dev-admin-token"}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_admin_token(x_admin_token=None)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_token_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": "dev-admin-token"}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_admin_token(x_admin_token="wrong-token")

        self.assertEqual(ctx.exception.status_code, 401)

    def test_correct_token_is_accepted(self):
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": "dev-admin-token"}):
            content_auth.verify_admin_token(x_admin_token="dev-admin-token")


class TestVerifyTenantToken(unittest.TestCase):
    def test_missing_header_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            content_auth.verify_tenant_token(
                x_tenant_token=None, session=_session_returning(None)
            )

        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_token_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            content_auth.verify_tenant_token(
                x_tenant_token="unknown-token", session=_session_returning(None)
            )

        self.assertEqual(ctx.exception.status_code, 401)

    def test_inactive_tenant_is_rejected_with_403(self):
        tenant = ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=EntitlementStatus.inactive,
        )

        with self.assertRaises(HTTPException) as ctx:
            content_auth.verify_tenant_token(
                x_tenant_token="tenant-token", session=_session_returning(tenant)
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_active_tenant_is_returned(self):
        tenant = ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=EntitlementStatus.active,
        )

        result = content_auth.verify_tenant_token(
            x_tenant_token="tenant-token", session=_session_returning(tenant)
        )

        self.assertIs(result, tenant)

    def test_trial_tenant_is_returned(self):
        tenant = ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=EntitlementStatus.trial,
        )

        result = content_auth.verify_tenant_token(
            x_tenant_token="tenant-token", session=_session_returning(tenant)
        )

        self.assertIs(result, tenant)


if __name__ == "__main__":
    unittest.main()
