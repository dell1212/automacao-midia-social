import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentCategory, ContentPieceType, RiskLevel
from app.models.content_generation import GenerationKind
from app.services.content import pieces as pieces_service


def _payload(**overrides):
    base = dict(
        campaign_id=1,
        type=ContentPieceType.image,
        idempotency_key="key-1",
        is_synthetic_media=True,
        generation_prompt="a cat",
        avatar_id=None,
        source_image_piece_id=None,
        voice_id=None,
        content_category=None,
        aspect_ratio="9:16",
        resolution=None,
        duration=None,
    )
    base.update(overrides)
    return MagicMock(**base)


class TestRequiredKinds(unittest.TestCase):
    def test_image_with_prompt_needs_image_provider(self):
        self.assertEqual(
            pieces_service.required_kinds_for(_payload()), [GenerationKind.image]
        )

    def test_image_from_avatar_without_prompt_needs_nothing(self):
        payload = _payload(generation_prompt=None, avatar_id=7)

        self.assertEqual(pieces_service.required_kinds_for(payload), [])

    def test_audio_needs_voice_provider(self):
        payload = _payload(type=ContentPieceType.audio)

        self.assertEqual(pieces_service.required_kinds_for(payload), [GenerationKind.voice])

    def test_video_from_prompt_needs_image_and_video(self):
        payload = _payload(type=ContentPieceType.video)

        self.assertEqual(
            pieces_service.required_kinds_for(payload),
            [GenerationKind.video, GenerationKind.image],
        )

    def test_video_from_avatar_with_voice_needs_video_and_voice(self):
        payload = _payload(type=ContentPieceType.video, avatar_id=7, voice_id="v1")

        self.assertEqual(
            pieces_service.required_kinds_for(payload),
            [GenerationKind.video, GenerationKind.voice],
        )

    def test_video_from_source_image_does_not_need_image_provider(self):
        payload = _payload(type=ContentPieceType.video, source_image_piece_id=3)

        self.assertEqual(
            pieces_service.required_kinds_for(payload), [GenerationKind.video]
        )


class TestCreatePieceIdempotency(unittest.TestCase):
    def test_existing_key_returns_the_same_piece_without_new_work(self):
        existing = MagicMock(id=42)
        session = MagicMock()

        with patch.object(
            pieces_service, "find_by_idempotency_key", return_value=existing
        ):
            with patch.object(pieces_service, "schedule_piece") as schedule:
                result, created = pieces_service.create_piece(
                    session, tenant_id=1, payload=_payload()
                )

        self.assertIs(result, existing)
        self.assertFalse(created)
        schedule.assert_not_called()
        session.add.assert_not_called()

    def test_new_key_creates_and_schedules(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece") as schedule:
                result, created = pieces_service.create_piece(
                    session, tenant_id=1, payload=_payload()
                )

        self.assertTrue(created)
        session.add.assert_called_once()
        schedule.assert_called_once()


class TestCreatePiecePolicy(unittest.TestCase):
    def test_medical_category_is_classified_as_high_risk(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece"):
                piece, _ = pieces_service.create_piece(
                    session,
                    tenant_id=1,
                    payload=_payload(content_category=ContentCategory.medical),
                )

        self.assertEqual(piece.risk_level, RiskLevel.high)
        self.assertTrue(piece.requires_human_review)
        self.assertEqual(piece.policy_version, "v1")

    def test_absent_category_is_inert(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece"):
                piece, _ = pieces_service.create_piece(
                    session, tenant_id=1, payload=_payload()
                )

        self.assertEqual(piece.risk_level, RiskLevel.none)
        self.assertFalse(piece.requires_human_review)


if __name__ == "__main__":
    unittest.main()
