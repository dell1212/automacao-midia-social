import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import asgi
from app.controllers import content_auth
from app.db import get_session
from app.models.content import ContentSocialAccount, ContentTenant, EntitlementStatus
from app.models.content_generation import (
    ContentGenerationProvider,
    GenerationKind,
    GenerationProviderName,
)


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


class UIConfigTestCase(unittest.TestCase):
    """Base class wiring FastAPI dependency overrides so these routes run
    end-to-end through the real app (real role check, real response_model
    serialization) without a live Postgres connection."""

    role = "admin"

    def setUp(self):
        self.client = TestClient(asgi.app)
        asgi.app.dependency_overrides[content_auth.verify_user_session] = (
            lambda: _user_session(self.role)
        )
        asgi.app.dependency_overrides[get_session] = lambda: MagicMock()

    def tearDown(self):
        asgi.app.dependency_overrides.clear()


# Every write route in ui_config.py: (method, path, json body).
# A minimal-but-valid body so requests clear Pydantic validation and reach
# the route body's require_role(admin) check — that check must fire before
# any service call, so the mocked `get_session` is never touched here.
WRITE_ROUTES = [
    ("POST", "/api/v1/content/ui/config/clients", {"name": "Acme Client"}),
    ("PUT", "/api/v1/content/ui/config/clients/1", {}),
    ("DELETE", "/api/v1/content/ui/config/clients/1", None),
    ("POST", "/api/v1/content/ui/config/campaigns", {"client_id": 1, "name": "Q1"}),
    ("PUT", "/api/v1/content/ui/config/campaigns/1", {}),
    ("DELETE", "/api/v1/content/ui/config/campaigns/1", None),
    (
        "POST",
        "/api/v1/content/ui/config/social-accounts",
        {
            "client_id": 1,
            "platform": "instagram",
            "external_account_id": "ext-1",
            "credentials": "secret",
        },
    ),
    ("PUT", "/api/v1/content/ui/config/social-accounts/1", {}),
    ("DELETE", "/api/v1/content/ui/config/social-accounts/1", None),
    (
        "POST",
        "/api/v1/content/ui/config/avatars",
        {"client_id": 1, "name": "Ana", "reference_image_url": "https://x/ref.png"},
    ),
    ("PUT", "/api/v1/content/ui/config/avatars/1", {}),
    ("DELETE", "/api/v1/content/ui/config/avatars/1", None),
    (
        "POST",
        "/api/v1/content/ui/config/approval-rules",
        {"campaign_id": 1, "condition": {}, "action": "auto_approve"},
    ),
    ("PUT", "/api/v1/content/ui/config/approval-rules/1", {}),
    ("DELETE", "/api/v1/content/ui/config/approval-rules/1", None),
    (
        "POST",
        "/api/v1/content/ui/config/campaigns/1/templates",
        {
            "campaign_id": 1,
            "type": "image",
            "is_synthetic_media": False,
            "aspect_ratio": "9:16",
        },
    ),
    ("PUT", "/api/v1/content/ui/config/templates/1", {}),
    ("DELETE", "/api/v1/content/ui/config/templates/1", None),
    (
        "POST",
        "/api/v1/content/ui/config/providers",
        {"kind": "image", "provider": "falai", "credentials": "api-key"},
    ),
    ("PUT", "/api/v1/content/ui/config/providers/1", {}),
    ("DELETE", "/api/v1/content/ui/config/providers/1", None),
]


class TestMemberForbiddenOnWriteRoutes(UIConfigTestCase):
    """A member session must get 403 from every write route, before any
    service/DB call — the guarantee the plan's Global Constraints demand
    ("toda rota de escrita exige role admin, checado no backend")."""

    role = "member"

    def test_every_write_route_rejects_member(self):
        for method, path, body in WRITE_ROUTES:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json=body)
                self.assertEqual(
                    response.status_code,
                    403,
                    f"{method} {path} returned {response.status_code}, expected 403",
                )


class TestCredentialsNeverLeaked(UIConfigTestCase):
    role = "member"  # read routes are open to both roles; member is the stricter case

    def test_social_account_list_omits_credentials(self):
        account = ContentSocialAccount(
            id=1,
            client_id=1,
            platform="instagram",
            external_account_id="ext-1",
            credentials_encrypted="super-secret-cipher-text",
            status="active",
        )
        with patch(
            "app.services.content.social_accounts.list_social_accounts",
            return_value=[account],
        ):
            response = self.client.get("/api/v1/content/ui/config/clients/1/social-accounts")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("credentials_encrypted", response.text)
        self.assertNotIn("super-secret-cipher-text", response.text)

    def test_provider_list_omits_credentials(self):
        provider = ContentGenerationProvider(
            id=1,
            tenant_id=1,
            kind=GenerationKind.image,
            provider=GenerationProviderName.falai,
            credentials_encrypted="super-secret-cipher-text",
            config={},
            priority=0,
        )
        with patch(
            "app.services.content.generation_providers.list_generation_providers",
            return_value=[provider],
        ):
            response = self.client.get("/api/v1/content/ui/config/providers")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("credentials_encrypted", response.text)
        self.assertNotIn("super-secret-cipher-text", response.text)


class TestCrossTenantReturns404(UIConfigTestCase):
    role = "admin"

    def test_avatar_not_found_for_tenant_is_404(self):
        """Avatar uses the direct-join tenant-scoping pattern (via ContentClient)."""
        with patch("app.services.content.avatars.get_avatar", return_value=None):
            response = self.client.get("/api/v1/content/ui/config/avatars/999")

        self.assertEqual(response.status_code, 404)

    def test_approval_rule_not_found_for_tenant_is_404(self):
        """ApprovalRule uses the two-step tenant-scoping pattern (via get_campaign)."""
        with patch(
            "app.services.content.approval_rules.get_approval_rule", return_value=None
        ):
            response = self.client.get("/api/v1/content/ui/config/approval-rules/999")

        self.assertEqual(response.status_code, 404)


class TestTemplateAvatarCrossTenantRejected(UIConfigTestCase):
    role = "admin"

    def test_create_template_rejects_avatar_from_another_tenant(self):
        with patch("app.services.content.avatars.get_avatar", return_value=None):
            response = self.client.post(
                "/api/v1/content/ui/config/campaigns/1/templates",
                json={
                    "campaign_id": 1,
                    "type": "image",
                    "is_synthetic_media": False,
                    "aspect_ratio": "9:16",
                    "avatar_id": 999,
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_update_template_rejects_avatar_from_another_tenant(self):
        with patch("app.services.content.avatars.get_avatar", return_value=None):
            response = self.client.put(
                "/api/v1/content/ui/config/templates/1",
                json={"avatar_id": 999},
            )

        self.assertEqual(response.status_code, 422)


class TestSocialAccountExternalIdValidation(UIConfigTestCase):
    role = "admin"

    def test_create_rejects_facebook_page_id_mismatch(self):
        with patch(
            "app.services.content.social_accounts.get_client", return_value=MagicMock()
        ):
            response = self.client.post(
                "/api/v1/content/ui/config/social-accounts",
                json={
                    "client_id": 1,
                    "platform": "facebook",
                    "external_account_id": "123",
                    "credentials": '{"access_token": "t", "page_id": "999"}',
                },
            )

        self.assertEqual(response.status_code, 422)

    def test_update_rejects_instagram_ig_user_id_mismatch(self):
        account = ContentSocialAccount(
            id=1,
            client_id=1,
            platform="instagram",
            external_account_id="abc",
            credentials_encrypted="old-enc",
            status="active",
        )
        with patch(
            "app.services.content.social_accounts.get_social_account", return_value=account
        ):
            response = self.client.put(
                "/api/v1/content/ui/config/social-accounts/1",
                json={"credentials": '{"access_token": "t", "ig_user_id": "other"}'},
            )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
