import os
from dataclasses import dataclass
from uuid import uuid4

import requests
from loguru import logger

_SUPABASE_URL_ENV = "SUPABASE_URL"
_SUPABASE_SERVICE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"
_BUCKET_ENV = "CONTENT_STORAGE_BUCKET"
_DEFAULT_BUCKET = "content-assets"

_UPLOAD_TIMEOUT = (30, 300)
# Signing is a metadata call, not a transfer — it has no reason to inherit the
# upload's 5-minute read budget, which a slow Supabase would otherwise spend
# once per asset, serially, before the review UI can render a piece.
_SIGN_TIMEOUT = (5, 15)


class StorageError(RuntimeError):
    """Uploading a generated artifact to Supabase Storage failed."""


@dataclass(frozen=True)
class UploadedObject:
    url: str
    storage_path: str
    size_bytes: int


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise StorageError(f"{name} is not set")
    return value


def _bucket() -> str:
    return os.environ.get(_BUCKET_ENV) or _DEFAULT_BUCKET


def upload_bytes(
    *,
    tenant_id: int,
    path_prefix: str,
    filename: str,
    data: bytes,
    content_type: str,
) -> UploadedObject:
    """Upload one file and return its public URL.

    The path is prefixed by tenant so a future storage-level policy can scope
    access per tenant without moving objects around. `path_prefix` groups
    objects under the tenant (a content piece id for generated artifacts,
    "avatars" for avatar reference images, etc).
    """
    base_url = _require_env(_SUPABASE_URL_ENV).rstrip("/")
    service_key = _require_env(_SUPABASE_SERVICE_KEY_ENV)
    bucket = _bucket()

    safe_name = os.path.basename(filename).replace(" ", "-")
    storage_path = f"{tenant_id}/{path_prefix}/{uuid4().hex}-{safe_name}"
    endpoint = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"

    try:
        response = requests.post(
            endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {service_key}",
                "Content-Type": content_type,
                "x-upsert": "false",
            },
            timeout=_UPLOAD_TIMEOUT,
        )
    except requests.RequestException as exc:
        # The service key can appear in a request exception's string form.
        raise StorageError(
            f"storage upload request failed for {storage_path}"
        ) from exc

    if response.status_code >= 400:
        raise StorageError(
            f"storage upload rejected for {storage_path}: "
            f"status={response.status_code}"
        )

    public_url = f"{base_url}/storage/v1/object/public/{bucket}/{storage_path}"
    logger.info(f"uploaded generated asset to storage: path={storage_path}")
    return UploadedObject(
        url=public_url, storage_path=storage_path, size_bytes=len(data)
    )


def create_signed_url(storage_path: str, *, expires_in: int = 600) -> str:
    """Signs a storage_path for temporary UI access.

    Uploads and the pipeline/publish paths keep using the public URL
    persisted on ContentAsset.url — this is only for what the review UI
    hands to the browser, generated fresh on every call (no caching, the
    default 10-minute TTL is already short enough).
    """
    base_url = _require_env(_SUPABASE_URL_ENV).rstrip("/")
    service_key = _require_env(_SUPABASE_SERVICE_KEY_ENV)
    bucket = _bucket()
    endpoint = f"{base_url}/storage/v1/object/sign/{bucket}/{storage_path}"

    try:
        response = requests.post(
            endpoint,
            json={"expiresIn": expires_in},
            headers={"Authorization": f"Bearer {service_key}"},
            timeout=_SIGN_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageError(f"storage sign request failed for {storage_path}") from exc

    if response.status_code >= 400:
        raise StorageError(
            f"storage sign rejected for {storage_path}: status={response.status_code}"
        )

    signed_url = response.json().get("signedURL")
    if not signed_url:
        raise StorageError(f"storage sign response missing signedURL for {storage_path}")

    return f"{base_url}/storage/v1{signed_url}"
