import unittest


from paperpilot.tools.basic_tools.daily_arxiv import (
    match_any_keyword_in_title_or_abstract,
    normalize_arxiv_category,
    normalize_daily_arxiv_settings,
)


class TestDailyArxivKeywordFilter(unittest.TestCase):
    def test_empty_keyword_list(self):
        matched = match_any_keyword_in_title_or_abstract(
            "Some Title", "Some Abstract", []
        )
        self.assertEqual(matched, [])

    def test_case_insensitive_match(self):
        matched = match_any_keyword_in_title_or_abstract(
            "An MLLM Survey", "We study mllm systems.", ["MLLM"]
        )
        self.assertEqual(matched, ["MLLM"])

    def test_hyphen_and_whitespace_normalization(self):
        matched = match_any_keyword_in_title_or_abstract(
            "A 3D-Reconstruction Approach", "", ["3D Reconstruction"]
        )
        self.assertEqual(matched, ["3D Reconstruction"])

    def test_matches_in_abstract(self):
        matched = match_any_keyword_in_title_or_abstract(
            "Title", "We propose a new agent framework.", ["Agent"]
        )
        self.assertEqual(matched, ["Agent"])

    def test_category_normalization_preserves_arxiv_format(self):
        self.assertEqual(normalize_arxiv_category("cs.cv"), "cs.CV")
        self.assertEqual(normalize_arxiv_category("  cs.AI  "), "cs.AI")
        self.assertEqual(normalize_arxiv_category("stat.ml"), "stat.ML")

    def test_settings_normalization_applies_to_categories(self):
        normalized = normalize_daily_arxiv_settings(
            {
                "categories": ["cs.cv", "cs.AI", "cs.cv", "stat.ml"],
                "keywordList": ["  Agent  ", "", None, "LLM"],
            }
        )
        self.assertEqual(normalized["categories"], ["cs.CV", "cs.AI", "stat.ML"])
        self.assertEqual(normalized["keywordList"], ["Agent", "LLM"])


if __name__ == "__main__":
    unittest.main()
