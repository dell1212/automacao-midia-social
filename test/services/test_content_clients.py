import unittest
from unittest.mock import MagicMock

from app.models.content import ContentClient
from app.services.content import clients as clients_service


class TestUpdateClient(unittest.TestCase):
    def test_updates_name_when_found(self):
        client = ContentClient(id=1, tenant_id=1, name="Old Name")
        session = MagicMock()
        session.exec.return_value.first.return_value = client

        result = clients_service.update_client(
            session, tenant_id=1, client_id=1, name="New Name"
        )

        self.assertEqual(result.name, "New Name")
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = clients_service.update_client(
            session, tenant_id=1, client_id=999, name="New Name"
        )

        self.assertIsNone(result)


class TestDeactivateClient(unittest.TestCase):
    def test_sets_is_active_false(self):
        client = ContentClient(id=1, tenant_id=1, name="Acme", is_active=True)
        session = MagicMock()
        session.exec.return_value.first.return_value = client

        result = clients_service.deactivate_client(session, tenant_id=1, client_id=1)

        self.assertFalse(result.is_active)
        session.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = clients_service.deactivate_client(session, tenant_id=1, client_id=999)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
