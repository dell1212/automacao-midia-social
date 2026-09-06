import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import InsightsResult
from app.services.content.publishers.facebook import FacebookAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="a cat")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="1234567890_987654321")
    base.update(overrides)
    return MagicMock(**base)


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


class TestFacebookFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(FacebookAdapter.supports_insights)

    def test_maps_canonical_response(self):
        fields = {
            "likes": {"summary": {"total_count": 20}},
            "comments": {"summary": {"total_count": 5}},
            "shares": {"count": 7},
        }
        insights = {
            "data": [
                {"name": "post_impressions_unique", "values": [{"value": 300}]}
            ]
        }

        with patch(
            "app.services.content.publishers.facebook.get_json",
            side_effect=[fields, insights],
        ) as get_json:
            result = FacebookAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertEqual(result.reach, 300)
        self.assertEqual(result.likes, 20)
        self.assertEqual(result.comments, 5)
        self.assertEqual(result.shares, 7)
        self.assertEqual(get_json.call_count, 2)

    def test_missing_shares_field_stays_none(self):
        fields = {
            "likes": {"summary": {"total_count": 4}},
            "comments": {"summary": {"total_count": 1}},
            # Facebook omits `shares` entirely on a post with zero shares —
            # it is not sent as {"count": 0}.
        }
        insights = {
            "data": [
                {"name": "post_impressions_unique", "values": [{"value": 50}]}
            ]
        }

        with patch(
            "app.services.content.publishers.facebook.get_json",
            side_effect=[fields, insights],
        ):
            result = FacebookAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsNone(result.shares)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.facebook.get_json",
            side_effect=PublicationError(PublicationErrorCode.rate_limit, "slow down"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                FacebookAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)


if __name__ == "__main__":
    unittest.main()
