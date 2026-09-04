"""Which accounts a piece publishes to.

The rule that keeps this additive: **no target rows means every active account
of the client**, which is exactly what the scheduler did before targeting
existed. Setting targets narrows; clearing them restores the old behaviour.
"""
from typing import List

from sqlmodel import Session, select

from app.models.content import (
    ContentCampaign,
    ContentPiece,
    ContentPieceTarget,
    ContentSocialAccount,
)


def list_targets(session: Session, *, content_piece_id: int) -> List[ContentPieceTarget]:
    return list(
        session.exec(
            select(ContentPieceTarget)
            .where(ContentPieceTarget.content_piece_id == content_piece_id)
            .order_by(ContentPieceTarget.social_account_id)
        ).all()
    )


def list_available_accounts(
    session: Session, *, piece: ContentPiece
) -> List[ContentSocialAccount]:
    """Every active account the piece's client could publish to."""
    campaign = session.get(ContentCampaign, piece.campaign_id)
    if campaign is None:
        return []
    return list(
        session.exec(
            select(ContentSocialAccount)
            .where(
                ContentSocialAccount.client_id == campaign.client_id,
                ContentSocialAccount.status == "active",
            )
            .order_by(ContentSocialAccount.platform)
        ).all()
    )


def resolve_target_accounts(
    session: Session, *, piece: ContentPiece
) -> List[ContentSocialAccount]:
    """The accounts this piece should actually go to.

    Target rows when they exist, otherwise every active account — the single
    place that fallback is decided, shared by the scheduler and the UI so the
    composer's channel list cannot disagree with what publishes.
    """
    available = list_available_accounts(session, piece=piece)
    targets = list_targets(session, content_piece_id=piece.id)
    if not targets:
        return available
    wanted = {target.social_account_id for target in targets}
    return [account for account in available if account.id in wanted]


def set_targets(
    session: Session, *, piece: ContentPiece, social_account_ids: List[int]
) -> List[ContentPieceTarget]:
    """Replace the piece's targets.

    An empty list clears targeting entirely rather than meaning "publish
    nowhere" — the piece falls back to all active accounts. "Publish nowhere"
    is expressed by not approving the piece, not by an empty target set.
    """
    allowed = {account.id for account in list_available_accounts(session, piece=piece)}
    wanted = {
        account_id for account_id in social_account_ids if account_id in allowed
    }

    for existing in list_targets(session, content_piece_id=piece.id):
        session.delete(existing)

    rows = [
        ContentPieceTarget(content_piece_id=piece.id, social_account_id=account_id)
        for account_id in sorted(wanted)
    ]
    for row in rows:
        session.add(row)
    session.commit()
    return rows
