import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine

from app.models import content_publishing  # noqa: F401  (registers tables in metadata)
from app.models.content import (
    ContentCampaign,
    ContentClient,
    ContentPiece,
    ContentPieceStatus,
    ContentPieceType,
    ContentSocialAccount,
    ContentTenant,
    EntitlementStatus,
)
from app.models.content_generation import ContentAsset, ContentAssetType
from app.models.content_publishing import PublicationStatus
from app.services.content import publications as publications_service
from app.services.content import publish_dispatcher as dispatcher
from app.services.content.publish_errors import PublicationError, PublicationErrorCode


class PublishChainIntegrationTestCase(unittest.TestCase):
    """Exercises resolve_publication_request -> claim_due_publications ->
    execute_claimed_publication together against a real SQLite engine — the
    seam between the original 14 tasks that no test (every one of which
    mocks the session) exercises today. Only the adapter/HTTP boundary
    (get_adapter, load_credentials) is mocked; everything else runs for
    real, including the compatibility check inside resolve_publication_request.
    """

    def setUp(self):
        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        self.session = Session(engine)
        self.addCleanup(self.session.close)

        tenant = ContentTenant(
            owner_user_id="u1", name="T", slug="t", api_token_hash="h",
            entitlement_status=EntitlementStatus.active,
        )
        self.session.add(tenant)
        self.session.commit()
        client = ContentClient(tenant_id=tenant.id, name="C")
        self.session.add(client)
        self.session.commit()
        campaign = ContentCampaign(client_id=client.id, name="Camp", horizon_days=7)
        self.session.add(campaign)
        self.session.commit()

        self.piece = ContentPiece(
            campaign_id=campaign.id,
            type=ContentPieceType.image,
            status=ContentPieceStatus.approved,
        )
        self.session.add(self.piece)
        self.session.commit()
        self.session.add(
            ContentAsset(
                tenant_id=tenant.id,
                client_id=client.id,
                content_piece_id=self.piece.id,
                type=ContentAssetType.image,
                url="https://x/asset.png",
                is_intermediate=False,
            )
        )
        self.account = ContentSocialAccount(
            client_id=client.id,
            platform="x",
            external_account_id="acc-1",
            credentials_encrypted="enc",
            status="active",
        )
        self.session.add(self.account)
        self.session.commit()
        self.session.refresh(self.piece)
        self.session.refresh(self.account)

    def _resolve_and_claim(self):
        accepted, rejected = publications_service.resolve_publication_request(
            self.session, piece=self.piece, social_account_ids=[self.account.id]
        )
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].status, PublicationStatus.queued)

        claimed = dispatcher.claim_due_publications(self.session, limit=10)
        self.assertEqual([row.id for row in claimed], [accepted[0].id])
        self.assertEqual(claimed[0].status, PublicationStatus.running)
        self.assertEqual(claimed[0].attempt_count, 1)
        return claimed[0]


class TestHappyPath(PublishChainIntegrationTestCase):
    def test_claim_then_execute_marks_succeeded_and_posts_the_piece(self):
        row = self._resolve_and_claim()

        adapter = MagicMock()
        adapter.publish.return_value = MagicMock(
            platform_post_id="post-1", platform_post_url="https://x.com/post-1"
        )
        with patch.object(dispatcher, "get_adapter", return_value=adapter):
            with patch.object(dispatcher, "load_credentials", return_value={}):
                dispatcher.execute_claimed_publication(self.session, row.id)

        self.session.refresh(row)
        self.session.refresh(self.piece)
        self.assertEqual(row.status, PublicationStatus.succeeded)
        self.assertEqual(row.platform_post_id, "post-1")
        self.assertEqual(self.piece.status, ContentPieceStatus.posted)
        self.assertIsNotNone(self.piece.posted_at)


class TestRetryableFailure(PublishChainIntegrationTestCase):
    def test_claim_then_execute_reschedules_without_getting_stuck_running(self):
        row = self._resolve_and_claim()

        adapter = MagicMock()
        adapter.publish.side_effect = PublicationError(
            PublicationErrorCode.rate_limit, "slow down"
        )
        with patch.object(dispatcher, "get_adapter", return_value=adapter):
            with patch.object(dispatcher, "load_credentials", return_value={}):
                dispatcher.execute_claimed_publication(self.session, row.id)

        self.session.refresh(row)
        self.assertEqual(row.status, PublicationStatus.retrying)
        self.assertIsNotNone(row.next_run_at)
        self.assertEqual(row.attempt_count, 1)

        # A due retry must be reclaimable by a later claim tick — the seam
        # this whole test exists to prove is wired correctly end to end.
        row.next_run_at = datetime(2000, 1, 1)
        self.session.add(row)
        self.session.commit()
        reclaimed = dispatcher.claim_due_publications(self.session, limit=10)
        self.assertEqual([r.id for r in reclaimed], [row.id])
        self.assertEqual(reclaimed[0].attempt_count, 2)


if __name__ == "__main__":
    unittest.main()
