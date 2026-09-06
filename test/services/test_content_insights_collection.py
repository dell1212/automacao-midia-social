import unittest
from datetime import datetime, timedelta

from app.services.content.insights_collection import due_for_collection


class TestDueForCollection(unittest.TestCase):
    def test_never_collected_within_first_window_is_due(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=1)

        self.assertTrue(
            due_for_collection(completed_at=completed_at, last_collected_at=None, now=now)
        )

    def test_collected_recently_within_six_hour_band_is_not_due(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=10)
        last_collected_at = now - timedelta(minutes=10)

        self.assertFalse(
            due_for_collection(
                completed_at=completed_at, last_collected_at=last_collected_at, now=now
            )
        )

    def test_collected_exactly_one_interval_ago_is_due(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=10)  # inside the 6h band
        last_collected_at = now - timedelta(hours=6)

        self.assertTrue(
            due_for_collection(
                completed_at=completed_at, last_collected_at=last_collected_at, now=now
            )
        )

    def test_at_exactly_48_hours_still_uses_the_six_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=48)

        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=5, minutes=59),
                now=now,
            )
        )
        self.assertTrue(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=6),
                now=now,
            )
        )

    def test_just_past_48_hours_uses_the_24_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(hours=48, minutes=1)

        # Only 6h since the last collection — not due yet in the 24h band.
        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=6),
                now=now,
            )
        )

    def test_at_exactly_7_days_still_uses_the_24_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=7)

        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=23, minutes=59),
                now=now,
            )
        )

    def test_just_past_7_days_uses_the_72_hour_band(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=7, minutes=1)

        # Only 25h since the last collection — not due yet in the 72h band.
        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(hours=25),
                now=now,
            )
        )

    def test_at_exactly_14_days_is_still_eligible(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=14)

        self.assertTrue(
            due_for_collection(completed_at=completed_at, last_collected_at=None, now=now)
        )

    def test_just_past_14_days_is_never_due_again(self):
        now = datetime(2026, 1, 10, 12, 0, 0)
        completed_at = now - timedelta(days=14, minutes=1)

        self.assertFalse(
            due_for_collection(completed_at=completed_at, last_collected_at=None, now=now)
        )
        # Even a stale last_collected_at can't make a post past the window due.
        self.assertFalse(
            due_for_collection(
                completed_at=completed_at,
                last_collected_at=now - timedelta(days=10),
                now=now,
            )
        )
