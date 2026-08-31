import unittest
from unittest.mock import MagicMock, patch

from app.models.content_generation import ContentAssetType
from app.services.content import pipeline


def _piece(**overrides):
    base = dict(id=10, avatar_id=None, generation_prompt=None)
    base.update(overrides)
    return MagicMock(**base)


def _avatar(**overrides):
    base = dict(reference_image_url="https://supabase.example/avatars/ref.png")
    base.update(overrides)
    return MagicMock(**base)


class TestRunImagePieceAvatarReuse(unittest.TestCase):
    def test_reuses_avatar_image_and_registers_it_as_an_external_asset(self):
        session = MagicMock()
        piece = _piece(avatar_id=4, generation_prompt=None)
        avatar = _avatar()

        with patch.object(
            pipeline.avatars_service, "get_avatar", return_value=avatar
        ) as get_avatar, patch.object(
            pipeline.assets_service, "create_external_asset"
        ) as create_external_asset, patch.object(
            pipeline.jobs_service, "create_job"
        ) as create_job, patch.object(
            pipeline.orchestrator, "run_job"
        ) as run_job:
            result = pipeline._run_image_piece(
                session, piece, tenant_id=1, client_id=2, aspect_ratio="9:16"
            )

        get_avatar.assert_called_once_with(session, tenant_id=1, avatar_id=4)
        create_external_asset.assert_called_once_with(
            session,
            tenant_id=1,
            client_id=2,
            content_piece_id=10,
            asset_type=ContentAssetType.image,
            url="https://supabase.example/avatars/ref.png",
            provider="avatar_reuse",
        )
        # No provider call for this path — that's the whole point of reuse.
        create_job.assert_not_called()
        run_job.assert_not_called()
        self.assertEqual(result, "https://supabase.example/avatars/ref.png")

    def test_missing_avatar_returns_none_without_registering_an_asset(self):
        session = MagicMock()
        piece = _piece(avatar_id=999, generation_prompt=None)

        with patch.object(
            pipeline.avatars_service, "get_avatar", return_value=None
        ), patch.object(
            pipeline.assets_service, "create_external_asset"
        ) as create_external_asset:
            result = pipeline._run_image_piece(
                session, piece, tenant_id=1, client_id=2, aspect_ratio="9:16"
            )

        create_external_asset.assert_not_called()
        self.assertIsNone(result)

    def test_avatar_with_a_prompt_calls_the_provider_instead_of_reusing(self):
        # avatar_id set but generation_prompt also set: the piece wants a
        # fresh generation, not the avatar's own image — must not take the
        # reuse shortcut just because avatar_id is present.
        session = MagicMock()
        piece = _piece(avatar_id=4, generation_prompt="a cat wearing sunglasses")
        generated_asset = MagicMock(url="https://supabase.example/generated.png")

        with patch.object(
            pipeline.avatars_service, "get_avatar"
        ) as get_avatar, patch.object(
            pipeline.assets_service, "create_external_asset"
        ) as create_external_asset, patch.object(
            pipeline.jobs_service, "create_job", return_value=MagicMock()
        ), patch.object(
            pipeline.orchestrator, "run_job", return_value=generated_asset
        ) as run_job:
            result = pipeline._run_image_piece(
                session, piece, tenant_id=1, client_id=2, aspect_ratio="9:16"
            )

        get_avatar.assert_not_called()
        create_external_asset.assert_not_called()
        run_job.assert_called_once()
        self.assertEqual(result, "https://supabase.example/generated.png")


if __name__ == "__main__":
    unittest.main()
