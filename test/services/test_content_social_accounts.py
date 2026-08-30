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


class TestUpdateSocialAccount(unittest.TestCase):
    def test_updates_external_id_and_reencrypts_credentials(self):
        account = ContentSocialAccount(
            id=1, client_id=1, platform="instagram", external_account_id="old",
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
