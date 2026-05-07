import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch


from paperpilot.database.dao.paper_dao import PaperDAO
from paperpilot.tools.basic_tools.daily_arxiv import (
    DailyArxivManager,
    calculate_daily_category_quotas,
    get_arxiv_category_weight,
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
                "maxDailyPapers": "2",
            }
        )
        self.assertEqual(normalized["categories"], ["cs.CV", "cs.AI", "stat.ML"])
        self.assertEqual(normalized["keywordList"], ["Agent", "LLM"])
        self.assertEqual(normalized["maxDailyPapers"], 2)
        self.assertEqual(sum(normalized["categoryQuotas"].values()), 2)

    def test_settings_normalization_clamps_max_daily_papers(self):
        normalized = normalize_daily_arxiv_settings({"maxDailyPapers": 9999})
        self.assertEqual(normalized["maxDailyPapers"], 500)

        normalized = normalize_daily_arxiv_settings({"maxDailyPapers": 0})
        self.assertEqual(normalized["maxDailyPapers"], 1)

    def test_system_categories_get_higher_quota_weight_than_ai_categories(self):
        self.assertGreater(
            get_arxiv_category_weight("cs.DC"),
            get_arxiv_category_weight("cs.AI"),
        )
        self.assertGreater(
            get_arxiv_category_weight("cs.OS"),
            get_arxiv_category_weight("cs.AI"),
        )

    def test_category_quotas_are_recalculated_from_current_categories(self):
        quotas = calculate_daily_category_quotas(["cs.AI", "cs.DC", "cs.OS"], 30)

        self.assertEqual(sum(quotas.values()), 30)
        self.assertGreater(quotas["cs.DC"], quotas["cs.AI"])
        self.assertGreater(quotas["cs.OS"], quotas["cs.AI"])

        updated_quotas = calculate_daily_category_quotas(["cs.AI", "cs.DC"], 30)
        self.assertEqual(sum(updated_quotas.values()), 30)
        self.assertNotIn("cs.OS", updated_quotas)
        self.assertGreater(updated_quotas["cs.DC"], quotas["cs.DC"])

    def test_fetch_papers_respects_max_daily_papers(self):
        class FakeAuthor:
            def __init__(self, name):
                self.name = name

        class FakeResult:
            def __init__(self, index):
                self.entry_id = f"https://arxiv.org/abs/2601.{index:05d}"
                self.authors = [FakeAuthor("Alice")]
                self.categories = ["cs.CV"]
                self.primary_category = "cs.CV"
                self.published = datetime(2026, 1, 1, 12, 0, 0)
                self.updated = self.published
                self.title = f"Paper {index}"
                self.summary = "An AI paper."
                self.pdf_url = f"https://arxiv.org/pdf/2601.{index:05d}.pdf"
                self.comment = None
                self.journal_ref = None

        class FakeClient:
            def results(self, _search):
                return [FakeResult(i) for i in range(5)]

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "daily_arxiv_settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                f.write('{"enabled": true, "categories": ["cs.CV"], "maxDailyPapers": 2}')

            manager = DailyArxivManager(base_dir=tmpdir, settings_file=settings_file)
            manager.client = FakeClient()
            manager._download_pdf = lambda paper, cat_dir, progress: os.path.join(
                tmpdir, f"{paper.arxiv_id}.pdf"
            )
            manager._generate_thumbnail = lambda *args, **kwargs: None

            saved = []
            manager._save_paper = lambda paper_dict, cat_dir: saved.append(paper_dict)

            with (
                patch.object(PaperDAO, "get_daily_papers", return_value=[]),
                patch.object(PaperDAO, "get_paper_by_arxiv_id", return_value=None),
                patch(
                    "paperpilot.tools.basic_tools.daily_arxiv.get_arxiv_announce_date",
                    return_value=datetime(2026, 1, 2),
                ),
            ):
                papers = manager.fetch_papers("cs.CV", date_str="2026-01-02")

            self.assertEqual(len(papers), 2)
            self.assertEqual(len(saved), 2)

    def test_two_stage_fetch_refills_unused_niche_category_quota(self):
        class FakeAuthor:
            def __init__(self, name):
                self.name = name

        class FakeResult:
            def __init__(self, category, index):
                safe_category = category.replace(".", "").lower()
                self.entry_id = f"https://arxiv.org/abs/2602.{safe_category}{index}"
                self.authors = [FakeAuthor("Alice")]
                self.categories = [category]
                self.primary_category = category
                self.published = datetime(2026, 2, 1, 12, 0, 0)
                self.updated = self.published
                self.title = f"{category} Paper {index}"
                self.summary = "A systems or AI paper."
                self.pdf_url = f"https://arxiv.org/pdf/2602.{safe_category}{index}.pdf"
                self.comment = None
                self.journal_ref = None

        class FakeClient:
            def results(self, search):
                query = getattr(search, "query", "")
                if "cs.DC" in query:
                    return [FakeResult("cs.DC", 0)]
                if "cs.AI" in query:
                    return [FakeResult("cs.AI", index) for index in range(5)]
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "daily_arxiv_settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                f.write(
                    '{"enabled": true, "categories": ["cs.AI", "cs.DC"], '
                    '"maxDailyPapers": 5}'
                )

            manager = DailyArxivManager(base_dir=tmpdir, settings_file=settings_file)
            manager.client = FakeClient()
            saved = []

            def fake_download(paper, _cat_dir, _progress):
                path = os.path.join(tmpdir, f"{paper.arxiv_id}.pdf")
                with open(path, "wb") as fp:
                    fp.write(b"%PDF-1.4 fake")
                return path

            def fake_save(paper_dict, _cat_dir):
                saved.append(
                    {
                        "arxiv_id": paper_dict["arxiv_id"],
                        "file_path": paper_dict["local_pdf_path"],
                        "fetch_category": paper_dict["fetch_category"],
                    }
                )

            manager._download_pdf = fake_download
            manager._generate_thumbnail = lambda *args, **kwargs: None
            manager._save_paper = fake_save

            with (
                patch.object(PaperDAO, "get_daily_papers", side_effect=lambda _date: saved),
                patch.object(PaperDAO, "get_paper_by_arxiv_id", return_value=None),
                patch(
                    "paperpilot.tools.basic_tools.daily_arxiv.get_arxiv_announce_date",
                    return_value=datetime(2026, 2, 2),
                ),
            ):
                manager.fetch_categories_for_date(
                    ["cs.AI", "cs.DC"], date_str="2026-02-02"
                )

            saved_categories = [paper["fetch_category"] for paper in saved]
            self.assertEqual(len(saved), 5)
            self.assertEqual(saved_categories.count("cs.DC"), 1)
            self.assertEqual(saved_categories.count("cs.AI"), 4)


if __name__ == "__main__":
    unittest.main()
