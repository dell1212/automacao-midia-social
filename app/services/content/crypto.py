import hashlib
import os
import secrets

from cryptography.fernet import Fernet

_ENCRYPTION_KEY_ENV = "CONTENT_MODULE_ENCRYPTION_KEY"


def _fernet() -> Fernet:
    key = os.environ.get(_ENCRYPTION_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{_ENCRYPTION_KEY_ENV} is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and set it as an env var."
        )
    return Fernet(key.encode())


def encrypt_credentials(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_credentials(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def generate_api_token() -> str:
    return secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
