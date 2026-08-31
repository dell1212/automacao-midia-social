import unittest

from app.services.content.providers.base import is_policy_error_text


class TestIsPolicyErrorText(unittest.TestCase):
    def test_matches_each_known_keyword_case_insensitively(self):
        for keyword in ("policy", "SAFETY", "Moderation", "prohibited", "BlockList"):
            with self.subTest(keyword=keyword):
                self.assertTrue(is_policy_error_text(f"request rejected: {keyword} violation"))

    def test_unrelated_text_does_not_match(self):
        self.assertFalse(is_policy_error_text("upstream service returned a 500"))

    def test_empty_text_does_not_match(self):
        self.assertFalse(is_policy_error_text(""))


if __name__ == "__main__":
    unittest.main()
