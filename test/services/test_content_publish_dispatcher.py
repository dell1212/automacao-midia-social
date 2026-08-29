import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
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
        # must fail this test, not just look fine. It must be
        # session.refresh(), not session.get(): get() with with_for_update
        # emits the locking SELECT but leaves the already-loaded attributes on
        # the identity-mapped `piece` untouched, so posted_at could still read
        # as None under a row that already has one.
        piece_lock_calls = [
            c
            for c in session.refresh.call_args_list
            if c.args and c.args[0] is piece and c.kwargs.get("with_for_update") is True
        ]
        self.assertTrue(
            piece_lock_calls,
            "piece row was not re-read with session.refresh(piece, with_for_update=True)",
        )
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
            for c in session.refresh.call_args_list
            if c.args and c.args[0] is piece and c.kwargs.get("with_for_update") is True
        ]
        self.assertTrue(
            piece_lock_calls,
            "piece row was not re-read with session.refresh(piece, with_for_update=True)",
        )
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

    def test_unexpected_exception_during_setup_fails_fast_not_left_running(self):
        """A row claimed as `running` must never get stuck there — and an
        unexpected exception in asset/credential lookup is a structural bug
        that fails identically on every attempt, so it resolves to `failed`,
        not to three wasted `transient` retries."""
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
            with patch.object(
                dispatcher, "recompute_publication_summary", return_value={}
            ):
                dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.failed)
        self.assertEqual(row.error_code, "invalid_params")

    def test_missing_final_asset_fails_without_calling_the_adapter(self):
        """Second layer of defense behind resolve_publication_request's
        fail-fast: an asset removed between enqueue and dispatch must not
        reach the adapter as `asset=None`."""
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

        with patch.object(dispatcher, "get_final_asset", return_value=None):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher, "recompute_publication_summary", return_value={}
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        adapter.publish.assert_not_called()
        self.assertEqual(row.status, PublicationStatus.failed)
        self.assertEqual(row.error_code, "unsupported_capability")

    def test_unexpected_exception_from_publish_is_not_retried_as_transient(self):
        """Every genuinely retryable failure already arrives as a
        PublicationError from the base-adapter HTTP helpers. A KeyError from
        an adapter reading a missing credentials field is a structural bug —
        it fails identically on every attempt, so it must go straight to
        `failed`, never to `retrying`."""
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
        adapter.publish.side_effect = KeyError("ig_user_id")

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher, "recompute_publication_summary", return_value={}
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.failed)
        self.assertEqual(row.error_code, "invalid_params")

    def test_transient_publication_error_still_retries(self):
        """The counterpart to the test above — reclassifying unknown
        exceptions must NOT have collapsed the real retryable path."""
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
            PublicationErrorCode.transient, "connection reset"
        )

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(row.status, PublicationStatus.retrying)
        self.assertEqual(row.error_code, "transient")
        self.assertIsNotNone(row.next_run_at)

    def test_no_transaction_is_held_open_across_the_adapter_call(self):
        """I2: the read transaction must be closed before publish() — a call
        that can take minutes must not sit on a pooled connection
        idle-in-transaction."""
        row = self._row()
        piece = MagicMock(id=10, posted_at=None, publication_summary=None)
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

        commits_before_publish = []
        adapter = MagicMock()

        def publish(*_args, **_kwargs):
            commits_before_publish.append(session.commit.call_count)
            return MagicMock(platform_post_id="p1", platform_post_url="https://x/p1")

        adapter.publish.side_effect = publish

        with patch.object(dispatcher, "get_final_asset", return_value=MagicMock()):
            with patch.object(dispatcher, "get_adapter", return_value=adapter):
                with patch.object(dispatcher, "load_credentials", return_value={}):
                    with patch.object(
                        dispatcher, "recompute_publication_summary", return_value={}
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(
            commits_before_publish,
            [1],
            "the read transaction was not committed before adapter.publish()",
        )
        # ...and that release has to actually stick: with the default
        # expire_on_commit, the first attribute the adapter touches
        # (piece.type, asset.url) lazy-loads and re-opens a transaction that
        # stays open for the whole HTTP call.
        self.assertIs(session.expire_on_commit, False)

    def test_success_writes_row_and_piece_in_a_single_transaction(self):
        """I3: the spec requires row + piece to land atomically. A commit
        between them leaves the publication `succeeded` while the piece never
        reaches `posted` if the process dies in the gap."""
        row = self._row()
        piece = MagicMock(id=10, posted_at=None, publication_summary=None)
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

        snapshots = []
        session.commit.side_effect = lambda: snapshots.append(
            (row.status, piece.publication_summary, piece.posted_at)
        )

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
                        return_value={"total": 1},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        # Exactly two commits: the pre-network read release, then ONE write
        # transaction carrying both mutations.
        self.assertEqual(len(snapshots), 2, f"unexpected commit sequence: {snapshots}")
        self.assertEqual(snapshots[0], (PublicationStatus.running, None, None))
        final_status, final_summary, final_posted_at = snapshots[1]
        self.assertEqual(final_status, PublicationStatus.succeeded)
        self.assertEqual(final_summary, {"total": 1})
        self.assertIsNotNone(final_posted_at)

    def test_terminal_failure_writes_row_and_piece_in_a_single_transaction(self):
        row = self._row()
        piece = MagicMock(id=10, posted_at=None, publication_summary=None)
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

        snapshots = []
        session.commit.side_effect = lambda: snapshots.append(
            (row.status, piece.publication_summary)
        )

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
                        return_value={"total": 1, "failed": 1},
                    ):
                        dispatcher.execute_claimed_publication(session, 1)

        self.assertEqual(len(snapshots), 2, f"unexpected commit sequence: {snapshots}")
        self.assertEqual(snapshots[0], (PublicationStatus.running, None))
        self.assertEqual(
            snapshots[1], (PublicationStatus.failed, {"total": 1, "failed": 1})
        )

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


class TestTickBackpressure(unittest.TestCase):
    """C1: claiming more rows than the pool can start leaves them `running`
    with `updated_at` stamped at claim time while they sit in the executor's
    unbounded queue — long enough for the stale-running sweep to reclaim a row
    that was never stuck, producing a duplicate post on the platform."""

    def setUp(self):
        self._set_in_flight(0)
        self.addCleanup(self._set_in_flight, 0)

    @staticmethod
    def _set_in_flight(value):
        with dispatcher._in_flight_lock:
            dispatcher._in_flight = value

    def test_saturated_pool_claims_nothing(self):
        self._set_in_flight(dispatcher.WORKERS)

        with patch.object(dispatcher, "get_engine") as get_engine:
            with patch.object(dispatcher, "Session"):
                with patch.object(dispatcher, "claim_due_publications") as claim:
                    dispatcher._tick()

        claim.assert_not_called()
        get_engine.assert_not_called()

    def test_claim_limit_is_bounded_by_free_capacity_not_batch_size(self):
        self._set_in_flight(dispatcher.WORKERS - 2)

        with patch.object(dispatcher, "BATCH_SIZE", 50):
            with patch.object(dispatcher, "get_engine"):
                with patch.object(dispatcher, "Session"):
                    with patch.object(
                        dispatcher, "claim_due_publications", return_value=[]
                    ) as claim:
                        dispatcher._tick()

        self.assertEqual(claim.call_args.kwargs["limit"], 2)

    def test_claim_limit_is_still_capped_by_batch_size(self):
        with patch.object(dispatcher, "BATCH_SIZE", 1):
            with patch.object(dispatcher, "get_engine"):
                with patch.object(dispatcher, "Session"):
                    with patch.object(
                        dispatcher, "claim_due_publications", return_value=[]
                    ) as claim:
                        dispatcher._tick()

        self.assertEqual(claim.call_args.kwargs["limit"], 1)

    def test_submitted_work_holds_capacity_until_the_future_completes(self):
        future = MagicMock()
        executor = MagicMock()
        executor.submit.return_value = future

        with patch.object(dispatcher, "_executor", executor):
            with patch.object(dispatcher, "get_engine"):
                with patch.object(dispatcher, "Session"):
                    with patch.object(
                        dispatcher,
                        "claim_due_publications",
                        return_value=[MagicMock(id=7), MagicMock(id=8)],
                    ):
                        dispatcher._tick()

        self.assertEqual(dispatcher._in_flight, 2)
        done_callback = future.add_done_callback.call_args.args[0]
        done_callback(future)
        done_callback(future)
        self.assertEqual(dispatcher._in_flight, 0)


class TestDispatcherLifecycle(unittest.TestCase):
    def setUp(self):
        # stop_dispatcher() shuts the pool down for good; hand the module a
        # live one back so tests that drive _tick() directly still work.
        self.addCleanup(self._restore_executor)

    @staticmethod
    def _restore_executor():
        dispatcher._executor = ThreadPoolExecutor(
            max_workers=dispatcher.WORKERS, thread_name_prefix="mpt-content-publish"
        )
        with dispatcher._in_flight_lock:
            dispatcher._in_flight = 0

    def test_start_and_stop_do_not_raise(self):
        with patch.object(dispatcher, "_tick"):
            dispatcher.start_dispatcher()
            dispatcher.stop_dispatcher()

    def test_stop_drains_in_flight_work_before_returning(self):
        """Stopping only the polling thread abandons submitted futures
        mid-publish, leaving rows stuck in `running` until the stale sweep."""
        finished = threading.Event()

        def slow_task():
            time.sleep(0.2)
            finished.set()

        with patch.object(dispatcher, "_tick"):
            dispatcher.start_dispatcher()
            dispatcher._executor.submit(slow_task)
            dispatcher.stop_dispatcher()

        self.assertTrue(
            finished.is_set(),
            "stop_dispatcher() returned while work was still in flight",
        )

    def test_start_after_stop_gets_a_live_executor(self):
        with patch.object(dispatcher, "_tick"):
            dispatcher.start_dispatcher()
            dispatcher.stop_dispatcher()
            dispatcher.start_dispatcher()
            try:
                future = dispatcher._executor.submit(lambda: "ok")
                self.assertEqual(future.result(timeout=5), "ok")
            finally:
                dispatcher.stop_dispatcher()


if __name__ == "__main__":
    unittest.main()
