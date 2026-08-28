import unittest
from unittest.mock import MagicMock, patch

import requests

from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers import base


class _StubAdapter(base.PublisherAdapter):
    platform = "stub"

    def check_compatibility(self, piece, asset):
        pass

    def publish(self, piece, asset, account, credentials):
        return base.PublishResult(platform_post_id="1", platform_post_url="https://example.com/1")


class TestAdapterRegistry(unittest.TestCase):
    def setUp(self):
        base._ADAPTER_REGISTRY.clear()

    def test_registered_adapter_is_returned(self):
        adapter = _StubAdapter()
        base.register_adapter(adapter)

        self.assertIs(base.get_adapter("stub"), adapter)

    def test_unknown_platform_raises_unsupported_capability(self):
        with self.assertRaises(PublicationError) as ctx:
            base.get_adapter("myspace")

        self.assertEqual(ctx.exception.code, PublicationErrorCode.unsupported_capability)


class TestLoadCredentials(unittest.TestCase):
    def test_decrypts_and_parses_json(self):
        account = MagicMock(credentials_encrypted="cipher")

        with patch.object(
            base, "decrypt_credentials", return_value='{"access_token": "tok"}'
        ):
            result = base.load_credentials(account)

        self.assertEqual(result, {"access_token": "tok"})


class TestRaiseForResponse(unittest.TestCase):
    def test_success_status_does_not_raise(self):
        response = MagicMock(status_code=200)

        base.raise_for_response(response)  # should not raise

    def test_rate_limit_status_raises_rate_limit(self):
        response = MagicMock(status_code=429)
        response.json.return_value = {"error": {"message": "slow down"}}

        with self.assertRaises(PublicationError) as ctx:
            base.raise_for_response(response)

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)
        self.assertEqual(ctx.exception.message, "slow down")

    def test_error_text_mentioning_policy_overrides_status_classification(self):
        response = MagicMock(status_code=400)
        response.json.return_value = {"error": {"message": "Content violates community guideline"}}

        with self.assertRaises(PublicationError) as ctx:
            base.raise_for_response(response)

        self.assertEqual(ctx.exception.code, PublicationErrorCode.content_policy)

    def test_non_json_error_body_falls_back_to_text(self):
        response = MagicMock(status_code=500)
        response.json.side_effect = ValueError()
        response.text = "internal error"

        with self.assertRaises(PublicationError) as ctx:
            base.raise_for_response(response)

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)
        self.assertEqual(ctx.exception.message, "internal error")


class TestPostForm(unittest.TestCase):
    def test_network_error_is_classified_as_transient(self):
        with patch.object(
            base.requests, "post", side_effect=requests.ConnectionError("boom")
        ):
            with self.assertRaises(PublicationError) as ctx:
                base.post_form("https://api.example.com", data={"a": "b"})

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)

    def test_successful_response_is_returned(self):
        ok_response = MagicMock(status_code=200)

        with patch.object(base.requests, "post", return_value=ok_response):
            result = base.post_form("https://api.example.com", data={"a": "b"})

        self.assertIs(result, ok_response)


if __name__ == "__main__":
    unittest.main()
