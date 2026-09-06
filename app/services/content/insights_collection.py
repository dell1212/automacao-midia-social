"""Pass 4 of automation_scheduler: post-publish engagement collection.

See docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md.

due_for_collection is the only scheduling logic and it is pure: nothing but
content_publication_insights' own snapshots is persisted to decide when to
recollect — the decision is always derived from completed_at and the most
recently recorded collected_at.

retry.run_with_retry does not work here: it is hard-coded to GenerationError
(the media-generation taxonomy in app/services/content/errors.py), not
PublicationError (the publish taxonomy this pass uses).
_fetch_insights_with_retry reimplements the same backoff shape, reusing the
pure retry.backoff_delay function and the publish taxonomy's own
is_retryable.
"""
import time
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import desc
from sqlmodel import Session, select

from app.models.content import ContentSocialAccount
from app.models.content_insights import ContentPublicationInsight
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content import retry
from app.services.content.publish_errors import (
    PublicationError,
    PublicationErrorCode,
    is_retryable,
)
from app.services.content.publishers.base import InsightsResult
from app.services.content.publishers.base import get_adapter, load_credentials

# Decreasing cadence: almost all engagement happens in the first few days.
# Each tuple is (end of window, interval within it), checked in order — the
# first window the post's age fits decides the interval.
INSIGHTS_WINDOW_DAYS = 14

_CADENCE = (
    (timedelta(hours=48), timedelta(hours=6)),
    (timedelta(days=7), timedelta(hours=24)),
    (timedelta(days=INSIGHTS_WINDOW_DAYS), timedelta(hours=72)),
)


def due_for_collection(
    *,
    completed_at: datetime,
    last_collected_at: Optional[datetime],
    now: datetime,
) -> bool:
    """Whether a publication should be recollected right now.

    completed_at is when the post went live; last_collected_at is the last
    time a collection (success or error) was attempted, or None if never.
    """
    age = now - completed_at
    interval = None
    for window, band_interval in _CADENCE:
        if age <= window:
            interval = band_interval
            break
    if interval is None:
        return False
    if last_collected_at is None:
        return True
    return now - last_collected_at >= interval


def _fetch_insights_with_retry(adapter, publication, account, credentials) -> InsightsResult:
    """Retries only failures that depend on the moment (rate_limit/transient),
    within this tick. Once attempts run out, or facing a non-retryable
    failure, it propagates — the caller records the error snapshot."""
    last_error: Optional[PublicationError] = None
    for attempt in range(1, retry.MAX_ATTEMPTS + 1):
        try:
            return adapter.fetch_insights(publication, account, credentials)
        except PublicationError as error:
            last_error = error
            if not is_retryable(error.code) or attempt == retry.MAX_ATTEMPTS:
                raise
            time.sleep(retry.backoff_delay(attempt))
    raise last_error


def collect_publication_insights(session: Session, *, batch_limit: int) -> None:
    """Pass 4: recollects engagement for successful publications from the
    last 14 days, respecting due_for_collection's cadence.

    Same shape as the other three passes: one query for the eligible rows,
    each item isolated in its own try/except Exception (one bad item can't
    sink the whole pass), commit per item. The one thing specific to this
    pass: a PublicationError from the collection itself is caught separately
    and turned into a recorded error snapshot — that is the expected,
    designed failure mode (see the design spec's Degradação section), not a
    bug to swallow into the generic catch-all.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=INSIGHTS_WINDOW_DAYS)
    publications = session.exec(
        select(ContentSocialPublication)
        .where(
            ContentSocialPublication.status == PublicationStatus.succeeded,
            ContentSocialPublication.platform_post_id.is_not(None),
            ContentSocialPublication.completed_at.is_not(None),
            ContentSocialPublication.completed_at >= cutoff,
        )
        .order_by(ContentSocialPublication.id)
    ).all()

    attempted = 0
    for publication in publications:
        try:
            adapter = get_adapter(publication.platform)
            if not adapter.supports_insights:
                continue

            latest = session.exec(
                select(ContentPublicationInsight)
                .where(
                    ContentPublicationInsight.publication_id == publication.id
                )
                .order_by(desc(ContentPublicationInsight.collected_at))
                .limit(1)
            ).first()
            if latest is not None and latest.error_code in (
                PublicationErrorCode.invalid_credentials.value,
                PublicationErrorCode.invalid_params.value,
            ):
                # Terminal failure: a permission gap or a deleted post does
                # not self-heal, so stop retrying this publication for good.
                continue
            if not due_for_collection(
                completed_at=publication.completed_at,
                last_collected_at=latest.collected_at if latest else None,
                now=now,
            ):
                continue

            account = session.get(ContentSocialAccount, publication.social_account_id)
            if account is None:
                continue
            credentials = load_credentials(account)

            if attempted >= batch_limit:
                break

            try:
                attempted += 1
                result = _fetch_insights_with_retry(
                    adapter, publication, account, credentials
                )
            except PublicationError as error:
                session.add(
                    ContentPublicationInsight(
                        tenant_id=publication.tenant_id,
                        client_id=publication.client_id,
                        content_piece_id=publication.content_piece_id,
                        publication_id=publication.id,
                        social_account_id=publication.social_account_id,
                        platform=publication.platform,
                        publication_cycle=publication.publication_cycle,
                        collected_at=now,
                        error_code=error.code.value,
                        error_message=error.message,
                    )
                )
                session.commit()
                continue
            except Exception as exc:
                # Not a designed PublicationError — an adapter bug (raw dict/
                # list indexing on a malformed API response, typically) that
                # would otherwise escape to the outer except and leave no
                # row, keeping due_for_collection True forever. error_code
                # deliberately doesn't match any PublicationErrorCode, so it
                # falls back to the normal cadence instead of being retried
                # every tick or treated as terminal.
                session.add(
                    ContentPublicationInsight(
                        tenant_id=publication.tenant_id,
                        client_id=publication.client_id,
                        content_piece_id=publication.content_piece_id,
                        publication_id=publication.id,
                        social_account_id=publication.social_account_id,
                        platform=publication.platform,
                        publication_cycle=publication.publication_cycle,
                        collected_at=now,
                        error_code="unexpected",
                        error_message=str(exc),
                    )
                )
                session.commit()
                continue

            session.add(
                ContentPublicationInsight(
                    tenant_id=publication.tenant_id,
                    client_id=publication.client_id,
                    content_piece_id=publication.content_piece_id,
                    publication_id=publication.id,
                    social_account_id=publication.social_account_id,
                    platform=publication.platform,
                    publication_cycle=publication.publication_cycle,
                    collected_at=now,
                    reach=result.reach,
                    impressions=result.impressions,
                    likes=result.likes,
                    comments=result.comments,
                    shares=result.shares,
                    raw=result.raw,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            logger.exception(
                f"publication {getattr(publication, 'id', None)}: insights collection failed"
            )
            continue
