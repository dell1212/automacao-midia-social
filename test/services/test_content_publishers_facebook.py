import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.facebook import FacebookAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="a cat")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


class TestFacebookCompatibility(unittest.TestCase):
    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            FacebookAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)

    def test_image_is_compatible(self):
        FacebookAdapter().check_compatibility(_piece(), _asset())


class TestFacebookPublish(unittest.TestCase):
    def test_image_posts_to_photos_endpoint(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"id": "post-1"}

        with patch(
            "app.services.content.publishers.facebook.post_form", return_value=response
        ) as post_form:
            result = FacebookAdapter().publish(
                _piece(), _asset(), MagicMock(), {"access_token": "tok", "page_id": "page-1"}
            )

        self.assertEqual(result.platform_post_id, "post-1")
        called_url = post_form.call_args.args[0]
        self.assertIn("/photos", called_url)

    def test_video_posts_to_videos_endpoint(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"id": "post-2"}

        with patch(
            "app.services.content.publishers.facebook.post_form", return_value=response
        ) as post_form:
            FacebookAdapter().publish(
                _piece(type=ContentPieceType.video),
                _asset(),
                MagicMock(),
                {"access_token": "tok", "page_id": "page-1"},
            )

        called_url = post_form.call_args.args[0]
        self.assertIn("/videos", called_url)


if __name__ == "__main__":
    unittest.main()
