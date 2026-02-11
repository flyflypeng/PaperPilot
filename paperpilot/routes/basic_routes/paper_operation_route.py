from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Tuple

from flask import Flask, jsonify, request, send_file

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import PaperStore
from paperpilot.database.dao.user_data_dao import ReadingListDAO, ReadingHistoryDAO
from paperpilot.tools.basic_tools.paper_repository import scan_papers_in_directory
from paperpilot.tools.basic_tools.upload_paper import (
    process_uploaded_pdf,
    search_arxiv_by_title_only,
)


class GetCategoriesFn(Protocol):
    def __call__(self) -> Dict[str, Any]: ...


class GetCategoryPathFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
        path: Optional[List[str]] = None,
    ) -> Optional[List[str]]: ...


class FindCategoryNodeFn(Protocol):
    def __call__(
        self,
        categories: Dict[str, Any],
        category_id: str,
    ) -> Optional[Dict[str, Any]]: ...


class GetPapersInCategoryFn(Protocol):
    def __call__(self, category_id: str, category_path: List[str]) -> List[Paper]: ...


class CreateCategoryFolderFn(Protocol):
    def __call__(self, category_path: List[str]) -> str: ...


class SavePaperMetadataFn(Protocol):
    def __call__(self, pdf_path: str, paper: Paper) -> None: ...


class GetPaperJsonPathFn(Protocol):
    def __call__(self, pdf_path: str) -> str: ...


class DeletePaperFilesFn(Protocol):
    def __call__(self, pdf_path: str) -> None: ...


class AddToReadingListFn(Protocol):
    def __call__(self, paper_id: str) -> None: ...


class RemoveFromReadingListFn(Protocol):
    def __call__(self, paper_id: str) -> None: ...


def register_paper_operation_routes(
    app: Flask,
    *,
    get_categories: GetCategoriesFn,
    get_category_path: GetCategoryPathFn,
    find_category_node: FindCategoryNodeFn,
    get_papers_in_category: GetPapersInCategoryFn,
    create_category_folder: CreateCategoryFolderFn,
    save_paper_metadata: SavePaperMetadataFn,
    get_paper_json_path: GetPaperJsonPathFn,
    delete_paper_files: DeletePaperFilesFn,
    extract_pdf_metadata: Optional[Any],  # No longer used, reserved for compatibility
    search_arxiv_by_title: Optional[Any],  # No longer used, reserved for compatibility
    reading_list_file: str,
    upload_folder: str,
    paper_store: PaperStore,
) -> None:

    def load_reading_list() -> List[str]:
        items = ReadingListDAO.get_list()
        return [item['paper_id'] for item in items]

    def save_reading_list(paper_ids: List[str]) -> None:
        pass

    def add_to_reading_list(paper_id: str) -> None:
        ReadingListDAO.add_item(paper_id, datetime.now().isoformat())

    def remove_from_reading_list(paper_id: str) -> None:
        ReadingListDAO.remove_item(paper_id)

    def is_in_reading_list(paper_id: str) -> bool:
        return paper_id in load_reading_list()

    def find_paper(paper_id: str) -> Optional[Tuple[Paper, List[str], str]]:
        entry = paper_store.get_entry(paper_id)
        if not entry:
            return None
        return entry.paper, list(entry.category_path), entry.category_id

    def collect_papers_by_ids(paper_ids: Iterable[str]) -> List[Paper]:
        ordered_ids = list(paper_ids)
        collected: List[Paper] = []
        seen: set[str] = set()
        for pid in ordered_ids:
            if pid in seen:
                continue
            paper = paper_store.get(pid)
            if paper:
                collected.append(paper)
                seen.add(pid)
        return collected

    @app.route("/api/papers/all")
    def api_all_papers():
        """Get all papers, sorted by upload date in descending order"""
        all_papers = paper_store.iter_all()
        # Sort by upload date in descending order (newest first)
        sorted_papers = sorted(
            all_papers, key=lambda p: p.upload_date or "", reverse=True
        )
        return jsonify([paper.to_dict() for paper in sorted_papers])

    @app.route("/api/papers/<category_id>")
    def api_papers(category_id: str):
        categories = get_categories()
        category_path = get_category_path(categories, category_id)

        if not category_path:
            return jsonify({"error": "Category not found"}), 404

        papers = get_papers_in_category(category_id, category_path)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/papers/<category_id>/recursive")
    def api_papers_recursive(category_id: str):
        """Recursively obtain papers under a category and all its subcategories (for first-level directories/Project）"""
        categories = get_categories()
        category_node = find_category_node(categories, category_id)

        if not category_node:
            return jsonify({"error": "Category not found"}), 404

        def collect_papers_recursive(node: Dict[str, Any]) -> List[Any]:
            """Recursively collect all papers under a category and its subcategories"""
            all_papers = []

            # Get papers in the current category
            node_path = get_category_path(categories, node["id"])
            if node_path:
                node_papers = get_papers_in_category(node["id"], node_path)
                all_papers.extend(node_papers)

            # Recursively process subcategories
            for child in node.get("children", []):
                all_papers.extend(collect_papers_recursive(child))

            return all_papers

        all_papers = collect_papers_recursive(category_node)

        # Sort by upload time (newest first)
        sorted_papers = sorted(
            all_papers, key=lambda p: p.upload_date or "", reverse=True
        )

        return jsonify([paper.to_dict() for paper in sorted_papers])

    @app.route("/api/paper/<paper_id>")
    def api_paper_info(paper_id: str):
        result = find_paper(paper_id)
        if result:
            paper, _, _ = result
            return jsonify(paper.to_dict())
        return jsonify({"error": "Paper not found"}), 404

    @app.route("/api/paper/<paper_id>/move", methods=["PUT"])
    def api_move_paper(paper_id: str):
        data = request.json or {}
        target_category_id = data.get("target_category_id")

        if not target_category_id:
            return (
                jsonify({"success": False, "error": "Target category ID is required"}),
                400,
            )

        categories = get_categories()
        result = find_paper(paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        paper_obj, source_path, source_category_id = result

        target_category = find_category_node(categories, target_category_id)
        if not target_category:
            return (
                jsonify({"success": False, "error": "Target category not found"}),
                404,
            )

        target_path = get_category_path(categories, target_category_id)
        if not target_path:
            return (
                jsonify({"success": False, "error": "Target category path not found"}),
                404,
            )

        try:
            target_folder = (
                os.path.join(upload_folder, *target_path[1:])
                if len(target_path) > 1
                else upload_folder
            )

            source_file_path = paper_obj.file_path
            source_json_path = get_paper_json_path(source_file_path)
            source_dir = os.path.dirname(source_file_path)
            source_base_name = os.path.splitext(os.path.basename(source_file_path))[0]

            os.makedirs(target_folder, exist_ok=True)

            target_file_path = os.path.join(target_folder, paper_obj.filename)
            target_json_path = get_paper_json_path(target_file_path)

            counter = 1
            original_filename = paper_obj.filename
            original_base_name = os.path.splitext(original_filename)[0]
            while os.path.exists(target_file_path):
                name, ext = os.path.splitext(original_filename)
                new_filename = f"{name}_{counter}{ext}"
                target_file_path = os.path.join(target_folder, new_filename)
                target_json_path = get_paper_json_path(target_file_path)
                counter += 1

            # finalizebase_name(May change due to duplicate name)
            final_base_name = os.path.splitext(os.path.basename(target_file_path))[0]

            # movePDFmaster file
            if os.path.exists(source_file_path):
                shutil.move(source_file_path, target_file_path)
                print(f"MovedPDFdocument: {source_file_path} -> {target_file_path}")

            # moveJSONdocument
            if os.path.exists(source_json_path):
                shutil.move(source_json_path, target_json_path)
                print(f"MovedJSONdocument: {source_json_path} -> {target_json_path}")

            # Mobile Chinese translation files
            zh_dual_source = os.path.join(source_dir, f"{source_base_name}.zh.dual.pdf")
            zh_mono_source = os.path.join(source_dir, f"{source_base_name}.zh.mono.pdf")
            translate_log_source = os.path.join(
                source_dir, f"{source_base_name}.translate.log"
            )

            zh_dual_target = os.path.join(
                target_folder, f"{final_base_name}.zh.dual.pdf"
            )
            zh_mono_target = os.path.join(
                target_folder, f"{final_base_name}.zh.mono.pdf"
            )
            translate_log_target = os.path.join(
                target_folder, f"{final_base_name}.translate.log"
            )

            if os.path.exists(zh_dual_source):
                shutil.move(zh_dual_source, zh_dual_target)
                print(
                    f"Chinese translation moved: {zh_dual_source} -> {zh_dual_target}"
                )
                # renewPaperChinese version path in the object
                paper_obj.chinese_version_path = zh_dual_target

            if os.path.exists(zh_mono_source):
                shutil.move(zh_mono_source, zh_mono_target)
                print(
                    f"Chinese translation moved(mono): {zh_mono_source} -> {zh_mono_target}"
                )

            if os.path.exists(translate_log_source):
                shutil.move(translate_log_source, translate_log_target)
                print(
                    f"Translation log moved: {translate_log_source} -> {translate_log_target}"
                )

            # moveAIInterpret the output directory
            source_outputs_dir = os.path.join(source_dir, "outputs")
            target_outputs_dir = os.path.join(target_folder, "outputs")

            if os.path.exists(source_outputs_dir):
                os.makedirs(target_outputs_dir, exist_ok=True)

                for item in os.listdir(source_outputs_dir):
                    item_path = os.path.join(source_outputs_dir, item)
                    # Check if it is the output directory of the current paper
                    if os.path.isdir(item_path) and source_base_name in item:
                        # Rename the output directory to match the new filename
                        if source_base_name != final_base_name:
                            new_item_name = item.replace(
                                source_base_name, final_base_name
                            )
                        else:
                            new_item_name = item

                        target_item_path = os.path.join(
                            target_outputs_dir, new_item_name
                        )

                        # If target already exists, add counter
                        item_counter = 1
                        while os.path.exists(target_item_path):
                            new_item_name = f"{item}_{item_counter}"
                            target_item_path = os.path.join(
                                target_outputs_dir, new_item_name
                            )
                            item_counter += 1

                        shutil.move(item_path, target_item_path)
                        print(
                            f"MovedAIInterpret the output: {item_path} -> {target_item_path}"
                        )

                        # renewPaperInterpretation result path in object
                        if (
                            paper_obj.analysis_result_path
                            and paper_obj.analysis_result_path.startswith(item_path)
                        ):
                            relative_path = os.path.relpath(
                                paper_obj.analysis_result_path, item_path
                            )
                            new_result_path = os.path.join(
                                target_item_path, relative_path
                            )
                            paper_obj.analysis_result_path = new_result_path
                            print(
                                f"Interpretation result path updated: {new_result_path}"
                            )

                # Clean up empty sourcesoutputsTable of contents
                try:
                    if not os.listdir(source_outputs_dir):
                        os.rmdir(source_outputs_dir)
                        print(
                            f"Empty source removedoutputsTable of contents: {source_outputs_dir}"
                        )
                except Exception:
                    pass

            # renewPaperBasic information about the object
            paper_obj.filename = os.path.basename(target_file_path)
            paper_obj.file_path = target_file_path

            # First update the category information in paper_store
            # so that the search index sees the latest category when saving metadata.
            paper_store.update_category(
                paper_id,
                category_id=target_category_id,
                category_path=target_path,
            )

            # Save updated metadata and update search index (with the new category)
            save_paper_metadata(target_file_path, paper_obj)

            return jsonify(
                {
                    "success": True,
                    "paper": paper_obj.to_dict(),
                    "source_category": source_category_id,
                    "target_category": target_category_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to move paper: {exc}")
            return (
                jsonify({"success": False, "error": f"Failed to move file: {exc}"}),
                500,
            )

    @app.route("/api/paper/<paper_id>/file")
    def api_get_paper_file(paper_id: str):
        result = find_paper(paper_id)
        if not result:
            return jsonify({"error": "Paper not found"}), 404

        paper, category_path, _ = result
        file_path = paper.file_path

        if not file_path:
            filename = paper.filename
            if filename and category_path:
                category_folder = create_category_folder(category_path[1:])
                file_path = os.path.join(category_folder, filename)
                print(f"Try to rebuild the path: {file_path}")

        if not file_path:
            return jsonify({"error": "File path not found in paper data"}), 404

        if not os.path.isabs(file_path):
            file_path = os.path.abspath(file_path)

        print(f"FindPDFdocument: {file_path}, exist: {os.path.exists(file_path)}")
        if not os.path.exists(file_path):
            return jsonify({"error": f"File not found: {file_path}"}), 404

        response = send_file(
            file_path,
            as_attachment=False,
            mimetype="application/pdf",
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.route("/api/paper/<paper_id>", methods=["DELETE"])
    def api_delete_paper(paper_id: str):
        try:
            result = find_paper(paper_id)
            if not result:
                return jsonify({"error": "Paper not found"}), 404

            paper, _, category_id = result
            if paper.file_path:
                delete_paper_files(paper.file_path)
            paper_store.remove(paper_id)

            return jsonify(
                {
                    "success": True,
                    "message": "Paper deleted successfully",
                    "paper": paper.to_dict(),
                    "category_id": category_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to delete paper: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>", methods=["PUT"])
    def api_update_paper(paper_id: str):
        try:
            data = request.json or {}
            result = find_paper(paper_id)
            if not result:
                return jsonify({"error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # Check whether the user has modified it manually title
            old_title = paper.title
            title_changed = False
            if "title" in data and data["title"] != old_title:
                title_changed = True
                new_title = data["title"]
                print(
                    f"[Title update] User changes title: '{old_title}' → '{new_title}'"
                )

            paper.update_from_dict(data)
            paper.extra["updated_date"] = datetime.now().isoformat()

            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            # If the user modified title, automatically re-crawl in the background
            if title_changed and new_title:

                def _auto_refresh_on_title_change():
                    try:
                        print(
                            f"[Automatic recapture] The title has been modified, start crawling again: {new_title}"
                        )

                        # Search using the new interface arXiv
                        best_match = search_arxiv_by_title_only(new_title)

                        if best_match:
                            print(
                                f"[Automatic recapture] found match: {best_match.get('title')[:50]}..."
                            )

                            # Update only arXiv Related information, do not modify the manual settings set by the user title
                            paper_obj = paper_store.get(paper_id)
                            if paper_obj:
                                # Update except title All fields except
                                paper_obj.authors = best_match.get("authors", "")
                                paper_obj.affiliation = best_match.get(
                                    "affiliation", ""
                                )
                                paper_obj.abstract = best_match.get("abstract", "")
                                paper_obj.year = best_match.get("year", "")
                                paper_obj.bibtex = best_match.get("bibtex", "")
                                paper_obj.arxiv_id = best_match.get("arxiv_id", "")
                                paper_obj.arxiv_published_date = best_match.get(
                                    "published_date"
                                )
                                paper_obj.summary = best_match.get("summary", "")
                                paper_obj.extra["auto_refreshed_date"] = (
                                    datetime.now().isoformat()
                                )

                                # Save updates
                                paper_store.upsert(
                                    paper_obj,
                                    category_id=category_id,
                                    category_path=category_path,
                                )
                                if paper_obj.file_path:
                                    save_paper_metadata(paper_obj.file_path, paper_obj)

                                print(
                                    f"[Automatic recapture] Completed: Author, affiliation, abstract and other information has been updated"
                                )
                            else:
                                print(
                                    f"[Automatic recapture] warn: not found paper {paper_id}"
                                )
                        else:
                            print(
                                f"[Automatic recapture] No match found, keep the information entered by the user unchanged"
                            )

                    except Exception as exc:  # noqa: BLE001
                        print(f"[Automatic recapture] fail: {exc}")

                # Start background thread
                thread = threading.Thread(
                    target=_auto_refresh_on_title_change, daemon=True
                )
                thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": "Paper updated successfully",
                    "paper": paper.to_dict(),
                    "auto_refresh_triggered": title_changed,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to update paper: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/reading-list", methods=["GET"])
    def api_get_reading_list():
        paper_ids = load_reading_list()

        # Auto-sync: scan _ReadingListTemp Table of contents, add papers in the table of contents to the to-read list
        reading_list_temp_path = os.path.join(upload_folder, "_ReadingListTemp")
        if os.path.exists(reading_list_temp_path):
            # Scan all papers in the directory
            temp_papers = scan_papers_in_directory(
                reading_list_temp_path,
                category_id="reading_list_temp",
                category_path=["Root", "_ReadingListTemp"],
            )

            # Will _ReadingListTemp Papers in the table of contents are added to the to-read list (if they are not already there)
            for paper in temp_papers:
                if paper.id not in paper_ids:
                    add_to_reading_list(paper.id)
                    paper_ids.append(paper.id)

        # Return all to-read list papers (no more limited number)
        papers = collect_papers_by_ids(paper_ids)
        return jsonify([paper.to_dict() for paper in papers])

    @app.route("/api/reading-list/<paper_id>/add", methods=["POST"])
    def api_add_to_reading_list(paper_id: str):
        result = find_paper(paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        add_to_reading_list(paper_id)
        return jsonify({"success": True})

    @app.route("/api/reading-list/<paper_id>/remove", methods=["POST"])
    def api_remove_from_reading_list(paper_id: str):
        if not is_in_reading_list(paper_id):
            return (
                jsonify({"success": False, "error": "Paper not in reading list"}),
                404,
            )

        # Get paper information
        result = find_paper(paper_id)
        if not result:
            return jsonify({"success": False, "error": "Paper not found"}), 404

        paper, category_path, category_id = result

        # Check if it is still in the temporary directory used by the reading list.
        # We require BOTH the category information and the actual file path to match
        # the temp directory, to avoid accidentally deleting papers that have already
        # been moved into a normal category.
        temp_dir = os.path.join(upload_folder, "_ReadingListTemp")
        is_temp_category = (
            category_id == "reading_list_temp"
            or (
                category_path
                and len(category_path) > 1
                and category_path[1] == "_ReadingListTemp"
            )
        )
        is_in_temp_dir = (
            bool(paper.file_path)
            and os.path.abspath(paper.file_path).startswith(os.path.abspath(temp_dir))
        )
        is_in_temp = is_temp_category and is_in_temp_dir

        # Get delete options
        data = request.json or {}
        delete_files = data.get("delete_files", False)

        # If it is in the temporary directory, the user is required to confirm the deletion of the file (regardless of the source)
        if is_in_temp and not delete_files:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Need to confirm deletion",
                        "requires_confirmation": True,
                        "message": "The paper has not been moved to a certain directory. Do you want to delete the paper file?",
                    }
                ),
                200,
            )  # return 200 for front-end processing

        # If file deletion is confirmed, delete the paper and its related files
        # As long as temp Delete files from directory
        if delete_files and is_in_temp and paper.file_path:
            delete_paper_files(paper.file_path)
            paper_store.remove(paper_id)
        elif not is_in_temp:
            # if not temp Directory, only removed from the to-read list, files are not deleted
            # The paper remains in its original catalog
            pass

        # Remove from to-read list
        remove_from_reading_list(paper_id)

        # Returns whether the file was deleted (the file is only deleted when it is in the temporary directory and the user confirms the deletion)
        return jsonify({"success": True, "deleted_files": delete_files and is_in_temp})

    @app.route("/api/paper/<paper_id>/read-time", methods=["POST"])
    def api_record_read_time(paper_id: str):
        """Record paper reading time (cumulative increment)"""
        try:
            import json as json_lib
            import os
            from datetime import datetime

            data = request.json or {}
            # Use incremental mode
            increment = data.get("increment", 0)

            if not isinstance(increment, (int, float)) or increment <= 0:
                return jsonify({"success": True, "read_time": 0}), 200

            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # Cumulative reading time increment
            paper.record_read_time(int(increment))

            # save to file
            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            # Update reading history
            today = datetime.now().strftime("%Y-%m-%d")
            duration = int(increment)
            timestamp = int(datetime.now().timestamp())
            
            ReadingHistoryDAO.add_history(today, duration, paper_id, timestamp)

            return jsonify({"success": True, "read_time": paper.read_time})

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to record reading time: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>/analysis-view-time", methods=["POST"])
    def api_record_analysis_view_time(paper_id: str):
        """Record AI Interpretation reading time (cumulative increments)"""
        try:
            data = request.json or {}
            # Use incremental mode
            increment = data.get("increment", 0)

            if not isinstance(increment, (int, float)) or increment <= 0:
                return jsonify({"success": True, "analysis_view_time": 0}), 200

            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result

            # Cumulative interpretation reading time increment
            paper.record_analysis_view_time(int(increment))

            # save to file
            if paper.file_path:
                save_paper_metadata(paper.file_path, paper)

            return jsonify(
                {"success": True, "analysis_view_time": paper.analysis_view_time}
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Record interpretation reading time failed: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/paper/<paper_id>/refresh-metadata", methods=["POST"])
    def api_refresh_paper_metadata(paper_id: str):
        """Re-crawl PDF metadata"""
        try:
            result = find_paper(paper_id)
            if not result:
                return jsonify({"success": False, "error": "Paper not found"}), 404

            paper, category_path, category_id = result
            file_path = paper.file_path

            if not file_path or not os.path.exists(file_path):
                return jsonify({"success": False, "error": "PDF file not found"}), 404

            # Start background thread processing
            def _refresh_metadata_async():
                try:
                    print(f"[Re-crawl] Start processing: {file_path}")

                    # Processed using the new unified interface PDF
                    filename = os.path.basename(file_path)
                    paper_info = process_uploaded_pdf(file_path, filename)

                    if not paper_info:
                        print("[Re-crawl] Unable to obtain paper information")
                        return

                    print(f"[Re-crawl] found match: {paper_info.get('title')[:50]}...")

                    # Use the information obtained
                    metadata = paper_info
                    arxiv_id = paper_info.get("arxiv_id")
                    arxiv_published_date = paper_info.get("published_date")

                    # step2: Rename the file according to the new title (if the title changes)
                    current_filename = os.path.basename(file_path)
                    new_filename = current_filename
                    new_file_path = file_path
                    category_folder = os.path.dirname(file_path)

                    if metadata and metadata.get("title"):

                        def _clean_filename(text: Optional[str]) -> Optional[str]:
                            if not text:
                                return None
                            cleaned = text
                            cleaned = re.sub(r'[<>:"/\\|?*]', "", cleaned)
                            cleaned = re.sub(r"\s+", " ", cleaned)
                            cleaned = cleaned.strip()
                            return cleaned[:200] if cleaned else None

                        clean_title = _clean_filename(metadata["title"])
                        if (
                            clean_title
                            and clean_title != os.path.splitext(current_filename)[0]
                        ):
                            new_filename = f"{clean_title}.pdf"
                            new_file_path = os.path.join(category_folder, new_filename)

                            counter = 1
                            original_new_filename = new_filename
                            while (
                                os.path.exists(new_file_path)
                                and new_file_path != file_path
                            ):
                                name, ext = os.path.splitext(original_new_filename)
                                new_filename = f"{name}_{counter}{ext}"
                                new_file_path = os.path.join(
                                    category_folder, new_filename
                                )
                                counter += 1

                            # Rename file
                            if new_file_path != file_path:
                                try:
                                    # move simultaneously JSON document
                                    old_json_path = get_paper_json_path(file_path)
                                    new_json_path = get_paper_json_path(new_file_path)

                                    os.rename(file_path, new_file_path)
                                    print(
                                        f"[Re-crawl] File has been renamed: {new_filename}"
                                    )

                                    if os.path.exists(old_json_path):
                                        os.rename(old_json_path, new_json_path)
                                        print(f"[Re-crawl] JSON File has been renamed")

                                except Exception as exc:  # noqa: BLE001
                                    print(f"[Re-crawl] Rename failed: {exc}")
                                    new_file_path = file_path
                                    new_filename = current_filename

                    # step3: renew Paper object
                    paper_obj = paper_store.get(paper_id)
                    if paper_obj and metadata:
                        paper_obj.filename = new_filename
                        paper_obj.file_path = new_file_path
                        paper_obj.title = metadata.get("title") or paper_obj.title
                        paper_obj.authors = metadata.get("authors", "")
                        paper_obj.arxiv_id = arxiv_id
                        # if there is arxiv_id,set up arxiv_url
                        if arxiv_id:
                            paper_obj.arxiv_url = (
                                metadata.get("arxiv_url")
                                or f"https://arxiv.org/abs/{arxiv_id}"
                            )
                        paper_obj.arxiv_published_date = arxiv_published_date
                        paper_obj.affiliation = metadata.get("affiliation", "")
                        paper_obj.year = metadata.get("year", "")
                        paper_obj.abstract = metadata.get("abstract", "")
                        paper_obj.summary = metadata.get("summary", "")
                        paper_obj.bibtex = metadata.get("bibtex", "")
                        paper_obj.keywords = metadata.get("keywords", "")
                        paper_obj.subject = metadata.get("subject", "")
                        paper_obj.extra["updated_date"] = datetime.now().isoformat()

                        # Save updates
                        paper_store.upsert(
                            paper_obj,
                            category_id=category_id,
                            category_path=category_path,
                        )
                        save_paper_metadata(new_file_path, paper_obj)
                        print(f"[Re-crawl] Finish: {new_filename}")
                    else:
                        print(f"[Re-crawl] warn: not found paper {paper_id}")

                except Exception as exc:  # noqa: BLE001
                    print(f"[Re-crawl] fail: {exc}")

            thread = threading.Thread(target=_refresh_metadata_async, daemon=True)
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": "Metadata crawling has started and will be processed in the background",
                    "paper_id": paper_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to start re-crawling: {exc}")
            return jsonify({"success": False, "error": str(exc)}), 500
