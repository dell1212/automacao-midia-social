import unittest
from unittest.mock import MagicMock

from app.models.content_generation import ContentAvatar
from app.services.content import avatars as avatars_service


class TestUpdateAvatar(unittest.TestCase):
    def test_updates_provided_fields(self):
        avatar = ContentAvatar(
            id=1, client_id=1, name="Old", reference_image_url="old.png", is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = avatar

        result = avatars_service.update_avatar(
            session, tenant_id=1, avatar_id=1, name="New", voice_id="voice-2"
        )

        self.assertEqual(result.name, "New")
        self.assertEqual(result.voice_id, "voice-2")
        self.assertEqual(result.reference_image_url, "old.png")
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = avatars_service.update_avatar(session, tenant_id=1, avatar_id=999, name="New")

        self.assertIsNone(result)


class TestDeactivateAvatar(unittest.TestCase):
    def test_sets_is_active_false(self):
        avatar = ContentAvatar(
            id=1, client_id=1, name="Acme", reference_image_url="a.png", is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = avatar

        result = avatars_service.deactivate_avatar(session, tenant_id=1, avatar_id=1)

        self.assertFalse(result.is_active)


if __name__ == "__main__":
    unittest.main()
