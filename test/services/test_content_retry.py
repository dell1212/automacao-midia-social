import unittest
from unittest.mock import patch

from app.services.content import retry
from app.services.content.errors import (
    GenerationError,
    GenerationErrorCode,
    classify_http_status,
    is_retryable,
)


class TestErrorClassification(unittest.TestCase):
    def test_rate_limit_is_retryable(self):
        self.assertTrue(is_retryable(GenerationErrorCode.rate_limit))

    def test_transient_is_retryable(self):
        self.assertTrue(is_retryable(GenerationErrorCode.transient))

    def test_timeout_is_retryable(self):
        self.assertTrue(is_retryable(GenerationErrorCode.timeout))

    def test_invalid_credentials_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.invalid_credentials))

    def test_invalid_params_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.invalid_params))

    def test_content_policy_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.content_policy))

    def test_unsupported_capability_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.unsupported_capability))

    def test_unknown_is_not_retryable(self):
        self.assertFalse(is_retryable(GenerationErrorCode.unknown))

    def test_http_429_maps_to_rate_limit(self):
        self.assertEqual(classify_http_status(429), GenerationErrorCode.rate_limit)

    def test_http_5xx_maps_to_transient(self):
        self.assertEqual(classify_http_status(503), GenerationErrorCode.transient)

    def test_http_401_maps_to_invalid_credentials(self):
        self.assertEqual(
            classify_http_status(401), GenerationErrorCode.invalid_credentials
        )

    def test_http_403_maps_to_invalid_credentials(self):
        self.assertEqual(
            classify_http_status(403), GenerationErrorCode.invalid_credentials
        )

    def test_http_400_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(400), GenerationErrorCode.invalid_params)

    def test_http_422_maps_to_invalid_params(self):
        self.assertEqual(classify_http_status(422), GenerationErrorCode.invalid_params)


class TestBackoffDelay(unittest.TestCase):
    def test_grows_exponentially(self):
        first = retry.backoff_delay(1, random_fn=lambda: 0.0)
        second = retry.backoff_delay(2, random_fn=lambda: 0.0)
        third = retry.backoff_delay(3, random_fn=lambda: 0.0)

        self.assertEqual(first, retry.BACKOFF_BASE_SECONDS)
        self.assertEqual(second, retry.BACKOFF_BASE_SECONDS * retry.BACKOFF_MULTIPLIER)
        self.assertEqual(
            third, retry.BACKOFF_BASE_SECONDS * retry.BACKOFF_MULTIPLIER**2
        )

    def test_is_capped_at_max_backoff(self):
        self.assertLessEqual(
            retry.backoff_delay(20, random_fn=lambda: 1.0),
            retry.MAX_BACKOFF_SECONDS * (1 + retry.JITTER_RATIO),
        )

    def test_jitter_widens_the_delay(self):
        without = retry.backoff_delay(1, random_fn=lambda: 0.0)
        with_jitter = retry.backoff_delay(1, random_fn=lambda: 1.0)

        self.assertGreater(with_jitter, without)


class TestRunWithRetry(unittest.TestCase):
    def test_returns_result_without_retrying_on_success(self):
        calls = []

        def operation():
            calls.append(1)
            return "ok"

        with patch.object(retry.time, "sleep"):
            result = retry.run_with_retry(operation)

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_retryable_error_up_to_max_attempts(self):
        calls = []

        def operation():
            calls.append(1)
            raise GenerationError(GenerationErrorCode.transient, "boom")

        with patch.object(retry.time, "sleep"):
            with self.assertRaises(GenerationError):
                retry.run_with_retry(operation)

        self.assertEqual(len(calls), retry.MAX_ATTEMPTS)

    def test_does_not_retry_non_retryable_error(self):
        calls = []

        def operation():
            calls.append(1)
            raise GenerationError(GenerationErrorCode.invalid_params, "bad")

        with patch.object(retry.time, "sleep"):
            with self.assertRaises(GenerationError):
                retry.run_with_retry(operation)

        self.assertEqual(len(calls), 1)

    def test_succeeds_after_a_retryable_failure(self):
        calls = []

        def operation():
            calls.append(1)
            if len(calls) == 1:
                raise GenerationError(GenerationErrorCode.rate_limit, "slow down")
            return "ok"

        with patch.object(retry.time, "sleep"):
            result = retry.run_with_retry(operation)

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)

    def test_reports_each_attempt(self):
        attempts = []

        def operation():
            raise GenerationError(GenerationErrorCode.transient, "boom")

        with patch.object(retry.time, "sleep"):
            with self.assertRaises(GenerationError):
                retry.run_with_retry(operation, on_attempt=attempts.append)

        self.assertEqual(attempts, list(range(1, retry.MAX_ATTEMPTS + 1)))


if __name__ == "__main__":
    unittest.main()
