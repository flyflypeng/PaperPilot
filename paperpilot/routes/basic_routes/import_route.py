"""
Zotero RDF Import route
Process from Zotero The function of importing papers
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

import requests
from flask import Flask, Response, jsonify, request
from werkzeug.utils import secure_filename

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import PaperStore
from paperpilot.tools.basic_tools.upload_paper import (
    fetch_bibtex_from_dblp,
    fetch_paper_by_arxiv_id_fast,
    search_arxiv_by_title_and_author_fast,
)


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class SaveCategoriesFn(Protocol):
    def __call__(self, categories: Dict[str, Any]) -> None: ...


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


# Import task status storage (support disconnection and reconnection)
import_tasks: Dict[str, Dict[str, Any]] = {}
import_tasks_lock = threading.Lock()

# Currently active import tasksID(Only one import task is allowed globally)
current_import_task_id: Optional[str] = None


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
            print(f"[Import] Removing from arXiv download PDF: {pdf_url}")
            response = requests.get(pdf_url, timeout=60, stream=True)
            response.raise_for_status()
            pdf_content = response.content
            filename = f"{arxiv_id}.pdf"
            print(f"[Import] Successfully downloaded PDF, size: {len(pdf_content)} bytes")
            return pdf_content, filename
        except requests.exceptions.RequestException as exc:
            print(f"[Import] from {pdf_url} Download failed: {exc}")
            continue

    print(f"[Import] all URL All downloads failed")
    return None


def _clean_filename(text: Optional[str]) -> Optional[str]:
    """Clean up filenames"""
    if not text:
        return None
    cleaned = text
    cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 100:
        cleaned = cleaned[:100] + "..."
    return cleaned or None


def _parse_category_path(category_str: str) -> List[str]:
    """
    parse category String is a list of paths

    For example:
    - "Scene Text Recognition" -> ["Scene Text Recognition"]
    - "Multi Modality/LLaVA" -> ["Multi Modality", "LLaVA"]
    - "A; B/C" -> Only take the first longest path ["B", "C"]
    """
    if not category_str:
        return []

    # If there are semicolons, take the first one (longest path)
    parts = category_str.split(";")
    if parts:
        category_str = parts[0].strip()

    # according to / division
    path_parts = [p.strip() for p in category_str.split("/") if p.strip()]
    return path_parts


def _find_or_create_category(
    categories: Dict[str, Any],
    category_path: List[str],
    save_categories: SaveCategoriesFn,
    create_category_folder: CreateCategoryFolderFn,
) -> Optional[str]:
    """
    Find or create a category, return to category ID

    Args:
        categories: Classification tree data
        category_path: Classification path, such as ["Multi Modality", "LLaVA"]
        save_categories: function to save categories
        create_category_folder: Function to create category folders

    Returns:
        Classification ID, return on failure None
    """
    if not category_path:
        return None

    def find_or_create_in_children(
        children: List[Dict], path: List[str], current_path: List[str]
    ) -> Optional[str]:
        if not path:
            return None

        target_name = path[0]
        remaining_path = path[1:]

        # Find an existing category
        for child in children:
            if child.get("name") == target_name:
                if remaining_path:
                    # Continue to search for subcategories
                    if "children" not in child:
                        child["children"] = []
                    return find_or_create_in_children(
                        child["children"], remaining_path, current_path + [target_name]
                    )
                else:
                    # Target category found
                    return child.get("id")

        # Not found, create a new category
        new_id = str(uuid.uuid4())
        new_category = {"id": new_id, "name": target_name, "children": []}
        children.append(new_category)

        # Create folder
        full_path = current_path + [target_name]
        try:
            create_category_folder(full_path)
            print(f"[Import] Create category folders: {'/'.join(full_path)}")
        except Exception as e:
            print(f"[Import] Failed to create category folder: {e}")

        if remaining_path:
            # Continue to create subcategories
            return find_or_create_in_children(
                new_category["children"], remaining_path, full_path
            )
        else:
            return new_id

    # Search starting from the root node
    root_children = categories.get("children", [])
    result = find_or_create_in_children(root_children, category_path, [])

    # Save updated categories
    if result:
        save_categories(categories)

    return result


def _find_or_create_category_under_parent(
    categories: Dict[str, Any],
    parent_category_id: str,
    category_path: List[str],
    save_categories: SaveCategoriesFn,
    create_category_folder: CreateCategoryFolderFn,
) -> Optional[str]:
    """
    Search or create a category in the specified parent directory and return the category ID

    For example:parent_category_id correspond "Project A"，category_path for ["Multi Modality", "LLaVA"]
    will create "Project A/Multi Modality/LLaVA"

    Args:
        categories: Classification tree data
        parent_category_id: parent directoryID
        category_path: Classification path, such as ["Multi Modality", "LLaVA"]
        save_categories: function to save categories
        create_category_folder: Function to create category folders

    Returns:
        Classification ID, return on failure None
    """
    if not category_path:
        # if not category_path, return directly to the parent directoryID
        return parent_category_id

    # Find parent directory node
    def find_node_by_id(
        node: Dict[str, Any], target_id: str
    ) -> Optional[Dict[str, Any]]:
        if node.get("id") == target_id:
            return node
        for child in node.get("children", []):
            result = find_node_by_id(child, target_id)
            if result:
                return result
        return None

    parent_node = find_node_by_id(categories, parent_category_id)
    if not parent_node:
        # The parent directory does not exist, fallback to the root directory
        return _find_or_create_category(
            categories, category_path, save_categories, create_category_folder
        )

    # Get the path of the parent directory (used to create folders)
    def get_path_to_node(
        root: Dict[str, Any], target_id: str, path: List[str] = None
    ) -> Optional[List[str]]:
        if path is None:
            path = []
        if root.get("id") == target_id:
            return path + [root.get("name", "")]
        for child in root.get("children", []):
            result = get_path_to_node(child, target_id, path + [root.get("name", "")])
            if result:
                return result
        return None

    parent_path = get_path_to_node(categories, parent_category_id)
    if not parent_path:
        parent_path = []
    else:
        # Remove "Root" if exists
        parent_path = [p for p in parent_path if p and p != "Root"]

    # Find or create categories under parent directory
    def find_or_create_in_children(
        children: List[Dict], path: List[str], current_folder_path: List[str]
    ) -> Optional[str]:
        if not path:
            return None

        target_name = path[0]
        remaining_path = path[1:]

        # Find an existing category
        for child in children:
            if child.get("name") == target_name:
                if remaining_path:
                    # Continue to search for subcategories
                    if "children" not in child:
                        child["children"] = []
                    return find_or_create_in_children(
                        child["children"],
                        remaining_path,
                        current_folder_path + [target_name],
                    )
                else:
                    # Target category found
                    return child.get("id")

        # Not found, create a new category
        new_id = str(uuid.uuid4())
        new_category = {"id": new_id, "name": target_name, "children": []}
        children.append(new_category)

        # Create folder
        full_folder_path = current_folder_path + [target_name]
        try:
            create_category_folder(full_folder_path)
            print(f"[Import] Create category folders: {'/'.join(full_folder_path)}")
        except Exception as e:
            print(f"[Import] Failed to create category folder: {e}")

        if remaining_path:
            # Continue to create subcategories
            return find_or_create_in_children(
                new_category["children"], remaining_path, full_folder_path
            )
        else:
            return new_id

    # Make sure the parent directory has children list
    if "children" not in parent_node:
        parent_node["children"] = []

    # Search from parent directory
    result = find_or_create_in_children(
        parent_node["children"], category_path, parent_path
    )

    # Save updated categories
    if result:
        save_categories(categories)

    return result


def _get_full_category_path(
    categories: Dict[str, Any],
    category_id: str,
    path: Optional[List[str]] = None,
) -> Optional[List[str]]:
    """Get the full path of the category"""
    if path is None:
        path = ["Root"]

    if categories.get("id") == category_id:
        return path + [categories.get("name", "")]

    for child in categories.get("children", []):
        result = _get_full_category_path(
            child, category_id, path + [categories.get("name", "")]
        )
        if result:
            return result

    return None


def register_import_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    save_categories: SaveCategoriesFn,
    get_category_path: GetCategoryPathFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    reading_list_file: str,
    paper_store: PaperStore,
    upload_folder: str,
) -> None:
    """Register and import related routes"""

    def _load_reading_list() -> list[str]:
        try:
            with open(reading_list_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("papers", [])
        except Exception:
            return []

    def _save_reading_list(paper_ids: list[str]) -> None:
        try:
            with open(reading_list_file, "w", encoding="utf-8") as f:
                json.dump({"papers": paper_ids}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _add_to_reading_list(paper_id: str) -> None:
        paper_ids = _load_reading_list()
        if paper_id not in paper_ids:
            paper_ids.append(paper_id)
            _save_reading_list(paper_ids)

    def _check_duplicate_in_folder(folder_path: str, title: str) -> bool:
        """Check if a paper with the same name already exists in the folder"""
        if not os.path.exists(folder_path):
            return False

        clean_title = _clean_filename(title)
        if not clean_title:
            return False

        # Check if there is a name with the same name PDF or JSON
        expected_pdf = f"{clean_title}.pdf"
        expected_json = f"{clean_title}.json"

        for filename in os.listdir(folder_path):
            if filename.lower() == expected_pdf.lower():
                return True
            # Also check JSON title in file
            if filename.endswith(".json"):
                try:
                    json_path = os.path.join(folder_path, filename)
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if (
                            data.get("title", "").strip().lower()
                            == title.strip().lower()
                        ):
                            return True
                except Exception:
                    pass
        return False

    def _check_paper_already_imported(paper_data: Dict[str, Any]) -> bool:
        """Check if the paper has been imported (via arXiv ID or title)"""
        # 1. Try starting with URL extract arXiv ID
        url = paper_data.get("extra", {}).get("url") or paper_data.get("url", "")
        arxiv_id = None
        if "arxiv.org" in url.lower():
            arxiv_id = _extract_arxiv_id_from_url(url)
        
        # 2. if there is arXiv ID,pass paper_store Find
        if arxiv_id:
            existing_entry = paper_store.get_by_arxiv_id(arxiv_id)
            if existing_entry:
                print(f"[Import] The paper already exists (via arXiv ID）: {arxiv_id}")
                return True
        
        # 3. if not arXiv ID, try to find by title
        title = paper_data.get("title", "").strip()
        if title:
            # Go through all papers and check if the titles match
            all_papers = paper_store.iter_all()
            for paper in all_papers:
                if paper.title and paper.title.strip().lower() == title.lower():
                    print(f"[Import] The paper already exists (via title): {title[:50]}")
                    return True
        
        return False

    def _filter_already_imported_papers(papers_data: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        """Filter out imported papers and return the list of unimported papers and the number of imported papers"""
        remaining_papers = []
        already_imported_count = 0
        
        for paper_data in papers_data:
            if _check_paper_already_imported(paper_data):
                already_imported_count += 1
            else:
                remaining_papers.append(paper_data)
        
        return remaining_papers, already_imported_count

    def _update_task_progress(task_id: str, **kwargs):
        """Update task progress (thread safe)"""
        with import_tasks_lock:
            task = import_tasks.get(task_id)
            if task:
                task.update(kwargs)
                task["last_update"] = datetime.now().isoformat()

    def _import_papers_task(
        task_id: str, papers_data: List[Dict[str, Any]], target_category_id: str = ""
    ):
        """Background import task

        Args:
            task_id: TaskID
            papers_data: Paper data list
            target_category_id: target directoryID, as the parent directory if specified,Zotero The classification structure will be created under
        """
        global current_import_task_id

        with import_tasks_lock:
            task = import_tasks.get(task_id)
            if not task:
                return

        total = len(papers_data)
        success_count = 0
        failed_count = 0
        skipped_count = 0
        duplicate_count = 0  # Number of repeats
        others_count = 0  # Enter Others quantity

        # If a target directory is specified, obtain its information in advance
        parent_category_id = None
        parent_category_path = None
        print(
            f"[Import] Received target directoryID: '{target_category_id}' (type: {type(target_category_id).__name__})"
        )
        if target_category_id:
            categories = get_categories()
            print(f"[Import] Looking for target directory...")
            parent_category_path = get_category_path(categories, target_category_id)
            print(f"[Import] Find results: {parent_category_path}")
            if parent_category_path:
                parent_category_id = target_category_id
                print(
                    f"[Import] ✅ will be in the directory '{'/'.join(parent_category_path[1:])}' Import under, keep Zotero Classification structure"
                )
            else:
                print(
                    f"[Import] ❌ Target directory does not exist: {target_category_id}, will press in the root directory Zotero Classification import"
                )
        else:
            print("[Import] No target directory specified, will press in the root directory Zotero Classification import")

        for idx, paper_data in enumerate(papers_data):
            # Check if canceled
            with import_tasks_lock:
                task = import_tasks.get(task_id)
                if task and task.get("cancelled", False):
                    print(f"[Import] Import task canceled")
                    _update_task_progress(
                        task_id,
                        status="cancelled",
                        progress=int((idx / total) * 100),
                        current=idx,
                        total=total,
                        message="Import canceled",
                        success_count=success_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        duplicate_count=duplicate_count,
                        others_count=others_count,
                    )
                    current_import_task_id = None
                    return
            
            try:
                # Update progress status
                _update_task_progress(
                    task_id,
                    status="importing",
                    progress=int((idx / total) * 100),
                    current=idx + 1,
                    total=total,
                    message=f"Processing: {paper_data.get('title', 'Unknown title')[:50]}...",
                    success_count=success_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    duplicate_count=duplicate_count,
                    others_count=others_count,
                )

                # examine category
                category_str = paper_data.get("extra", {}).get(
                    "category"
                ) or paper_data.get("category")

                # parse category path
                if category_str:
                    category_path = _parse_category_path(category_str)
                else:
                    category_path = []

                # Mark whether to enter Others
                is_others = False

                # if not category or category that is "Others", put in Others Table of contents
                if not category_path or (
                    len(category_path) == 1 and category_path[0].lower() == "others"
                ):
                    category_path = ["Others"]
                    is_others = True
                    print(
                        f"[Import] Uncategorized papers, put in Others: {paper_data.get('title', 'unknown')[:50]}"
                    )

                # Find or create a category
                # If a parent directory is specified, create a classification structure under the parent directory
                categories = get_categories()
                if parent_category_id:
                    category_id = _find_or_create_category_under_parent(
                        categories,
                        parent_category_id,
                        category_path,
                        save_categories,
                        create_category_folder,
                    )
                else:
                    category_id = _find_or_create_category(
                        categories,
                        category_path,
                        save_categories,
                        create_category_folder,
                    )

                if not category_id:
                    print(f"[Import] Failed to create category: {category_path}")
                    failed_count += 1
                    continue

                # Get the full path to the category (for paper_store）
                categories = get_categories()  # Retrieve updated categories
                full_category_path = get_category_path(categories, category_id)
                if not full_category_path:
                    full_category_path = ["Root"] + category_path

                # try to start from arXiv Get the paper
                arxiv_id = None
                paper_info = None

                # 1. examine URL Is there any arXiv
                url = paper_data.get("extra", {}).get("url") or paper_data.get(
                    "url", ""
                )
                if "arxiv.org" in url.lower():
                    arxiv_id = _extract_arxiv_id_from_url(url)
                    if arxiv_id:
                        print(f"[Import] from URL extract arXiv ID: {arxiv_id}")
                        paper_info = fetch_paper_by_arxiv_id_fast(arxiv_id)

                # 2. if not arXiv URL, use title+Author search
                if not paper_info:
                    title = paper_data.get("title", "")
                    authors = paper_data.get("authors", "")
                    if title:
                        # Construct a search query
                        search_title = f"{title} {authors}" if authors else title
                        print(f"[Import] Search using titles arXiv: {search_title[:50]}...")

                        # Extract the first author
                        first_author = authors.split(",")[0].strip() if authors else ""
                        if first_author:
                            paper_info = search_arxiv_by_title_and_author_fast(
                                title, first_author
                            )

                        if paper_info:
                            arxiv_id = paper_info.get("arxiv_id")

                # 3. If still not found, skip
                if not paper_info or not arxiv_id:
                    print(
                        f"[Import] Unable to access from arXiv Get the paper: {paper_data.get('title', 'unknown')[:50]}"
                    )
                    skipped_count += 1
                    continue

                # Get full folder path (including parent directory)
                # full_category_path The format is ["Root", "ParentDir", "Category", ...]
                # Need to be removed when creating a folder "Root"
                folder_path_parts = (
                    full_category_path[1:]
                    if len(full_category_path) > 1
                    else category_path
                )

                # Check whether the target directory already has a paper with the same name (duplicate detection)
                category_folder = create_category_folder(folder_path_parts)
                paper_title = paper_info.get("title", "")
                if paper_title and _check_duplicate_in_folder(
                    category_folder, paper_title
                ):
                    print(f"[Import] Skip duplicate papers: {paper_title[:50]}")
                    duplicate_count += 1
                    continue

                # download PDF
                pdf_result = _download_arxiv_pdf(arxiv_id)
                if not pdf_result:
                    print(f"[Import] download PDF fail: {arxiv_id}")
                    failed_count += 1
                    continue

                pdf_content, pdf_filename = pdf_result

                # Create category folder and save PDF(use full path)
                category_folder = create_category_folder(folder_path_parts)

                # Use the paper title as the file name
                clean_title = _clean_filename(paper_info.get("title"))
                if clean_title:
                    pdf_filename = f"{clean_title}.pdf"

                file_path = os.path.join(category_folder, pdf_filename)

                # Handle file name conflicts
                counter = 1
                original_filename = pdf_filename
                while os.path.exists(file_path):
                    name, ext = os.path.splitext(original_filename)
                    pdf_filename = f"{name}_{counter}{ext}"
                    file_path = os.path.join(category_folder, pdf_filename)
                    counter += 1

                # keep PDF
                with open(file_path, "wb") as f:
                    f.write(pdf_content)
                print(f"[Import] PDF saved: {file_path}")

                # create Paper object
                paper_id = str(uuid.uuid4())
                # build arxiv_url
                arxiv_url = None
                if arxiv_id:
                    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"

                new_paper = Paper(
                    id=paper_id,
                    filename=pdf_filename,
                    original_filename=pdf_filename,
                    file_path=file_path,
                    upload_date=datetime.now().isoformat(),
                    title=paper_info.get("title", ""),
                    authors=paper_info.get("authors", ""),
                    arxiv_id=arxiv_id,
                    arxiv_url=arxiv_url,
                    arxiv_published_date=paper_info.get("published_date"),
                    year=paper_info.get("year", ""),
                    abstract=paper_info.get("abstract", ""),
                    summary=paper_info.get("summary", ""),
                    bibtex="",
                    notes=paper_data.get("notes", ""),
                    github=None,  # from Zotero When importing,GitHub is empty but the field exists
                    homepage=None,  # from Zotero When importing,Homepage is empty but the field exists
                    upload_source="zotero_import",
                )

                # Register to paper_store
                registered_paper = paper_store.upsert(
                    new_paper, category_id=category_id, category_path=full_category_path
                )

                # Save metadata
                save_paper_metadata(file_path, registered_paper)

                # Note: Imported papers are not added to the to-read list

                success_count += 1
                if is_others:
                    others_count += 1
                print(f"[Import] ✅ Imported successfully: {paper_info.get('title', '')[:50]}")

                # Background acquisition DBLP BibTeX(asynchronous)
                if paper_info.get("title") and paper_info.get("authors"):
                    threading.Thread(
                        target=_fetch_dblp_bibtex_async,
                        args=(
                            paper_id,
                            paper_info["title"],
                            paper_info["authors"],
                            arxiv_id,
                            file_path,
                            category_id,
                            full_category_path,
                        ),
                        daemon=True,
                    ).start()

            except Exception as e:
                print(f"[Import] ❌ Failed to import paper: {e}")
                import traceback

                traceback.print_exc()
                failed_count += 1

        # Import completed
        _update_task_progress(
            task_id,
            status="completed",
            progress=100,
            current=total,
            total=total,
            success_count=success_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            duplicate_count=duplicate_count,
            others_count=others_count,
            message="Import completed",
        )

        # Clear current task mark
        current_import_task_id = None

        print(
            f"[Import] Import completed: success {success_count}, fail {failed_count}, jump over {skipped_count}, repeat {duplicate_count}, Others {others_count}"
        )

    def _fetch_dblp_bibtex_async(
        paper_id: str,
        title: str,
        authors: str,
        arxiv_id: str,
        file_path: str,
        category_id: str,
        category_path: List[str],
    ):
        """Asynchronous acquisition DBLP BibTeX"""
        try:
            bibtex = fetch_bibtex_from_dblp(title, authors, arxiv_id)
            if bibtex:
                paper = paper_store.get(paper_id)
                if paper:
                    paper.bibtex = bibtex
                    paper_store.upsert(
                        paper, category_id=category_id, category_path=category_path
                    )
                    save_paper_metadata(file_path, paper)
                    print(f"[Import DBLP] ✅ BibTeX updated: {paper_id}")
        except Exception as e:
            print(f"[Import DBLP] ❌ get BibTeX fail: {e}")

    @app.route("/api/import/zotero", methods=["POST"])
    def api_import_zotero():
        """Upload and parse Zotero RDF document"""
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No document provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400

        if not file.filename.lower().endswith(".rdf"):
            return jsonify({"success": False, "error": "Please upload .rdf format file"}), 400

        # Get target directory parameters (optional)
        target_category_id = request.form.get("target_category_id", "").strip()
        print(f"[Import] target directoryID: {target_category_id or '(according toZoteroClassification)'}")

        try:
            # Save temporary files
            temp_dir = os.path.join(upload_folder, ".temp")
            os.makedirs(temp_dir, exist_ok=True)

            temp_filename = f"zotero_{uuid.uuid4().hex[:8]}.rdf"
            temp_path = os.path.join(temp_dir, temp_filename)
            file.save(temp_path)
            print(f"[Import] RDF File saved: {temp_path}")

            # parse RDF document
            try:
                from paperpilot.tools.basic_tools.zotero_parser import ZoteroRDFParser

                parser = ZoteroRDFParser(temp_path)
                papers = parser.parse()

                # Convert to list of dictionaries
                papers_data = []
                for paper in papers:
                    paper_dict = paper.to_dict()
                    papers_data.append(paper_dict)

                print(f"[Import] Analysis completed, found {len(papers_data)} papers")

            finally:
                # Clean temporary files
                try:
                    os.remove(temp_path)
                    fixed_path = temp_path.replace(".rdf", "_fixed.rdf")
                    if os.path.exists(fixed_path):
                        os.remove(fixed_path)
                except Exception:
                    pass

            if not papers_data:
                return jsonify({"success": False, "error": "No papers found"}), 400

            # Check if there is already an import task in progress
            global current_import_task_id
            if current_import_task_id:
                with import_tasks_lock:
                    existing_task = import_tasks.get(current_import_task_id)
                    if existing_task and existing_task.get("status") not in [
                        "completed",
                        "error",
                        "cancelled",
                    ]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "There is an import task in progress",
                                    "task_id": current_import_task_id,
                                }
                            ),
                            400,
                        )

            # Check and filter imported papers (restore import function)
            remaining_papers, already_imported_count = _filter_already_imported_papers(papers_data)
            
            if not remaining_papers:
                return jsonify({
                    "success": False,
                    "error": "All papers have been imported",
                    "already_imported": already_imported_count,
                    "total": len(papers_data),
                }), 400

            # If there are imported papers, record the information
            resume_message = ""
            if already_imported_count > 0:
                resume_message = f"detected {already_imported_count} papers have been imported and will be {already_imported_count + 1} Chapter starts and continues importing"
                print(f"[Import] {resume_message}")

            # Create import task
            task_id = str(uuid.uuid4())
            current_import_task_id = task_id

            with import_tasks_lock:
                import_tasks[task_id] = {
                    "status": "starting",
                    "progress": 0,
                    "current": 0,
                    "total": len(remaining_papers),
                    "original_total": len(papers_data),  # raw total
                    "already_imported_count": already_imported_count,  # Imported quantity
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "duplicate_count": 0,
                    "others_count": 0,
                    "message": resume_message or "Preparing to import...",
                    "start_time": datetime.now().isoformat(),
                    "last_update": datetime.now().isoformat(),
                    "cancelled": False,
                }

            # Start the background import task (do not use daemon=True, ensure the task is completed)
            thread = threading.Thread(
                target=_import_papers_task,
                args=(task_id, remaining_papers, target_category_id),
            )
            thread.start()

            message = f"Start importing {len(remaining_papers)} papers"
            if already_imported_count > 0:
                message += f"(skipped {already_imported_count} imported papers)"

            return jsonify(
                {
                    "success": True,
                    "task_id": task_id,
                    "total_papers": len(remaining_papers),
                    "original_total": len(papers_data),
                    "already_imported": already_imported_count,
                    "message": message,
                }
            )

        except Exception as e:
            print(f"[Import] parse RDF fail: {e}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": f"Parsing failed: {str(e)}"}), 500

    @app.route("/api/import/zotero/status")
    def api_import_status():
        """Get the current import task status (for recovery after page refresh)"""
        global current_import_task_id

        if not current_import_task_id:
            return jsonify({"has_task": False})

        with import_tasks_lock:
            task = import_tasks.get(current_import_task_id)
            if not task:
                current_import_task_id = None
                return jsonify({"has_task": False})

            return jsonify(
                {
                    "has_task": True,
                    "task_id": current_import_task_id,
                    "status": task.get("status"),
                    "progress": task.get("progress", 0),
                    "current": task.get("current", 0),
                    "total": task.get("total", 0),
                    "message": task.get("message", ""),
                    "success_count": task.get("success_count", 0),
                    "failed_count": task.get("failed_count", 0),
                    "skipped_count": task.get("skipped_count", 0),
                    "duplicate_count": task.get("duplicate_count", 0),
                    "others_count": task.get("others_count", 0),
                    "original_total": task.get("original_total", task.get("total", 0)),
                    "already_imported_count": task.get("already_imported_count", 0),
                }
            )

    @app.route("/api/import/zotero/progress/<task_id>")
    def api_import_progress(task_id):
        """Get import progress (SSE, read from task status)"""

        def generate():
            last_status = None

            while True:
                with import_tasks_lock:
                    task = import_tasks.get(task_id)
                    if not task:
                        yield f"data: {json.dumps({'status': 'error', 'message': 'Task does not exist'})}\n\n"
                        return

                    # Build progress data
                    progress_data = {
                        "status": task.get("status"),
                        "progress": task.get("progress", 0),
                        "current": task.get("current", 0),
                        "total": task.get("total", 0),
                        "message": task.get("message", ""),
                        "success_count": task.get("success_count", 0),
                        "failed_count": task.get("failed_count", 0),
                        "skipped_count": task.get("skipped_count", 0),
                        "duplicate_count": task.get("duplicate_count", 0),
                        "others_count": task.get("others_count", 0),
                        "original_total": task.get("original_total", task.get("total", 0)),
                        "already_imported_count": task.get("already_imported_count", 0),
                    }

                # Sent only when status changes
                current_key = (
                    progress_data["status"],
                    progress_data["current"],
                    progress_data["message"],
                )
                if current_key != last_status:
                    yield f"data: {json.dumps(progress_data)}\n\n"
                    last_status = current_key

                # End the flow if completed, on error, or canceled
                if progress_data["status"] in ["completed", "error", "cancelled"]:
                    break

                # Take a short hibernation to avoid CPU overload
                time.sleep(0.5)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/api/import/zotero/cancel/<task_id>", methods=["POST"])
    def api_cancel_import(task_id):
        """Cancel import task"""
        global current_import_task_id

        with import_tasks_lock:
            task = import_tasks.get(task_id)
            if not task:
                return jsonify({"success": False, "error": "Task does not exist"}), 404

            # Check task status
            status = task.get("status")
            if status in ["completed", "error", "cancelled"]:
                return jsonify({"success": False, "error": f"Task completed{status}"}), 400

            # Mark as canceled
            task["cancelled"] = True
            task["status"] = "cancelling"
            task["message"] = "Canceling import..."
            task["last_update"] = datetime.now().isoformat()

            # If this is the current task, clear the flag
            if current_import_task_id == task_id:
                current_import_task_id = None

        print(f"[Import] Import tasks {task_id} Marked for cancellation")
        return jsonify({"success": True, "message": "Cancellation request sent"})

    @app.route("/api/import/from-export", methods=["POST"])
    def api_import_from_export():
        """Import generated from export function ZIP document"""
        import shutil
        import tempfile
        import zipfile

        if "file" not in request.files:
            return jsonify({"success": False, "error": "No document provided"}), 400

        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400

        # Check file extension
        if not file.filename.lower().endswith(".zip"):
            return jsonify({"success": False, "error": "Only supports ZIP document"}), 400

        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix="import_export_")

        try:
            # Save uploaded ZIP document
            zip_path = os.path.join(temp_dir, "export.zip")
            file.save(zip_path)

            # Unzip ZIP document
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)

            print(f"[Import] Unzip ZIP file to: {extract_dir}")
            with zipfile.ZipFile(zip_path, "r") as zipf:
                zipf.extractall(extract_dir)

            # Check if there is papers folder
            papers_folder = os.path.join(extract_dir, "papers")
            if not os.path.exists(papers_folder) or not os.path.isdir(papers_folder):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Invalid export file: missing papers folder",
                        }
                    ),
                    400,
                )

            # 1. First copy the entire folder structure to the target location (so the directory tree is immediately visible)
            print(f"[Import] Start copying folder structure to: {upload_folder}")
            for item in os.listdir(papers_folder):
                src_path = os.path.join(papers_folder, item)
                dst_path = os.path.join(upload_folder, item)

                if os.path.isdir(src_path):
                    # copy entire directory
                    if os.path.exists(dst_path):
                        # If the target directory already exists, merge the contents
                        shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
                    else:
                        shutil.copytree(src_path, dst_path)
                else:
                    # Copy files
                    shutil.copy2(src_path, dst_path)

            print(f"[Import] Folder copy completed")

            # calculate JSON Number of documents (number of papers)
            total_papers = sum(
                [
                    len([f for f in files if f.endswith(".json")])
                    for _, _, files in os.walk(upload_folder)
                ]
            )

            # Check if there is already an import task in progress
            global current_import_task_id
            if current_import_task_id:
                with import_tasks_lock:
                    existing_task = import_tasks.get(current_import_task_id)
                    if existing_task and existing_task.get("status") not in [
                        "completed",
                        "error",
                    ]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "There is an import task in progress",
                                    "task_id": current_import_task_id,
                                }
                            ),
                            400,
                        )

            # Create import task
            task_id = str(uuid.uuid4())
            current_import_task_id = task_id

            with import_tasks_lock:
                import_tasks[task_id] = {
                    "status": "starting",
                    "progress": 0,
                    "current": 0,
                    "total": total_papers,
                    "success_count": 0,
                    "failed_count": 0,
                    "skipped_count": 0,
                    "duplicate_count": 0,
                    "others_count": 0,
                    "message": "Folder copied, start rebuilding paper...",
                    "start_time": datetime.now().isoformat(),
                    "last_update": datetime.now().isoformat(),
                    "cancelled": False,
                }

            # 2. Start a background task to rebuild the paper (from arXiv download PDF）
            thread = threading.Thread(
                target=_rebuild_papers_from_json,
                args=(task_id, upload_folder),
                daemon=False,
            )
            thread.start()

            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)

            return jsonify(
                {
                    "success": True,
                    "task_id": task_id,
                    "total_papers": total_papers,
                    "message": "The folder has been imported and the paper is being reconstructed in the background",
                }
            )

        except zipfile.BadZipFile:
            return jsonify({"success": False, "error": "Invalid ZIP document"}), 400
        except Exception as e:
            print(f"Import failed: {e}")
            import traceback

            traceback.print_exc()
            # Clean up temporary directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({"success": False, "error": str(e)}), 500

    def _rebuild_papers_from_json(
        task_id: str,
        papers_folder: str,
    ):
        """Background task: from JSON Metadata reconstruction paper (from arXiv download PDF）"""
        global current_import_task_id

        def update_progress(
            status=None,
            progress=None,
            current=None,
            total=None,
            message=None,
            success_count=None,
            failed_count=None,
            skipped_count=None,
            duplicate_count=None,
        ):
            """Update task progress"""
            with import_tasks_lock:
                if task_id in import_tasks:
                    task = import_tasks[task_id]
                    if status is not None:
                        task["status"] = status
                    if progress is not None:
                        task["progress"] = progress
                    if current is not None:
                        task["current"] = current
                    if total is not None:
                        task["total"] = total
                    if message is not None:
                        task["message"] = message
                    if success_count is not None:
                        task["success_count"] = success_count
                    if failed_count is not None:
                        task["failed_count"] = failed_count
                    if skipped_count is not None:
                        task["skipped_count"] = skipped_count
                    if duplicate_count is not None:
                        task["duplicate_count"] = duplicate_count
                    task["last_update"] = datetime.now().isoformat()

        success_count = 0
        failed_count = 0
        skipped_count = 0
        duplicate_count = 0

        try:
            # 1. collect all JSON files (exclude configuration files)
            json_files = []
            exclude_files = {
                "categories.json",
                "reading_list.json",
                "user_settings.json",
                "reading_history.json",
                "agentic_settings.json",
                "daily_arxiv_settings.json",
            }

            for root, dirs, files in os.walk(papers_folder):
                # Exclude hidden directories
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                for file in files:
                    if file.endswith(".json") and file not in exclude_files:
                        json_path = os.path.join(root, file)
                        json_files.append(json_path)

            total_papers = len(json_files)
            print(f"[Import] turn up {total_papers} papers JSON document")

            update_progress(
                status="importing",
                progress=0,
                current=0,
                total=total_papers,
                message="Start importing papers...",
            )

            # 2. Process one by one JSON document
            for idx, json_path in enumerate(json_files):
                # Check if canceled
                with import_tasks_lock:
                    task = import_tasks.get(task_id)
                    if task and task.get("cancelled", False):
                        print(f"[Import] Import task canceled")
                        update_progress(
                            status="cancelled",
                            progress=int((idx / total_papers) * 100),
                            current=idx,
                            total=total_papers,
                            message="Import canceled",
                            success_count=success_count,
                            failed_count=failed_count,
                            skipped_count=skipped_count,
                            duplicate_count=duplicate_count,
                        )
                        current_import_task_id = None
                        return
                
                try:
                    # read JSON metadata
                    with open(json_path, "r", encoding="utf-8") as f:
                        paper_meta = json.load(f)

                    title = paper_meta.get("title", "")
                    authors = paper_meta.get("authors", "")
                    arxiv_id = paper_meta.get("arxiv_id", "")

                    if not title:
                        print(f"[Import] Skip: Missing title")
                        skipped_count += 1
                        continue

                    # update progress
                    update_progress(
                        status="importing",
                        progress=int((idx / total_papers) * 100),
                        current=idx,
                        total=total_papers,
                        message=f"Importing: {title[:50]}...",
                        success_count=success_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        duplicate_count=duplicate_count,
                    )

                    # Get the directory where the paper is located
                    paper_dir = os.path.dirname(json_path)

                    # Check if there is already one in this directory PDF
                    pdf_exists = False
                    expected_pdf_name = os.path.basename(json_path).replace(
                        ".json", ".pdf"
                    )
                    expected_pdf_path = os.path.join(paper_dir, expected_pdf_name)

                    if os.path.exists(expected_pdf_path):
                        print(f"[Import] PDF Already exists, skip download: {title[:50]}")
                        # But you still need to register to the system
                        pdf_exists = True
                        pdf_path = expected_pdf_path

                    # 3. if PDF does not exist, from arXiv download
                    if not pdf_exists:
                        pdf_content = None
                        pdf_filename = None

                        if arxiv_id:
                            # have arXiv ID, download directly
                            result = _download_arxiv_pdf(arxiv_id)
                            if result:
                                pdf_content, pdf_filename = result
                        else:
                            # No arXiv ID, try searching
                            if title and authors:
                                print(f"[Import] try search arXiv: {title[:50]}...")
                                paper_info = search_arxiv_by_title_and_author_fast(
                                    title, authors
                                )
                                if paper_info and paper_info.get("arxiv_id"):
                                    result = _download_arxiv_pdf(paper_info["arxiv_id"])
                                    if result:
                                        pdf_content, pdf_filename = result
                                        # Update metadata in arXiv ID
                                        paper_meta["arxiv_id"] = paper_info["arxiv_id"]
                                        if not paper_meta.get("arxiv_url"):
                                            paper_meta["arxiv_url"] = paper_info.get(
                                                "url", ""
                                            )

                        if not pdf_content:
                            print(f"[Import] Unable to download PDF: {title[:50]}")
                            failed_count += 1
                            continue

                        # 4. keep PDF
                        pdf_path = expected_pdf_path
                        with open(pdf_path, "wb") as f:
                            f.write(pdf_content)

                    # 5. Update metadata
                    paper_meta["file_path"] = pdf_path
                    if not paper_meta.get("id"):
                        paper_meta["id"] = str(uuid.uuid4())
                    paper_meta["upload_source"] = "export_import"

                    # Save the updated JSON
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(paper_meta, f, ensure_ascii=False, indent=2)

                    # 6. Register to paper_store
                    from paperpilot.core.base_paper import Paper

                    new_paper = Paper(
                        id=paper_meta["id"],
                        title=paper_meta.get("title", ""),
                        authors=paper_meta.get("authors", ""),
                        file_path=pdf_path,
                        upload_date=paper_meta.get("upload_date", ""),
                        filename=paper_meta.get("filename", ""),
                        original_filename=paper_meta.get("original_filename", ""),
                        arxiv_url=paper_meta.get("arxiv_url")
                        or paper_meta.get("url", ""),
                        arxiv_id=paper_meta.get("arxiv_id", ""),
                        arxiv_published_date=paper_meta.get("arxiv_published_date", ""),
                        year=paper_meta.get("year", ""),
                        abstract=paper_meta.get("abstract", ""),
                        summary=paper_meta.get("summary", ""),
                        bibtex=paper_meta.get("bibtex", ""),
                        notes=paper_meta.get("notes", ""),
                        upload_source="export_import",
                        affiliation=paper_meta.get("affiliation", ""),
                        journal=paper_meta.get("journal", ""),
                        subject=paper_meta.get("subject", ""),
                        keywords=paper_meta.get("keywords", ""),
                        starred=paper_meta.get("starred", False),
                        read_time=paper_meta.get("read_time", 0),
                        analysis_view_time=paper_meta.get("analysis_view_time", 0),
                        translation_time=paper_meta.get("translation_time", 0),
                        analysis_time=paper_meta.get("analysis_time", 0),
                    )

                    # Get the classification path (relative to papers_folder）
                    rel_dir = os.path.relpath(paper_dir, papers_folder)
                    category_path_parts = (
                        rel_dir.split(os.sep) if rel_dir != "." else []
                    )

                    if category_path_parts:
                        # Find or create a category
                        current_categories = get_categories()
                        category_id = _find_or_create_category(
                            current_categories,
                            category_path_parts,
                            save_categories,
                            create_category_folder,
                        )

                        if category_id:
                            category_path = ["root"] + category_path_parts
                            paper_store.upsert(
                                new_paper,
                                category_id=category_id,
                                category_path=category_path,
                            )
                            save_paper_metadata(pdf_path, new_paper)
                    else:
                        # Papers in the root directory
                        paper_store.upsert(
                            new_paper, category_id="root", category_path=["root"]
                        )
                        save_paper_metadata(pdf_path, new_paper)

                    success_count += 1
                    print(f"[Import] ✅ Imported successfully: {title[:50]}")

                except Exception as e:
                    print(f"[Import] ❌ Processing failed: {json_path}, mistake: {e}")
                    import traceback

                    traceback.print_exc()
                    failed_count += 1

            # Import completed
            update_progress(
                status="completed",
                progress=100,
                current=total_papers,
                total=total_papers,
                message="Import completed",
                success_count=success_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                duplicate_count=duplicate_count,
            )

            print(
                f"[Import] Import completed: success {success_count}, fail {failed_count}, jump over {skipped_count}, repeat {duplicate_count}"
            )

        except Exception as e:
            print(f"[Import] Import task failed: {e}")
            import traceback

            traceback.print_exc()

            update_progress(
                status="error",
                message=f"Import failed: {str(e)}",
            )

        finally:
            # Clear current task mark
            current_import_task_id = None

    def _import_from_export_task_old(
        task_id: str,
        papers_list: List[Dict[str, Any]],
        extract_dir: str,
        manifest: Dict[str, Any],
    ):
        """Background task: Importing papers generated from the export function"""
        success_count = 0
        failed_count = 0
        skipped_count = 0
        duplicate_count = 0
        others_count = 0
        total = len(papers_list)

        try:
            # Restore classification structure
            exported_categories = manifest.get("categories", {})
            current_categories = get_categories()

            # Merge classification structure (simple append to root directory)
            # TODO: Classifications can be merged more intelligently

            for idx, paper_info in enumerate(papers_list):
                try:
                    _update_task_progress(
                        task_id,
                        status="importing",
                        progress=int((idx / total) * 100),
                        current=idx,
                        total=total,
                        success_count=success_count,
                        failed_count=failed_count,
                        skipped_count=skipped_count,
                        duplicate_count=duplicate_count,
                        others_count=others_count,
                        message=f"Importing: {paper_info['metadata'].get('title', '')[:50]}...",
                    )

                    paper_metadata = paper_info["metadata"]
                    category_path_list = paper_info["category_path"]  # ['CS', 'ML']

                    # Make sure the target category exists
                    full_category_path = ["root"] + category_path_list
                    category_id = None

                    # Traverse the classification path and create non-existing categories
                    current_node = current_categories
                    for cat_name in category_path_list:
                        # Find subcategories
                        found = False
                        for child in current_node.get("children", []):
                            if child.get("name") == cat_name:
                                current_node = child
                                category_id = child.get("id")
                                found = True
                                break

                        # If it does not exist, create a new category
                        if not found:
                            # Create new category
                            new_cat_id = str(uuid.uuid4())
                            new_category = {
                                "id": new_cat_id,
                                "name": cat_name,
                                "children": [],
                                "isPinned": False,
                            }
                            if "children" not in current_node:
                                current_node["children"] = []
                            current_node["children"].append(new_category)
                            current_node = new_category
                            category_id = new_cat_id

                            # Save classification tree
                            save_categories(current_categories)

                    if not category_id:
                        print(f"[Import] ⚠️ Unable to create classification path: {category_path_list}")
                        failed_count += 1
                        continue

                    # Create category folders
                    category_folder = create_category_folder(full_category_path)

                    # Check if the same paper already exists
                    paper_id = paper_metadata.get("id")
                    existing_paper = paper_store.get(paper_id) if paper_id else None
                    if existing_paper:
                        print(
                            f"[Import] 📋 The paper already exists, skip: {paper_metadata.get('title', '')[:50]}"
                        )
                        duplicate_count += 1
                        continue

                    # generate new paper_id
                    new_paper_id = str(uuid.uuid4())

                    # copy PDF document
                    pdf_filename = os.path.basename(paper_metadata.get("file_path", ""))
                    if not pdf_filename:
                        pdf_filename = f"{new_paper_id}.pdf"

                    zip_pdf_path = os.path.join(
                        extract_dir,
                        "papers",
                        "/".join(category_path_list),
                        pdf_filename,
                    )

                    if not os.path.exists(zip_pdf_path):
                        print(f"[Import] ⚠️ PDF File does not exist: {zip_pdf_path}")
                        skipped_count += 1
                        continue

                    # copy PDF to target location
                    dest_pdf_path = os.path.join(category_folder, pdf_filename)
                    shutil.copy2(zip_pdf_path, dest_pdf_path)

                    # Copy Chinese translation (if available)
                    chinese_path = paper_metadata.get("chinese_version_path")
                    if chinese_path:
                        chinese_filename = os.path.basename(chinese_path)
                        zip_chinese_path = os.path.join(
                            extract_dir,
                            "papers",
                            "/".join(category_path_list),
                            chinese_filename,
                        )
                        if os.path.exists(zip_chinese_path):
                            dest_chinese_path = os.path.join(
                                category_folder, chinese_filename
                            )
                            shutil.copy2(zip_chinese_path, dest_chinese_path)
                            paper_metadata["chinese_version_path"] = dest_chinese_path

                    # copy AI Interpretation (if any)
                    analysis_path = paper_metadata.get("analysis_result_path")
                    if analysis_path:
                        analysis_filename = os.path.basename(analysis_path)
                        zip_analysis_path = os.path.join(
                            extract_dir,
                            "papers",
                            "/".join(category_path_list),
                            analysis_filename,
                        )
                        if os.path.exists(zip_analysis_path):
                            dest_analysis_path = os.path.join(
                                category_folder, analysis_filename
                            )
                            shutil.copy2(zip_analysis_path, dest_analysis_path)
                            paper_metadata["analysis_result_path"] = dest_analysis_path

                            # Copy picture folder
                            images_folder_name = analysis_filename.replace(
                                "_analysis.md", "_images"
                            )
                            zip_images_path = os.path.join(
                                extract_dir,
                                "papers",
                                "/".join(category_path_list),
                                images_folder_name,
                            )
                            if os.path.exists(zip_images_path) and os.path.isdir(
                                zip_images_path
                            ):
                                dest_images_path = os.path.join(
                                    category_folder, images_folder_name
                                )
                                if os.path.exists(dest_images_path):
                                    shutil.rmtree(dest_images_path)
                                shutil.copytree(zip_images_path, dest_images_path)

                    # create Paper object
                    new_paper = Paper(
                        id=new_paper_id,
                        title=paper_metadata.get("title", ""),
                        authors=paper_metadata.get("authors", ""),
                        file_path=dest_pdf_path,
                        url=paper_metadata.get("url", ""),
                        arxiv_id=paper_metadata.get("arxiv_id", ""),
                        arxiv_published_date=paper_metadata.get(
                            "arxiv_published_date", ""
                        ),
                        year=paper_metadata.get("year", ""),
                        abstract=paper_metadata.get("abstract", ""),
                        summary=paper_metadata.get("summary", ""),
                        bibtex=paper_metadata.get("bibtex", ""),
                        notes=paper_metadata.get("notes", ""),
                        upload_source="export_import",
                        has_chinese_version=paper_metadata.get(
                            "has_chinese_version", False
                        ),
                        chinese_version_path=paper_metadata.get(
                            "chinese_version_path", ""
                        ),
                        has_analysis_result=paper_metadata.get(
                            "has_analysis_result", False
                        ),
                        analysis_result_path=paper_metadata.get(
                            "analysis_result_path", ""
                        ),
                        read_time=paper_metadata.get("read_time", 0),
                        analysis_view_time=paper_metadata.get("analysis_view_time", 0),
                    )

                    # Register to paper_store
                    registered_paper = paper_store.upsert(
                        new_paper,
                        category_id=category_id,
                        category_path=full_category_path,
                    )

                    # Save metadata
                    save_paper_metadata(dest_pdf_path, registered_paper)

                    success_count += 1
                    print(
                        f"[Import] ✅ Imported successfully: {paper_metadata.get('title', '')[:50]}"
                    )

                except Exception as e:
                    print(f"[Import] ❌ Failed to import paper: {e}")
                    import traceback

                    traceback.print_exc()
                    failed_count += 1

            # Import completed
            _update_task_progress(
                task_id,
                status="completed",
                progress=100,
                current=total,
                total=total,
                success_count=success_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                duplicate_count=duplicate_count,
                others_count=others_count,
                message="Import completed",
            )

            # TODO: Restore to-read list, reading history, user settings
            # reading_list = manifest.get("reading_list", [])
            # reading_history = manifest.get("reading_history", {})
            # user_settings = manifest.get("user_settings", {})

        except Exception as e:
            print(f"[Import] ❌ Import task failed: {e}")
            import traceback

            traceback.print_exc()

            update_progress(
                status="error",
                message=f"Import failed: {str(e)}",
            )

        finally:
            # Clear current task mark
            global current_import_task_id
            current_import_task_id = None

            # Clean up temporary directory
            temp_dir = os.path.dirname(extract_dir)
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as e:
                    print(f"[Import] Failed to clean up temporary directory: {e}")

            print(
                f"[Import] Import completed: success {success_count}, fail {failed_count}, jump over {skipped_count}, repeat {duplicate_count}"
            )
