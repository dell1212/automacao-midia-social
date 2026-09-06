import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceType
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import InsightsResult
from app.services.content.publishers.instagram import InstagramAdapter


def _piece(**overrides):
    base = dict(id=1, type=ContentPieceType.image, generation_prompt="a cat")
    base.update(overrides)
    return MagicMock(**base)


def _asset(url="https://cdn.example.com/a.jpg"):
    return MagicMock(url=url)


def _account():
    return MagicMock()


def _publication(**overrides):
    base = dict(platform_post_id="17900000000000000")
    base.update(overrides)
    return MagicMock(**base)


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
    def test_publish_waits_for_finished_then_publishes_it(self):
        container_response = MagicMock(status_code=200)
        container_response.json.return_value = {"id": "container-1"}
        status_response = MagicMock(status_code=200)
        status_response.json.return_value = {"status_code": "FINISHED"}
        publish_response = MagicMock(status_code=200)
        publish_response.json.return_value = {"id": "media-1"}

        with patch(
            "app.services.content.publishers.instagram.post_form",
            side_effect=[container_response, publish_response],
        ) as post_form:
            with patch(
                "app.services.content.publishers.instagram.get_json",
                return_value=status_response.json(),
            ) as get_json:
                result = InstagramAdapter().publish(
                    _piece(),
                    _asset(),
                    _account(),
                    {"access_token": "tok", "ig_user_id": "ig-1"},
                )

        self.assertEqual(result.platform_post_id, "media-1")
        self.assertIn("media-1", result.platform_post_url)
        self.assertEqual(post_form.call_count, 2)
        get_json.assert_called_once()
        self.assertIn("container-1", get_json.call_args.args[0])

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

    def test_waits_through_in_progress_before_finishing(self):
        container_response = MagicMock(status_code=200)
        container_response.json.return_value = {"id": "container-1"}
        publish_response = MagicMock(status_code=200)
        publish_response.json.return_value = {"id": "media-1"}

        with patch(
            "app.services.content.publishers.instagram.post_form",
            side_effect=[container_response, publish_response],
        ):
            with patch(
                "app.services.content.publishers.instagram.get_json",
                side_effect=[{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}],
            ) as get_json:
                with patch("app.services.content.publishers.instagram.time.sleep"):
                    result = InstagramAdapter().publish(
                        _piece(), _asset(), _account(),
                        {"access_token": "tok", "ig_user_id": "ig-1"},
                    )

        self.assertEqual(result.platform_post_id, "media-1")
        self.assertEqual(get_json.call_count, 2)

    def test_error_status_raises_non_retryable(self):
        container_response = MagicMock(status_code=200)
        container_response.json.return_value = {"id": "container-1"}

        with patch(
            "app.services.content.publishers.instagram.post_form",
            return_value=container_response,
        ):
            with patch(
                "app.services.content.publishers.instagram.get_json",
                return_value={"status_code": "ERROR"},
            ):
                with self.assertRaises(PublicationError) as ctx:
                    InstagramAdapter().publish(
                        _piece(), _asset(), _account(),
                        {"access_token": "tok", "ig_user_id": "ig-1"},
                    )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)

    def test_deadline_elapsed_raises_transient_without_publishing(self):
        container_response = MagicMock(status_code=200)
        container_response.json.return_value = {"id": "container-1"}

        with patch(
            "app.services.content.publishers.instagram.post_form",
            return_value=container_response,
        ) as post_form:
            with patch(
                "app.services.content.publishers.instagram.get_json",
            ) as get_json:
                with patch(
                    "app.services.content.publishers.instagram.time.monotonic",
                    side_effect=[0, 1000],
                ):
                    with self.assertRaises(PublicationError) as ctx:
                        InstagramAdapter().publish(
                            _piece(), _asset(), _account(),
                            {"access_token": "tok", "ig_user_id": "ig-1"},
                        )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)
        get_json.assert_not_called()
        post_form.assert_called_once()


class TestInstagramFetchInsights(unittest.TestCase):
    def test_declares_support(self):
        self.assertTrue(InstagramAdapter.supports_insights)

    def test_maps_canonical_response(self):
        fields_response = {"id": "media-1", "like_count": 12, "comments_count": 3}
        insights_response = {"data": [{"name": "reach", "values": [{"value": 240}]}]}

        with patch(
            "app.services.content.publishers.instagram.get_json",
            side_effect=[fields_response, insights_response],
        ) as get_json:
            result = InstagramAdapter().fetch_insights(
                _publication(), _account(), {"access_token": "tok"}
            )

        self.assertIsInstance(result, InsightsResult)
        self.assertEqual(result.reach, 240)
        self.assertEqual(result.likes, 12)
        self.assertEqual(result.comments, 3)
        self.assertIsNone(result.shares)
        self.assertEqual(get_json.call_count, 2)

    def test_error_propagates_uncaught(self):
        with patch(
            "app.services.content.publishers.instagram.get_json",
            side_effect=PublicationError(
                PublicationErrorCode.invalid_credentials, "no scope"
            ),
        ):
            with self.assertRaises(PublicationError) as ctx:
                InstagramAdapter().fetch_insights(
                    _publication(), _account(), {"access_token": "tok"}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)


if __name__ == "__main__":
    unittest.main()
