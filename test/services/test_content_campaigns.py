import unittest
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.services.content import campaigns as campaigns_service
from app.models.content import ContentCampaign


class TestListCampaignsForTenant(unittest.TestCase):
    def test_returns_campaigns_across_clients(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["campaign-a", "campaign-b"]

        result = campaigns_service.list_campaigns_for_tenant(session, tenant_id=1)

        self.assertEqual(result, ["campaign-a", "campaign-b"])
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("TENANT_ID = 1", compiled)


class TestUpdateCampaign(unittest.TestCase):
    def test_updates_name_and_horizon(self):
        campaign = ContentCampaign(id=1, client_id=1, name="Old", horizon_days=7)
        session = MagicMock()
        session.exec.return_value.first.return_value = campaign

        result = campaigns_service.update_campaign(
            session, tenant_id=1, campaign_id=1, name="New", horizon_days=14
        )

        self.assertEqual(result.name, "New")
        self.assertEqual(result.horizon_days, 14)
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = campaigns_service.update_campaign(
            session, tenant_id=1, campaign_id=999, name="New"
        )

        self.assertIsNone(result)


class TestArchiveCampaign(unittest.TestCase):
    def test_sets_status_archived(self):
        campaign = ContentCampaign(id=1, client_id=1, name="Acme", status="active")
        session = MagicMock()
        session.exec.return_value.first.return_value = campaign

        result = campaigns_service.archive_campaign(session, tenant_id=1, campaign_id=1)

        self.assertEqual(result.status, "archived")
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = campaigns_service.archive_campaign(session, tenant_id=1, campaign_id=999)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
