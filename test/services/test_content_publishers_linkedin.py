import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.linkedin import LinkedInAdapter
from app.services.content.publishers.base import InsightsResult


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="hello world")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="urn:li:share:123")
    base.update(overrides)
    return MagicMock(**base)


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


class TestLinkedInFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(LinkedInAdapter.supports_insights)

    def test_maps_canonical_response(self):
        social_actions = {
            "likesSummary": {"totalLikes": 8},
            "commentsSummary": {"aggregatedTotalComments": 2},
        }
        statistics = {
            "results": {
                "urn:li:share:123": {
                    "totalShareStatistics": {
                        "impressionCount": 500,
                        "shareCount": 4,
                    }
                }
            }
        }

        with patch(
            "app.services.content.publishers.linkedin.get_json",
            side_effect=[social_actions, statistics],
        ) as get_json:
            result = LinkedInAdapter().fetch_insights(
                _publication(),
                _account(),
                {"access_token": "tok", "author_urn": "urn:li:organization:1"},
            )

        self.assertIsNone(result.reach)
        self.assertEqual(result.impressions, 500)
        self.assertEqual(result.likes, 8)
        self.assertEqual(result.comments, 2)
        self.assertEqual(result.shares, 4)
        self.assertEqual(get_json.call_count, 2)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.linkedin.get_json",
            side_effect=PublicationError(PublicationErrorCode.transient, "blip"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                LinkedInAdapter().fetch_insights(
                    _publication(),
                    _account(),
                    {"access_token": "tok", "author_urn": "urn:li:organization:1"},
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)


if __name__ == "__main__":
    unittest.main()
