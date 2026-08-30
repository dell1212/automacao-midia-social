import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentGenerationTemplate, ContentPieceType
from app.services.content import generation_templates as templates_service


class TestCreateTemplate(unittest.TestCase):
    def test_returns_none_when_campaign_not_found(self):
        session = MagicMock()

        with patch.object(templates_service, "get_campaign", return_value=None):
            result = templates_service.create_template(
                session,
                tenant_id=1,
                campaign_id=99,
                type=ContentPieceType.image,
                generation_prompt="a cat",
                avatar_id=None,
                voice_id=None,
                is_synthetic_media=False,
                content_category=None,
                aspect_ratio="9:16",
                resolution=None,
                duration=None,
            )

        self.assertIsNone(result)
        session.add.assert_not_called()

    def test_creates_and_persists_template_when_campaign_exists(self):
        session = MagicMock()
        campaign = MagicMock(id=5)

        with patch.object(templates_service, "get_campaign", return_value=campaign):
            templates_service.create_template(
                session,
                tenant_id=1,
                campaign_id=5,
                type=ContentPieceType.video,
                generation_prompt="a dog",
                avatar_id=None,
                voice_id="v1",
                is_synthetic_media=True,
                content_category=None,
                aspect_ratio="16:9",
                resolution="1080p",
                duration=10,
            )

        session.add.assert_called_once()
        added = session.add.call_args.args[0]
        self.assertEqual(added.campaign_id, 5)
        self.assertEqual(added.type, ContentPieceType.video)
        self.assertEqual(added.aspect_ratio, "16:9")
        session.commit.assert_called_once()


class TestListTemplates(unittest.TestCase):
    def test_returns_empty_list_when_campaign_not_found(self):
        session = MagicMock()

        with patch.object(templates_service, "get_campaign", return_value=None):
            result = templates_service.list_templates(session, tenant_id=1, campaign_id=99)

        self.assertEqual(result, [])

    def test_returns_templates_for_campaign(self):
        session = MagicMock()
        campaign = MagicMock(id=5)
        rows = [MagicMock(), MagicMock()]
        session.exec.return_value.all.return_value = rows

        with patch.object(templates_service, "get_campaign", return_value=campaign):
            result = templates_service.list_templates(session, tenant_id=1, campaign_id=5)

        self.assertEqual(result, rows)


class TestGetTemplate(unittest.TestCase):
    def test_returns_template_when_campaign_belongs_to_tenant(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=MagicMock(id=1)):
            result = templates_service.get_template(session, tenant_id=1, template_id=1)

        self.assertIs(result, template)

    def test_returns_none_when_campaign_belongs_to_other_tenant(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=None):
            result = templates_service.get_template(session, tenant_id=2, template_id=1)

        self.assertIsNone(result)


class TestUpdateTemplate(unittest.TestCase):
    def test_updates_provided_fields(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, generation_prompt="old",
            aspect_ratio="9:16", is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=MagicMock(id=1)):
            result = templates_service.update_template(
                session, tenant_id=1, template_id=1, generation_prompt="new", aspect_ratio="1:1",
            )

        self.assertEqual(result.generation_prompt, "new")
        self.assertEqual(result.aspect_ratio, "1:1")
        session.commit.assert_called_once()


class TestDeactivateTemplate(unittest.TestCase):
    def test_sets_is_active_false(self):
        template = ContentGenerationTemplate(
            id=1, campaign_id=1, type=ContentPieceType.image, is_active=True,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = template

        with patch.object(templates_service, "get_campaign", return_value=MagicMock(id=1)):
            result = templates_service.deactivate_template(session, tenant_id=1, template_id=1)

        self.assertFalse(result.is_active)
