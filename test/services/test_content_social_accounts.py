import json
import unittest
from unittest.mock import MagicMock

from app.models.content import ContentSocialAccount
from app.services.content import social_accounts as social_accounts_service


class TestGetSocialAccount(unittest.TestCase):
    def test_returns_account_when_found(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="ext-1",
            credentials_encrypted="enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.get_social_account(session, tenant_id=1, account_id=1)

        self.assertIs(result, account)

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = social_accounts_service.get_social_account(session, tenant_id=1, account_id=999)

        self.assertIsNone(result)


class TestCreateSocialAccount(unittest.TestCase):
    def test_rejects_facebook_page_id_mismatch(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = MagicMock()  # client exists

        with self.assertRaises(ValueError):
            social_accounts_service.create_social_account(
                session,
                tenant_id=1,
                client_id=1,
                platform="facebook",
                external_account_id="123",
                credentials=json.dumps({"access_token": "t", "page_id": "999"}),
            )

    def test_accepts_matching_facebook_page_id(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = MagicMock()

        result = social_accounts_service.create_social_account(
            session,
            tenant_id=1,
            client_id=1,
            platform="facebook",
            external_account_id="123",
            credentials=json.dumps({"access_token": "t", "page_id": "123"}),
        )

        self.assertEqual(result.external_account_id, "123")

    def test_skips_validation_for_platform_without_credential_id(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = MagicMock()

        result = social_accounts_service.create_social_account(
            session,
            tenant_id=1,
            client_id=1,
            platform="tiktok",
            external_account_id="anything",
            credentials=json.dumps({"access_token": "t"}),
        )

        self.assertEqual(result.external_account_id, "anything")


class TestUpdateSocialAccount(unittest.TestCase):
    def test_rejects_instagram_ig_user_id_mismatch_on_credentials_update(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="abc",
            credentials_encrypted="old-enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        with self.assertRaises(ValueError):
            social_accounts_service.update_social_account(
                session,
                tenant_id=1,
                account_id=1,
                credentials=json.dumps({"access_token": "t", "ig_user_id": "other"}),
            )

    def test_rejects_mismatch_when_only_external_account_id_changes(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="abc",
            credentials_encrypted=social_accounts_service.encrypt_credentials(
                json.dumps({"access_token": "t", "ig_user_id": "abc"})
            ),
            status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        with self.assertRaises(ValueError):
            social_accounts_service.update_social_account(
                session, tenant_id=1, account_id=1, external_account_id="different"
            )

    def test_updates_external_id_and_reencrypts_credentials(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="youtube", external_account_id="old",
            credentials_encrypted="old-enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.update_social_account(
            session, tenant_id=1, account_id=1, external_account_id="new", credentials="new-secret"
        )

        self.assertEqual(result.external_account_id, "new")
        self.assertNotEqual(result.credentials_encrypted, "old-enc")
        session.commit.assert_called_once()

    def test_preserves_credentials_when_omitted(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="ext-1",
            credentials_encrypted="unchanged-enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.update_social_account(session, tenant_id=1, account_id=1)

        self.assertEqual(result.credentials_encrypted, "unchanged-enc")


class TestRevokeSocialAccount(unittest.TestCase):
    def test_sets_status_revoked(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="ext-1",
            credentials_encrypted="enc", status="active",
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = social_accounts_service.revoke_social_account(session, tenant_id=1, account_id=1)

        self.assertEqual(result.status, "revoked")


if __name__ == "__main__":
    unittest.main()
