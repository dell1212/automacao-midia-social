import os
import unittest
from unittest.mock import MagicMock, patch

from app.services.content import storage


_ENV = {
    "SUPABASE_URL": "https://proj.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-key",
}


class TestCreateSignedUrl(unittest.TestCase):
    def test_returns_full_signed_url_on_success(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "signedURL": "/object/sign/content-assets/1/2/file.png?token=abc"
        }

        with patch.dict(os.environ, _ENV):
            with patch.object(storage.requests, "post", return_value=response) as mock_post:
                result = storage.create_signed_url("1/2/file.png", expires_in=600)

        self.assertEqual(
            result,
            "https://proj.supabase.co/storage/v1/object/sign/content-assets/1/2/file.png?token=abc",
        )
        mock_post.assert_called_once()
        called_url = mock_post.call_args.args[0]
        self.assertEqual(
            called_url,
            "https://proj.supabase.co/storage/v1/object/sign/content-assets/1/2/file.png",
        )
        self.assertEqual(mock_post.call_args.kwargs["json"], {"expiresIn": 600})

    def test_raises_storage_error_on_http_error(self):
        response = MagicMock(status_code=403)

        with patch.dict(os.environ, _ENV):
            with patch.object(storage.requests, "post", return_value=response):
                with self.assertRaises(storage.StorageError):
                    storage.create_signed_url("1/2/file.png")

    def test_raises_storage_error_when_response_missing_signed_url(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {}

        with patch.dict(os.environ, _ENV):
            with patch.object(storage.requests, "post", return_value=response):
                with self.assertRaises(storage.StorageError):
                    storage.create_signed_url("1/2/file.png")

    def test_raises_storage_error_when_service_key_missing(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://proj.supabase.co"}, clear=True):
            with self.assertRaises(storage.StorageError):
                storage.create_signed_url("1/2/file.png")


if __name__ == "__main__":
    unittest.main()
