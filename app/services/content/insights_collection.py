"""Pass 4 of automation_scheduler: post-publish engagement collection.

See docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md.

due_for_collection is the only scheduling logic and it is pure: nothing but
content_publication_insights' own snapshots is persisted to decide when to
recollect — the decision is always derived from completed_at and the most
recently recorded collected_at.
"""
from datetime import datetime, timedelta
from typing import Optional

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
