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
    def test_publish_waits_for_publish_complete_then_returns_the_real_post_id(self):
        init_response = MagicMock(status_code=200)
        init_response.json.return_value = {"data": {"publish_id": "pub-1"}}

        with patch(
            "app.services.content.publishers.tiktok.post_json"
        ) as post_json:
            post_json.side_effect = [
                init_response,
                MagicMock(
                    status_code=200,
                    json=lambda: {
                        "data": {
                            "status": "PUBLISH_COMPLETE",
                            "publicaly_available_post_id": [7123456789],
                        }
                    },
                ),
            ]
            result = TikTokAdapter().publish(
                _piece(), _asset(), MagicMock(), {"access_token": "tok"}
            )

        self.assertEqual(result.platform_post_id, "7123456789")
        self.assertIsNone(result.platform_post_url)
        init_body = post_json.call_args_list[0].args[1]
        self.assertEqual(init_body["source_info"]["video_url"], "https://cdn.example.com/a.mp4")
        status_body = post_json.call_args_list[1].args[1]
        self.assertEqual(status_body["publish_id"], "pub-1")

    def test_waits_through_processing_before_completing(self):
        init_response = MagicMock(status_code=200)
        init_response.json.return_value = {"data": {"publish_id": "pub-1"}}
        processing_response = MagicMock(status_code=200)
        processing_response.json.return_value = {"data": {"status": "PROCESSING_UPLOAD"}}
        complete_response = MagicMock(status_code=200)
        complete_response.json.return_value = {
            "data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [42]}
        }

        with patch(
            "app.services.content.publishers.tiktok.post_json",
            side_effect=[init_response, processing_response, complete_response],
        ) as post_json:
            with patch("app.services.content.publishers.tiktok.time.sleep"):
                result = TikTokAdapter().publish(
                    _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                )

        self.assertEqual(result.platform_post_id, "42")
        self.assertEqual(post_json.call_count, 3)

    def test_failed_status_raises_non_retryable_with_fail_reason(self):
        init_response = MagicMock(status_code=200)
        init_response.json.return_value = {"data": {"publish_id": "pub-1"}}
        failed_response = MagicMock(status_code=200)
        failed_response.json.return_value = {
            "data": {"status": "FAILED", "fail_reason": "video_pull_failed"}
        }

        with patch(
            "app.services.content.publishers.tiktok.post_json",
            side_effect=[init_response, failed_response],
        ):
            with self.assertRaises(PublicationError) as ctx:
                TikTokAdapter().publish(_piece(), _asset(), MagicMock(), {"access_token": "tok"})

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)
        self.assertIn("video_pull_failed", ctx.exception.message)

    def test_sent_to_inbox_raises_non_retryable(self):
        init_response = MagicMock(status_code=200)
        init_response.json.return_value = {"data": {"publish_id": "pub-1"}}
        inbox_response = MagicMock(status_code=200)
        inbox_response.json.return_value = {"data": {"status": "SEND_TO_USER_INBOX"}}

        with patch(
            "app.services.content.publishers.tiktok.post_json",
            side_effect=[init_response, inbox_response],
        ):
            with self.assertRaises(PublicationError) as ctx:
                TikTokAdapter().publish(_piece(), _asset(), MagicMock(), {"access_token": "tok"})

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)

    def test_deadline_elapsed_raises_transient(self):
        init_response = MagicMock(status_code=200)
        init_response.json.return_value = {"data": {"publish_id": "pub-1"}}

        with patch(
            "app.services.content.publishers.tiktok.post_json"
        ) as post_json:
            post_json.side_effect = [init_response]
            with patch(
                "app.services.content.publishers.tiktok.time.monotonic",
                side_effect=[0, 1000],
            ):
                with self.assertRaises(PublicationError) as ctx:
                    TikTokAdapter().publish(
                        _piece(), _asset(), MagicMock(), {"access_token": "tok"}
                    )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)
        post_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
