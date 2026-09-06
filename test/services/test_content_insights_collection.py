import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import content_insights  # noqa: F401  (registra a tabela no metadata)
from app.models.content import ContentClient, ContentSocialAccount, ContentTenant
from app.models.content_insights import ContentPublicationInsight
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
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


class TestCollectPublicationInsights(unittest.TestCase):
    def _session(self):
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        session = Session(engine)
        tenant = ContentTenant(
            owner_user_id="u1", name="T", slug="t", api_token_hash="h"
        )
        session.add(tenant)
        session.commit()
        client = ContentClient(tenant_id=tenant.id, name="C")
        session.add(client)
        session.commit()
        account = ContentSocialAccount(
            client_id=client.id,
            platform="instagram",
            external_account_id="ig-1",
            credentials_encrypted="irrelevant-for-this-test",
        )
        session.add(account)
        session.commit()
        publication = ContentSocialPublication(
            tenant_id=tenant.id,
            client_id=client.id,
            content_piece_id=1,
            social_account_id=account.id,
            platform="instagram",
            status=PublicationStatus.succeeded,
            platform_post_id="media-1",
            publication_cycle=1,
            completed_at=datetime.utcnow() - timedelta(hours=1),
        )
        session.add(publication)
        session.commit()
        return session, publication, account

    def _fake_adapter(self, *, supports_insights=True, fetch_result=None, fetch_error=None):
        adapter = MagicMock()
        adapter.supports_insights = supports_insights
        if fetch_error is not None:
            adapter.fetch_insights.side_effect = fetch_error
        else:
            adapter.fetch_insights.return_value = fetch_result or InsightsResult(likes=5)
        return adapter

    def test_successful_collection_writes_a_snapshot(self):
        session, publication, account = self._session()
        adapter = self._fake_adapter(
            fetch_result=InsightsResult(reach=100, likes=5, comments=1, shares=0)
        )

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            with patch.object(insights_collection, "load_credentials", return_value={}):
                insights_collection.collect_publication_insights(session, batch_limit=50)

        rows = session.exec(select(ContentPublicationInsight)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].publication_id, publication.id)
        self.assertEqual(rows[0].reach, 100)
        self.assertEqual(rows[0].likes, 5)
        self.assertIsNone(rows[0].error_code)

    def test_fetch_failure_writes_an_error_snapshot_not_a_crash(self):
        session, publication, account = self._session()
        adapter = self._fake_adapter(
            fetch_error=PublicationError(
                PublicationErrorCode.invalid_credentials, "missing scope"
            )
        )

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            with patch.object(insights_collection, "load_credentials", return_value={}):
                with patch.object(insights_collection.time, "sleep"):
                    insights_collection.collect_publication_insights(session, batch_limit=50)

        rows = session.exec(select(ContentPublicationInsight)).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].error_code, "invalid_credentials")
        self.assertIsNone(rows[0].reach)
        self.assertIsNone(rows[0].likes)

    def test_platform_without_insights_support_is_skipped(self):
        session, publication, account = self._session()
        adapter = self._fake_adapter(supports_insights=False)

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            insights_collection.collect_publication_insights(session, batch_limit=50)

        adapter.fetch_insights.assert_not_called()
        self.assertEqual(session.exec(select(ContentPublicationInsight)).all(), [])

    def test_publication_not_yet_due_is_skipped(self):
        session, publication, account = self._session()
        # A snapshot collected 10 minutes ago, well inside the 6h band for a
        # 1-hour-old post — the next collection is not due yet.
        session.add(
            ContentPublicationInsight(
                tenant_id=publication.tenant_id,
                client_id=publication.client_id,
                content_piece_id=publication.content_piece_id,
                publication_id=publication.id,
                social_account_id=account.id,
                platform="instagram",
                publication_cycle=1,
                collected_at=datetime.utcnow() - timedelta(minutes=10),
                likes=1,
            )
        )
        session.commit()
        adapter = self._fake_adapter()

        with patch.object(insights_collection, "get_adapter", return_value=adapter):
            insights_collection.collect_publication_insights(session, batch_limit=50)

        adapter.fetch_insights.assert_not_called()
        self.assertEqual(len(session.exec(select(ContentPublicationInsight)).all()), 1)
