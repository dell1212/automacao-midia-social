from typing import Any, Optional

import requests
from loguru import logger

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers.base import (
    DEFAULT_DOWNLOAD_TIMEOUT,
    DEFAULT_SUBMIT_TIMEOUT,
    GeneratedAsset,
    raise_for_response,
    wrap_request_exception,
)

API_BASE_URL = "https://api.elevenlabs.io/v1"


def _headers(api_key: str) -> dict:
    return {"xi-api-key": api_key, "Content-Type": "application/json"}


def generate_voice(
    *,
    api_key: str,
    model_id: str,
    text: str,
    voice_id: Optional[str] = None,
    poll_timeout: Optional[float] = None,
    **extra: Any,
) -> GeneratedAsset:
    """Text-to-speech. Synchronous — ElevenLabs streams the audio back.

    `poll_timeout` is accepted for interface parity with the polling providers
    and used as the read timeout; there is no queue to poll here.
    """
    if not voice_id:
        raise GenerationError(
            GenerationErrorCode.invalid_params,
            "elevenlabs requires a voice_id",
        )

    payload: dict = {"text": text, "model_id": model_id}
    voice_settings = extra.get("voice_settings")
    if voice_settings:
        payload["voice_settings"] = voice_settings

    logger.info(f"generating voice on elevenlabs: model={model_id}")
    try:
        response = requests.post(
            f"{API_BASE_URL}/text-to-speech/{voice_id}",
            json=payload,
            headers=_headers(api_key),
            timeout=(30, poll_timeout or DEFAULT_DOWNLOAD_TIMEOUT[1]),
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="elevenlabs") from exc

    raise_for_response(response, provider="elevenlabs")
    return GeneratedAsset(
        data=response.content,
        mime_type=response.headers.get("Content-Type", "audio/mpeg"),
        filename=f"{voice_id}.mp3",
        input_units=float(len(text)),
        raw_metadata={"voice_id": voice_id},
    )


def validate_credentials(api_key: str) -> None:
    try:
        response = requests.get(
            f"{API_BASE_URL}/user",
            headers={"xi-api-key": api_key},
            timeout=DEFAULT_SUBMIT_TIMEOUT,
        )
    except Exception as exc:
        raise wrap_request_exception(exc, provider="elevenlabs") from exc

    if response.status_code in (401, 403):
        raise GenerationError(
            GenerationErrorCode.invalid_credentials,
            "elevenlabs rejected the API key",
        )
