from datetime import datetime
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from app.models.content import ContentCampaign, ContentClient, ContentPiece, ContentSocialAccount
from app.models.content_generation import ContentAsset
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content.assets import list_assets_for_piece
from app.services.content.publish_errors import PublicationError
from app.services.content.publishers.base import get_adapter


def get_final_asset(session: Session, *, content_piece_id: int) -> Optional[ContentAsset]:
    assets = list_assets_for_piece(session, content_piece_id=content_piece_id)
    return next((asset for asset in assets if not asset.is_intermediate), None)


def get_social_account_for_piece(
    session: Session, *, piece: ContentPiece, social_account_id: int
) -> Optional[ContentSocialAccount]:
    campaign = session.get(ContentCampaign, piece.campaign_id)
    if campaign is None:
        return None
    return session.exec(
        select(ContentSocialAccount).where(
            ContentSocialAccount.id == social_account_id,
            ContentSocialAccount.client_id == campaign.client_id,
            ContentSocialAccount.status == "active",
        )
    ).first()


def get_publication_for_pair(
    session: Session, *, content_piece_id: int, social_account_id: int
) -> Optional[ContentSocialPublication]:
    return session.exec(
        select(ContentSocialPublication).where(
            ContentSocialPublication.content_piece_id == content_piece_id,
            ContentSocialPublication.social_account_id == social_account_id,
        )
    ).first()


def list_publications_for_piece(
    session: Session, *, content_piece_id: int
) -> List[ContentSocialPublication]:
    return list(
        session.exec(
            select(ContentSocialPublication)
            .where(ContentSocialPublication.content_piece_id == content_piece_id)
            .order_by(ContentSocialPublication.id)
        ).all()
    )


def _tenant_id_for_piece(session: Session, piece: ContentPiece) -> int:
    campaign = session.get(ContentCampaign, piece.campaign_id)
    client = session.get(ContentClient, campaign.client_id)
    return client.tenant_id


def resolve_publication_request(
    session: Session, *, piece: ContentPiece, social_account_ids: List[int]
) -> Tuple[List[ContentSocialPublication], List[dict]]:
    """Resolve one /publish call into accepted rows and rejected reasons.

    Compatibility is checked here, before any row exists — an incompatible
    pair never becomes a doomed job (see spec: "Compatibilidade — fail-fast").
    """
    accepted: List[ContentSocialPublication] = []
    rejected: List[dict] = []
    asset = get_final_asset(session, content_piece_id=piece.id)

    for social_account_id in social_account_ids:
        account = get_social_account_for_piece(
            session, piece=piece, social_account_id=social_account_id
        )
        if account is None:
            rejected.append(
                {
                    "social_account_id": social_account_id,
                    "platform": None,
                    "reason": "account_not_found",
                    "message": "Social account not found, inactive, or belongs to another client",
                }
            )
            continue

        # No adapter's check_compatibility() looks at `asset`, so without this
        # a piece with no final asset would silently produce `queued` rows
        # that can only fail later inside the dispatcher — the opposite of the
        # spec's "Compatibilidade — fail-fast".
        if asset is None:
            rejected.append(
                {
                    "social_account_id": social_account_id,
                    "platform": account.platform,
                    "reason": "unsupported_capability",
                    "message": "Content piece has no final asset to publish",
                }
            )
            continue

        try:
            adapter = get_adapter(account.platform)
            adapter.check_compatibility(piece, asset)
        except PublicationError as error:
            rejected.append(
                {
                    "social_account_id": social_account_id,
                    "platform": account.platform,
                    "reason": error.code.value,
                    "message": error.message,
                }
            )
            continue

        existing = get_publication_for_pair(
            session, content_piece_id=piece.id, social_account_id=social_account_id
        )
        if existing is None:
            row = ContentSocialPublication(
                tenant_id=_tenant_id_for_piece(session, piece),
                client_id=account.client_id,
                content_piece_id=piece.id,
                social_account_id=social_account_id,
                platform=account.platform,
                status=PublicationStatus.queued,
                request_payload={"generation_prompt": piece.generation_prompt},
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            accepted.append(row)
        elif existing.status == PublicationStatus.failed:
            existing.status = PublicationStatus.queued
            existing.attempt_count = 0
            existing.error_code = None
            existing.error_message = None
            existing.next_run_at = None
            existing.publication_cycle += 1
            existing.updated_at = datetime.utcnow()
            session.add(existing)
            session.commit()
            session.refresh(existing)
            accepted.append(existing)
        else:
            accepted.append(existing)

    return accepted, rejected
