import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.linkedin import LinkedInAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="hello world")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


class TestLinkedInCompatibility(unittest.TestCase):
    def test_audio_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            LinkedInAdapter().check_compatibility(_piece(type=ContentPieceType.audio), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestLinkedInPublish(unittest.TestCase):
    def test_publish_registers_uploads_and_posts(self):
        register_response = MagicMock(status_code=200)
        register_response.json.return_value = {
            "value": {
                "uploadMechanism": {
                    "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {
                        "uploadUrl": "https://upload.linkedin.com/put-here"
                    }
                },
                "asset": "urn:li:digitalmediaAsset:abc",
            }
        }
        upload_result = MagicMock(status_code=201)
        post_response = MagicMock(status_code=201)
        post_response.headers = {"x-restli-id": "urn:li:share:123"}

        with patch(
            "app.services.content.publishers.linkedin.get_bytes", return_value=b"binary-image"
        ):
            with patch(
                "app.services.content.publishers.linkedin.post_json",
                side_effect=[register_response, post_response],
            ) as post_json_mock:
                with patch(
                    "app.services.content.publishers.linkedin.requests.put",
                    return_value=upload_result,
                ) as requests_put_mock:
                    result = LinkedInAdapter().publish(
                        _piece(),
                        _asset(),
                        MagicMock(),
                        {"access_token": "tok", "author_urn": "urn:li:person:1"},
                    )

        self.assertEqual(result.platform_post_id, "urn:li:share:123")

        # The uploadUrl/asset URN from step 1's response must thread into
        # steps 3 and 4, not get hardcoded or dropped — a wrong or stale
        # URN here would silently attach the wrong media to the post.
        self.assertEqual(requests_put_mock.call_args.args[0], "https://upload.linkedin.com/put-here")
        ugc_post_body = post_json_mock.call_args_list[1].args[1]
        self.assertEqual(
            ugc_post_body["specificContent"]["com.linkedin.ugc.ShareContent"]["media"][0]["media"],
            "urn:li:digitalmediaAsset:abc",
        )


if __name__ == "__main__":
    unittest.main()
