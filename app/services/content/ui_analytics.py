"""Aggregates for the analytics dashboard.

Everything here is computed from tables that already exist. Link clicks are
still absent rather than faked — they need a URL shortener with a public
redirect route this system does not have (Instagram feed and TikTok have no
clickable link at all, and only Facebook/LinkedIn report clicks even when
one exists), which is a separate decision. Engagement (reach, interactions,
rate) IS collected, by the automation_scheduler's insights_collection pass.

Two substitutions the reference cannot make, because it does not generate the
media it publishes: generation cost (real money, from ContentGenerationJob)
and the auto-approval rate (how much of the pipeline runs without a human).
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Session, func, or_, select

from app.models.content import (
    ApprovalAction,
    ContentCampaign,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentSocialAccount,
)
from app.models.content_analytics import (
    AccountPerformanceRead,
    AnalyticsOverview,
    AnalyticsTiles,
    AnalyticsWindow,
    CadenceBucket,
    PlatformSlice,
    ThroughputBucket,
)
from app.models.content_generation import ContentGenerationJob
from app.models.content_insights import ContentPublicationInsight
from app.models.content_publishing import ContentSocialPublication, PublicationStatus


def _publications_in_range(
    session: Session, *, tenant_id: int, date_from: datetime, date_to: datetime
) -> List[ContentSocialPublication]:
    """ContentSocialPublication carries its own tenant_id, so the publication
    side needs no join chain."""
    return list(
        session.exec(
            select(ContentSocialPublication).where(
                ContentSocialPublication.tenant_id == tenant_id,
                ContentSocialPublication.completed_at != None,  # noqa: E711
                ContentSocialPublication.completed_at.between(date_from, date_to),
            )
        ).all()
    )


@dataclass(frozen=True)
class _EngagementTotals:
    reach: Optional[int]
    interactions: Optional[int]
    engagement_rate: Optional[float]
    reach_substituted_accounts: int


def _pick_latest(
    rows: List[ContentPublicationInsight],
) -> Dict[int, ContentPublicationInsight]:
    """From several rows (publications and timestamps mixed together),
    keeps only the most recently collected one per publication_id — summing
    all of them would count the same like fifteen times."""
    latest: Dict[int, ContentPublicationInsight] = {}
    for row in rows:
        current = latest.get(row.publication_id)
        if current is None or row.collected_at > current.collected_at:
            latest[row.publication_id] = row
    return latest


def _latest_insight_by_publication(
    session: Session, publication_ids: List[int]
) -> Dict[int, ContentPublicationInsight]:
    if not publication_ids:
        return {}
    rows = session.exec(
        select(ContentPublicationInsight).where(
            ContentPublicationInsight.publication_id.in_(publication_ids),
            # A row with every metric null is a recorded failure, not data —
            # ignoring it here is what keeps a broken token from silently
            # zeroing out engagement instead of just not contributing.
            or_(
                ContentPublicationInsight.reach.is_not(None),
                ContentPublicationInsight.impressions.is_not(None),
                ContentPublicationInsight.likes.is_not(None),
                ContentPublicationInsight.comments.is_not(None),
                ContentPublicationInsight.shares.is_not(None),
            ),
        )
    ).all()
    return _pick_latest(rows)


def _engagement_tiles(
    succeeded: List[ContentSocialPublication],
    latest_by_publication: Dict[int, ContentPublicationInsight],
) -> _EngagementTotals:
    reach_total = 0
    reach_present = False
    substituted_accounts: set = set()
    interactions_total = 0
    interactions_present = False

    for publication in succeeded:
        snapshot = latest_by_publication.get(publication.id)
        if snapshot is None:
            continue

        if snapshot.reach is not None:
            reach_total += snapshot.reach
            reach_present = True
        elif snapshot.impressions is not None:
            reach_total += snapshot.impressions
            reach_present = True
            substituted_accounts.add(publication.social_account_id)

        if (
            snapshot.likes is not None
            or snapshot.comments is not None
            or snapshot.shares is not None
        ):
            interactions_total += (
                (snapshot.likes or 0) + (snapshot.comments or 0) + (snapshot.shares or 0)
            )
            interactions_present = True

    return _EngagementTotals(
        reach=reach_total if reach_present else None,
        interactions=interactions_total if interactions_present else None,
        engagement_rate=(
            round(interactions_total / reach_total, 4)
            if reach_present and reach_total and interactions_present
            else None
        ),
        reach_substituted_accounts=len(substituted_accounts),
    )


def get_overview(
    session: Session,
    *,
    tenant_id: int,
    date_from: datetime,
    date_to: datetime,
) -> AnalyticsOverview:
    publications = _publications_in_range(
        session, tenant_id=tenant_id, date_from=date_from, date_to=date_to
    )

    succeeded = [p for p in publications if p.status == PublicationStatus.succeeded]
    failed = [p for p in publications if p.status == PublicationStatus.failed]

    # Forward-looking on purpose, and deliberately NOT bounded by the reporting
    # window: that window is trailing (last N days up to now), and a scheduled
    # piece is by definition in the future, so bounding it here would make this
    # tile permanently read zero.
    scheduled = session.exec(
        select(func.count(ContentPiece.id))
        .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(
            ContentClient.tenant_id == tenant_id,
            ContentPiece.status == ContentPieceStatus.approved,
            ContentPiece.scheduled_for != None,  # noqa: E711
            ContentPiece.scheduled_for >= datetime.utcnow(),
        )
    ).one()

    engagement = _engagement_tiles(
        succeeded,
        _latest_insight_by_publication(
            session, [p.id for p in succeeded if p.id is not None]
        ),
    )
    tiles = AnalyticsTiles(
        published=len(succeeded),
        scheduled=int(scheduled or 0),
        failed=len(failed),
        reach=engagement.reach,
        interactions=engagement.interactions,
        engagement_rate=engagement.engagement_rate,
        reach_substituted_accounts=engagement.reach_substituted_accounts,
    )

    # Time bucketing happens in Python rather than SQL on purpose: date_trunc
    # and extract() are Postgres-specific, and the volumes here are small. It
    # also keeps day/hour boundaries in one place instead of splitting them
    # between the query and the client.
    per_day: Dict[str, Counter] = defaultdict(Counter)
    per_hour: Counter = Counter()
    per_platform: Counter = Counter()
    per_platform_failed: Counter = Counter()
    per_account: Dict[int, Counter] = defaultdict(Counter)

    for publication in publications:
        when = publication.completed_at
        day = when.date().isoformat()
        outcome = (
            "succeeded" if publication.status == PublicationStatus.succeeded else "failed"
        )
        per_day[day][outcome] += 1
        if outcome == "succeeded":
            per_hour[when.hour] += 1
            per_platform[publication.platform] += 1
        else:
            per_platform_failed[publication.platform] += 1
        per_account[publication.social_account_id][outcome] += 1

    throughput = [
        ThroughputBucket(
            day=day,
            published=counts["succeeded"],
            failed=counts["failed"],
            success_rate=(
                round(counts["succeeded"] / (counts["succeeded"] + counts["failed"]), 4)
                if (counts["succeeded"] + counts["failed"])
                else None
            ),
        )
        for day, counts in sorted(per_day.items())
    ]

    platform_mix = [
        PlatformSlice(
            platform=platform,
            published=per_platform.get(platform, 0),
            failed=per_platform_failed.get(platform, 0),
        )
        for platform in sorted(set(per_platform) | set(per_platform_failed))
    ]

    cadence = [
        CadenceBucket(hour=hour, published=per_hour.get(hour, 0)) for hour in range(24)
    ]

    accounts = {
        account.id: account
        for account in session.exec(
            select(ContentSocialAccount)
            .join(ContentClient, ContentClient.id == ContentSocialAccount.client_id)
            .where(ContentClient.tenant_id == tenant_id)
        ).all()
    }
    account_performance = []
    for account_id, counts in per_account.items():
        account = accounts.get(account_id)
        attempted = counts["succeeded"] + counts["failed"]
        account_performance.append(
            AccountPerformanceRead(
                social_account_id=account_id,
                platform=account.platform if account else "unknown",
                label=account.external_account_id if account else f"#{account_id}",
                published=counts["succeeded"],
                failed=counts["failed"],
                success_rate=(
                    round(counts["succeeded"] / attempted, 4) if attempted else None
                ),
            )
        )
    account_performance.sort(key=lambda row: row.published, reverse=True)

    # Generation cost — real money the reference product structurally cannot
    # report, because it does not generate the media it publishes.
    cost_rows = session.exec(
        select(ContentGenerationJob).where(
            ContentGenerationJob.tenant_id == tenant_id,
            ContentGenerationJob.created_at.between(date_from, date_to),
        )
    ).all()
    total_cost = sum(
        (job.actual_cost if job.actual_cost is not None else (job.estimated_cost or 0.0))
        for job in cost_rows
    )
    currency = next((job.currency for job in cost_rows if job.currency), None)

    decided = session.exec(
        select(ContentPiece.approval_action, func.count(ContentPiece.id))
        .join(ContentCampaign, ContentCampaign.id == ContentPiece.campaign_id)
        .join(ContentClient, ContentClient.id == ContentCampaign.client_id)
        .where(
            ContentClient.tenant_id == tenant_id,
            ContentPiece.approval_action != None,  # noqa: E711
            ContentPiece.created_at.between(date_from, date_to),
        )
        .group_by(ContentPiece.approval_action)
    ).all()
    decided_counts = {action: count for action, count in decided}
    auto = decided_counts.get(ApprovalAction.auto_approve, 0)
    total_decided = sum(decided_counts.values())

    window = AnalyticsWindow(
        best_hour=(per_hour.most_common(1)[0][0] if per_hour else None),
        active_accounts=len(
            [a for a in accounts.values() if a.status == "active"]
        ),
        total_pieces=len(
            set(publication.content_piece_id for publication in publications)
        ),
        generation_cost=round(total_cost, 4) if cost_rows else None,
        generation_currency=currency,
        autoapproved_pct=(round(auto / total_decided, 4) if total_decided else None),
    )

    return AnalyticsOverview(
        date_from=date_from,
        date_to=date_to,
        tiles=tiles,
        throughput=throughput,
        platform_mix=platform_mix,
        cadence_by_hour=cadence,
        account_performance=account_performance,
        window=window,
    )
