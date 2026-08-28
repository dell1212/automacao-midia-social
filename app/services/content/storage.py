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
    content_piece_id: int,
    filename: str,
    data: bytes,
    content_type: str,
) -> UploadedObject:
    """Upload one generated artifact and return its public URL.

    The path is prefixed by tenant so a future storage-level policy can scope
    access per tenant without moving objects around.
    """
    base_url = _require_env(_SUPABASE_URL_ENV).rstrip("/")
    service_key = _require_env(_SUPABASE_SERVICE_KEY_ENV)
    bucket = _bucket()

    safe_name = os.path.basename(filename).replace(" ", "-")
    storage_path = f"{tenant_id}/{content_piece_id}/{uuid4().hex}-{safe_name}"
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
