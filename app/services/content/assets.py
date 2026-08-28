from typing import List, Optional

from sqlmodel import Session, select

from app.models.content_generation import (
    ContentAsset,
    ContentAssetType,
    ContentGenerationJob,
)
from app.services.content.storage import UploadedObject


def create_asset(
    session: Session,
    *,
    job: ContentGenerationJob,
    asset_type: ContentAssetType,
    uploaded: UploadedObject,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    mime_type: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration: Optional[float] = None,
    is_intermediate: bool = False,
) -> ContentAsset:
    asset = ContentAsset(
        tenant_id=job.tenant_id,
        client_id=job.client_id,
        content_piece_id=job.content_piece_id,
        generation_job_id=job.id,
        type=asset_type,
        url=uploaded.url,
        storage_path=uploaded.storage_path,
        mime_type=mime_type,
        size_bytes=uploaded.size_bytes,
        width=width or None,
        height=height or None,
        duration=duration,
        provider=provider,
        model=model,
        is_intermediate=is_intermediate,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def list_assets_for_piece(
    session: Session, *, content_piece_id: int
) -> List[ContentAsset]:
    return list(
        session.exec(
            select(ContentAsset)
            .where(ContentAsset.content_piece_id == content_piece_id)
            .order_by(ContentAsset.id)
        ).all()
    )
