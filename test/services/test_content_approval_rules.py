import unittest
from unittest.mock import MagicMock, patch

from app.models.content import ApprovalAction, ContentApprovalRule
from app.services.content import approval_rules as approval_rules_service


class TestGetApprovalRule(unittest.TestCase):
    def test_returns_rule_when_campaign_belongs_to_tenant(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={}, action=ApprovalAction.auto_approve, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=MagicMock(id=1)):
            result = approval_rules_service.get_approval_rule(session, tenant_id=1, rule_id=1)

        self.assertIs(result, rule)

    def test_returns_none_when_rule_row_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = approval_rules_service.get_approval_rule(session, tenant_id=1, rule_id=999)

        self.assertIsNone(result)

    def test_returns_none_when_campaign_belongs_to_other_tenant(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={}, action=ApprovalAction.auto_approve, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=None):
            result = approval_rules_service.get_approval_rule(session, tenant_id=2, rule_id=1)

        self.assertIsNone(result)


class TestUpdateApprovalRule(unittest.TestCase):
    def test_updates_provided_fields(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={"a": 1}, action=ApprovalAction.require_review,
            priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=MagicMock(id=1)):
            result = approval_rules_service.update_approval_rule(
                session, tenant_id=1, rule_id=1, priority=10, action=ApprovalAction.auto_approve,
            )

        self.assertEqual(result.priority, 10)
        self.assertEqual(result.action, ApprovalAction.auto_approve)
        self.assertEqual(result.condition, {"a": 1})
        session.commit.assert_called_once()


class TestDeleteApprovalRule(unittest.TestCase):
    def test_deletes_and_returns_true_when_found(self):
        rule = ContentApprovalRule(
            id=1, campaign_id=1, condition={}, action=ApprovalAction.auto_approve, priority=0,
        )
        session = MagicMock()
        session.exec.return_value.first.return_value = rule

        with patch.object(approval_rules_service, "get_campaign", return_value=MagicMock(id=1)):
            result = approval_rules_service.delete_approval_rule(session, tenant_id=1, rule_id=1)

        self.assertTrue(result)
        session.delete.assert_called_once_with(rule)
        session.commit.assert_called_once()

    def test_returns_false_when_not_found(self):
        session = MagicMock()
        session.exec.return_value.first.return_value = None

        result = approval_rules_service.delete_approval_rule(session, tenant_id=1, rule_id=999)

        self.assertFalse(result)
        session.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
