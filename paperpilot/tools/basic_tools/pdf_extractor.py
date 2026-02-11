from __future__ import annotations

import re
from typing import Dict, Optional

import fitz  # PyMuPDF
import PyPDF2


def preprocess_pdf_text(text: str) -> str:
    """Normalize raw text extracted from PDF pages."""
    if not text:
        return ""
    t = text
    t = re.sub(r"-\s*\n\s*", "", t)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[\t\f]+", " ", t)
    t = re.sub(r"\u00A0", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    return t


def extract_title_by_fontsize(pdf_path: str) -> Optional[str]:
    """
    Extract titles by font size (enhanced version with position filtering)

    Filter out first arXiv Noisy text in sidebar and header footer,
    Then find the largest font size from the remaining text as the title.

    Args:
        pdf_path: PDF file path

    Returns:
        The extracted title, returned if failed None
    """
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            return None

        page = doc[0]  # Only look at the first page
        rect = page.rect
        page_width = rect.width
        page_height = rect.height

        blocks = page.get_text("dict")["blocks"]

        # Collect all text fragments (size, text, bbox)
        all_spans = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if not text:
                        continue
                    # keep: (font size, text content, bounding box)
                    all_spans.append((span["size"], text, span["bbox"]))

        # Sort by font size from largest to smallest, if the sizes are the same sort by vertical position
        all_spans.sort(key=lambda x: (-x[0], x[2][1]))

        if not all_spans:
            doc.close()
            return None

        # Find the real title (filter the noise)
        title_candidates = []
        target_size = 0

        for size, text, bbox in all_spans:
            # 1. Content filtering
            if re.search(r"arxiv:\d{4}\.\d+", text, re.IGNORECASE):
                continue
            if len(text) < 5:  # Titles are generally no shorter than5characters
                continue
            if re.match(r"^[\d\s\.\-]+$", text):  # pure numbers/symbol
                continue
            if text.lower() in ["arxiv", "preprint", "abstract", "introduction"]:
                continue

            # 2. Location filtering
            # arXiv The left sidebar is usually within the page width 15% Within, filter out
            if bbox[2] < page_width * 0.15:
                continue

            # 3. Determine the title
            if target_size == 0:
                target_size = size
                title_candidates.append(text)
            # Same font size (handling multi-line titles)
            elif abs(size - target_size) < 0.5:
                title_candidates.append(text)
            # The font size becomes noticeably smaller and the title section ends
            else:
                break

        doc.close()

        if not title_candidates:
            return None

        # Splice and clean titles
        title = " ".join(title_candidates)
        title = re.sub(r"\s+", " ", title).strip()

        # length check
        if 10 < len(title) < 500:
            return title

        return None

    except Exception as exc:
        print(f"Failed to extract title by font size: {exc}")
        return None


def extract_title_from_text(text: str) -> Optional[str]:
    """Old text extraction method as a downgrade solution"""
    lines = text.strip().split("\n")
    for line in lines[:10]:
        line = line.strip()
        if 10 < len(line) < 300:
            if (
                not line.isupper()
                and re.search(r"[a-zA-Z]", line)
                and not re.search(r"^\d+$", line)
                and not re.search(r"^(page|vol|volume|issue|doi|arxiv)", line.lower())
                and not re.search(r"@|\.com|\.org", line.lower())
            ):
                return line
    return None


def extract_authors_from_text(text: str) -> Optional[str]:
    lines = text.strip().split("\n")
    author_patterns = [
        r"^([A-Z][a-z]+ [A-Z][a-z]+(?:, [A-Z][a-z]+ [A-Z][a-z]+)*)",
        r"^([A-Z]\. [A-Z][a-z]+(?:, [A-Z]\. [A-Z][a-z]+)*)",
        r"^([A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+(?:, [A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+)*)",
    ]
    for line in lines[:15]:
        line = line.strip()
        if 5 < len(line) < 200:
            for pattern in author_patterns:
                match = re.match(pattern, line)
                if match:
                    authors = match.group(1)
                    if re.search(r"[A-Z][a-z]+", authors) and not re.search(
                        r"\d", authors
                    ):
                        return authors
    return None


def extract_affiliation_from_text(text: str) -> Optional[str]:
    lines = text.strip().split("\n")
    institution_keywords = [
        r"university",
        r"college",
        r"institute",
        r"laboratory",
        r"lab",
        r"department",
        r"school",
        r"center",
        r"centre",
        r"research",
        r"academy",
        r"corporation",
        r"company",
        r"inc\.",
        r"ltd\.",
        r"google",
        r"microsoft",
        r"openai",
        r"anthropic",
        r"meta",
        r"stanford",
        r"mit",
        r"harvard",
        r"berkeley",
        r"cambridge",
    ]
    affiliations: list[str] = []
    for line in lines[:20]:
        line_stripped = line.strip()
        if 10 < len(line_stripped) < 300:
            for keyword in institution_keywords:
                if re.search(keyword, line_stripped, re.IGNORECASE):
                    if not re.search(
                        r"^(abstract|introduction|keywords|references)",
                        line_stripped.lower(),
                    ):
                        affiliations.append(line_stripped)
                        break
    unique_affiliations: list[str] = []
    for aff in affiliations:
        if aff not in unique_affiliations:
            unique_affiliations.append(aff)
        if len(unique_affiliations) >= 3:
            break
    return "; ".join(unique_affiliations) if unique_affiliations else None


def extract_abstract_from_text(text: str) -> Optional[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    stop_markers = (
        r"keywords|index\s*terms|subject[s]?|introduction|background|materials\s+and\s+methods|"
        r"methods|results|conclusions|references|acknowledg(e)?ments|1\.|i\.|ii\.|iii\."
        r"|Keywords|Introduction|Background|Methods|Results|Conclusion|References"
    )
    start_markers = r"abstract|summary|Abstract|Summary"
    pattern = rf"(?is)\b(?:{start_markers})\b\s*[:\.\-]?\s*(.+?)(?=\n\s*(?:{stop_markers})\b|\n\n\s*[A-Z][A-Za-z ]+\b|\Z)"
    match = re.search(pattern, normalized)
    if match:
        abstract = re.sub(r"\s+", " ", match.group(1).strip())
        if 50 <= len(abstract) <= 5000 and re.search(r"[a-z]", abstract, re.I):
            return abstract

    lines = normalized.split("\n")
    abstract_started = False
    buffer: list[str] = []
    for line in lines:
        line_stripped = line.strip()
        if not abstract_started:
            if re.match(
                r"(?i)^(abstract|summary|Abstract|Summary)\b\s*[:\-\.]?\s*$", line_stripped
            ) or re.match(
                r"(?i)^(abstract|summary|Abstract|Summary)\b\s*[:\-\.]?",
                line_stripped,
            ):
                after = re.sub(
                    r"(?i)^(abstract|summary|Abstract|Summary)\b\s*[:\-\.]?\s*",
                    "",
                    line_stripped,
                )
                if after:
                    buffer.append(after)
                abstract_started = True
            continue
        else:
            if re.match(rf"(?i)^\s*(?:{stop_markers})\b", line_stripped):
                break
            buffer.append(line)

    candidate = re.sub(r"\s+", " ", " ".join(buffer)).strip()
    if 50 <= len(candidate) <= 5000 and re.search(r"[a-z]", candidate, re.I):
        return candidate

    paragraphs = re.split(r"\n\s*\n", normalized)
    for paragraph in paragraphs[:8]:
        p = re.sub(r"\s+", " ", paragraph.strip())
        if (
            120 <= len(p) <= 5000
            and not re.match(
                r"(?i)^(keywords|index\s*terms|introduction|references|acknowledg(e)?ments|References|Introduction|Keywords)",
                p,
            )
            and p.count(".") >= 2
        ):
            return p
    return None
