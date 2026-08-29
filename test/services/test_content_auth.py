import base64
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.controllers import content_auth
from app.models.content import ContentTenant, EntitlementStatus
from app.services.content.crypto import hash_api_token


def _session_returning(tenant):
    session = MagicMock()
    session.exec.return_value.first.return_value = tenant
    return session


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _forge_hs256_token(claims: dict, secret: str) -> str:
    """Hand-builds an HS256 JWT signed with `secret` as the HMAC key.

    Bypasses PyJWT's own `jwt.encode`, which (as of PyJWT 2.10+) refuses to
    use a PEM-formatted key as an HMAC secret. An attacker forging a token
    isn't bound by that client-side guard, so this reproduces the actual
    algorithm-confusion attack surface: a token whose header claims HS256,
    signed with the server's *public* RSA key bytes.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def _generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


class TestVerifyAdminToken(unittest.TestCase):
    def test_missing_env_fails_closed_with_500(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_admin_token(x_admin_token="anything")

        self.assertEqual(ctx.exception.status_code, 500)

    def test_missing_header_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": "dev-admin-token"}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_admin_token(x_admin_token=None)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_wrong_token_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": "dev-admin-token"}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_admin_token(x_admin_token="wrong-token")

        self.assertEqual(ctx.exception.status_code, 401)

    def test_correct_token_is_accepted(self):
        with patch.dict(os.environ, {"CONTENT_ADMIN_TOKEN": "dev-admin-token"}):
            content_auth.verify_admin_token(x_admin_token="dev-admin-token")


class TestVerifyTenantToken(unittest.TestCase):
    def test_missing_header_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            content_auth.verify_tenant_token(
                x_tenant_token=None, session=_session_returning(None)
            )

        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_token_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            content_auth.verify_tenant_token(
                x_tenant_token="unknown-token", session=_session_returning(None)
            )

        self.assertEqual(ctx.exception.status_code, 401)

    def test_inactive_tenant_is_rejected_with_403(self):
        tenant = ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=EntitlementStatus.inactive,
        )

        with self.assertRaises(HTTPException) as ctx:
            content_auth.verify_tenant_token(
                x_tenant_token="tenant-token", session=_session_returning(tenant)
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_active_tenant_is_returned(self):
        tenant = ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=EntitlementStatus.active,
        )

        result = content_auth.verify_tenant_token(
            x_tenant_token="tenant-token", session=_session_returning(tenant)
        )

        self.assertIs(result, tenant)

    def test_trial_tenant_is_returned(self):
        tenant = ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=EntitlementStatus.trial,
        )

        result = content_auth.verify_tenant_token(
            x_tenant_token="tenant-token", session=_session_returning(tenant)
        )

        self.assertIs(result, tenant)


class TestVerifyUserSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_pem, cls.public_pem = _generate_rsa_keypair()
        cls.other_private_pem, _ = _generate_rsa_keypair()

    def _token(self, private_pem=None, **claim_overrides):
        claims = {
            "tenant_id": 1,
            "user_id": "user-1",
            "role": "admin",
            "name": "Ana",
            "exp": int(time.time()) + 3600,
        }
        claims.update(claim_overrides)
        return jwt.encode(claims, private_pem or self.private_pem, algorithm="RS256")

    def _tenant(self, status=EntitlementStatus.active):
        return ContentTenant(
            id=1,
            owner_user_id="u1",
            name="Acme",
            slug="acme",
            api_token_hash=hash_api_token("tenant-token"),
            entitlement_status=status,
        )

    def _session_returning_tenant(self, tenant):
        session = MagicMock()
        session.get.return_value = tenant
        return session

    def test_missing_header_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=None, session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_non_bearer_header_is_rejected(self):
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization="Token abc", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_public_key_env_fails_closed_with_500(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {self._token()}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 500)

    def test_wrong_signature_is_rejected(self):
        token = self._token(private_pem=self.other_private_pem)
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_expired_token_is_rejected(self):
        token = self._token(exp=int(time.time()) - 60)
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_tenant_id_claim_is_rejected(self):
        claims = {
            "user_id": "user-1",
            "role": "admin",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(claims, self.private_pem, algorithm="RS256")
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_exp_claim_is_rejected(self):
        claims = {
            "tenant_id": 1,
            "user_id": "user-1",
            "role": "admin",
        }
        token = jwt.encode(claims, self.private_pem, algorithm="RS256")
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_hs256_algorithm_confusion_is_rejected(self):
        claims = {
            "tenant_id": 1,
            "user_id": "user-1",
            "role": "admin",
            "exp": int(time.time()) + 3600,
        }
        token = _forge_hs256_token(claims, self.public_pem)
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_invalid_role_claim_is_rejected(self):
        token = self._token(role="superadmin")
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}", session=MagicMock()
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_unknown_tenant_is_rejected(self):
        token = self._token()
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}",
                    session=self._session_returning_tenant(None),
                )
        self.assertEqual(ctx.exception.status_code, 401)

    def test_inactive_tenant_is_rejected_with_403(self):
        token = self._token()
        tenant = self._tenant(status=EntitlementStatus.inactive)
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            with self.assertRaises(HTTPException) as ctx:
                content_auth.verify_user_session(
                    authorization=f"Bearer {token}",
                    session=self._session_returning_tenant(tenant),
                )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_valid_token_returns_user_session(self):
        token = self._token()
        tenant = self._tenant()
        with patch.dict(os.environ, {"CONTENT_UI_JWT_PUBLIC_KEY": self.public_pem}):
            result = content_auth.verify_user_session(
                authorization=f"Bearer {token}",
                session=self._session_returning_tenant(tenant),
            )
        self.assertIs(result.tenant, tenant)
        self.assertEqual(result.user_id, "user-1")
        self.assertEqual(result.role, "admin")
        self.assertEqual(result.name, "Ana")


class TestRequireRole(unittest.TestCase):
    def test_matching_role_passes(self):
        session = content_auth.UserSession(
            tenant=MagicMock(), user_id="u1", role="admin", name=None
        )
        content_auth.require_role(session, "admin")  # does not raise

    def test_mismatched_role_raises_403(self):
        session = content_auth.UserSession(
            tenant=MagicMock(), user_id="u1", role="member", name=None
        )
        with self.assertRaises(HTTPException) as ctx:
            content_auth.require_role(session, "admin")
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
