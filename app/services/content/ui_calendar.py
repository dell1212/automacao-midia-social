from datetime import datetime
from typing import List, Optional, Sequence

from sqlmodel import Session, func, or_, select

from app.models.content import (
    ContentCampaign,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentSocialAccount,
)
from app.models.content_calendar import (
    CalendarFilterOption,
    CalendarFiltersResponse,
    CalendarItemRead,
    CalendarPlatformRead,
    CalendarRangeRead,
    CalendarResponse,
    CalendarState,
)
from app.models.content_generation import ContentAsset
from app.models.content_publishing import ContentSocialPublication
from app.services.content import storage
from app.services.content.ui_pieces import _resolve_signed_url

_TITLE_MAX = 80

# Publishing has started for the piece; the schedule no longer decides when it
# goes out, so the calendar shows it as locked.
_LOCKED_STATES = (CalendarState.publishing, CalendarState.published, CalendarState.failed)


def derive_calendar_state(
    *,
    status: ContentPieceStatus,
    scheduled_for: Optional[datetime],
    publication_summary: Optional[dict],
    has_publications: bool,
) -> CalendarState:
    """Map the stored state machine onto the five states a calendar shows.

    The single place this mapping happens — calendar, composer and analytics
    all read it from here, so the vocabularies can never drift apart.
    """
    summary = publication_summary or {}
    succeeded = int(summary.get("succeeded") or 0)
    failed = int(summary.get("failed") or 0)
    pending = int(summary.get("pending") or 0)

    # A piece that failed generation never reaches publishing at all.
    if status == ContentPieceStatus.failed:
        return CalendarState.failed

    if has_publications:
        if pending > 0:
            return CalendarState.publishing
        # Every attempt resolved. Anything that landed on at least one platform
        # reads as published; only a clean sweep of failures is a failure —
        # otherwise a piece live on two networks would show up red because the
        # third rejected it.
        if succeeded > 0:
            return CalendarState.published
        if failed > 0:
            return CalendarState.failed
        return CalendarState.publishing

    if status == ContentPieceStatus.posted:
        return CalendarState.published
    if scheduled_for is not None and status == ContentPieceStatus.approved:
        return CalendarState.scheduled
    return CalendarState.draft


def _title_for(piece: ContentPiece) -> str:
    source = (piece.generation_prompt or piece.narration_script or "").strip()
    if not source:
        return f"Peça #{piece.id}"
    if len(source) <= _TITLE_MAX:
        return source
    return source[: _TITLE_MAX - 1].rstrip() + "…"


def _platforms_from_summary(summary: Optional[dict]) -> List[CalendarPlatformRead]:
    platforms = (summary or {}).get("platforms") or {}
    if not isinstance(platforms, dict):
        return []
    return [
        CalendarPlatformRead(
            platform=str(name),
            succeeded=int((counts or {}).get("succeeded") or 0),
            failed=int((counts or {}).get("failed") or 0),
        )
        for name, counts in sorted(platforms.items())
    ]


def _thumbnail_map(session: Session, piece_ids: Sequence[int]) -> dict[int, str]:
    """One signed URL per piece, for the smallest renderable asset it has.

    Signed in bulk here rather than per card, and failures drop the thumbnail
    instead of the row — the same tolerance get_piece_detail applies.
    """
    if not piece_ids:
        return {}
    rows = session.exec(
        select(ContentAsset)
        .where(
            ContentAsset.content_piece_id.in_(list(piece_ids)),
            ContentAsset.is_intermediate == False,  # noqa: E712
        )
        .order_by(ContentAsset.content_piece_id, ContentAsset.id)
    ).all()

    thumbs: dict[int, str] = {}
    for asset in rows:
        if asset.content_piece_id in thumbs:
            continue
        signed = _resolve_signed_url(storage_path=asset.storage_path, url=asset.url)
        if signed is not None:
            thumbs[asset.content_piece_id] = signed
    return thumbs


def _base_statement(*, tenant_id: int, date_from: datetime, date_to: datetime):
    """Pieces whose position on the calendar falls inside the range.

    A piece is placed by `scheduled_for`, or by `posted_at` when it went out
    without ever having been scheduled (a manual publish) — without the second
    arm those pieces would be invisible on the calendar even though they were
    published.
    """
    return (
        select(ContentPiece, ContentCampaign, ContentClient)
        .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(
            ContentClient.tenant_id == tenant_id,
            or_(
                ContentPiece.scheduled_for.between(date_from, date_to),
                (ContentPiece.scheduled_for == None)  # noqa: E711
                & ContentPiece.posted_at.between(date_from, date_to),
            ),
        )
    )


def get_calendar(
    session: Session,
    *,
    tenant_id: int,
    date_from: datetime,
    date_to: datetime,
    client_id: Optional[int] = None,
    campaign_ids: Optional[List[int]] = None,
    states: Optional[List[CalendarState]] = None,
) -> CalendarResponse:
    statement = _base_statement(
        tenant_id=tenant_id, date_from=date_from, date_to=date_to
    )
    if client_id is not None:
        statement = statement.where(ContentClient.id == client_id)
    if campaign_ids:
        statement = statement.where(ContentPiece.campaign_id.in_(campaign_ids))

    rows = session.exec(statement.order_by(ContentPiece.scheduled_for)).all()

    piece_ids = [row[0].id for row in rows]
    published_ids = set(
        session.exec(
            select(ContentSocialPublication.content_piece_id)
            .where(ContentSocialPublication.content_piece_id.in_(piece_ids))
            .distinct()
        ).all()
    ) if piece_ids else set()

    thumbs = _thumbnail_map(session, piece_ids)

    items: List[CalendarItemRead] = []
    for piece, campaign, client in rows:
        state = derive_calendar_state(
            status=piece.status,
            scheduled_for=piece.scheduled_for,
            publication_summary=piece.publication_summary,
            has_publications=piece.id in published_ids,
        )
        items.append(
            CalendarItemRead(
                id=piece.id,
                campaign_id=piece.campaign_id,
                campaign_name=campaign.name,
                client_id=client.id,
                client_name=client.name,
                type=piece.type,
                status=piece.status,
                calendar_state=state,
                scheduled_for=piece.scheduled_for,
                posted_at=piece.posted_at,
                title=_title_for(piece),
                thumbnail_url=thumbs.get(piece.id),
                platforms=_platforms_from_summary(piece.publication_summary),
                is_locked=piece.id in published_ids,
            )
        )

    # Counted from the same unfiltered-by-status set the items came from, so a
    # pill always answers "how many would this filter show".
    counts: dict[str, int] = {"all": len(items)}
    for state in CalendarState:
        counts[state.value] = sum(1 for item in items if item.calendar_state == state)

    # Filtering on calendar_state, not status: the pills above are labelled and
    # counted by calendar state, so filtering by the stored status would make a
    # pill's count and its result disagree.
    if states:
        wanted = set(states)
        items = [item for item in items if item.calendar_state in wanted]

    return CalendarResponse(
        range=CalendarRangeRead(date_from=date_from, date_to=date_to),
        counts=counts,
        items=items,
    )


def get_filters(session: Session, *, tenant_id: int) -> CalendarFiltersResponse:
    """Everything the calendar toolbar needs, in one round trip instead of the
    four separate list calls the header would otherwise fire."""
    clients = session.exec(
        select(ContentClient)
        .where(
            ContentClient.tenant_id == tenant_id,
            ContentClient.is_active == True,  # noqa: E712
        )
        .order_by(ContentClient.name)
    ).all()

    campaigns = session.exec(
        select(ContentCampaign)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(ContentClient.tenant_id == tenant_id, ContentCampaign.status != "archived")
        .order_by(ContentCampaign.name)
    ).all()

    accounts = session.exec(
        select(ContentSocialAccount)
        .join(ContentClient, ContentClient.id == ContentSocialAccount.client_id)
        .where(ContentClient.tenant_id == tenant_id, ContentSocialAccount.status != "revoked")
        .order_by(ContentSocialAccount.platform)
    ).all()

    return CalendarFiltersResponse(
        clients=[CalendarFilterOption(id=str(c.id), label=c.name) for c in clients],
        campaigns=[CalendarFilterOption(id=str(c.id), label=c.name) for c in campaigns],
        platforms=[
            CalendarFilterOption(id=p, label=p)
            for p in sorted({a.platform for a in accounts})
        ],
        accounts=[
            CalendarFilterOption(
                id=str(a.id), label=f"{a.platform} · {a.external_account_id}"
            )
            for a in accounts
        ],
    )
