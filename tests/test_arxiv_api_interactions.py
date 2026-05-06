import unittest
from types import SimpleNamespace
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import pytest
import requests
from unittest.mock import MagicMock, patch

from paperpilot.tools.basic_tools.arxiv_client import get_bibtex_enhanced
from paperpilot.tools.basic_tools.upload_paper import (
    fetch_paper_by_arxiv_id_fast,
    search_arxiv_by_title_and_author_fast,
    search_arxiv_by_title_only_fast,
)


ARXIV_ID = "1706.03762"
ARXIV_TITLE = "Attention Is All You Need"
ARXIV_AUTHOR = "Ashish Vaswani"


class FakeSearch:
    def __init__(self, query=None, id_list=None, max_results=None, sort_by=None, sort_order=None):
        self.query = query
        self.id_list = id_list
        self.max_results = max_results
        self.sort_by = sort_by
        self.sort_order = sort_order


class FakeClient:
    def __init__(self, paper=None):
        self.paper = paper
        self.last_search = None

    def results(self, search):
        self.last_search = search
        return iter([self.paper] if self.paper else [])


def make_paper(*, entry_id="https://arxiv.org/abs/2502.05383v1", title="A Paper"):
    return SimpleNamespace(
        entry_id=entry_id,
        title=title,
        summary="This is the abstract.",
        published=SimpleNamespace(year=2025, isoformat=lambda: "2025-02-01T12:00:00"),
        pdf_url="https://arxiv.org/pdf/2502.05383v1.pdf",
        primary_category="cs.CV",
        categories=["cs.CV", "cs.AI"],
        authors=[SimpleNamespace(name="Alice"), SimpleNamespace(name="Bob")],
    )


class TestArxivApiFormats(unittest.TestCase):
    @pytest.mark.integration
    def test_arxiv_atom_api_returns_expected_metadata(self):
        response = requests.get(
            "https://export.arxiv.org/api/query",
            params={"id_list": ARXIV_ID},
            timeout=20,
        )
        self.assertEqual(response.status_code, 200)

        root = ET.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        self.assertIsNotNone(entry)

        title = entry.findtext("atom:title", default="", namespaces=ns).strip()
        authors = [
            author.findtext("atom:name", default="", namespaces=ns).strip()
            for author in entry.findall("atom:author", ns)
        ]
        authors = [a for a in authors if a]
        category_terms = [
            cat.attrib.get("term")
            for cat in entry.findall("atom:category", ns)
            if cat.attrib.get("term")
        ]

        self.assertEqual(title, ARXIV_TITLE)
        self.assertGreaterEqual(len(authors), 1)
        self.assertIn("cs.CL", category_terms)


class TestArxivApiMockedBehavior(unittest.TestCase):
    def test_fetch_paper_by_arxiv_id_fast_uses_arxiv_client(self):
        fake_client = FakeClient(make_paper())
        with patch(
            "paperpilot.tools.basic_tools.upload_paper.arxiv.Client",
            return_value=fake_client,
        ), patch(
            "paperpilot.tools.basic_tools.upload_paper.arxiv.Search",
            FakeSearch,
        ):
            result = fetch_paper_by_arxiv_id_fast("arXiv:2502.05383v1")

        self.assertIsNotNone(result)
        self.assertEqual(result["arxiv_id"], "2502.05383")
        self.assertEqual(result["title"], "A Paper")
        self.assertEqual(result["authors"], "Alice, Bob")
        self.assertEqual(result["primary_category"], "cs.CV")
        self.assertEqual(fake_client.last_search.id_list, ["2502.05383"])

    def test_search_arxiv_by_title_and_author_fast_builds_query(self):
        fake_client = FakeClient(make_paper(entry_id="https://arxiv.org/abs/2502.05383v2"))
        with patch(
            "paperpilot.tools.basic_tools.upload_paper.arxiv.Client",
            return_value=fake_client,
        ), patch(
            "paperpilot.tools.basic_tools.upload_paper.arxiv.Search",
            FakeSearch,
        ):
            result = search_arxiv_by_title_and_author_fast("A: Better Title", "Alice")

        self.assertIsNotNone(result)
        self.assertEqual(
            fake_client.last_search.query,
            'ti:"A  Better Title" AND au:"Alice"',
        )
        self.assertEqual(result["arxiv_id"], "2502.05383")

    def test_search_arxiv_by_title_only_fast_builds_query(self):
        fake_client = FakeClient(make_paper(entry_id="https://arxiv.org/abs/2502.05383v3"))
        with patch(
            "paperpilot.tools.basic_tools.upload_paper.arxiv.Client",
            return_value=fake_client,
        ), patch(
            "paperpilot.tools.basic_tools.upload_paper.arxiv.Search",
            FakeSearch,
        ):
            result = search_arxiv_by_title_only_fast("My Title")

        self.assertIsNotNone(result)
        self.assertEqual(fake_client.last_search.query, 'ti:"My Title"')
        self.assertEqual(result["arxiv_id"], "2502.05383")

    def test_get_bibtex_enhanced_prefers_dblp_result(self):
        with patch(
            "paperpilot.tools.basic_tools.arxiv_client.get_bibtex_from_dblp",
            return_value="@article{dblp}",
        ), patch(
            "paperpilot.tools.basic_tools.arxiv_client.urllib.request.urlopen",
        ) as fake_urlopen:
            result = get_bibtex_enhanced("A Paper", "Alice Bob", "2502.05383")

        self.assertEqual(result, "@article{dblp}")
        fake_urlopen.assert_not_called()

    def test_get_bibtex_enhanced_falls_back_to_arxiv(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"@article{arxiv}"
        with patch(
            "paperpilot.tools.basic_tools.arxiv_client.get_bibtex_from_dblp",
            return_value=None,
        ), patch(
            "paperpilot.tools.basic_tools.arxiv_client.urllib.request.urlopen",
            return_value=response,
        ):
            result = get_bibtex_enhanced("A Paper", "Alice Bob", "2502.05383")

        self.assertEqual(result, "@article{arxiv}")

    def test_get_bibtex_enhanced_returns_none_when_all_sources_fail(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"Error: not found"
        with patch(
            "paperpilot.tools.basic_tools.arxiv_client.get_bibtex_from_dblp",
            return_value=None,
        ), patch(
            "paperpilot.tools.basic_tools.arxiv_client.urllib.request.urlopen",
            return_value=response,
        ):
            result = get_bibtex_enhanced("A Paper", "Alice Bob", "2502.05383")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
