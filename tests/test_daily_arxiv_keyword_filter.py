import unittest


from resophy.tools.basic_tools.daily_arxiv import match_any_keyword_in_title_or_abstract


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


if __name__ == "__main__":
    unittest.main()

