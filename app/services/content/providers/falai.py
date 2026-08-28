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

QUEUE_BASE_URL = "https://queue.fal.run"
_MAX_POLL_SECONDS = 900.0


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Key {api_key}"}


def _submit(api_key: str, model_id: str, payload: dict) -> tuple[str, str]:
    """Submit to the fal queue; returns (status_url, response_url)."""
    try:
        response = requests.post(
            f"{QUEUE_BASE_URL}/{model_id.strip('/')}",
            json=payload,
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="falai") from exc

    raise_for_response(response, provider="falai")
    body = response.json()
    status_url = body.get("status_url")
    response_url = body.get("response_url")
    if not status_url or not response_url:
        raise GenerationError(
            GenerationErrorCode.unknown, "falai response is missing queue urls"
        )
    return status_url, response_url


def _poll(
    api_key: str,
    status_url: str,
    response_url: str,
    poll_timeout: Optional[float] = None,
) -> dict:
    deadline = time.monotonic() + (poll_timeout or _MAX_POLL_SECONDS)

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                status_url, headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
            )
        except Exception as exc:
            raise wrap_request_exception(exc, provider="falai") from exc

        raise_for_response(response, provider="falai")
        status = str(response.json().get("status", "")).upper()

        if status == "COMPLETED":
            try:
                result = requests.get(
                    response_url,
                    headers=_headers(api_key),
                    timeout=DEFAULT_SUBMIT_TIMEOUT,
                )
            except Exception as exc:
                raise wrap_request_exception(exc, provider="falai") from exc
            raise_for_response(result, provider="falai")
            return result.json()
        if status in ("FAILED", "CANCELLED"):
            raise GenerationError(
                GenerationErrorCode.unknown, f"falai request ended as {status}"
            )
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

    raise GenerationError(
        GenerationErrorCode.timeout, "falai request did not finish in time"
    )


def _extract_url(result: dict, key: str) -> str:
    node = result.get(key)
    if isinstance(node, dict) and node.get("url"):
        return node["url"]
    if isinstance(node, list) and node and isinstance(node[0], dict):
        url = node[0].get("url")
        if url:
            return url
    raise GenerationError(
        GenerationErrorCode.unknown, f"falai result has no {key} url"
    )


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
        payload["image_url"] = source_image_url
    payload.update(extra)

    logger.info(f"generating image on falai: model={model_id}")
    status_url, response_url = _submit(api_key, model_id, payload)
    result = _poll(api_key, status_url, response_url, poll_timeout)
    asset = download_asset(
        _extract_url(result, "images"),
        provider="falai",
        filename="falai-image.png",
        mime_type="image/png",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        output_units=1,
        raw_metadata={"seed": result.get("seed")},
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
        payload["duration"] = str(int(duration))
    if source_image_url:
        payload["image_url"] = source_image_url
    payload.update(extra)

    logger.info(f"generating video on falai: model={model_id}")
    status_url, response_url = _submit(api_key, model_id, payload)
    result = _poll(api_key, status_url, response_url, poll_timeout)
    asset = download_asset(
        _extract_url(result, "video"),
        provider="falai",
        filename="falai-video.mp4",
        mime_type="video/mp4",
    )
    return GeneratedAsset(
        data=asset.data,
        mime_type=asset.mime_type,
        filename=asset.filename,
        duration=float(duration) if duration else None,
        output_units=float(duration) if duration else None,
        raw_metadata={"seed": result.get("seed")},
    )


def validate_credentials(api_key: str) -> None:
    try:
        response = requests.get(
            "https://rest.alpha.fal.ai/tokens/",
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="falai") from exc

    if response.status_code in (401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials, "falai rejected the API key"
        )
