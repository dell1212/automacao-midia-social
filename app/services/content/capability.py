from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

from sqlmodel import Session, select

from app.models.content_generation import ContentGenerationProvider
from app.services.content.catalog import ModelEntry, list_models


class GenerationMode(str, Enum):
    text_to_image = "text_to_image"
    image_to_image = "image_to_image"
    text_to_video = "text_to_video"
    image_to_video = "image_to_video"
    voice = "voice"


_MODE_SUPPORT_ATTRIBUTE = {
    GenerationMode.text_to_image: "supports_text_to_image",
    GenerationMode.image_to_image: "supports_image_to_image",
    GenerationMode.text_to_video: "supports_text_to_video",
    GenerationMode.image_to_video: "supports_image_to_video",
}


@dataclass(frozen=True)
class GenerationRequirements:
    kind: str
    mode: GenerationMode
    aspect_ratio: Optional[str] = None
    resolution: Optional[str] = None
    duration: Optional[int] = None
    needs_reference_image: bool = False
    needs_avatar: bool = False


@dataclass(frozen=True)
class Candidate:
    provider: str
    model_id: str
    priority: int
    provider_row_id: int


def model_supports(entry: ModelEntry, requirements: GenerationRequirements) -> bool:
    """Whether a catalog model can satisfy this request.

    Empty capability lists in the catalog mean "unconstrained", and unset
    requirement fields mean "caller does not care" — both sides default to
    permissive so a model is only rejected on a real conflict.
    """
    if not entry.is_active or entry.kind != requirements.kind:
        return False

    support_attribute = _MODE_SUPPORT_ATTRIBUTE.get(requirements.mode)
    if support_attribute is not None and not getattr(entry, support_attribute):
        return False

    if requirements.needs_reference_image and not entry.supports_reference_image:
        return False

    if requirements.needs_avatar and not entry.supports_avatar:
        return False

    if (
        requirements.aspect_ratio
        and entry.supported_ratios
        and requirements.aspect_ratio not in entry.supported_ratios
    ):
        return False

    if (
        requirements.resolution
        and entry.supported_resolutions
        and requirements.resolution not in entry.supported_resolutions
    ):
        return False

    if (
        requirements.duration is not None
        and entry.max_duration is not None
        and requirements.duration > entry.max_duration
    ):
        return False

    return True


def _default_catalog_lookup(provider: str, kind: str) -> Sequence[ModelEntry]:
    return list_models(provider=provider, kind=kind)


def select_candidates(
    session: Session,
    *,
    tenant_id: int,
    requirements: GenerationRequirements,
    catalog_lookup: Optional[Callable[[str, str], Sequence[ModelEntry]]] = None,
) -> list[Candidate]:
    """Resolve the ordered list of (provider, model) pairs to try.

    Capability comes first: priority only breaks ties among models that can
    actually satisfy the request. A high-priority provider whose models do not
    support the requested mode/ratio/duration is simply not a candidate.
    """
    lookup = catalog_lookup or _default_catalog_lookup

    provider_rows = list(
        session.exec(
            select(ContentGenerationProvider).where(
                ContentGenerationProvider.tenant_id == tenant_id,
                ContentGenerationProvider.kind == requirements.kind,
                ContentGenerationProvider.is_active == True,  # noqa: E712
            )
        ).all()
    )

    candidates: list[Candidate] = []
    for row in sorted(provider_rows, key=lambda item: item.priority):
        allowed = (row.config or {}).get("allowed_models")
        for entry in lookup(row.provider, requirements.kind):
            if allowed and entry.model_id not in allowed:
                continue
            if not model_supports(entry, requirements):
                continue
            candidates.append(
                Candidate(
                    provider=row.provider,
                    model_id=entry.model_id,
                    priority=row.priority,
                    provider_row_id=row.id,
                )
            )

    return candidates
