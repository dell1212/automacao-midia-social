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


def archive_assets_of_type(
    session: Session, *, content_piece_id: int, asset_type: ContentAssetType
) -> List[ContentAsset]:
    """Marks the current non-intermediate asset(s) of this type as
    intermediate — get_piece_detail already filters those out of the UI, so
    this is how a manually-replaced asset stops showing up without deleting
    the old file (keeps it recoverable, matches how pipeline intermediates
    already work).
    """
    assets = list(
        session.exec(
            select(ContentAsset).where(
                ContentAsset.content_piece_id == content_piece_id,
                ContentAsset.type == asset_type,
                ContentAsset.is_intermediate == False,  # noqa: E712
            )
        ).all()
    )
    for asset in assets:
        asset.is_intermediate = True
        session.add(asset)
    session.commit()
    return assets


def create_manual_asset(
    session: Session,
    *,
    tenant_id: int,
    client_id: int,
    content_piece_id: int,
    asset_type: ContentAssetType,
    uploaded: UploadedObject,
    mime_type: Optional[str] = None,
) -> ContentAsset:
    """Like create_asset, but for an admin's manual upload rather than a
    pipeline job — there's no ContentGenerationJob to pull tenant/client ids
    from, so they're passed directly and generation_job_id stays None
    (already nullable on the model).
    """
    asset = ContentAsset(
        tenant_id=tenant_id,
        client_id=client_id,
        content_piece_id=content_piece_id,
        generation_job_id=None,
        type=asset_type,
        url=uploaded.url,
        storage_path=uploaded.storage_path,
        mime_type=mime_type,
        size_bytes=uploaded.size_bytes,
        is_intermediate=False,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
