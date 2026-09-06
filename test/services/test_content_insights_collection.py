import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.content import insights_collection, retry
from app.services.content.insights_collection import due_for_collection
from app.services.content.publish_errors import PublicationError, PublicationErrorCode
from app.services.content.publishers.base import InsightsResult


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


class TestFetchInsightsWithRetry(unittest.TestCase):
    def test_returns_result_on_first_success(self):
        adapter = MagicMock()
        adapter.fetch_insights.return_value = InsightsResult(likes=1)

        with patch("app.services.content.insights_collection.time.sleep") as sleep:
            result = insights_collection._fetch_insights_with_retry(
                adapter, MagicMock(), MagicMock(), {}
            )

        self.assertEqual(result.likes, 1)
        sleep.assert_not_called()

    def test_retries_transient_then_succeeds(self):
        adapter = MagicMock()
        adapter.fetch_insights.side_effect = [
            PublicationError(PublicationErrorCode.transient, "blip"),
            InsightsResult(likes=2),
        ]

        with patch("app.services.content.insights_collection.time.sleep") as sleep:
            result = insights_collection._fetch_insights_with_retry(
                adapter, MagicMock(), MagicMock(), {}
            )

        self.assertEqual(result.likes, 2)
        sleep.assert_called_once()

    def test_non_retryable_raises_immediately_without_sleeping(self):
        adapter = MagicMock()
        adapter.fetch_insights.side_effect = PublicationError(
            PublicationErrorCode.invalid_credentials, "no scope"
        )

        with patch("app.services.content.insights_collection.time.sleep") as sleep:
            with self.assertRaises(PublicationError) as ctx:
                insights_collection._fetch_insights_with_retry(
                    adapter, MagicMock(), MagicMock(), {}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.invalid_credentials)
        sleep.assert_not_called()
        self.assertEqual(adapter.fetch_insights.call_count, 1)

    def test_retryable_exhausted_raises_last_error(self):
        adapter = MagicMock()
        adapter.fetch_insights.side_effect = PublicationError(
            PublicationErrorCode.rate_limit, "slow down"
        )

        with patch("app.services.content.insights_collection.time.sleep"):
            with self.assertRaises(PublicationError) as ctx:
                insights_collection._fetch_insights_with_retry(
                    adapter, MagicMock(), MagicMock(), {}
                )

        self.assertEqual(ctx.exception.code, PublicationErrorCode.rate_limit)
        self.assertEqual(adapter.fetch_insights.call_count, retry.MAX_ATTEMPTS)
