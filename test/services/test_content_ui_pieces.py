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
        narration_script=None,
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

    def test_unsignable_asset_is_kept_with_a_null_url_instead_of_failing(self):
        session = MagicMock()
        piece = _piece()
        broken = _asset(storage_path="1/10/broken.png")
        ok = _asset(storage_path="1/10/ok.png")

        def sign(storage_path):
            if storage_path == "1/10/broken.png":
                raise ui_pieces.storage.StorageError("sign rejected")
            return "https://signed/ok.png"

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=piece), \
             patch.object(
                 ui_pieces.assets_service, "list_assets_for_piece", return_value=[broken, ok]
             ), \
             patch.object(
                 ui_pieces.publications_service, "list_publications_for_piece", return_value=[]
             ), \
             patch.object(ui_pieces.storage, "create_signed_url", side_effect=sign):
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=10)

        # The broken asset still has to appear — dropping it would let a
        # reviewer approve the piece without knowing an asset was missing.
        self.assertEqual(len(result.assets), 2)
        self.assertIsNone(result.assets[0].signed_url)
        self.assertEqual(result.assets[1].signed_url, "https://signed/ok.png")

    def test_asset_with_no_storage_path_uses_the_url_as_is(self):
        # Reused-avatar assets have no storage_path (nothing of ours to
        # sign) — the reviewer must still see something, so the plain url
        # is used instead of calling create_signed_url at all.
        session = MagicMock()
        piece = _piece(avatar_id=4, generation_prompt=None)
        external_asset = _asset(storage_path=None, url="https://supabase.example/avatars/ref.png")

        with patch.object(ui_pieces.pieces_service, "get_piece", return_value=piece), \
             patch.object(
                 ui_pieces.assets_service, "list_assets_for_piece", return_value=[external_asset]
             ), \
             patch.object(
                 ui_pieces.publications_service, "list_publications_for_piece", return_value=[]
             ), \
             patch.object(ui_pieces.storage, "create_signed_url") as mock_sign:
            result = ui_pieces.get_piece_detail(session, tenant_id=1, piece_id=10)

        self.assertEqual(result.assets[0].signed_url, "https://supabase.example/avatars/ref.png")
        mock_sign.assert_not_called()

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
