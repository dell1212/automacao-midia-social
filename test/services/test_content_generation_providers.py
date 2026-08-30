import unittest
from unittest.mock import MagicMock

from app.models.content_generation import (
    ContentGenerationProvider,
    GenerationKind,
    GenerationProviderName,
)
from app.services.content import generation_providers as providers_service


class TestUpdateGenerationProvider(unittest.TestCase):
    def test_updates_priority_and_config_without_touching_credentials(self):
        row = ContentGenerationProvider(
            id=1, tenant_id=1, kind=GenerationKind.image, provider=GenerationProviderName.falai,
            credentials_encrypted="unchanged-enc", config={"a": 1}, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = row

        result = providers_service.update_generation_provider(
            session, tenant_id=1, provider_id=1, priority=5, config={"b": 2}
        )

        self.assertEqual(result.priority, 5)
        self.assertEqual(result.config, {"b": 2})
        self.assertEqual(result.credentials_encrypted, "unchanged-enc")
        session.commit.assert_called_once()

    def test_reencrypts_credentials_when_provided(self):
        row = ContentGenerationProvider(
            id=1, tenant_id=1, kind=GenerationKind.image, provider=GenerationProviderName.falai,
            credentials_encrypted="old-enc", config={}, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = row

        result = providers_service.update_generation_provider(
            session, tenant_id=1, provider_id=1, credentials="new-secret"
        )

        self.assertNotEqual(result.credentials_encrypted, "old-enc")

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = providers_service.update_generation_provider(
            session, tenant_id=1, provider_id=999, priority=5
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
