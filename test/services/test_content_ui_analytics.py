import unittest
from datetime import datetime

from app.models.content_insights import ContentPublicationInsight
from app.models.content_publishing import ContentSocialPublication, PublicationStatus
from app.services.content import ui_analytics


def _publication(id_, social_account_id=1):
    return ContentSocialPublication(
        id=id_,
        tenant_id=1,
        client_id=1,
        content_piece_id=1,
        social_account_id=social_account_id,
        platform="instagram",
        status=PublicationStatus.succeeded,
        publication_cycle=1,
    )


def _insight(publication_id, collected_at, **overrides):
    base = dict(
        tenant_id=1,
        client_id=1,
        content_piece_id=1,
        publication_id=publication_id,
        social_account_id=1,
        platform="instagram",
        publication_cycle=1,
        collected_at=collected_at,
    )
    base.update(overrides)
    return ContentPublicationInsight(**base)


class TestPickLatest(unittest.TestCase):
    def test_keeps_only_the_most_recent_row_per_publication(self):
        rows = [
            _insight(1, datetime(2026, 1, 1), likes=1),
            _insight(1, datetime(2026, 1, 3), likes=3),
            _insight(1, datetime(2026, 1, 2), likes=2),
            _insight(2, datetime(2026, 1, 1), likes=10),
        ]

        latest = ui_analytics._pick_latest(rows)

        self.assertEqual(len(latest), 2)
        self.assertEqual(latest[1].likes, 3)
        self.assertEqual(latest[2].likes, 10)

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(ui_analytics._pick_latest([]), {})


class TestEngagementTiles(unittest.TestCase):
    def test_no_snapshots_returns_all_none(self):
        totals = ui_analytics._engagement_tiles([_publication(1)], {})

        self.assertIsNone(totals.reach)
        self.assertIsNone(totals.interactions)
        self.assertIsNone(totals.engagement_rate)
        self.assertEqual(totals.reach_substituted_accounts, 0)

    def test_sums_reach_and_interactions_across_publications(self):
        pub1, pub2 = _publication(1, social_account_id=1), _publication(2, social_account_id=2)
        latest = {
            1: _insight(1, datetime(2026, 1, 1), reach=100, likes=5, comments=1, shares=0),
            2: _insight(2, datetime(2026, 1, 1), reach=50, likes=2, comments=0, shares=1),
        }

        totals = ui_analytics._engagement_tiles([pub1, pub2], latest)

        self.assertEqual(totals.reach, 150)
        self.assertEqual(totals.interactions, 9)
        self.assertEqual(totals.engagement_rate, round(9 / 150, 4))
        self.assertEqual(totals.reach_substituted_accounts, 0)

    def test_missing_reach_substitutes_impressions_and_counts_the_account(self):
        pub1, pub2 = _publication(1, social_account_id=1), _publication(2, social_account_id=2)
        latest = {
            # Instagram: real reach.
            1: _insight(1, datetime(2026, 1, 1), reach=100, likes=1),
            # LinkedIn-shaped: no reach, only impressions.
            2: _insight(2, datetime(2026, 1, 1), impressions=400, likes=2),
        }

        totals = ui_analytics._engagement_tiles([pub1, pub2], latest)

        self.assertEqual(totals.reach, 500)
        self.assertEqual(totals.reach_substituted_accounts, 1)

    def test_zero_reach_does_not_divide_by_zero(self):
        pub1 = _publication(1)
        latest = {1: _insight(1, datetime(2026, 1, 1), reach=0, likes=3)}

        totals = ui_analytics._engagement_tiles([pub1], latest)

        self.assertEqual(totals.reach, 0)
        self.assertEqual(totals.interactions, 3)
        self.assertIsNone(totals.engagement_rate)

    def test_publication_with_no_snapshot_is_ignored(self):
        pub1, pub2 = _publication(1), _publication(2)
        latest = {1: _insight(1, datetime(2026, 1, 1), reach=10, likes=1)}

        totals = ui_analytics._engagement_tiles([pub1, pub2], latest)

        self.assertEqual(totals.reach, 10)
        self.assertEqual(totals.interactions, 1)
