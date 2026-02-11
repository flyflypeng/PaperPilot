from __future__ import annotations

import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Protocol

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import PaperStore
from paperpilot.database.dao.user_data_dao import ReadingListDAO
from paperpilot.tools.basic_tools.upload_paper import (
    fetch_bibtex_from_dblp,
    process_uploaded_pdf_fast,
)


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


def _clean_filename(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = text
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 100:
        cleaned = cleaned[:100] + "..."
    return cleaned or None


def register_upload_from_pdf_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    reading_list_file: str,
    paper_store: PaperStore,
) -> None:
    def _add_to_reading_list(paper_id: str) -> None:
        ReadingListDAO.add_item(paper_id, datetime.now().isoformat())

    def _process_pdf_metadata_background(
        paper_id: str,
        file_path: str,
        original_filename: str,
        category_id: str,
        category_path: list[str],
        category_folder: str,
    ):
        """Background processing: Use new unified interface processing PDF Upload (two stages: first arXiv,back DBLP）"""
        try:
            print(f"[Backstage] Start processingPDFmetadata: {file_path}")

            # 【stage1】Get it quickly arXiv message(no wait DBLP）
            paper_info = process_uploaded_pdf_fast(file_path, original_filename)

            if not paper_info:
                print("[Backstage] Unable to obtain paper information, keep original file name")
                paper_info = {}

            # Rename files based on title
            current_filename = os.path.basename(file_path)
            new_filename = current_filename
            new_file_path = file_path

            if paper_info.get("title"):
                clean_title = _clean_filename(paper_info["title"])
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
                        print(f"[Backstage] File has been renamed to: {new_filename}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"[Backstage] Failed to rename file: {exc}")
                        new_file_path = file_path
                        new_filename = current_filename

            # 【stage1】Update now Paper object(arXiv information)
            paper = paper_store.get(paper_id)
            if paper:
                paper.filename = new_filename
                paper.file_path = new_file_path
                paper.title = paper_info.get("title") or paper.title
                paper.authors = paper_info.get("authors", "")
                paper.arxiv_id = paper_info.get("arxiv_id")
                # if there is arxiv_id,set up arxiv_url
                if paper_info.get("arxiv_id"):
                    paper.arxiv_url = (
                        paper_info.get("arxiv_url")
                        or f"https://arxiv.org/abs/{paper_info.get('arxiv_id')}"
                    )
                paper.arxiv_published_date = paper_info.get("published_date")
                paper.affiliation = paper_info.get("affiliation", "")
                paper.year = paper_info.get("year", "")
                paper.abstract = paper_info.get("abstract", "")
                paper.summary = paper_info.get("summary", "")
                paper.bibtex = ""  # Temporarily empty
                paper.keywords = paper_info.get("keywords", "")
                paper.subject = paper_info.get("subject", "")

                # Save the updated paper（arXiv information)
                paper_store.upsert(
                    paper, category_id=category_id, category_path=category_path
                )
                save_paper_metadata(new_file_path, paper)
                print(f"[Backstage stage1] ✅ arXiv Information has been updated: {new_filename}")

                # 【stage2】Background acquisition BibTeX(priority DBLP, use after failure arXiv）
                if paper_info.get("title") and paper_info.get("authors"):
                    print(f"[Backstage stage2] Start getting BibTeX...")
                    arxiv_id = paper_info.get("arxiv_id")
                    bibtex = fetch_bibtex_from_dblp(
                        title=paper_info["title"],
                        authors=paper_info["authors"],
                        arxiv_id=arxiv_id or "",
                    )
                    if bibtex:
                        paper.bibtex = bibtex
                        paper_store.upsert(
                            paper, category_id=category_id, category_path=category_path
                        )
                        save_paper_metadata(new_file_path, paper)
                        print(f"[Backstage stage2] ✅ BibTeX updated")
                    else:
                        print(f"[Backstage stage2] ❌ Not obtained BibTeX")

                print(f"[Backstage] Paper metadata processing completed: {new_filename}")
            else:
                print(f"[Backstage] warn: not found paper {paper_id}")

        except Exception as exc:  # noqa: BLE001
            print(f"[Backstage] deal withPDFMetadata failed: {exc}")
            import traceback

            traceback.print_exc()

    @app.route("/api/upload", methods=["POST"])
    def api_upload():
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"})

        file = request.files["file"]
        category_id = request.form.get("category_id")

        if file.filename == "":
            return jsonify({"success": False, "error": "No file selected"})

        if not file.filename.lower().endswith(".pdf"):
            return jsonify({"success": False, "error": "Only PDF files are allowed"})

        categories = get_categories()

        # Special handling: To-be-read listcategory_id
        if category_id == "reading_list_temp":
            category_path = ["Root", "_ReadingListTemp"]
        else:
            category_path = get_category_path(categories, category_id)
            if not category_path:
                return jsonify({"success": False, "error": "Category not found"})

        category_folder = create_category_folder(category_path[1:])  # jump over Root
        filename = secure_filename(file.filename)
        file_path = os.path.join(category_folder, filename)

        # Handle file name conflicts
        counter = 1
        original_filename = filename
        while os.path.exists(file_path):
            name, ext = os.path.splitext(original_filename)
            filename = f"{name}_{counter}{ext}"
            file_path = os.path.join(category_folder, filename)
            counter += 1

        # Save file now
        file.save(file_path)
        print(f"File saved: {file_path}")

        # Create placeholder Paper Object (using original filename)
        paper_id = str(uuid.uuid4())
        paper_info = {
            "id": paper_id,
            "filename": filename,
            "original_filename": file.filename,
            "file_path": file_path,
            "upload_date": datetime.now().isoformat(),
            "title": os.path.splitext(file.filename)[0],  # Temporarily use filename as title
            "authors": "",
            "arxiv_id": None,
            "arxiv_published_date": None,
            "affiliation": "",
            "year": "",
            "journal": "",
            "abstract": "",
            "summary": "",
            "bibtex": "",
            "keywords": "",
            "subject": "",
            "notes": "",
            "starred": False,
            "read_time": 0,
            "analysis_view_time": 0,
            "translation_time": 0,
            "analysis_time": 0,
        }

        paper = Paper.from_dict(paper_info)
        if not paper:
            return jsonify({"success": False, "error": "Failed to create thesis object"}), 500

        # Register now paper(Let users see)
        registered_paper = paper_store.upsert(
            paper, category_id=category_id, category_path=category_path
        )
        save_paper_metadata(file_path, registered_paper)
        _add_to_reading_list(registered_paper.id)

        # Start a background thread to process metadata
        thread = threading.Thread(
            target=_process_pdf_metadata_background,
            args=(
                paper_id,
                file_path,
                file.filename,
                category_id,
                category_path,
                category_folder,
            ),
            daemon=True,
        )
        thread.start()

        print(f"[Return immediately] The paper has been added and is being processed in the background: {filename}")
        return jsonify({"success": True, "paper": registered_paper.to_dict()})
