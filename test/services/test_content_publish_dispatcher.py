import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceStatus
from app.models.content_publishing import PublicationStatus
from app.services.content import publish_dispatcher as dispatcher
from app.services.content.publish_errors import PublicationError, PublicationErrorCode


class TestClaimDuePublications(unittest.TestCase):
    def test_claim_marks_rows_running_and_bumps_attempt_count(self):
        row = MagicMock(status=PublicationStatus.queued, attempt_count=0)
        session = MagicMock()
        session.exec.return_value.all.return_value = [row]

        result = dispatcher.claim_due_publications(session, limit=5)

        self.assertEqual(result, [row])
        self.assertEqual(row.status, PublicationStatus.running)
        self.assertEqual(row.attempt_count, 1)
        session.commit.assert_called_once()


class TestRecomputePublicationSummary(unittest.TestCase):
    def test_aggregates_by_platform_and_outcome(self):
        rows = [
            MagicMock(platform="instagram", status=PublicationStatus.succeeded),
            MagicMock(platform="instagram", status=PublicationStatus.failed),
            MagicMock(platform="tiktok", status=PublicationStatus.succeeded),
            MagicMock(platform="youtube", status=PublicationStatus.queued),
        ]
        session = MagicMock()
        session.exec.return_value.all.return_value = rows

        summary = dispatcher.recompute_publication_summary(session, content_piece_id=1)

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["platforms"]["instagram"], {"succeeded": 1, "failed": 1})
        self.assertEqual(summary["platforms"]["tiktok"], {"succeeded": 1, "failed": 0})


class TestExecuteClaimedPublication(unittest.TestCase):
    def _row(self, **overrides):
        base = dict(
            id=1,
            content_piece_id=10,
            social_account_id=5,
            platform="instagram",
            status=PublicationStatus.running,
            attempt_count=1,
            max_attempts=3,
        )
        base.update(overrides)
        return MagicMock(**base)

    def test_success_marks_succeeded_and_updates_piece(self):
        row = self._row()
        piece = MagicMock(id=10, posted_at=None, status=ContentPieceStatus.approved)
        account = MagicMock()
        session = MagicMock()
        session.get.side_effect = lambda model, id_: {
            ("ContentSocialPublication", 1): row,
        }.get((model.__name__, id_), None)

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.return_value = MagicMock(
            platform_post_id="p1", platform_post_url="https://x/p1"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher,
                        "recompute_publication_summary",
                        return_value={"total": 1, "succeeded": 1, "failed": 0, "pending": 0, "platforms": {}},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.succeeded)
        self.assertEqual(row.platform_post_id, "p1")
        self.assertEqual(piece.status, ContentPieceStatus.posted)
        self.assertIsNotNone(piece.posted_at)

    def test_retryable_failure_schedules_next_run_without_marking_failed(self):
        row = self._row(attempt_count=1, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.side_effect = PublicationError(
            PublicationErrorCode.rate_limit, "slow down"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.retrying)
        self.assertIsNotNone(row.next_run_at)
        self.assertEqual(row.error_code, "rate_limit")

    def test_non_retryable_failure_marks_failed_and_updates_summary(self):
        row = self._row()
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.side_effect = PublicationError(
            PublicationErrorCode.invalid_params, "bad payload"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher,
                        "recompute_publication_summary",
                        return_value={"total": 1, "succeeded": 0, "failed": 1, "pending": 0, "platforms": {}},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.failed)
        self.assertEqual(row.error_code, "invalid_params")

    def test_exhausted_retries_marks_failed(self):
        row = self._row(attempt_count=3, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        adapter = MagicMock()
        adapter.publish.side_effect = PublicationError(
            PublicationErrorCode.transient, "boom"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher,
                        "recompute_publication_summary",
                        return_value={"total": 1, "succeeded": 0, "failed": 1, "pending": 0, "platforms": {}},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.failed)

    def test_unexpected_exception_during_setup_is_retried_not_left_running(self):
        """A row claimed as `running` must never get stuck there — even a bug
        in asset/credential lookup has to resolve to retrying/failed."""
        row = self._row(attempt_count=1, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_):
            if model.__name__ == "ContentSocialPublication":
                return row
            if model.__name__ == "ContentPiece":
                return piece
            if model.__name__ == "ContentSocialAccount":
                return account
            return None

        session = MagicMock()
        session.get.side_effect = get_side_effect

        with patch.object(
            dispatcher, "get_final_asset", side_effect=RuntimeError("db exploded")
        ):
            dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.retrying)
        self.assertIsNotNone(row.next_run_at)
        self.assertEqual(row.error_code, "transient")


class TestDispatcherLifecycle(unittest.TestCase):
    def test_start_and_stop_do_not_raise(self):
        with patch.object(dispatcher, "_tick"):
            dispatcher.start_dispatcher()
            dispatcher.stop_dispatcher()


if __name__ == "__main__":
    unittest.main()
