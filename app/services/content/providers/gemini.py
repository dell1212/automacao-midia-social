import base64
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
    is_policy_error_text,
    raise_for_response,
    wrap_request_exception,
)

API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_MAX_POLL_SECONDS = 900.0


def _headers(api_key: str) -> dict:
    return {"x-goog-api-key": api_key, "Content-Type": "application/json"}


def _inline_image_data(source_image_url: str) -> dict:
    """Gemini's REST API takes reference images as inline base64 bytes, not a
    URL — every image this module can produce is a Supabase HTTPS URL (or an
    avatar's reference_image_url), never a gs:// URI, so gcsUri is not an
    option here.
    """
    asset = download_asset(
        source_image_url, provider="gemini", filename="source.bin", mime_type="image/png"
    )
    return {
        "mimeType": asset.mime_type,
        "data": base64.b64encode(asset.data).decode("ascii"),
    }


def _post(api_key: str, path: str, payload: dict) -> dict:
    try:
        response = requests.post(
            f"{API_BASE_URL}/{path}",
            json=payload,
            headers=_headers(api_key),
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="gemini") from exc

    raise_for_response(response, provider="gemini")
    return response.json()


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
    parts: list[dict] = []
    if source_image_url:
        parts.append({"inlineData": _inline_image_data(source_image_url)})
    parts.append({"text": prompt})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    if aspect_ratio:
        payload["generationConfig"]["imageConfig"] = {"aspectRatio": aspect_ratio}

    logger.info(f"generating image on gemini: model={model_id}")
    body = _post(api_key, f"models/{model_id}:generateContent", payload)

    candidates = body.get("candidates") or []
    for candidate in candidates:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return GeneratedAsset(
                    data=base64.b64decode(inline["data"]),
                    mime_type=inline.get("mimeType", "image/png"),
                    filename="gemini-image.png",
                    output_units=1,
                )

    finish_reason = candidates[0].get("finishReason") if candidates else None
    if finish_reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
        raise GenerationError(
            GenerationErrorCode.content_policy,
            f"gemini refused the request: {finish_reason}",
        )
    raise GenerationError(
        GenerationErrorCode.unknown, "gemini response contains no image data"
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
    instance: dict = {"prompt": prompt}
    if source_image_url:
        image_data = _inline_image_data(source_image_url)
        instance["image"] = {
            "bytesBase64Encoded": image_data["data"],
            "mimeType": image_data["mimeType"],
        }

    parameters: dict = {}
    if aspect_ratio:
        parameters["aspectRatio"] = aspect_ratio
    if duration:
        parameters["durationSeconds"] = int(duration)

    logger.info(f"generating video on gemini: model={model_id}")
    operation = _post(
        api_key,
        f"models/{model_id}:predictLongRunning",
        {"instances": [instance], "parameters": parameters},
    )
    operation_name = operation.get("name")
    if not operation_name:
        raise GenerationError(
            GenerationErrorCode.unknown, "gemini response has no operation name"
        )

    deadline = time.monotonic() + (poll_timeout or _MAX_POLL_SECONDS)
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{API_BASE_URL}/{operation_name}",
                headers=_headers(api_key),
                timeout=DEFAULT_SUBMIT_TIMEOUT,
            )
        except Exception as exc:
            raise wrap_request_exception(exc, provider="gemini") from exc

        raise_for_response(response, provider="gemini")
        body = response.json()

        if body.get("done"):
            error = body.get("error")
            if error:
                raise GenerationError(
                    GenerationErrorCode.content_policy
                    if is_policy_error_text(str(error))
                    else GenerationErrorCode.unknown,
                    f"gemini operation failed with code {error.get('code')}",
                )
            samples = (
                (body.get("response") or {}).get("generateVideoResponse", {})
            ).get("generatedSamples") or []
            for sample in samples:
                encoded = (sample.get("video") or {}).get("bytesBase64Encoded")
                if encoded:
                    return GeneratedAsset(
                        data=base64.b64decode(encoded),
                        mime_type="video/mp4",
                        filename="gemini-video.mp4",
                        duration=float(duration) if duration else None,
                        output_units=float(duration) if duration else None,
                    )
            raise GenerationError(
                GenerationErrorCode.unknown, "gemini operation returned no video data"
            )
        time.sleep(DEFAULT_POLL_INTERVAL_SECONDS)

    raise GenerationError(
        GenerationErrorCode.timeout, "gemini operation did not finish in time"
    )


def validate_credentials(api_key: str) -> None:
    try:
        response = requests.get(
            f"{API_BASE_URL}/models", headers=_headers(api_key), timeout=DEFAULT_SUBMIT_TIMEOUT
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="gemini") from exc

    if response.status_code in (400, 401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials, "gemini rejected the API key"
        )
