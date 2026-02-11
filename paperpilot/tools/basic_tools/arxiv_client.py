"""
Use official arxiv Enhanced version of the library arXiv client
Provide more complete thesis information, including BibTeX
priority use DBLP get BibTeX, use after failure arXiv
"""

from __future__ import annotations

import re
import urllib.request
from typing import Optional

import arxiv
import requests


def _extract_author_names(authors_str: str, max_authors: int = 3) -> str:
    """
    Extract from author string before N author's last name

    Args:
        authors_str: Author string, in the format of "First Last, First Last, ..."
        max_authors: Maximum number of authors extracted

    Returns:
        forward N Last names of authors, separated by spaces
    """
    if not authors_str:
        return ""

    # split author
    authors = [a.strip() for a in authors_str.split(",")]
    author_names = []

    for author in authors[:max_authors]:
        # Extract last name (last word)
        parts = author.split()
        if parts:
            # Take the last word as the last name
            last_name = parts[-1]
            author_names.append(last_name)

    return " ".join(author_names)


def get_bibtex_from_dblp(title: str, authors: Optional[str] = None) -> Optional[str]:
    """
    pass DBLP API Get the paper BibTeX

    Args:
        title: Paper title
        authors: Author string (optional), in the format: "First Last, First Last, ..."

    Returns:
        Returns if successful BibTeX String, returned on failure None
    """
    try:
        # Extract the last names of the first three authors
        author_query = ""
        if authors:
            author_names = _extract_author_names(authors, max_authors=3)
            if author_names:
                author_query = author_names

        # Construct a search query
        if author_query:
            query_string = f"{title} {author_query}"
        else:
            query_string = title

        search_url = "https://dblp.org/search/publ/api"
        params = {"q": query_string, "format": "json", "h": 1}

        print(f"[DBLP] search: [{query_string}]")

        # Set timeout
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Parse search results
        try:
            hits = data["result"]["hits"]["hit"]
        except KeyError:
            print("[DBLP] Return data format exception")
            return None

        if not hits:
            print("[DBLP] No relevant papers found")
            return None

        # get BibTeX Key
        first_hit = hits[0]["info"]
        paper_key = first_hit["key"]
        bib_url = f"https://dblp.org/rec/{paper_key}.bib"

        # get BibTeX
        bib_response = requests.get(bib_url, params={"view": 0}, timeout=10)
        bib_response.raise_for_status()

        bibtex = bib_response.text
        print(f"[DBLP] successfully obtained BibTeX")
        return bibtex

    except requests.exceptions.RequestException as e:
        print(f"[DBLP] Network request error: {e}")
        return None
    except Exception as e:
        print(f"[DBLP] An error occurred: {e}")
        return None


def get_bibtex_enhanced(
    title: str, authors: Optional[str] = None, arxiv_id: Optional[str] = None
) -> Optional[str]:
    """
    Get the paper BibTeX, take priority DBLP, use after failure arXiv

    Args:
        title: Paper title
        authors: Author string (optional)
        arxiv_id: arXiv ID(optional) as a downgrade option

    Returns:
        BibTeX String, returned if both fail None
    """
    # Try first DBLP(More accurate, especially for published papers)
    if title:
        bibtex = get_bibtex_from_dblp(title, authors)
        if bibtex:
            return bibtex

    # DBLP fails if there is arXiv ID, try to start from arXiv get
    if arxiv_id:
        try:
            bibtex_url = f"https://arxiv.org/bibtex/{arxiv_id}"
            with urllib.request.urlopen(bibtex_url, timeout=10) as response:
                bibtex = response.read().decode("utf-8")
                if bibtex and not bibtex.startswith("Error"):
                    print(f"[arXiv] successfully obtained BibTeX (ID: {arxiv_id})")
                    return bibtex
        except Exception as exc:
            print(f"[arXiv] get BibTeX fail: {exc}")

    print("[BibTeX] All sources fail")
    return None
