import io
import time
from typing import Optional

from loguru import logger
from PIL import Image
from sqlmodel import Session

from app.models.content_generation import (
    ContentAsset,
    ContentAssetType,
    ContentGenerationJob,
    GenerationJobStatus,
)
from app.services.content import assets as assets_service
from app.services.content import jobs as jobs_service
from app.services.content import providers as provider_adapters
from app.services.content.capability import GenerationRequirements, select_candidates
from app.services.content.catalog import list_models
from app.services.content.errors import GenerationError, GenerationErrorCode
from app.services.content.generation_providers import (
    decrypt_provider_credentials,
    get_generation_provider,
)
from app.services.content.retry import run_with_retry
from app.services.content.storage import StorageError, upload_bytes


def estimate_cost(
    provider: str, model_id: str, *, units: Optional[float]
) -> tuple[Optional[float], Optional[str]]:
    """Estimate the spend of one generation from the catalog's cost_config."""
    if units is None:
        return None, None
    for entry in list_models(provider=provider):
        if entry.model_id != model_id:
            continue
        price = entry.cost_config.get("price")
        currency = entry.cost_config.get("currency")
        if price is None:
            return None, currency
        return round(float(price) * float(units), 6), currency
    return None, None


def _probe_image_dimensions(data: bytes) -> tuple[Optional[int], Optional[int]]:
    """Best-effort image dimensions for an adapter that didn't report them.

    No adapter's GeneratedAsset currently carries width/height, so without
    this every image asset's dimensions are stored as NULL even though the
    bytes are right there. Never fatal: dimensions are a nice-to-have on the
    asset registry, not something worth failing a generation over.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:  # noqa: BLE001 - dimensions are best-effort only
        return None, None


def run_job(
    session: Session,
    *,
    job: ContentGenerationJob,
    requirements: GenerationRequirements,
    params: dict,
    asset_type: ContentAssetType,
    timeout_seconds: Optional[float] = None,
    is_intermediate: bool = False,
) -> Optional[ContentAsset]:
    """Execute one generation job end to end.

    Walks the capability-ordered candidate list: retryable failures re-run the
    same (provider, model) per the retry policy; non-retryable ones move
    straight to the next candidate, since insisting would fail identically.
    Returns the created asset, or None when every candidate is exhausted (the
    job is marked failed in that case).

    `timeout_seconds` is pushed down into each adapter's poll deadline rather
    than enforced by abandoning a worker thread — a thread left polling a paid
    provider is exactly the leak the per-kind pools exist to prevent.
    """
    candidates = select_candidates(
        session, tenant_id=job.tenant_id, requirements=requirements
    )
    if not candidates:
        jobs_service.mark_failed(
            session,
            job,
            error_code=GenerationErrorCode.no_compatible_model.value,
            error_message=(
                f"no active provider/model satisfies kind={requirements.kind} "
                f"mode={requirements.mode.value}"
            ),
        )
        return None

    jobs_service.mark_running(session, job)
    last_error: Optional[GenerationError] = None

    for candidate in candidates:
        provider_row = get_generation_provider(
            session, tenant_id=job.tenant_id, provider_id=candidate.provider_row_id
        )
        if provider_row is None:
            continue

        api_key = decrypt_provider_credentials(provider_row)
        started = time.monotonic()

        def attempt():
            try:
                return provider_adapters.generate(
                    provider=candidate.provider,
                    kind=requirements.kind,
                    api_key=api_key,
                    model_id=candidate.model_id,
                    poll_timeout=timeout_seconds,
                    **params,
                )
            except GenerationError:
                raise
            except Exception as exc:
                # Anything unclassified (malformed JSON, a bad base64 payload,
                # etc.) must still become a GenerationError, or it propagates
                # past run_job entirely and the job row is left stuck in
                # `running` forever. Only the exception type name is carried
                # in the message — never str(exc), which could echo response
                # content, matching wrap_request_exception's redaction
                # discipline in providers/base.py.
                raise GenerationError(
                    GenerationErrorCode.unknown,
                    f"{candidate.provider} adapter raised {type(exc).__name__}",
                ) from exc

        try:
            generated = run_with_retry(
                attempt,
                on_attempt=lambda number: jobs_service.record_attempt(
                    session,
                    job,
                    attempt=number,
                    provider=candidate.provider,
                    model=candidate.model_id,
                ),
            )
        except GenerationError as error:
            last_error = error
            logger.warning(
                f"generation job {job.id} failed on "
                f"{candidate.provider}/{candidate.model_id}: {error.code.value}"
            )
            continue

        if not jobs_service.is_still_running(session, job.id):
            # The job was already settled (timeout) while the provider was
            # still working. Drop the late result instead of resurrecting it.
            logger.warning(
                f"discarding late result for generation job {job.id} "
                f"(status is no longer running)"
            )
            return None

        try:
            uploaded = upload_bytes(
                tenant_id=job.tenant_id,
                path_prefix=str(job.content_piece_id),
                filename=generated.filename,
                data=generated.data,
                content_type=generated.mime_type,
            )
        except StorageError as error:
            jobs_service.mark_failed(
                session,
                job,
                error_code=GenerationErrorCode.unknown.value,
                error_message=str(error),
            )
            return None

        units = generated.output_units or generated.input_units
        estimated, currency = estimate_cost(
            candidate.provider, candidate.model_id, units=units
        )

        jobs_service.mark_completed(
            session,
            job,
            provider=candidate.provider,
            model=candidate.model_id,
            response_metadata=generated.raw_metadata,
            input_units=generated.input_units,
            output_units=generated.output_units,
            estimated_cost=estimated,
            actual_cost=generated.actual_cost,
            currency=generated.currency or currency,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

        width, height = generated.width, generated.height
        if asset_type == ContentAssetType.image and (width is None or height is None):
            width, height = _probe_image_dimensions(generated.data)

        asset = assets_service.create_asset(
            session,
            job=job,
            asset_type=asset_type,
            uploaded=uploaded,
            provider=candidate.provider,
            model=candidate.model_id,
            mime_type=generated.mime_type,
            width=width,
            height=height,
            duration=generated.duration,
            is_intermediate=is_intermediate,
        )
        logger.info(
            f"generation job {job.id} completed on "
            f"{candidate.provider}/{candidate.model_id}, asset={asset.id}"
        )
        return asset

    jobs_service.mark_failed(
        session,
        job,
        error_code=(last_error.code.value if last_error else GenerationErrorCode.unknown.value),
        error_message=(
            last_error.message if last_error else "all provider candidates failed"
        ),
        status=(
            GenerationJobStatus.timeout
            if last_error and last_error.code == GenerationErrorCode.timeout
            else GenerationJobStatus.failed
        ),
    )
    return None
