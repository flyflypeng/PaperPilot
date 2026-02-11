from __future__ import annotations

import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Protocol

import requests
from flask import Flask, jsonify, request

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import PaperStore
from paperpilot.database.dao.user_data_dao import ReadingListDAO
from paperpilot.tools.basic_tools.upload_paper import (
    fetch_bibtex_from_dblp, fetch_paper_by_arxiv_id_fast)


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[list[str]] = None,
    ) -> Optional[list[str]]: ...


class CreateCategoryFolderFn(Protocol):
    def __call__(self, category_path: list[str]) -> str: ...


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


def _extract_arxiv_id_from_url(url: str) -> Optional[str]:
    """from URL extracted from arXiv ID"""
    patterns = [
        r"arxiv\.org/pdf/([\d.]+(?:v\d+)?)",
        r"arxiv\.org/abs/([\d.]+(?:v\d+)?)",
        r"^([\d.]+(?:v\d+)?)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            arxiv_id = match.group(1)
            if "v" in arxiv_id:
                arxiv_id = arxiv_id.split("v")[0]
            return arxiv_id
    return None


def _download_arxiv_pdf(arxiv_id: str) -> Optional[tuple[bytes, str]]:
    """download arXiv PDF(Priority to use export.arxiv.org）"""
    # Try first export.arxiv.org
    pdf_urls = [
        f"https://export.arxiv.org/pdf/{arxiv_id}.pdf",
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    ]

    for pdf_url in pdf_urls:
        try:
            print(f"Removing from arXiv download PDF: {pdf_url}")
            response = requests.get(pdf_url, timeout=30, stream=True)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                print(f"warn: Content-Type no PDF: {content_type}")
            pdf_content = response.content
            filename = f"{arxiv_id}.pdf"
            print(f"Successfully downloaded PDF, size: {len(pdf_content)} bytes")
            return pdf_content, filename
        except requests.exceptions.RequestException as exc:
            print(f"from {pdf_url} Download failed: {exc}")
            continue

    print(f"all URL All downloads failed")
    return None


def _clean_filename(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = text
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 100:
        cleaned = cleaned[:100] + "..."
    return cleaned or None


def register_update_from_url_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    reading_list_file: str,
    reading_list_temp_dir: str,
    paper_store: PaperStore,
) -> None:
    def _add_to_reading_list(paper_id: str) -> None:
        ReadingListDAO.add_item(paper_id, datetime.now().isoformat())

    def _fetch_dblp_bibtex_background(
        paper_id: str,
        title: str,
        authors: str,
        arxiv_id: str,
        file_path: str,
        category_id: str,
        category_path: list[str],
    ):
        """Background acquisition DBLP BibTeX and update the paper"""
        try:
            print(f"[Backstage DBLP] Start getting BibTeX: {title[:50]}...")
            bibtex = fetch_bibtex_from_dblp(title, authors, arxiv_id)

            if bibtex:
                paper = paper_store.get(paper_id)
                if paper:
                    paper.bibtex = bibtex
                    paper_store.upsert(
                        paper, category_id=category_id, category_path=category_path
                    )
                    save_paper_metadata(file_path, paper)
                    print(f"[Backstage DBLP] ✅ BibTeX updated: {paper_id}")
                else:
                    print(f"[Backstage DBLP] ❌ Paper not found: {paper_id}")
            else:
                print(f"[Backstage DBLP] ❌ Not obtained BibTeX")
        except Exception as exc:
            print(f"[Backstage DBLP] ❌ get BibTeX fail: {exc}")

    @app.route("/api/upload/arxiv", methods=["POST"])
    def api_upload_arxiv():
        """from arXiv URL Download and import PDF(quick return,DBLP background acquisition)"""
        try:
            data = request.json or {}
            arxiv_url = data.get("arxiv_url", "").strip()
            category_id = data.get("category_id")
            use_temp_dir = data.get("use_temp_dir", False)  # Whether to use the temporary directory of the to-be-read list

            if not arxiv_url:
                return jsonify({"success": False, "error": "Not provided arXiv URL"}), 400

            # If using temp Directory, use directly temp directory path
            if use_temp_dir:
                category_folder = reading_list_temp_dir
                category_path = ["Root", "_ReadingListTemp"]
                category_id = "reading_list_temp"  # Use special ID
            else:
                if not category_id:
                    return jsonify({"success": False, "error": "No category selected"}), 400

                categories = get_categories()
                category_path = get_category_path(categories, category_id)

                if not category_path:
                    return jsonify({"success": False, "error": "Category not found"}), 404

                category_folder = create_category_folder(category_path[1:])

            arxiv_id = _extract_arxiv_id_from_url(arxiv_url)
            if not arxiv_id:
                return (
                    jsonify({"success": False, "error": "Unable to access from URL extracted from arXiv ID"}),
                    400,
                )

            print(f"extracted arXiv ID: {arxiv_id}")

            result = _download_arxiv_pdf(arxiv_id)
            if not result:
                return jsonify({"success": False, "error": "download PDF fail"}), 500

            pdf_content, filename = result
            file_path = os.path.join(category_folder, filename)

            counter = 1
            original_filename = filename
            while os.path.exists(file_path):
                name, ext = os.path.splitext(original_filename)
                filename = f"{name}_{counter}{ext}"
                file_path = os.path.join(category_folder, filename)
                counter += 1

            with open(file_path, "wb") as f:
                f.write(pdf_content)

            print(f"PDF saved to: {file_path}")

            # 【Get it quickly】only from arXiv API Get information without waiting DBLP
            metadata = fetch_paper_by_arxiv_id_fast(arxiv_id)

            if not metadata:
                print(f"warn: Unable to access from arXiv API Get information")
                metadata = {"arxiv_id": arxiv_id}
            else:
                print(f"successfully from arXiv API Get paper information: {metadata.get('title')}")

            new_filename = filename
            if metadata.get("title"):
                clean_title = _clean_filename(metadata["title"])
                if clean_title:
                    new_filename = f"{clean_title}.pdf"
                    new_file_path = os.path.join(category_folder, new_filename)

                    counter = 1
                    original_new_filename = new_filename
                    while os.path.exists(new_file_path):
                        name, ext = os.path.splitext(original_new_filename)
                        new_filename = f"{name}_{counter}{ext}"
                        new_file_path = os.path.join(category_folder, new_filename)
                        counter += 1

                    try:
                        os.rename(file_path, new_file_path)
                        file_path = new_file_path
                        filename = new_filename
                        print(f"File has been renamed to: {filename}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"Failed to rename file: {exc}")

            paper_id = str(uuid.uuid4())
            # Build arXiv URL(Priority is given to using user-provided URL, otherwise according to arxiv_id build)
            if arxiv_url.startswith("http"):
                final_arxiv_url = arxiv_url
            else:
                final_arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"

            paper_info = {
                "id": paper_id,
                "filename": filename,
                "original_filename": filename,
                "file_path": file_path,
                "upload_date": datetime.now().isoformat(),
                "title": (metadata.get("title") or arxiv_id),
                "authors": metadata.get("authors", ""),
                "arxiv_id": arxiv_id,
                "arxiv_url": metadata.get("arxiv_url")
                or final_arxiv_url,  # priority use metadata in URL, otherwise use the built URL
                "arxiv_published_date": metadata.get("published_date"),
                "affiliation": metadata.get("affiliation", ""),
                "year": metadata.get("year", ""),
                "journal": "",
                "abstract": metadata.get("abstract", ""),
                "summary": metadata.get("summary", ""),
                "bibtex": "",  # Temporarily empty, obtained in the background DBLP post-fill
                "keywords": metadata.get("keywords", ""),
                "subject": metadata.get("subject", ""),
                "notes": "",
                "starred": False,
                "read_time": 0,
                "translation_time": 0,
                "analysis_time": 0,
            }

            paper = Paper.from_dict(paper_info)
            if not paper:
                return jsonify({"success": False, "error": "Failed to create thesis object"}), 500

            # If using temp table of contents, tagged sources
            if use_temp_dir:
                paper.upload_source = "reading_list_url"

            registered_paper = paper_store.upsert(
                paper, category_id=category_id, category_path=category_path
            )
            save_paper_metadata(file_path, registered_paper)
            _add_to_reading_list(registered_paper.id)

            # 【Background acquisition BibTeX(priority DBLP, use after failure arXiv）】
            if metadata.get("title"):
                thread = threading.Thread(
                    target=_fetch_dblp_bibtex_background,
                    args=(
                        paper_id,
                        metadata["title"],
                        metadata.get("authors", ""),  # authors Can be empty
                        arxiv_id,
                        file_path,
                        category_id,
                        category_path,
                    ),
                    daemon=True,
                )
                thread.start()
                print(f"[Return immediately] Paper has been added,BibTeX Getting in the background...")

            return jsonify({"success": True, "paper": registered_paper.to_dict()})

        except Exception as exc:  # noqa: BLE001
            print(f"from arXiv Import failed: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": f"Import failed: {str(exc)}"}), 500
