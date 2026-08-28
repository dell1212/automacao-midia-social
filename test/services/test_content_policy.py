import unittest

from app.models.content import ContentCategory, RiskLevel
from app.services.content import policy


class TestRiskForCategory(unittest.TestCase):
    def test_none_category_is_no_risk(self):
        self.assertEqual(policy.risk_for_category(None), RiskLevel.none)

    def test_medical_is_high_risk(self):
        self.assertEqual(
            policy.risk_for_category(ContentCategory.medical), RiskLevel.high
        )

    def test_pharmaceutical_is_high_risk(self):
        self.assertEqual(
            policy.risk_for_category(ContentCategory.pharmaceutical), RiskLevel.high
        )

    def test_financial_is_medium_risk(self):
        self.assertEqual(
            policy.risk_for_category(ContentCategory.financial), RiskLevel.medium
        )

    def test_every_category_has_a_mapping(self):
        for category in ContentCategory:
            self.assertIsInstance(policy.risk_for_category(category), RiskLevel)

    def test_no_category_maps_to_none_risk(self):
        # `none` is reserved for "no declared category" so the absence of a
        # declaration stays distinguishable from a declared low-risk niche.
        for category in ContentCategory:
            self.assertNotEqual(policy.risk_for_category(category), RiskLevel.none)


class TestClassify(unittest.TestCase):
    def test_high_risk_requires_human_review(self):
        result = policy.classify(ContentCategory.medical)

        self.assertEqual(result.risk_level, RiskLevel.high)
        self.assertTrue(result.requires_human_review)
        self.assertEqual(result.policy_version, policy.POLICY_VERSION)

    def test_medium_risk_does_not_require_human_review(self):
        result = policy.classify(ContentCategory.financial)

        self.assertEqual(result.risk_level, RiskLevel.medium)
        self.assertFalse(result.requires_human_review)

    def test_absent_category_is_inert(self):
        result = policy.classify(None)

        self.assertEqual(result.risk_level, RiskLevel.none)
        self.assertFalse(result.requires_human_review)
        self.assertEqual(result.policy_version, policy.POLICY_VERSION)

    def test_is_deterministic(self):
        self.assertEqual(
            policy.classify(ContentCategory.gambling),
            policy.classify(ContentCategory.gambling),
        )


if __name__ == "__main__":
    unittest.main()
