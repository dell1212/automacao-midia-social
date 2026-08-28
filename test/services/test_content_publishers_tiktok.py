import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.tiktok import TikTokAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.video, generation_prompt="a cat video")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.mp4"):
    return MagicMock(url=url)


class TestTikTokCompatibility(unittest.TestCase):
    def test_image_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            TikTokAdapter().check_compatibility(_piece(type=ContentPieceType.image), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestTikTokPublish(unittest.TestCase):
    def test_publish_returns_publish_id(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"data": {"publish_id": "pub-1"}}

        with patch(
            "app.services.content.publishers.tiktok.post_json", return_value=response
        ) as post_json:
            result = TikTokAdapter().publish(
                _piece(), _asset(), MagicMock(), {"access_token": "tok"}
            )

        self.assertEqual(result.platform_post_id, "pub-1")
        body = post_json.call_args.args[1]
        self.assertEqual(body["source_info"]["video_url"], "https://cdn.example.com/a.mp4")


if __name__ == "__main__":
    unittest.main()
