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
        # The real adapters register themselves at import time, so clearing
        # the registry without restoring it leaves every later test in the
        # same process unable to resolve a real platform.
        saved = dict(base._ADAPTER_REGISTRY)
        self.addCleanup(lambda: base._ADAPTER_REGISTRY.update(saved))
        self.addCleanup(base._ADAPTER_REGISTRY.clear)
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


class TestGetJson(unittest.TestCase):
    def test_returns_parsed_json_body(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"status_code": "FINISHED"}

        with patch.object(base.requests, "get", return_value=response) as get:
            result = base.get_json(
                "https://api.example.com/container-1", params={"fields": "status_code"}
            )

        self.assertEqual(result, {"status_code": "FINISHED"})
        self.assertEqual(get.call_args.kwargs["params"], {"fields": "status_code"})

    def test_network_error_is_classified_as_transient(self):
        with patch.object(
            base.requests, "get", side_effect=requests.ConnectionError("boom")
        ):
            with self.assertRaises(PublicationError) as ctx:
                base.get_json("https://api.example.com/container-1")

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)

    def test_error_status_raises_publication_error(self):
        response = MagicMock(status_code=400)
        response.json.return_value = {"error": {"message": "bad request"}}

        with patch.object(base.requests, "get", return_value=response):
            with self.assertRaises(PublicationError) as ctx:
                base.get_json("https://api.example.com/container-1")

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)


class TestGetBytes(unittest.TestCase):
    def test_404_response_classifies_as_invalid_params(self):
        response = MagicMock(status_code=404)
        response.json.return_value = {"error": {"message": "not found"}}

        with patch.object(base.requests, "get", return_value=response):
            with self.assertRaises(PublicationError) as ctx:
                base.get_bytes("https://example.com/asset.jpg")

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_params)

    def test_network_error_is_classified_as_transient(self):
        with patch.object(
            base.requests, "get", side_effect=requests.ConnectionError("boom")
        ):
            with self.assertRaises(PublicationError) as ctx:
                base.get_bytes("https://example.com/asset.jpg")

        self.assertEqual(ctx.exception.code, PublicationErrorCode.transient)


if __name__ == "__main__":
    unittest.main()
