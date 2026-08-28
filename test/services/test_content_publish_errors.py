import unittest

from app.services.content.publish_errors import (
    PublicationErrorCode,
    classify_http_status,
    is_retryable,
)


class TestPublicationErrorClassification(unittest.TestCase):
    def test_rate_limit_is_retryable(self):
        self.assertTrue(is_retryable(PublicationErrorCode.rate_limit))

    def test_transient_is_retryable(self):
        self.assertTrue(is_retryable(PublicationErrorCode.transient))

    def test_invalid_credentials_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.invalid_credentials))

    def test_invalid_params_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.invalid_params))

    def test_content_policy_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.content_policy))

    def test_unsupported_capability_is_not_retryable(self):
        self.assertFalse(is_retryable(PublicationErrorCode.unsupported_capability))

    def test_http_429_maps_to_rate_limit(self):
        self.assertEqual(classify_http_status(429), PublicationErrorCode.rate_limit)

    def test_http_5xx_maps_to_transient(self):
        self.assertEqual(classify_http_status(503), PublicationErrorCode.transient)

    def test_http_401_maps_to_invalid_credentials(self):
        self.assertEqual(classify_http_status(401), PublicationErrorCode.invalid_credentials)

    def test_http_403_maps_to_invalid_credentials(self):
        self.assertEqual(classify_http_status(403), PublicationErrorCode.invalid_credentials)

    def test_http_400_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(400), PublicationErrorCode.invalid_params)

    def test_http_422_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(422), PublicationErrorCode.invalid_params)


if __name__ == "__main__":
    unittest.main()
