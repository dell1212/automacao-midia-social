import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

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

    def test_claim_statement_uses_skip_locked_and_reclaims_stale_running(self):
        """The one property this whole task exists to guarantee — assert on
        the actual compiled SQL, not just the mocked effect. A future edit
        that silently drops with_for_update(skip_locked=True) must fail this
        test, not just look fine in a mocked unit test."""
        session = MagicMock()
        session.exec.return_value.all.return_value = []

        dispatcher.claim_due_publications(session, limit=5)

        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("FOR UPDATE SKIP LOCKED", compiled)
        self.assertIn("NULLS FIRST", compiled)
        self.assertIn("STATUS", compiled)
        self.assertIn("RUNNING", compiled)


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

        def get_side_effect(model, id_, **kwargs):
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
        # The summary recompute+write must happen under a row lock, or two
        # workers finishing near-simultaneously on the same piece can
        # silently overwrite each other's result — removing with_for_update
        # must fail this test, not just look fine.
        piece_lock_calls = [
            c
            for c in session.get.call_args_list
            if c.args and c.args[0].__name__ == "ContentPiece" and c.kwargs.get("with_for_update") is True
        ]
        self.assertTrue(piece_lock_calls, "piece row was not re-fetched with with_for_update=True")
        # Same requirement for the fencing re-fetch, and it must be
        # session.refresh(), not session.get(): get() with with_for_update
        # emits the SELECT but leaves the already-loaded attributes on the
        # identity-mapped instance untouched, so the attempt_count comparison
        # can never fail — a no-op wearing the shape of a fence.
        fencing_calls = [
            c
            for c in session.refresh.call_args_list
            if c.args and c.args[0] is row and c.kwargs.get("with_for_update") is True
        ]
        self.assertTrue(
            fencing_calls, "fencing check did not call session.refresh(row, with_for_update=True)"
        )

    def test_retryable_failure_schedules_next_run_without_marking_failed(self):
        row = self._row(attempt_count=1, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_, **kwargs):
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

        def get_side_effect(model, id_, **kwargs):
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
        piece_lock_calls = [
            c
            for c in session.get.call_args_list
            if c.args and c.args[0].__name__ == "ContentPiece" and c.kwargs.get("with_for_update") is True
        ]
        self.assertTrue(piece_lock_calls, "piece row was not re-fetched with with_for_update=True")
        fencing_calls = [
            c
            for c in session.refresh.call_args_list
            if c.args and c.args[0] is row and c.kwargs.get("with_for_update") is True
        ]
        self.assertTrue(
            fencing_calls, "fencing check did not call session.refresh(row, with_for_update=True)"
        )

    def test_exhausted_retries_marks_failed(self):
        row = self._row(attempt_count=3, max_attempts=3)
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_, **kwargs):
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

        def get_side_effect(model, id_, **kwargs):
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

    def test_semaphore_is_released_after_publish_raises(self):
        """If the semaphore leaked on failure, a same-platform publication
        would eventually deadlock waiting for a permit that never comes
        back — this must hold even on the error path, not just success."""
        row = self._row()
        piece = MagicMock(id=10, posted_at=None)
        account = MagicMock()

        def get_side_effect(model, id_, **kwargs):
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
                        dispatcher, "recompute_publication_summary", return_value={}
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        # Acquire ALL permits, not just one — with PLATFORM_CONCURRENCY=2, a
        # single leaked permit still leaves 1 available and a "was at least
        # one free" check wouldn't catch it. Draining every permit is the
        # only way this test actually fails if the finally-release were
        # removed.
        semaphore = dispatcher._platform_semaphore(row.platform)
        acquired = [
            semaphore.acquire(blocking=False) for _ in range(dispatcher.PLATFORM_CONCURRENCY)
        ]
        self.assertTrue(
            all(acquired), "semaphore permit(s) leaked after adapter.publish raised"
        )
        for was_acquired in acquired:
            if was_acquired:
                semaphore.release()


class TestDispatcherLifecycle(unittest.TestCase):
    def test_start_and_stop_do_not_raise(self):
        with patch.object(dispatcher, "_tick"):
            dispatcher.start_dispatcher()
            dispatcher.stop_dispatcher()


if __name__ == "__main__":
    unittest.main()
