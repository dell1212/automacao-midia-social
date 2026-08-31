import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.models.content import ContentCategory, ContentPieceStatus, ContentPieceType, RiskLevel
from app.models.content_generation import GenerationKind
from app.services.content import pieces as pieces_service


def _payload(**overrides):
    base = dict(
        campaign_id=1,
        type=ContentPieceType.image,
        idempotency_key="key-1",
        is_synthetic_media=True,
        generation_prompt="a cat",
        avatar_id=None,
        source_image_piece_id=None,
        voice_id=None,
        content_category=None,
        aspect_ratio="9:16",
        resolution=None,
        duration=None,
    )
    base.update(overrides)
    return MagicMock(**base)


class TestRequiredKinds(unittest.TestCase):
    def test_image_with_prompt_needs_image_provider(self):
        self.assertEqual(
            pieces_service.required_kinds_for(_payload()), [GenerationKind.image]
        )

    def test_image_from_avatar_without_prompt_needs_nothing(self):
        payload = _payload(generation_prompt=None, avatar_id=7)

        self.assertEqual(pieces_service.required_kinds_for(payload), [])

    def test_audio_needs_voice_provider(self):
        payload = _payload(type=ContentPieceType.audio)

        self.assertEqual(pieces_service.required_kinds_for(payload), [GenerationKind.voice])

    def test_video_from_prompt_needs_image_and_video(self):
        payload = _payload(type=ContentPieceType.video)

        self.assertEqual(
            pieces_service.required_kinds_for(payload),
            [GenerationKind.video, GenerationKind.image],
        )

    def test_video_from_avatar_with_voice_needs_video_and_voice(self):
        payload = _payload(type=ContentPieceType.video, avatar_id=7, voice_id="v1")

        self.assertEqual(
            pieces_service.required_kinds_for(payload),
            [GenerationKind.video, GenerationKind.voice],
        )

    def test_video_from_source_image_does_not_need_image_provider(self):
        payload = _payload(type=ContentPieceType.video, source_image_piece_id=3)

        self.assertEqual(
            pieces_service.required_kinds_for(payload), [GenerationKind.video]
        )


class TestListPieces(unittest.TestCase):
    def test_returns_empty_list_when_campaign_not_found(self):
        session = MagicMock()

        with patch.object(pieces_service, "get_campaign", return_value=None):
            result = pieces_service.list_pieces(session, tenant_id=1, campaign_id=99)

        self.assertEqual(result, [])

    def test_no_status_filters_by_campaign_only(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["piece-a", "piece-b"]

        with patch.object(pieces_service, "get_campaign", return_value=MagicMock()):
            result = pieces_service.list_pieces(session, tenant_id=1, campaign_id=1)

        self.assertEqual(result, ["piece-a", "piece-b"])
        statement = session.exec.call_args.args[0]
        where_compiled = str(
            statement.whereclause.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("CAMPAIGN_ID = 1", where_compiled)
        self.assertNotIn("STATUS", where_compiled)

    def test_status_filter_is_applied_when_given(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["piece-a"]

        with patch.object(pieces_service, "get_campaign", return_value=MagicMock()):
            result = pieces_service.list_pieces(
                session,
                tenant_id=1,
                campaign_id=1,
                status=ContentPieceStatus.pending_approval,
            )

        self.assertEqual(result, ["piece-a"])
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("CAMPAIGN_ID = 1", compiled)
        self.assertIn("STATUS = 'PENDING_APPROVAL'", compiled)


class TestCreatePieceIdempotency(unittest.TestCase):
    def test_existing_key_returns_the_same_piece_without_new_work(self):
        existing = MagicMock(id=42)
        session = MagicMock()

        with patch.object(
            pieces_service, "find_by_idempotency_key", return_value=existing
        ):
            with patch.object(pieces_service, "schedule_piece") as schedule:
                result, created = pieces_service.create_piece(session, payload=_payload())

        self.assertIs(result, existing)
        self.assertFalse(created)
        schedule.assert_not_called()
        session.add.assert_not_called()

    def test_new_key_creates_and_schedules(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece") as schedule:
                result, created = pieces_service.create_piece(session, payload=_payload())

        self.assertTrue(created)
        session.add.assert_called_once()
        schedule.assert_called_once()


class TestCreatePiecePolicy(unittest.TestCase):
    def test_medical_category_is_classified_as_high_risk(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece"):
                piece, _ = pieces_service.create_piece(
                    session,
                    payload=_payload(content_category=ContentCategory.medical),
                )

        self.assertEqual(piece.risk_level, RiskLevel.high)
        self.assertTrue(piece.requires_human_review)
        self.assertEqual(piece.policy_version, "v1")

    def test_absent_category_is_inert(self):
        session = MagicMock()

        with patch.object(pieces_service, "find_by_idempotency_key", return_value=None):
            with patch.object(pieces_service, "schedule_piece"):
                piece, _ = pieces_service.create_piece(session, payload=_payload())

        self.assertEqual(piece.risk_level, RiskLevel.none)
        self.assertFalse(piece.requires_human_review)


class TestApprovePiece(unittest.TestCase):
    def test_returns_none_when_piece_not_found(self):
        session = MagicMock()

        with patch.object(pieces_service, "get_piece", return_value=None):
            result = pieces_service.approve_piece(session, tenant_id=1, piece_id=99)

        self.assertIsNone(result)

    def test_approves_when_still_pending_approval(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.pending_approval)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.approve_piece(session, tenant_id=1, piece_id=10)

        self.assertIs(result, piece)
        session.commit.assert_called_once()
        session.refresh.assert_called_once_with(piece)

        # Regression guard: the mocked rowcount above proves nothing about
        # what predicate actually reached the DB. Compile the real statement
        # passed to session.exec and assert the WHERE clause still ANDs both
        # the id and the pending_approval status — a future edit that drops
        # the status predicate would still pass every assertion above.
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("STATUS = 'PENDING_APPROVAL'", compiled)
        self.assertIn("ID = 10", compiled)

    def test_returns_none_when_status_changed_concurrently(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.pending_approval)
        session = MagicMock()
        session.exec.return_value.rowcount = 0

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.approve_piece(session, tenant_id=1, piece_id=10)

        self.assertIsNone(result)
        session.refresh.assert_not_called()


class TestRejectPiece(unittest.TestCase):
    def test_rejects_when_still_pending_approval(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.pending_approval)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.reject_piece(session, tenant_id=1, piece_id=10)

        self.assertIs(result, piece)
        session.commit.assert_called_once()

        # Regression guard: same rationale as TestApprovePiece — assert on
        # the real compiled statement so a dropped status predicate fails
        # this test instead of silently going inert.
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("STATUS = 'PENDING_APPROVAL'", compiled)
        self.assertIn("ID = 10", compiled)

    def test_returns_none_when_status_changed_concurrently(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.pending_approval)
        session = MagicMock()
        session.exec.return_value.rowcount = 0

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.reject_piece(session, tenant_id=1, piece_id=10)

        self.assertIsNone(result)


class TestUpdatePiece(unittest.TestCase):
    def test_returns_none_when_piece_not_found(self):
        session = MagicMock()

        with patch.object(pieces_service, "get_piece", return_value=None):
            result = pieces_service.update_piece(
                session, tenant_id=1, piece_id=99, generation_prompt="new"
            )

        self.assertIsNone(result)

    def test_diffs_only_changed_fields(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.draft,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session,
                tenant_id=1,
                piece_id=10,
                generation_prompt="a cat",  # unchanged — must not appear in diff
                risk_level=RiskLevel.high,
            )

        self.assertIsNotNone(result)
        updated, diff = result
        self.assertIs(updated, piece)
        self.assertEqual(
            diff, {"risk_level": {"before": "none", "after": "high"}}
        )
        self.assertNotIn("status", diff)

    def test_narration_script_diffs_independently_of_generation_prompt(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.draft,
            generation_prompt="a robot waving",
            narration_script=None,
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session,
                tenant_id=1,
                piece_id=10,
                narration_script="Meet Rex, the good boy next door.",
            )

        updated, diff = result
        self.assertEqual(
            diff,
            {
                "narration_script": {
                    "before": None,
                    "after": "Meet Rex, the good boy next door.",
                }
            },
        )
        self.assertNotIn("generation_prompt", diff)

    def test_reverts_approved_to_pending_approval_and_logs_it(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.approved,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session, tenant_id=1, piece_id=10, generation_prompt="a dog"
            )

        updated, diff = result
        self.assertEqual(
            diff["status"], {"before": "approved", "after": "pending_approval"}
        )
        self.assertEqual(
            diff["generation_prompt"], {"before": "a cat", "after": "a dog"}
        )

    def test_no_op_edit_on_approved_piece_does_not_revert_status(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.approved,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session, tenant_id=1, piece_id=10
            )

        self.assertIsNotNone(result)
        updated, diff = result
        self.assertEqual(diff, {})
        self.assertEqual(updated.status, ContentPieceStatus.approved)

    def test_returns_none_when_posted_concurrently(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.pending_approval,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 0

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.update_piece(
                session, tenant_id=1, piece_id=10, generation_prompt="a dog"
            )

        self.assertIsNone(result)
        session.refresh.assert_not_called()

    def test_where_clause_excludes_posted(self):
        piece = MagicMock(
            id=10,
            status=ContentPieceStatus.draft,
            generation_prompt="a cat",
            avatar_id=None,
            voice_id=None,
            content_category=None,
            risk_level=RiskLevel.none,
            scheduled_for=None,
        )
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            pieces_service.update_piece(
                session, tenant_id=1, piece_id=10, generation_prompt="a dog"
            )

        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("STATUS != 'POSTED'", compiled)
        self.assertIn("ID = 10", compiled)


class TestMarkAssetReplaced(unittest.TestCase):
    def test_returns_none_when_piece_not_found(self):
        session = MagicMock()

        with patch.object(pieces_service, "get_piece", return_value=None):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=99)

        self.assertIsNone(result)

    def test_no_diff_when_piece_not_in_decided_state(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.draft)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        self.assertIsNotNone(result)
        updated, diff = result
        self.assertIs(updated, piece)
        self.assertEqual(diff, {})

    def test_reverts_approved_to_pending_approval_and_logs_it(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.approved)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        updated, diff = result
        self.assertEqual(
            diff["status"], {"before": "approved", "after": "pending_approval"}
        )

    def test_returns_none_when_posted_concurrently(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.pending_approval)
        session = MagicMock()
        session.exec.return_value.rowcount = 0

        with patch.object(pieces_service, "get_piece", return_value=piece):
            result = pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        self.assertIsNone(result)
        session.refresh.assert_not_called()

    def test_where_clause_excludes_posted(self):
        piece = MagicMock(id=10, status=ContentPieceStatus.draft)
        session = MagicMock()
        session.exec.return_value.rowcount = 1

        with patch.object(pieces_service, "get_piece", return_value=piece):
            pieces_service.mark_asset_replaced(session, tenant_id=1, piece_id=10)

        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("STATUS != 'POSTED'", compiled)
        self.assertIn("ID = 10", compiled)


if __name__ == "__main__":
    unittest.main()
