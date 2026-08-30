import unittest
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from app.services.content import audit


class TestWriteAuditLog(unittest.TestCase):
    def test_details_defaults_to_none(self):
        session = MagicMock()

        entry = audit.write_audit_log(
            session,
            tenant_id=1,
            entity_type="content_piece",
            entity_id=10,
            action="approved",
            actor="user:u1",
        )

        self.assertIsNone(entry.details)
        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_details_is_persisted_when_given(self):
        session = MagicMock()
        details = {"generation_prompt": {"before": "a cat", "after": "a dog"}}

        entry = audit.write_audit_log(
            session,
            tenant_id=1,
            entity_type="content_piece",
            entity_id=10,
            action="edited",
            actor="user:u1",
            details=details,
        )

        self.assertEqual(entry.details, details)


class TestListAuditLog(unittest.TestCase):
    def test_filters_by_tenant_entity_type_and_entity_id(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = ["row"]

        result = audit.list_audit_log(
            session, tenant_id=1, entity_type="content_piece", entity_id=10
        )

        self.assertEqual(result, ["row"])
        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("TENANT_ID = 1", compiled)
        self.assertIn("ENTITY_TYPE = 'CONTENT_PIECE'", compiled)
        self.assertIn("ENTITY_ID = 10", compiled)

    def test_defaults_to_tenant_only_filter(self):
        session = MagicMock()
        session.exec.return_value.all.return_value = []

        audit.list_audit_log(session, tenant_id=1)

        statement = session.exec.call_args.args[0]
        compiled = str(
            statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        ).upper()
        self.assertIn("TENANT_ID = 1", compiled)
        self.assertNotIn("ENTITY_TYPE = ", compiled)


if __name__ == "__main__":
    unittest.main()
