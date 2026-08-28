import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.x import XAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="hello world")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


class TestXCompatibility(unittest.TestCase):
    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            XAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestXPublish(unittest.TestCase):
    def test_publish_uploads_media_then_creates_tweet(self):
        upload_response = MagicMock(status_code=200)
        upload_response.json.return_value = {"media_id_string": "media-1"}
        tweet_response = MagicMock(status_code=201)
        tweet_response.json.return_value = {"data": {"id": "tweet-1"}}

        with patch(
            "app.services.content.publishers.x.get_bytes", return_value=b"binary-image"
        ):
            with patch(
                "app.services.content.publishers.x.post_form", return_value=upload_response
            ):
                with patch(
                    "app.services.content.publishers.x.post_json",
                    return_value=tweet_response,
                ) as post_json:
                    result = XAdapter().publish(
                        _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                    )

        self.assertEqual(result.platform_post_id, "tweet-1")
        body = post_json.call_args.args[1]
        self.assertEqual(body["media"]["media_ids"], ["media-1"])


if __name__ == "__main__":
    unittest.main()
