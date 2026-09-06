import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import InsightsResult
from app.services.content.publishers.x import XAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="hello world")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="1700000000000000000")
    base.update(overrides)
    return MagicMock(**base)


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


class TestXFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(XAdapter.supports_insights)

    def test_maps_canonical_response(self):
        response = {
            "data": {
                "public_metrics": {
                    "like_count": 10,
                    "reply_count": 2,
                    "retweet_count": 3,
                    "quote_count": 1,
                    "impression_count": 700,
                }
            }
        }

        with patch(
            "app.services.content.publishers.x.get_json", return_value=response
        ) as get_json:
            result = XAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsNone(result.reach)
        self.assertEqual(result.impressions, 700)
        self.assertEqual(result.likes, 10)
        self.assertEqual(result.comments, 2)
        self.assertEqual(result.shares, 4)  # retweets + quote tweets
        get_json.assert_called_once()

    def test_no_retweet_or_quote_data_leaves_shares_none(self):
        response = {
            "data": {
                "public_metrics": {
                    "like_count": 1,
                    "reply_count": 0,
                    "impression_count": 20,
                }
            }
        }

        with patch(
            "app.services.content.publishers.x.get_json", return_value=response
        ):
            result = XAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsNone(result.shares)

    def test_partial_share_data_sums_present_values(self):
        # One share metric present, the other entirely absent from API response
        response = {
            "data": {
                "public_metrics": {
                    "like_count": 5,
                    "reply_count": 1,
                    "retweet_count": 5,
                    # quote_count is entirely absent
                    "impression_count": 100,
                }
            }
        }

        with patch(
            "app.services.content.publishers.x.get_json", return_value=response
        ):
            result = XAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertEqual(result.shares, 5)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.x.get_json",
            side_effect=PublicationError(
                PublicationErrorCode.invalid_credentials, "no scope"
            ),
        ):
            with self.assertRaises(PublicationError) as ctx:
                XAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)


if __name__ == "__main__":
    unittest.main()
