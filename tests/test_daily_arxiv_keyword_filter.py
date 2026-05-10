import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch


from paperpilot.database.dao.paper_dao import PaperDAO
from paperpilot.tools.basic_tools.daily_arxiv import (
    DailyArxivManager,
    DEFAULT_MAX_NEW_PAPERS_PER_CATEGORY_PER_FETCH,
    DEFAULT_REPLACEMENT_CANDIDATE_LIMIT,
    build_daily_arxiv_replacement_payload,
    calculate_daily_category_quotas,
    get_arxiv_category_weight,
    should_keep_paper_by_institution_tier,
    match_any_keyword_in_title_or_abstract,
    normalize_arxiv_category,
    normalize_arxiv_category_ratios,
    normalize_daily_arxiv_settings,
    validate_arxiv_category_ratios,
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
        self.assertEqual(
            normalized["maxNewPapersPerCategoryPerFetch"],
            DEFAULT_MAX_NEW_PAPERS_PER_CATEGORY_PER_FETCH,
        )
        self.assertEqual(
            normalized["replacementCandidateLimit"],
            DEFAULT_REPLACEMENT_CANDIDATE_LIMIT,
        )
        self.assertEqual(sum(normalized["categoryQuotas"].values()), 2)

    def test_settings_normalization_clamps_max_daily_papers(self):
        normalized = normalize_daily_arxiv_settings({"maxDailyPapers": 9999})
        self.assertEqual(normalized["maxDailyPapers"], 500)

        normalized = normalize_daily_arxiv_settings({"maxDailyPapers": 0})
        self.assertEqual(normalized["maxDailyPapers"], 1)

    def test_replacement_payload_includes_institution_tiers(self):
        payload = build_daily_arxiv_replacement_payload(
            {
                "arxiv_id": "2603.00001",
                "title": "Candidate Paper",
                "authors": ["Alice"],
                "abstract": "A useful system paper.",
                "fetch_category": "cs.OS",
                "affiliations": ["MIT"],
            },
            [
                {
                    "arxiv_id": "2603.00000",
                    "title": "Existing Paper",
                    "authors": ["Bob"],
                    "abstract": "An existing paper.",
                    "fetch_category": "cs.OS",
                    "affiliations": ["Example Lab"],
                }
            ],
            {
                "S": ["MIT", " MIT "],
                "A": ["CMU"],
                "B": [],
                "C": ["Other labs"],
            },
        )

        self.assertEqual(payload["institution_tiers"]["S"], ["MIT"])
        self.assertEqual(payload["institution_tiers"]["A"], ["CMU"])
        self.assertEqual(payload["institution_tiers"]["C"], ["Other labs"])
        self.assertEqual(payload["candidate"]["affiliations"], ["MIT"])

    def test_institution_tier_filter_respects_quality_strategy(self):
        quality_config = {
            "strategy": "strict",
            "strategies": {
                "strict": {
                    "minInstitutionTier": "A",
                    "allowUnknownInstitutions": False,
                }
            },
            "institutionTiers": {
                "S": ["MIT"],
                "A": ["CMU"],
                "B": ["Stanford"],
                "C": ["Other reputable universities"],
            },
        }

        keep, _reason = should_keep_paper_by_institution_tier(
            {"affiliations": ["MIT"]}, quality_config
        )
        self.assertTrue(keep)

        keep, reason = should_keep_paper_by_institution_tier(
            {"affiliations": ["Stanford"]}, quality_config
        )
        self.assertFalse(keep)
        self.assertIn("below minimum", reason)

        keep, reason = should_keep_paper_by_institution_tier(
            {"affiliations": ["Unknown Lab"]}, quality_config
        )
        self.assertFalse(keep)
        self.assertIn("unknown", reason)

    def test_balanced_institution_tier_filter_allows_unknown_but_rejects_low_tier(self):
        quality_config = {
            "strategy": "balanced",
            "strategies": {
                "balanced": {
                    "minInstitutionTier": "B",
                    "allowUnknownInstitutions": True,
                }
            },
            "institutionTiers": {
                "S": ["MIT"],
                "A": ["CMU"],
                "B": ["Stanford"],
                "C": ["Other Lab"],
            },
        }

        keep, _reason = should_keep_paper_by_institution_tier(
            {"affiliations": ["Unknown Lab"]}, quality_config
        )
        self.assertTrue(keep)

        keep, reason = should_keep_paper_by_institution_tier(
            {"affiliations": ["Other Lab"]}, quality_config
        )
        self.assertFalse(keep)
        self.assertIn("below minimum", reason)

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

    def test_explicit_category_ratios_override_weighted_quotas(self):
        quotas = calculate_daily_category_quotas(
            ["cs.AI", "cs.DC"],
            10,
            {"cs.AI": 70, "cs.DC": 30},
        )

        self.assertEqual(quotas, {"cs.AI": 7, "cs.DC": 3})

    def test_category_ratio_validation_requires_exact_total_when_explicit(self):
        self.assertIsNone(validate_arxiv_category_ratios({}, ["cs.AI", "cs.DC"]))
        self.assertIsNone(
            validate_arxiv_category_ratios(
                {"cs.AI": 60, "cs.DC": 40}, ["cs.AI", "cs.DC"]
            )
        )

        over_total = validate_arxiv_category_ratios(
            {"cs.AI": 70, "cs.DC": 40}, ["cs.AI", "cs.DC"]
        )
        under_total = validate_arxiv_category_ratios(
            {"cs.AI": 70}, ["cs.AI", "cs.DC"]
        )

        self.assertIn("exceeds 100%", over_total)
        self.assertIn("exactly 100%", under_total)

    def test_category_ratios_are_normalized_to_current_categories(self):
        ratios = normalize_arxiv_category_ratios(
            {"cs.ai": "65", "cs.DC": 35, "cs.OS": 10},
            ["cs.AI", "cs.DC"],
        )

        self.assertEqual(ratios, {"cs.AI": 65.0, "cs.DC": 35.0})

    def test_settings_normalization_applies_explicit_category_ratios(self):
        normalized = normalize_daily_arxiv_settings(
            {
                "categories": ["cs.ai", "cs.DC"],
                "categoryRatios": {"cs.AI": 80, "cs.DC": 20},
                "maxDailyPapers": 10,
            }
        )

        self.assertEqual(normalized["categoryRatios"], {"cs.AI": 80.0, "cs.DC": 20.0})
        self.assertEqual(normalized["categoryQuotas"], {"cs.AI": 8, "cs.DC": 2})

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

    def test_fetch_papers_filters_by_institution_tier_and_continues_candidates(self):
        class FakeAuthor:
            def __init__(self, name):
                self.name = name

        class FakeResult:
            def __init__(self, index):
                self.entry_id = f"https://arxiv.org/abs/2604.{index:05d}"
                self.authors = [FakeAuthor("Alice")]
                self.categories = ["cs.CV"]
                self.primary_category = "cs.CV"
                self.published = datetime(2026, 4, 1, 12, 0, 0)
                self.updated = self.published
                self.title = f"Paper {index}"
                self.summary = "An AI paper."
                self.pdf_url = f"https://arxiv.org/pdf/2604.{index:05d}.pdf"
                self.comment = None
                self.journal_ref = None

        class FakeClient:
            def results(self, _search):
                return [FakeResult(i) for i in range(3)]

        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "daily_arxiv_settings.json")
            settings = {
                "enabled": True,
                "categories": ["cs.CV"],
                "maxDailyPapers": 2,
                "maxNewPapersPerCategoryPerFetch": 2,
                "replacementCandidateLimit": 0,
                "qualityConfig": {
                    "strategy": "strict",
                    "strategies": {
                        "strict": {
                            "minInstitutionTier": "A",
                            "allowUnknownInstitutions": False,
                        }
                    },
                    "institutionTiers": {
                        "S": ["MIT"],
                        "A": ["CMU"],
                        "B": ["Stanford"],
                        "C": [],
                    },
                },
            }
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f)

            manager = DailyArxivManager(base_dir=tmpdir, settings_file=settings_file)
            manager.client = FakeClient()
            manager.set_llm_config_callback(
                lambda: {
                    "llmBaseUrl": "http://example.test/v1",
                    "llmApiKey": "token",
                    "llmModel": "test-model",
                }
            )

            def fake_download(paper, _cat_dir, _progress):
                path = os.path.join(tmpdir, f"{paper.arxiv_id}.pdf")
                with open(path, "wb") as fp:
                    fp.write(b"%PDF-1.4 fake")
                return path

            affiliations_by_id = {
                "2604.00000": ["Unknown Lab"],
                "2604.00001": ["MIT"],
                "2604.00002": ["CMU"],
            }

            downloaded_ids = []
            manager._download_pdf = fake_download
            manager._generate_thumbnail = lambda *args, **kwargs: None
            manager._download_pdf_first_page_text = lambda paper: paper.arxiv_id
            manager._extract_affiliations_from_first_page_text = (
                lambda first_page_text, *_args, **_kwargs: {
                    "affiliations": affiliations_by_id[first_page_text],
                    "countries": [],
                    "homepage": None,
                    "github": None,
                }
            )

            def tracked_download(paper, cat_dir, progress):
                downloaded_ids.append(paper.arxiv_id)
                return fake_download(paper, cat_dir, progress)

            manager._download_pdf = tracked_download

            saved = []
            manager._save_paper = lambda paper_dict, _cat_dir: saved.append(paper_dict)

            with (
                patch.object(PaperDAO, "get_daily_papers", return_value=[]),
                patch.object(PaperDAO, "get_paper_by_arxiv_id", return_value=None),
                patch(
                    "paperpilot.tools.basic_tools.daily_arxiv.get_arxiv_announce_date",
                    return_value=datetime(2026, 4, 2),
                ),
                patch(
                    "paperpilot.tools.basic_tools.daily_arxiv.extract_summary_and_keywords_with_llm",
                    return_value={"summary": "summary", "keywords": []},
                ),
            ):
                papers = manager.fetch_papers("cs.CV", date_str="2026-04-02")

            self.assertEqual(
                [paper["arxiv_id"] for paper in papers],
                ["2604.00001", "2604.00002"],
            )
            self.assertEqual(
                [paper["arxiv_id"] for paper in saved],
                ["2604.00001", "2604.00002"],
            )
            self.assertEqual(downloaded_ids, ["2604.00001", "2604.00002"])
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "2604.00000.pdf")))

    def test_incremental_fetch_does_not_force_fill_unused_quota(self):
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
                    '"maxDailyPapers": 5, '
                    '"maxNewPapersPerCategoryPerFetch": 1, '
                    '"replacementCandidateLimit": 0}'
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
            manager._download_pdf_first_page_text = lambda paper: ""

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
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved_categories.count("cs.DC"), 1)
            self.assertEqual(saved_categories.count("cs.AI"), 1)

    def test_full_quota_can_replace_existing_paper_when_llm_accepts_candidate(self):
        class FakeAuthor:
            def __init__(self, name):
                self.name = name

        class FakeResult:
            def __init__(self, index):
                self.entry_id = f"https://arxiv.org/abs/2603.{index:05d}"
                self.authors = [FakeAuthor("Alice")]
                self.categories = ["cs.AI"]
                self.primary_category = "cs.AI"
                self.published = datetime(2026, 3, 1, 12, 0, 0)
                self.updated = self.published
                self.title = f"New Paper {index}"
                self.summary = "A much more valuable AI paper."
                self.pdf_url = f"https://arxiv.org/pdf/2603.{index:05d}.pdf"
                self.comment = None
                self.journal_ref = None

        class FakeClient:
            def results(self, _search):
                return [FakeResult(1)]

        with tempfile.TemporaryDirectory() as tmpdir:
            old_pdf = os.path.join(tmpdir, "old.pdf")
            with open(old_pdf, "wb") as fp:
                fp.write(b"%PDF-1.4 old")
            settings_file = os.path.join(tmpdir, "daily_arxiv_settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                f.write(
                    '{"enabled": true, "categories": ["cs.AI"], '
                    '"maxDailyPapers": 1, "replacementCandidateLimit": 1}'
                )

            saved = [
                {
                    "id": "daily_2603.00000",
                    "arxiv_id": "2603.00000",
                    "title": "Old Paper",
                    "abstract": "Older, less relevant paper.",
                    "file_path": old_pdf,
                    "fetch_category": "cs.AI",
                    "is_daily": True,
                }
            ]
            deleted = []

            manager = DailyArxivManager(base_dir=tmpdir, settings_file=settings_file)
            manager.client = FakeClient()
            manager.set_llm_config_callback(
                lambda: {
                    "llmBaseUrl": "http://example.test/v1",
                    "llmApiKey": "token",
                    "llmModel": "test-model",
                }
            )

            def fake_download(paper, _cat_dir, _progress):
                path = os.path.join(tmpdir, f"{paper.arxiv_id}.pdf")
                with open(path, "wb") as fp:
                    fp.write(b"%PDF-1.4 new")
                return path

            def fake_save(paper_dict, _cat_dir):
                saved.append(
                    {
                        "id": f"daily_{paper_dict['arxiv_id']}",
                        "arxiv_id": paper_dict["arxiv_id"],
                        "title": paper_dict["title"],
                        "abstract": paper_dict["abstract"],
                        "file_path": paper_dict["local_pdf_path"],
                        "fetch_category": paper_dict["fetch_category"],
                        "is_daily": True,
                    }
                )

            manager._download_pdf = fake_download
            manager._generate_thumbnail = lambda *args, **kwargs: None
            manager._save_paper = fake_save
            manager._download_pdf_first_page_text = lambda paper: ""

            with (
                patch.object(PaperDAO, "get_daily_papers", side_effect=lambda _date: saved),
                patch.object(PaperDAO, "get_paper_by_arxiv_id", return_value=None),
                patch.object(PaperDAO, "delete_paper", side_effect=lambda paper_id: deleted.append(paper_id)),
                patch(
                    "paperpilot.tools.basic_tools.daily_arxiv.get_arxiv_announce_date",
                    return_value=datetime(2026, 3, 2),
                ),
                patch(
                    "paperpilot.tools.basic_tools.daily_arxiv.select_daily_arxiv_replacement_with_llm",
                    return_value={
                        "accept": True,
                        "replace_arxiv_id": "2603.00000",
                        "score": 0.9,
                        "reason": "candidate is stronger",
                    },
                ),
            ):
                papers = manager.fetch_papers("cs.AI", date_str="2026-03-02")

            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["arxiv_id"], "2603.00001")
            self.assertEqual(deleted, ["daily_2603.00000"])
            self.assertFalse(os.path.exists(old_pdf))


if __name__ == "__main__":
    unittest.main()
