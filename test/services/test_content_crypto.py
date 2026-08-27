import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.services.content import crypto


class TestContentCrypto(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode()
        self.env_patch = patch.dict(
            os.environ, {"CONTENT_MODULE_ENCRYPTION_KEY": self.key}
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    def test_encrypt_decrypt_roundtrip(self):
        ciphertext = crypto.encrypt_credentials("secret-token")

        self.assertNotEqual(ciphertext, "secret-token")
        self.assertEqual(crypto.decrypt_credentials(ciphertext), "secret-token")

    def test_decrypt_fails_with_different_key(self):
        ciphertext = crypto.encrypt_credentials("secret-token")

        with patch.dict(
            os.environ,
            {"CONTENT_MODULE_ENCRYPTION_KEY": Fernet.generate_key().decode()},
        ):
            with self.assertRaises(Exception):
                crypto.decrypt_credentials(ciphertext)

    def test_encrypt_requires_encryption_key_env(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                crypto.encrypt_credentials("secret-token")

    def test_hash_api_token_is_deterministic_and_not_plaintext(self):
        token = crypto.generate_api_token()

        self.assertEqual(crypto.hash_api_token(token), crypto.hash_api_token(token))
        self.assertNotEqual(crypto.hash_api_token(token), token)

    def test_generate_api_token_is_unique(self):
        self.assertNotEqual(crypto.generate_api_token(), crypto.generate_api_token())


if __name__ == "__main__":
    unittest.main()
