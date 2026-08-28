import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.instagram import InstagramAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="a cat")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


class TestInstagramCompatibility(unittest.TestCase):
    def test_image_is_compatible(self):
        InstagramAdapter().check_compatibility(_piece(type=ContentPieceType.image), _asset())

    def test_video_is_compatible(self):
        InstagramAdapter().check_compatibility(_piece(type=ContentPieceType.video), _asset())

    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            InstagramAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestInstagramPublish(unittest.TestCase):
    def test_publish_creates_container_then_publishes_it(self):
        container_response = MagicMock(status_code=200)
        container_response.json.return_value = {"id": "container-1"}
        publish_response = MagicMock(status_code=200)
        publish_response.json.return_value = {"id": "media-1"}

        with patch(
            "app.services.content.publishers.instagram.post_form",
            side_effect=[container_response, publish_response],
        ) as post_form:
            result = InstagramAdapter().publish(
                _piece(),
                _asset(),
                _account(),
                {"access_token": "tok", "ig_user_id": "ig-1"},
            )

        self.assertEqual(result.platform_post_id, "media-1")
        self.assertIn("media-1", result.platform_post_url)
        self.assertEqual(post_form.call_count, 2)

    def test_container_creation_failure_propagates(self):
        with patch(
            "app.services.content.publishers.instagram.post_form",
            side_effect=PublicationError(PublicationErrorCode.rate_limit, "slow down"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                InstagramAdapter().publish(
                    _piece(), _asset(), _account(), {"access_token": "tok", "ig_user_id": "ig-1"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)


if __name__ == "__main__":
    unittest.main()
