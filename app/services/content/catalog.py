import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

import yaml

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "models_catalog.yaml")

_VALID_KINDS = frozenset({"image", "video", "voice"})

_REQUIRED_FIELDS = (
    "provider",
    "kind",
    "model_id",
    "name",
    "is_active",
    "supports_text_to_image",
    "supports_image_to_image",
    "supports_text_to_video",
    "supports_image_to_video",
    "supports_reference_image",
    "supports_avatar",
    "supported_ratios",
    "supported_resolutions",
    "max_duration",
    "cost_config",
)


class ModelCatalogError(RuntimeError):
    """The model catalog file is missing, unreadable, or malformed.

    Raised at import/boot time on purpose: a broken catalog must fail loudly
    on startup instead of silently producing "no compatible model" at the
    first paid generation.
    """


@dataclass(frozen=True)
class ModelEntry:
    provider: str
    kind: str
    model_id: str
    name: str
    is_active: bool
    supports_text_to_image: bool
    supports_image_to_image: bool
    supports_text_to_video: bool
    supports_image_to_video: bool
    supports_reference_image: bool
    supports_avatar: bool
    supported_ratios: tuple[str, ...]
    supported_resolutions: tuple[str, ...]
    max_duration: Optional[int]
    cost_config: dict


def _build_entry(raw: Any, index: int) -> ModelEntry:
    if not isinstance(raw, dict):
        raise ModelCatalogError(f"catalog entry #{index} is not a mapping")

    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ModelCatalogError(
            f"catalog entry #{index} is missing required fields: {', '.join(missing)}"
        )

    kind = str(raw["kind"])
    if kind not in _VALID_KINDS:
        raise ModelCatalogError(
            f"catalog entry #{index} has unknown kind {kind!r} "
            f"(expected one of {sorted(_VALID_KINDS)})"
        )

    max_duration = raw["max_duration"]
    if max_duration is not None:
        try:
            max_duration = int(max_duration)
        except (TypeError, ValueError) as exc:
            raise ModelCatalogError(
                f"catalog entry #{index} has a non-numeric max_duration"
            ) from exc

    return ModelEntry(
        provider=str(raw["provider"]),
        kind=kind,
        model_id=str(raw["model_id"]),
        name=str(raw["name"]),
        is_active=bool(raw["is_active"]),
        supports_text_to_image=bool(raw["supports_text_to_image"]),
        supports_image_to_image=bool(raw["supports_image_to_image"]),
        supports_text_to_video=bool(raw["supports_text_to_video"]),
        supports_image_to_video=bool(raw["supports_image_to_video"]),
        supports_reference_image=bool(raw["supports_reference_image"]),
        supports_avatar=bool(raw["supports_avatar"]),
        supported_ratios=tuple(str(item) for item in raw["supported_ratios"] or ()),
        supported_resolutions=tuple(
            str(item) for item in raw["supported_resolutions"] or ()
        ),
        max_duration=max_duration,
        cost_config=dict(raw["cost_config"] or {}),
    )


def load_catalog(path: Optional[str] = None) -> tuple[ModelEntry, ...]:
    """Read and validate the catalog file. Never cached — see get_catalog."""
    target = path or _CATALOG_PATH
    try:
        with open(target, "r", encoding="utf-8") as handle:
            raw_entries = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise ModelCatalogError(f"model catalog not found at {target}") from exc
    except yaml.YAMLError as exc:
        raise ModelCatalogError(f"model catalog at {target} is not valid YAML") from exc

    if not isinstance(raw_entries, list):
        raise ModelCatalogError(
            f"model catalog at {target} must be a list of model entries"
        )

    entries = tuple(
        _build_entry(raw, index) for index, raw in enumerate(raw_entries)
    )

    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry.provider, entry.model_id)
        if key in seen:
            raise ModelCatalogError(
                f"duplicate model_id {entry.model_id!r} for provider {entry.provider!r}"
            )
        seen.add(key)

    return entries


@lru_cache(maxsize=1)
def get_catalog() -> tuple[ModelEntry, ...]:
    return load_catalog()


def list_models(
    *, provider: Optional[str] = None, kind: Optional[str] = None
) -> list[ModelEntry]:
    entries = get_catalog()
    return [
        entry
        for entry in entries
        if entry.is_active
        and (provider is None or entry.provider == provider)
        and (kind is None or entry.kind == kind)
    ]
