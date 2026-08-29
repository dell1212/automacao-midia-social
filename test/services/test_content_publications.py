import unittest
from unittest.mock import MagicMock, patch

from app.models.content_publishing import PublicationStatus
from app.services.content import publications as publications_service


def _piece(**overrides):
    base = dict(id=10, campaign_id=1)
    base.update(overrides)
    return MagicMock(**base)


def _account(**overrides):
    base = dict(id=5, client_id=2, platform="instagram", status="active")
    base.update(overrides)
    return MagicMock(**base)


class TestGetSocialAccountForPiece(unittest.TestCase):
    def test_wrong_client_is_rejected(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = publications_service.get_social_account_for_piece(
            session, piece=_piece(), social_account_id=5
        )

        self.assertIsNone(result)

    def test_inactive_account_is_rejected(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = publications_service.get_social_account_for_piece(
            session, piece=_piece(), social_account_id=5
        )

        self.assertIsNone(result)

    def test_active_account_of_same_client_is_returned(self):
        account = _account()
        session = MagicMock()
        session.exec.return_value.first.return_value = account

        result = publications_service.get_social_account_for_piece(
            session, piece=_piece(), social_account_id=5
        )

        self.assertIs(result, account)


class TestResolvePublicationRequest(unittest.TestCase):
    def test_unknown_account_is_rejected(self):
        session = MagicMock()
        piece = _piece()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=None
        ):
            accepted, rejected = publications_service.resolve_publication_request(
                session, piece=piece, social_account_ids=[5]
            )

        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["social_account_id"], 5)
        self.assertEqual(rejected[0]["reason"], "account_not_found")

    def test_incompatible_platform_is_rejected_without_creating_a_row(self):
        session = MagicMock()
        piece = _piece()
        account = _account()
        adapter = MagicMock()
        adapter.check_compatibility.side_effect = Exception("boom")

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                from app.services.content.publish_errors import (
                    PublicationError,
                    PublicationErrorCode,
                )

                adapter.check_compatibility.side_effect = PublicationError(
                    PublicationErrorCode.unsupported_capability, "nope"
                )
                with patch.object(
                    publications_service, "get_adapter", return_value=adapter
                ):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["reason"], "unsupported_capability")
        session.add.assert_not_called()

    def test_missing_final_asset_is_rejected_without_creating_a_row(self):
        """No adapter's check_compatibility() looks at `asset`, so without an
        explicit guard a piece with no final asset silently becomes a `queued`
        row that can only fail later in the dispatcher — the spec requires
        fail-fast at request time."""
        session = MagicMock()
        piece = _piece()
        account = _account()
        adapter = MagicMock()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(publications_service, "get_final_asset", return_value=None):
                with patch.object(
                    publications_service, "get_adapter", return_value=adapter
                ):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(accepted, [])
        self.assertEqual(rejected[0]["reason"], "unsupported_capability")
        self.assertEqual(rejected[0]["platform"], "instagram")
        adapter.check_compatibility.assert_not_called()
        session.add.assert_not_called()

    def test_new_pair_is_created_as_queued(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None  # no existing row
        piece = _piece()
        account = _account()
        adapter = MagicMock()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                with patch.object(publications_service, "get_adapter", return_value=adapter):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].status, PublicationStatus.queued)
        session.add.assert_called()
        session.commit.assert_called()

    def test_failed_pair_is_reset_as_retry(self):
        existing = MagicMock(
            status=PublicationStatus.failed,
            attempt_count=3,
            error_code="rate_limit",
            error_message="slow down",
            next_run_at="something",
            publication_cycle=1,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = existing
        piece = _piece()
        account = _account()
        adapter = MagicMock()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                with patch.object(publications_service, "get_adapter", return_value=adapter):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(accepted, [existing])
        self.assertEqual(existing.status, PublicationStatus.queued)
        self.assertEqual(existing.attempt_count, 0)
        self.assertIsNone(existing.error_code)
        self.assertIsNone(existing.error_message)
        self.assertIsNone(existing.next_run_at)
        self.assertEqual(existing.publication_cycle, 2)

    def test_succeeded_pair_is_a_no_op(self):
        existing = MagicMock(status=PublicationStatus.succeeded)
        session = MagicMock()
        session.exec.return_value.first.return_value = existing
        piece = _piece()
        account = _account()
        adapter = MagicMock()

        with patch.object(
            publications_service, "get_social_account_for_piece", return_value=account
        ):
            with patch.object(
                publications_service, "get_final_asset", return_value=MagicMock()
            ):
                with patch.object(publications_service, "get_adapter", return_value=adapter):
                    accepted, rejected = publications_service.resolve_publication_request(
                        session, piece=piece, social_account_ids=[5]
                    )

        self.assertEqual(accepted, [existing])
        session.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
