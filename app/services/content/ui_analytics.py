"""Aggregates for the analytics dashboard.

Everything here is computed from tables that already exist. Two of the
reference product's six headline numbers — link clicks and engagement — are
deliberately absent rather than faked: both need post-publish telemetry that
this system has never collected (no shortener, no platform insights worker).
They are returned as null so the UI can render them as "not collected yet"
instead of quietly dropping them from the grid.

Two substitutions the reference cannot make, because it does not generate the
media it publishes: generation cost (real money, from ContentGenerationJob)
and the auto-approval rate (how much of the pipeline runs without a human).
"""
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Session, func, select

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
    resolved = len(succeeded) + len(failed)

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

    tiles = AnalyticsTiles(
        published=len(succeeded),
        scheduled=int(scheduled or 0),
        failed=len(failed),
        success_rate=round(len(succeeded) / resolved, 4) if resolved else None,
        # Not collected yet — see the module docstring.
        link_clicks=None,
        engagement=None,
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
