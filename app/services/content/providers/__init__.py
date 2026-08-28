from types import ModuleType
from typing import Any

from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.providers import wavespeed
from app.services.content.providers.base import GeneratedAsset

_ADAPTERS: dict[str, ModuleType] = {
    "wavespeed": wavespeed,
}

_KIND_TO_FUNCTION = {
    "image": "generate_image",
    "video": "generate_video",
    "voice": "generate_voice",
}


def get_adapter(provider: str) -> ModuleType:
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise GenerationError(
            GenerationErrorCode.unsupported_capability,
            f"no adapter registered for provider {provider!r}",
        )
    return adapter


def generate(
    *, provider: str, kind: str, api_key: str, model_id: str, **params: Any
) -> GeneratedAsset:
    adapter = get_adapter(provider)
    function_name = _KIND_TO_FUNCTION.get(kind)
    function = getattr(adapter, function_name, None) if function_name else None
    if function is None:
        raise GenerationError(
            GenerationErrorCode.unsupported_capability,
            f"provider {provider!r} does not support kind {kind!r}",
        )
    return function(api_key=api_key, model_id=model_id, **params)


def validate_credentials(*, provider: str, api_key: str) -> None:
    adapter = get_adapter(provider)
    validator = getattr(adapter, "validate_credentials", None)
    if validator is None:
        return
    validator(api_key)
