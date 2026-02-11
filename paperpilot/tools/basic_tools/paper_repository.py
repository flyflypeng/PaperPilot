from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Iterable, List, Optional

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import paper_store
from paperpilot.database.dao.paper_dao import PaperDAO


def get_paper_json_path(pdf_path: str) -> str:
    return os.path.splitext(pdf_path)[0] + ".json"


def save_paper_metadata(pdf_path: str, paper_data) -> None:
    if isinstance(paper_data, Paper):
        paper = paper_data
    else:
        paper = Paper.from_dict(paper_data) if paper_data else None
    
    if paper:
        # Ensure file_path is set
        if not paper.file_path:
            paper.file_path = pdf_path
        
        try:
            PaperDAO.save_paper(paper.to_dict())
        except Exception as exc:
            print(f"Failed to save article metadata to DB: {exc}")
            
        # Optional: Delete legacy JSON if it exists to avoid confusion?
        # json_path = get_paper_json_path(pdf_path)
        # if os.path.exists(json_path):
        #    os.remove(json_path)


def load_paper_metadata(pdf_path: str) -> Optional[Paper]:
    # 1. Try loading from DB
    try:
        data = PaperDAO.get_paper_by_path(pdf_path)
        if data:
            return Paper.from_dict(data)
    except Exception as exc:
        print(f"Failed to load from DB: {exc}")

    # 2. Fallback to JSON file (Legacy support & Migration)
    json_path = get_paper_json_path(pdf_path)
    try:
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                paper = Paper.from_dict(json.load(f))
                # Auto-migrate to DB
                if paper:
                    paper.sync_filesystem(pdf_path, os.path.basename(pdf_path))
                    save_paper_metadata(pdf_path, paper)
                return paper
    except Exception as exc:
        print(f"Failed to load article metadata from JSON: {exc}")
    return None


def delete_paper_files(pdf_path: str) -> None:
    json_path = get_paper_json_path(pdf_path)

    # Delete physical files
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
        print(f"DeletedPDFdocument: {pdf_path}")

    if os.path.exists(json_path):
        os.remove(json_path)
        print(f"DeletedJSONdocument: {json_path}")

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    pdf_dir = os.path.dirname(pdf_path)
    zh_dual = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
    zh_mono = os.path.join(pdf_dir, f"{base_name}.zh.mono.pdf")
    for f in (zh_dual, zh_mono):
        try:
            if os.path.exists(f):
                os.remove(f)
                print(f"Chinese translation removedPDF: {f}")
        except Exception as exc:
            print(f"Remove Chinese translationPDFfail: {f}, {exc}")

    outputs_dir = os.path.join(pdf_dir, "outputs")
    if os.path.exists(outputs_dir):
        for item in os.listdir(outputs_dir):
            item_path = os.path.join(outputs_dir, item)
            if os.path.isdir(item_path) and base_name in item:
                shutil.rmtree(item_path)
                print(f"DeletedAIInterpret the output directory: {item_path}")
        try:
            if not os.listdir(outputs_dir):
                os.rmdir(outputs_dir)
                print(f"Empty deletedoutputsTable of contents: {outputs_dir}")
        except Exception:
            pass
            
    # Delete from DB
    try:
        # We need the ID. Try to get it from DB first.
        data = PaperDAO.get_paper_by_path(pdf_path)
        if data and data.get('id'):
            PaperDAO.delete_paper(data['id'])
    except Exception as e:
        print(f"Failed to delete paper from DB: {e}")


def scan_papers_in_directory(
    directory_path: str,
    *,
    category_id: str,
    category_path: Iterable[str],
) -> List[Paper]:
    category_path_list = list(category_path)
    paper_store.mark_category_initialized(category_id, category_path_list)
    papers: List[Paper] = []
    if not os.path.exists(directory_path):
        return papers

    for filename in os.listdir(directory_path):
        if not filename.lower().endswith(".pdf"):
            continue

        if filename.endswith(".zh.dual.pdf") or filename.endswith(".zh.mono.pdf"):
            continue

        pdf_path = os.path.join(directory_path, filename)
        paper = load_paper_metadata(pdf_path)

        if paper:
            paper.sync_filesystem(pdf_path, filename)
        else:
            paper = Paper.create_default(
                filename=filename,
                file_path=pdf_path,
                original_filename=filename,
                upload_date=datetime.fromtimestamp(
                    os.path.getctime(pdf_path)
                ).isoformat(),
            )

        paper.mark_starred(getattr(paper, "starred", False))

        base_name = os.path.splitext(filename)[0]
        dual_file = os.path.join(directory_path, f"{base_name}.zh.dual.pdf")
        paper.mark_chinese_version(dual_file if os.path.exists(dual_file) else None)
        if not paper.has_chinese_version:
            paper.use_chinese_version = False

        pdf_dir = os.path.dirname(pdf_path)
        outputs_dir = os.path.join(pdf_dir, "outputs")
        analysis_result_path = None
        if os.path.exists(outputs_dir):
            for item in os.listdir(outputs_dir):
                item_path = os.path.join(outputs_dir, item)
                if os.path.isdir(item_path) and base_name in item:
                    vlm_dir = os.path.join(item_path, "vlm")
                    if os.path.exists(vlm_dir):
                        result_file = os.path.join(vlm_dir, "result.md")
                        if os.path.exists(result_file):
                            analysis_result_path = result_file
                            break
        paper.mark_analysis_result(analysis_result_path)

        registered = paper_store.upsert(
            paper, category_id=category_id, category_path=category_path_list
        )
        save_paper_metadata(pdf_path, registered)
        papers.append(registered)

    return papers


def refresh_paper_status(paper: Paper) -> None:
    """Check the file system and update the translation and interpretation status of the paper"""
    if not paper.file_path or not os.path.exists(paper.file_path):
        return
    
    pdf_dir = os.path.dirname(paper.file_path)
    base_name = os.path.splitext(os.path.basename(paper.file_path))[0]
    
    # Check translation files
    dual_file = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
    paper.mark_chinese_version(dual_file if os.path.exists(dual_file) else None)
    
    # Check interpretation results
    outputs_dir = os.path.join(pdf_dir, "outputs")
    analysis_result_path = None
    if os.path.exists(outputs_dir):
        for item in os.listdir(outputs_dir):
            item_path = os.path.join(outputs_dir, item)
            if os.path.isdir(item_path) and base_name in item:
                vlm_dir = os.path.join(item_path, "vlm")
                if os.path.exists(vlm_dir):
                    result_file = os.path.join(vlm_dir, "result.md")
                    if os.path.exists(result_file):
                        analysis_result_path = result_file
                        break
    paper.mark_analysis_result(analysis_result_path)


def get_papers_in_category(
    upload_folder: str, category_id: str, category_path: List[str]
) -> List[Paper]:
    if not category_path:
        return []
    if paper_store.is_category_initialized(category_id):
        papers = paper_store.list_by_category(category_id)
        # Refresh status of each paper (check file system)
        for paper in papers:
            old_has_chinese = paper.has_chinese_version
            old_has_analysis = paper.has_analysis_result
            refresh_paper_status(paper)
            # If the status changes, save to JSON document
            if (paper.has_chinese_version != old_has_chinese or 
                paper.has_analysis_result != old_has_analysis):
                if paper.file_path and os.path.exists(paper.file_path):
                    save_paper_metadata(paper.file_path, paper)
        return papers
    directory_path = os.path.join(upload_folder, *category_path[1:])
    return scan_papers_in_directory(
        directory_path, category_id=category_id, category_path=category_path
    )
