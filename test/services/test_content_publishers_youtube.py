import json
import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import InsightsResult
from app.services.content.publishers.youtube import YouTubeAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.video, generation_prompt="a cat video")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.mp4"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="yt-1")
    base.update(overrides)
    return MagicMock(**base)


class TestYouTubeCompatibility(unittest.TestCase):
    def test_image_is_rejected(self):
        with self.assertRaises(PublicationError) as ctx:
            YouTubeAdapter().check_compatibility(_piece(type=ContentPieceType.image), _asset())

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)

    def test_video_is_compatible(self):
        YouTubeAdapter().check_compatibility(_piece(), _asset())


class TestYouTubePublish(unittest.TestCase):
    def test_publish_fetches_asset_and_uploads(self):
        upload_response = MagicMock(status_code=200)
        upload_response.json.return_value = {"id": "video-1"}

        with patch(
            "app.services.content.publishers.youtube.get_bytes", return_value=b"binary-video"
        ) as get_bytes:
            with patch(
                "app.services.content.publishers.youtube.requests.post",
                return_value=upload_response,
            ) as post:
                result = YouTubeAdapter().publish(
                    _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                )

        get_bytes.assert_called_once_with("https://cdn.example.com/a.mp4")
        self.assertEqual(result.platform_post_id, "video-1")
        self.assertIn("video-1", result.platform_post_url)
        self.assertIn("Bearer tok", post.call_args.kwargs["headers"]["Authorization"])

    def test_upload_error_is_classified(self):
        error_response = MagicMock(status_code=401)
        error_response.json.return_value = {"error": {"message": "invalid token"}}

        with patch(
            "app.services.content.publishers.youtube.get_bytes", return_value=b"binary-video"
        ):
            with patch(
                "app.services.content.publishers.youtube.requests.post",
                return_value=error_response,
            ):
                with self.assertRaises(PublicationError) as ctx:
                    YouTubeAdapter().publish(
                        _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                    )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)


class TestYouTubeFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(YouTubeAdapter.supports_insights)

    def test_maps_canonical_response(self):
        response = {
            "items": [
                {
                    "statistics": {
                        "viewCount": "1500",
                        "likeCount": "80",
                        "commentCount": "12",
                    }
                }
            ]
        }

        with patch(
            "app.services.content.publishers.youtube.get_json", return_value=response
        ) as get_json:
            result = YouTubeAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsInstance(result, InsightsResult)
        self.assertIsNone(result.reach)
        self.assertEqual(result.impressions, 1500)
        self.assertEqual(result.likes, 80)
        self.assertEqual(result.comments, 12)
        self.assertIsNone(result.shares)
        get_json.assert_called_once()

    def test_no_items_is_invalid_params(self):
        with patch(
            "app.services.content.publishers.youtube.get_json",
            return_value={"items": []},
        ):
            with self.assertRaises(PublicationError) as ctx:
                YouTubeAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.youtube.get_json",
            side_effect=PublicationError(PublicationErrorCode.transient, "blip"),
        ):
            with self.assertRaises(PublicationError) as ctx:
                YouTubeAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)


if __name__ == "__main__":
    unittest.main()
