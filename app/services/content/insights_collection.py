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

from app.services.content import retry
from app.services.content.publish_errors import PublicationError, is_retryable
from app.services.content.publishers.base import InsightsResult

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
