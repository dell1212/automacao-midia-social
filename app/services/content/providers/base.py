from dataclasses import dataclass, field
from typing import Optional

import requests

from app.services.content.errors import (
    GenerationError,
    GenerationErrorCode,
    classify_http_status,
)

# Providers that submit a job and poll for it need a ceiling; the orchestrator
# enforces a per-kind timeout above this, so this is only a safety net.
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_SUBMIT_TIMEOUT = (30, 60)
DEFAULT_DOWNLOAD_TIMEOUT = (30, 300)


@dataclass(frozen=True)
class GeneratedAsset:
    """One artifact returned by a provider, already downloaded into memory."""

    data: bytes
    mime_type: str
    filename: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    input_units: Optional[float] = None
    output_units: Optional[float] = None
    actual_cost: Optional[float] = None
    currency: Optional[str] = None
    raw_metadata: dict = field(default_factory=dict)


def raise_for_response(response: requests.Response, *, provider: str) -> None:
    """Translate an HTTP error response into the canonical taxonomy.

    Never include the response body verbatim in the message: provider errors
    sometimes echo the request, which can carry the API key.
    """
    if response.status_code < 400:
        return
    code = classify_http_status(response.status_code)
    raise GenerationError(
        code, f"{provider} request failed with status {response.status_code}"
    )


def wrap_request_exception(exc: Exception, *, provider: str) -> GenerationError:
    """Network-level failures are transient by definition."""
    if isinstance(exc, requests.exceptions.Timeout):
        return GenerationError(
            GenerationErrorCode.timeout, f"{provider} request timed out"
        )
    if isinstance(exc, requests.RequestException):
        return GenerationError(
            GenerationErrorCode.transient, f"{provider} request failed: {type(exc).__name__}"
        )
    return GenerationError(
        GenerationErrorCode.unknown, f"{provider} request raised {type(exc).__name__}"
    )


def download_asset(
    url: str, *, provider: str, filename: str, mime_type: str
) -> GeneratedAsset:
    try:
        response = requests.get(url, timeout=DEFAULT_DOWNLOAD_TIMEOUT)
    except Exception as exc:
        raise wrap_request_exception(exc, provider=provider) from exc

    raise_for_response(response, provider=provider)
    return GeneratedAsset(
        data=response.content,
        mime_type=response.headers.get("Content-Type", mime_type),
        filename=filename,
    )
