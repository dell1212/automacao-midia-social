import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import requests
from loguru import logger
from sqlmodel import Session

from app.db import get_engine
from app.models.content import (
    ContentCampaign,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentPieceType,
)
from app.models.content_generation import (
    ContentAsset,
    ContentAssetType,
    ContentGenerationJob,
    GenerationKind,
)
from app.services.content import assets as assets_service
from app.services.content import audit
from app.services.content import avatars as avatars_service
from app.services.content import jobs as jobs_service
from app.services.content import orchestrator
from app.services.content.capability import GenerationMode, GenerationRequirements
from app.services.content.composition import mux_narration
from app.services.content.image_ops import normalize_to_ratio
from app.services.content.storage import StorageError, upload_bytes

# Image and voice calls return in seconds; video polling parks a thread for
# minutes. Separate pools keep a burst of video work from starving everything
# else, mirroring how _cross_post_executor is bounded in app/services/task.py.
# A piece runs entirely inside the pool matching its type — never split across
# pools, or the fast thread would just block waiting on the video one.
_FAST_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.environ.get("CONTENT_FAST_WORKERS", 4)),
    thread_name_prefix="mpt-content-fast",
)
_VIDEO_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.environ.get("CONTENT_VIDEO_WORKERS", 2)),
    thread_name_prefix="mpt-content-video",
)
_PENDING_SLOTS = threading.BoundedSemaphore(
    int(os.environ.get("CONTENT_MAX_PENDING_PIECES", 20))
)

KIND_TIMEOUT_SECONDS: dict[GenerationKind, int] = {
    GenerationKind.image: 60,
    GenerationKind.voice: 60,
    GenerationKind.video: 600,
}

_FETCH_TIMEOUT = (30, 120)


def schedule_piece(
    piece_id: int,
    *,
    piece_type: ContentPieceType,
    aspect_ratio: str = "9:16",
    resolution: Optional[str] = None,
    duration: Optional[int] = None,
) -> bool:
    """Queue a piece's generation graph. False when the queue is saturated.

    A saturated queue is not an error: the piece stays in `generating` and the
    caller's request still succeeds, which is why the semaphore is acquired
    without blocking.
    """
    if not _PENDING_SLOTS.acquire(blocking=False):
        logger.warning(
            f"content generation queue is full; piece {piece_id} stays queued"
        )
        return False

    def runner():
        try:
            _run_piece(
                piece_id,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration=duration,
            )
        finally:
            _PENDING_SLOTS.release()

    executor = (
        _VIDEO_EXECUTOR if piece_type == ContentPieceType.video else _FAST_EXECUTOR
    )
    executor.submit(runner)
    return True


def _run_piece(
    piece_id: int,
    *,
    aspect_ratio: str,
    resolution: Optional[str],
    duration: Optional[int],
) -> None:
    """Own one piece from queued to settled, in a single thread and session."""
    with Session(get_engine()) as session:
        piece = session.get(ContentPiece, piece_id)
        if piece is None:
            logger.error(f"generation pipeline: piece {piece_id} not found")
            return

        campaign = session.get(ContentCampaign, piece.campaign_id)
        client = session.get(ContentClient, campaign.client_id) if campaign else None
        if client is None:
            logger.error(
                f"generation pipeline: could not resolve tenant for piece {piece_id}"
            )
            return

        tenant_id = client.tenant_id
        client_id = client.id

        try:
            if piece.type == ContentPieceType.image:
                asset_url = _run_image_piece(
                    session,
                    piece,
                    tenant_id=tenant_id,
                    client_id=client_id,
                    aspect_ratio=aspect_ratio,
                )
            elif piece.type == ContentPieceType.audio:
                asset_url = _run_audio_piece(
                    session, piece, tenant_id=tenant_id, client_id=client_id
                )
            else:
                asset_url = _run_video_piece(
                    session,
                    piece,
                    tenant_id=tenant_id,
                    client_id=client_id,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    duration=duration,
                )
        except Exception as exc:  # noqa: BLE001 - a piece must never stay stuck
            logger.exception(f"generation pipeline crashed for piece {piece_id}: {exc}")
            asset_url = None

        _finalize(session, piece, asset_url=asset_url, tenant_id=tenant_id)


def _finalize(
    session: Session,
    piece: ContentPiece,
    *,
    asset_url: Optional[str],
    tenant_id: int,
) -> None:
    piece.status = (
        ContentPieceStatus.pending_approval if asset_url else ContentPieceStatus.failed
    )
    piece.asset_url = asset_url
    piece.updated_at = datetime.utcnow()
    session.add(piece)
    session.commit()

    audit.write_audit_log(
        session,
        tenant_id=tenant_id,
        entity_type="content_piece",
        entity_id=piece.id,
        action="generated" if asset_url else "generation_failed",
        actor="system:generation",
    )


def _run_image_piece(
    session: Session,
    piece: ContentPiece,
    *,
    tenant_id: int,
    client_id: int,
    aspect_ratio: str,
) -> Optional[str]:
    if piece.avatar_id and not piece.generation_prompt:
        # Reusing the avatar's own image: no provider call, no job, no cost.
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant_id, avatar_id=piece.avatar_id
        )
        return avatar.reference_image_url if avatar else None

    params = {"prompt": piece.generation_prompt, "aspect_ratio": aspect_ratio}
    job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.image,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=job,
        requirements=GenerationRequirements(
            kind=GenerationKind.image.value,
            mode=GenerationMode.text_to_image,
            aspect_ratio=aspect_ratio,
        ),
        params=params,
        asset_type=ContentAssetType.image,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.image],
    )
    return asset.url if asset else None


def _run_audio_piece(
    session: Session, piece: ContentPiece, *, tenant_id: int, client_id: int
) -> Optional[str]:
    voice_id = _resolve_voice_id(session, piece, tenant_id=tenant_id)
    params = {"text": piece.generation_prompt, "voice_id": voice_id}
    job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.voice,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=job,
        requirements=GenerationRequirements(
            kind=GenerationKind.voice.value, mode=GenerationMode.voice
        ),
        params=params,
        asset_type=ContentAssetType.audio,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.voice],
    )
    return asset.url if asset else None


def _run_video_piece(
    session: Session,
    piece: ContentPiece,
    *,
    tenant_id: int,
    client_id: int,
    aspect_ratio: str,
    resolution: Optional[str],
    duration: Optional[int],
) -> Optional[str]:
    base_image_url = _resolve_base_image(
        session,
        piece,
        tenant_id=tenant_id,
        client_id=client_id,
        aspect_ratio=aspect_ratio,
    )
    if base_image_url:
        base_image_url = _normalized_base_image(
            piece,
            tenant_id=tenant_id,
            base_image_url=base_image_url,
            aspect_ratio=aspect_ratio,
        )

    narration_asset = None
    voice_id = _resolve_voice_id(session, piece, tenant_id=tenant_id)
    if voice_id:
        voice_params = {"text": piece.generation_prompt, "voice_id": voice_id}
        voice_job = jobs_service.create_job(
            session,
            tenant_id=tenant_id,
            client_id=client_id,
            content_piece_id=piece.id,
            kind=GenerationKind.voice,
            request_payload=voice_params,
        )
        narration_asset = orchestrator.run_job(
            session,
            job=voice_job,
            requirements=GenerationRequirements(
                kind=GenerationKind.voice.value, mode=GenerationMode.voice
            ),
            params=voice_params,
            asset_type=ContentAssetType.audio,
            timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.voice],
            is_intermediate=True,
        )

    mode = (
        GenerationMode.image_to_video if base_image_url else GenerationMode.text_to_video
    )
    params: dict = {"prompt": piece.generation_prompt, "aspect_ratio": aspect_ratio}
    if duration:
        params["duration"] = duration
    if base_image_url:
        params["source_image_url"] = base_image_url

    video_job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.video,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=video_job,
        requirements=GenerationRequirements(
            kind=GenerationKind.video.value,
            mode=mode,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration=duration,
            needs_reference_image=bool(base_image_url),
        ),
        params=params,
        asset_type=ContentAssetType.video,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.video],
        # The raw provider video is intermediate whenever narration will be
        # muxed on top of it; the composed file becomes the piece's asset.
        is_intermediate=narration_asset is not None,
    )
    if asset is None:
        return None
    if narration_asset is None:
        return asset.url

    composed_url = _compose_with_narration(
        session,
        piece,
        tenant_id=tenant_id,
        video_job=video_job,
        asset=asset,
        narration_url=narration_asset.url,
    )
    if composed_url is None:
        # Composition failed: ship the silent video rather than the whole
        # piece. Undo the intermediate flag so the piece still points at a
        # non-intermediate asset.
        asset.is_intermediate = False
        session.add(asset)
        session.commit()
        return asset.url
    return composed_url


def _resolve_base_image(
    session: Session,
    piece: ContentPiece,
    *,
    tenant_id: int,
    client_id: int,
    aspect_ratio: str,
) -> Optional[str]:
    """Pick the image the video will animate, in the spec's precedence order.

    avatar -> source image piece -> newly generated image. Returns None when
    none applies, which makes the video a text-to-video generation.
    """
    if piece.avatar_id:
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant_id, avatar_id=piece.avatar_id
        )
        if avatar is not None:
            return avatar.reference_image_url

    if piece.source_image_piece_id:
        for asset in assets_service.list_assets_for_piece(
            session, content_piece_id=piece.source_image_piece_id
        ):
            if asset.type == ContentAssetType.image and not asset.is_intermediate:
                return asset.url

    params = {"prompt": piece.generation_prompt, "aspect_ratio": aspect_ratio}
    job = jobs_service.create_job(
        session,
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=piece.id,
        kind=GenerationKind.image,
        request_payload=params,
    )
    asset = orchestrator.run_job(
        session,
        job=job,
        requirements=GenerationRequirements(
            kind=GenerationKind.image.value,
            mode=GenerationMode.text_to_image,
            aspect_ratio=aspect_ratio,
        ),
        params=params,
        asset_type=ContentAssetType.image,
        timeout_seconds=KIND_TIMEOUT_SECONDS[GenerationKind.image],
        is_intermediate=True,
    )
    return asset.url if asset else None


def _normalized_base_image(
    piece: ContentPiece,
    *,
    tenant_id: int,
    base_image_url: str,
    aspect_ratio: str,
) -> str:
    """Crop/pad the base image to the video's ratio and re-upload it.

    An avatar's reference image is registered once and reused across output
    formats, so a square portrait feeding a 9:16 video is the common case.
    The normalized file is what the provider actually receives, so it is
    persisted rather than discarded. Any failure here degrades to the original
    URL: a slightly off-ratio frame beats failing the whole piece.
    """
    try:
        response = requests.get(base_image_url, timeout=_FETCH_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - normalization is best-effort
        logger.warning(f"could not fetch base image for normalization: {exc}")
        return base_image_url

    original = response.content
    data, width, _height = normalize_to_ratio(original, aspect_ratio)
    if data is original or not width:
        # Ratio already matched (or was unparseable): nothing to upload.
        return base_image_url

    try:
        uploaded = upload_bytes(
            tenant_id=tenant_id,
            path_prefix=str(piece.id),
            filename="base-normalized.png",
            data=data,
            content_type="image/png",
        )
    except StorageError as exc:
        logger.warning(f"could not upload normalized base image: {exc}")
        return base_image_url

    return uploaded.url


def _compose_with_narration(
    session: Session,
    piece: ContentPiece,
    *,
    tenant_id: int,
    video_job: ContentGenerationJob,
    asset: ContentAsset,
    narration_url: str,
) -> Optional[str]:
    """Mux the narration onto the generated video, upload, and register it.

    Registered against the raw video's job so the composed file — the
    piece's final, non-intermediate asset — has a content_assets row like
    every other generated output, instead of being a bare storage URL the
    registry has never heard of.
    """
    try:
        video_response = requests.get(asset.url, timeout=_FETCH_TIMEOUT)
        video_response.raise_for_status()
        audio_response = requests.get(narration_url, timeout=_FETCH_TIMEOUT)
        audio_response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - composition is best-effort
        logger.warning(f"could not fetch assets for composition: {exc}")
        return None

    composed = mux_narration(video_response.content, audio_response.content)
    if composed is None:
        return None

    try:
        composed_upload = upload_bytes(
            tenant_id=tenant_id,
            path_prefix=str(piece.id),
            filename="composed.mp4",
            data=composed,
            content_type="video/mp4",
        )
    except StorageError as exc:
        logger.warning(f"could not upload composed video: {exc}")
        return None

    composed_asset = assets_service.create_asset(
        session,
        job=video_job,
        asset_type=ContentAssetType.video,
        uploaded=composed_upload,
        provider=asset.provider,
        model=asset.model,
        mime_type="video/mp4",
        is_intermediate=False,
    )
    logger.info(f"composed narration into video for piece {piece.id}")
    return composed_asset.url


def _resolve_voice_id(
    session: Session, piece: ContentPiece, *, tenant_id: int
) -> Optional[str]:
    """Explicit voice wins over the avatar's, so a piece can override it."""
    if piece.voice_id:
        return piece.voice_id
    if piece.avatar_id:
        avatar = avatars_service.get_avatar(
            session, tenant_id=tenant_id, avatar_id=piece.avatar_id
        )
        if avatar is not None:
            return avatar.voice_id
    return None
