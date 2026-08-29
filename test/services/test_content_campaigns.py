import unittest
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.services.content import campaigns as campaigns_service


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


if __name__ == "__main__":
    unittest.main()
