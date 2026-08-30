import unittest
from unittest.mock import MagicMock

from app.models.content_generation import ContentAssetType
from app.services.content import assets as assets_service
from app.services.content.storage import UploadedObject


class TestArchiveAssetsOfType(unittest.TestCase):
    def test_marks_matching_non_intermediate_assets_as_intermediate(self):
        asset = MagicMock(is_intermediate=False)
        session = MagicMock()
        session.exec.return_value.all.return_value = [asset]

        result = assets_service.archive_assets_of_type(
            session, content_piece_id=10, asset_type=ContentAssetType.video
        )

        self.assertEqual(result, [asset])
        self.assertTrue(asset.is_intermediate)
        session.commit.assert_called_once()

    def test_no_matching_assets_returns_empty_list(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = []

        result = assets_service.archive_assets_of_type(
            session, content_piece_id=10, asset_type=ContentAssetType.video
        )

        self.assertEqual(result, [])


class TestCreateManualAsset(unittest.TestCase):
    def test_creates_asset_without_a_generation_job(self):
        session = MagicMock()
        uploaded = UploadedObject(
            url="https://x/1/10/file.mp4", storage_path="1/10/file.mp4", size_bytes=1024
        )

        asset = assets_service.create_manual_asset(
            session,
            tenant_id=1,
            client_id=2,
            content_piece_id=10,
            asset_type=ContentAssetType.video,
            uploaded=uploaded,
            mime_type="video/mp4",
        )

        self.assertIsNone(asset.generation_job_id)
        self.assertEqual(asset.storage_path, "1/10/file.mp4")
        self.assertFalse(asset.is_intermediate)
        session.add.assert_called_once()
        session.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
