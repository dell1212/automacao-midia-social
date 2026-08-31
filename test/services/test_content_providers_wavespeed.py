import unittest
from unittest.mock import MagicMock, patch

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers import wavespeed


def _response(json_data):
    response = MagicMock(status_code=200)
    response.json.return_value = json_data
    return response


class TestPollFailureClassification(unittest.TestCase):
    def test_policy_error_text_raises_content_policy(self):
        response = _response({"data": {"status": "failed", "error": "blocked by content policy"}})

        with patch.object(wavespeed.requests, "get", return_value=response):
            with self.assertRaises(GenerationError) as ctx:
                wavespeed._poll("k", "pred-1")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.content_policy)

    def test_non_policy_error_raises_unknown(self):
        response = _response({"data": {"status": "failed", "error": "internal server error"}})

        with patch.object(wavespeed.requests, "get", return_value=response):
            with self.assertRaises(GenerationError) as ctx:
                wavespeed._poll("k", "pred-1")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.unknown)

    def test_cancelled_status_is_also_classified(self):
        response = _response({"data": {"status": "cancelled", "error": "safety review failed"}})

        with patch.object(wavespeed.requests, "get", return_value=response):
            with self.assertRaises(GenerationError) as ctx:
                wavespeed._poll("k", "pred-1")

        self.assertEqual(ctx.exception.code, GenerationErrorCode.content_policy)


if __name__ == "__main__":
    unittest.main()
