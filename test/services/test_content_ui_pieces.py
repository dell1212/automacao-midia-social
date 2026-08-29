import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.models.content import ContentPieceStatus, ContentPieceType, RiskLevel
from app.models.content_generation import ContentAssetType
from app.models.content_publishing import PublicationStatus
from app.services.content import ui_pieces


def _piece(**overrides):
    base = dict(
        id=10,
        campaign_id=1,
        type=ContentPieceType.image,
        status=ContentPieceStatus.pending_approval,
        generation_prompt="a cat",
        avatar_id=None,
        is_synthetic_media=True,
        content_category=None,
        risk_level=RiskLevel.none,
        requires_human_review=False,
        policy_version="v1",
        scheduled_for=None,
        approval_action=None,
        approved_at=None,
        posted_at=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return MagicMock(**base)


def _asset(**overrides):
    base = dict(
        type=ContentAssetType.image,
        storage_path="1/10/file.png",
        mime_type="image/png",
        width=1024,
        height=1024,
        duration=None,
        is_intermediate=False,
    )
    base.update(overrides)
    return MagicMock(**base)


def _publication(**overrides):
    base = dict(
        id=1,
        content_piece_id=10,
        social_account_id=1,
        platform="instagram",
        status=PublicationStatus.succeeded,
        attempt_count=1,
        max_attempts=3,
        publication_cycle=1,
        platform_post_id="p1",
        platform_post_url="https://instagram.com/p/1",
        error_code=None,
        error_message=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        completed_at=datetime(2026, 1, 1),
    )
    base.update(overrides)
    return MagicMock(**base)


class TestGetPieceDetail(unittest.TestCase):
    def test_returns_none_when_piece_not_found(self):
        session = MagicMock()

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=None):
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=99)

        self.assertIsNone(result)

    def test_excludes_intermediate_assets_and_signs_the_rest(self):
        session = MagicMock()
        piece = _piece()
        final_asset = _asset()
        intermediate_asset = _asset(storage_path="1/10/intermediate.png", is_intermediate=True)

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=piece), \
             patch.object(
                 ui_pieces.assets_service,
                 "list_assets_for_piece",
                 return_value=[intermediate_asset, final_asset],
             ), \
             patch.object(
                 ui_pieces.publications_service, "list_publications_for_piece", return_value=[]
             ), \
             patch.object(
                 ui_pieces.storage, "create_signed_url", return_value="https://signed/file.png"
             ) as mock_sign:
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=10)

        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].signed_url, "https://signed/file.png")
        mock_sign.assert_called_once_with("1/10/file.png")

    def test_includes_publications(self):
        session = MagicMock()
        piece = _piece()
        publication = _publication()

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=piece), \
             patch.object(ui_pieces.assets_service, "list_assets_for_piece", return_value=[]), \
             patch.object(
                 ui_pieces.publications_service,
                 "list_publications_for_piece",
                 return_value=[publication],
             ), \
             patch.object(ui_pieces.storage, "create_signed_url"):
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=10)

        self.assertEqual(len(result.publications), 1)
        self.assertEqual(result.publications[0].platform, "instagram")


if __name__ == "__main__":
    unittest.main()
