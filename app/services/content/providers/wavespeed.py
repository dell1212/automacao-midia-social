import time
from typing import Any, Optional

import requests
from loguru import logger

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers.base import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_SUBMIT_TIMEOUT,
    GeneratedAsset,
    download_asset,
    raise_for_response,
    wrap_request_exception,
)

API_BASE_URL = "https://api.wavespeed.ai/api/v3"
_SUCCESS_STATUSES = frozenset({"completed", "succeeded"})
_FAILURE_STATUSES = frozenset({"failed", "cancelled", "timeout"})
_MAX_POLL_SECONDS = 900.0


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _submit(api_key: str, model_id: str, payload: dict) -> str:
    """Submit a prediction and return its id.

    A submission is never retried inside the adapter: the request may already
    have created a billable task upstream, and resending would double-charge.
    The retry policy above only re-runs whole attempts that failed before a
    task existed.
    """
    endpoint = f"{API_BASE_URL}/{model_id.strip('/')}"
    try:
        response = requests.post(
            endpoint, json=payload, headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="wavespeed") from exc

    raise_for_response(response, provider="wavespeed")
    body = response.json()
    prediction_id = (body.get("data") or {}).get("id")
    if not prediction_id:
        raise GenerationError(
            GenerationErrorCode.unknown, "wavespeed response has no prediction id"
        )
    return prediction_id


def _poll(api_key: str, prediction_id: str, poll_timeout: Optional[float] = None) -> dict:
    deadline = time.monotonic() + (poll_timeout or _MAX_POLL_SECONDS)
    endpoint = f"{API_BASE_URL}/predictions/{prediction_id}/result"

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                endpoint, headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
            )
        except Exception as exc:
            raise wrap_request_exception(exc, provider="wavespeed") from exc

        raise_for_response(response, provider="wavespeed")
        data = response.json().get("data") or {}
        status = str(data.get("status", "")).lower()

        if status in _SUCCESS_STATUSES:
            return data
        if status in _FAILURE_STATUSES:
            raise GenerationError(
                GenerationErrorCode.content_policy
                if "policy" in str(data.get("error", "")).lower()
                else GenerationErrorCode.unknown,
                f"wavespeed prediction {prediction_id} ended as {status}",
            )
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

    raise GenerationError(
        GenerationErrorCode.timeout,
        f"wavespeed prediction {prediction_id} did not finish in time",
    )


def _first_output_url(data: dict) -> str:
    outputs = data.get("outputs") or []
    if not outputs:
        raise GenerationError(
            GenerationErrorCode.unknown, "wavespeed prediction returned no outputs"
        )
    return outputs[0]


def generate_image(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    aspect_ratio: Optional[str] = None,
    source_image_url: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    payload: dict = {"prompt": prompt}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if source_image_url:
        payload["image"] = source_image_url
    payload.update(extra)

    logger.info(f"generating image on wavespeed: model={model_id}")
    prediction_id = _submit(api_key, model_id, payload)
    data = _poll(api_key, prediction_id, poll_timeout)
    asset = download_asset(
        _first_output_url(data),
        provider="wavespeed",
        filename=f"{prediction_id}.png",
        mime_type="image/png",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        output_units=1,
        raw_metadata={"prediction_id": prediction_id},
    )


def generate_video(
    *,
    api_key: str,
    model_id: str,
    prompt: str,
    source_image_url: Optional[str] = None,
    aspect_ratio: Optional[str] = None,
    duration: Optional[int] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    payload: dict = {"prompt": prompt}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if duration:
        payload["duration"] = int(duration)
    if source_image_url:
        payload["image"] = source_image_url
    payload.update(extra)

    logger.info(f"generating video on wavespeed: model={model_id}")
    prediction_id = _submit(api_key, model_id, payload)
    data = _poll(api_key, prediction_id, poll_timeout)
    asset = download_asset(
        _first_output_url(data),
        provider="wavespeed",
        filename=f"{prediction_id}.mp4",
        mime_type="video/mp4",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        duration=float(duration) if duration else None,
        output_units=float(duration) if duration else None,
        raw_metadata={"prediction_id": prediction_id},
    )


def validate_credentials(api_key: str) -> None:
    """Cheap authenticated call, used when a tenant registers the provider."""
    try:
        response = requests.get(
            f"{API_BASE_URL}/balance",
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="wavespeed") from exc

    if response.status_code in (401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials, "wavespeed rejected the API key"
        )
