from __future__ import annotations

import os
import subprocess
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List

from flask import jsonify, request, send_file

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store
from resophy.tools.agent_tools.translate_pdf import (
    TranslationDependencies,
    translate_paper_task,
)
from resophy.tools.api_test_utils import test_llm_api

CategoryPath = List[str]


def register_agent_translate_routes(
    app,
    *,
    translation_tasks: Dict[str, Dict[str, Any]],
    translation_tasks_lock: threading.Lock,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], CategoryPath | None],
    get_papers_in_category: Callable[[str, CategoryPath], List[Paper]],
    save_paper_metadata: Callable[[str, Any], None],
    agentic_settings_file: str,
) -> None:
    @app.route("/api/paper/translate", methods=["POST"])
    def api_translate_paper():
        """translatePDFpaper - Start background task"""
        try:
            data = request.json or {}
            paper_id = data.get("paper_id")
            openai_model = data.get("openai_model")
            openai_base_url = data.get("openai_base_url")
            openai_api_key = data.get("openai_api_key")

            if (
                not paper_id
                or not openai_model
                or not openai_base_url
                or not openai_api_key
            ):
                return jsonify({"success": False, "error": "Missing required parameters"}), 400

            # Test before starting a task LLM API connect
            llm_success, llm_error = test_llm_api(
                openai_model, openai_base_url, openai_api_key
            )
            if not llm_success:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"LLM API test failed: {llm_error}",
                        }
                    ),
                    400,
                )

            with translation_tasks_lock:
                for task_id, task_info in translation_tasks.items():
                    if (
                        task_info["paper_id"] == paper_id
                        and task_info["status"] == "running"
                    ):
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "There is already a translation task running for this paper",
                                    "task_id": task_id,
                                }
                            ),
                            400,
                        )

            # First try from paper_store Find papers in（support _ReadingListTemp Table of contents）
            entry = paper_store.get_entry(paper_id)
            if entry:
                paper = entry.paper
                category_path = list(entry.category_path)
            else:
                # if paper_store Not found in , use recursive search of classification tree
                categories = get_categories()

                def search_paper_recursive(node):
                    category_path = get_category_path(categories, node["id"])
                    if category_path:
                        papers = get_papers_in_category(node["id"], category_path)
                        for paper in papers:
                            if paper.id == paper_id:
                                return paper, category_path

                    if "children" in node:
                        for child in node["children"]:
                            result = search_paper_recursive(child)
                            if result:
                                return result

                    return None

                result = None
                for child in categories.get("children", []):
                    result = search_paper_recursive(child)
                    if result:
                        break

                if not result:
                    return jsonify({"success": False, "error": "Paper not found"}), 404

                paper, category_path = result
            pdf_path = paper.file_path

            if not pdf_path or not os.path.exists(pdf_path):
                return jsonify({"success": False, "error": "PDFFile does not exist"}), 404

            pdf_dir = os.path.dirname(pdf_path)
            pdf_filename = os.path.basename(pdf_path)

            task_id = str(uuid.uuid4())

            with translation_tasks_lock:
                translation_tasks[task_id] = {
                    "paper_id": paper_id,
                    "status": "queued",
                    "progress": 0,
                    "logs": [],
                    "log_lock": threading.Lock(),
                    "process": None,
                    "start_time": datetime.now().isoformat(),
                    "result": None,
                }

            deps = TranslationDependencies(
                translation_tasks=translation_tasks,
                translation_tasks_lock=translation_tasks_lock,
                get_categories=get_categories,
                get_category_path=get_category_path,
                get_papers_in_category=get_papers_in_category,
                save_paper_metadata=save_paper_metadata,
            )

            thread = threading.Thread(
                target=translate_paper_task,
                args=(
                    task_id,
                    paper_id,
                    pdf_path,
                    pdf_dir,
                    pdf_filename,
                    openai_model,
                    openai_base_url,
                    openai_api_key,
                    deps,
                ),
            )
            thread.daemon = True
            thread.start()

            return jsonify(
                {"success": True, "message": "Translation task started", "task_id": task_id}
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to start translation task: {exc}")
            import traceback

            traceback.print_exc()
            return (
                jsonify({"success": False, "error": f"Failed to start translation task: {str(exc)}"}),
                500,
            )

    @app.route("/api/paper/translate/active", methods=["GET"])
    def api_get_active_translations():
        """Get all ongoing translation tasks"""
        with translation_tasks_lock:
            active_tasks = []
            for task_id, task_info in translation_tasks.items():
                if task_info["status"] in ["queued", "running"]:
                    active_tasks.append(
                        {
                            "task_id": task_id,
                            "paper_id": task_info["paper_id"],
                            "status": task_info["status"],
                            "start_time": task_info["start_time"],
                        }
                    )
            return jsonify({"success": True, "tasks": active_tasks})

    @app.route("/api/paper/translate/<task_id>/logs", methods=["GET"])
    def api_get_translation_logs(task_id):
        """Get logs of translation tasks"""
        with translation_tasks_lock:
            if task_id not in translation_tasks:
                return jsonify({"success": False, "error": "Task does not exist"}), 404

            task_info = translation_tasks[task_id]
            with task_info["log_lock"]:
                logs = task_info["logs"].copy()
                progress = int(task_info.get("progress") or 0)

            return jsonify(
                {
                    "success": True,
                    "status": task_info["status"],
                    "progress": max(0, min(100, progress)),
                    "logs": logs,
                    "start_time": task_info["start_time"],
                    "result": task_info.get("result"),
                }
            )

    @app.route("/api/paper/translate/<task_id>/cancel", methods=["POST"])
    def api_cancel_translation(task_id):
        """Cancel translation task"""
        with translation_tasks_lock:
            if task_id not in translation_tasks:
                return jsonify({"success": False, "error": "Task does not exist"}), 404

            task_info = translation_tasks[task_id]

            if task_info["status"] in ["completed", "failed", "cancelled"]:
                return (
                    jsonify({"success": False, "error": "The task has ended and cannot be canceled"}),
                    400,
                )

            process = task_info.get("process")
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                except Exception as exc:  # noqa: BLE001
                    print(f"Failed to terminate process: {exc}")

            task_info["status"] = "cancelled"
            task_info["result"] = {"success": False, "error": "Translation canceled"}

            return jsonify({"success": True, "message": "Translation task canceled"})

    @app.route("/api/paper/<paper_id>/chinese/file")
    def api_get_chinese_paper_file(paper_id):
        """Get the Chinese versionPDFdocument"""
        # First try from paper_store Find papers in（support _ReadingListTemp Table of contents）
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
        else:
            # if paper_store Not found in , use recursive search of classification tree
            categories = get_categories()

            def search_paper_file(node):
                category_path = get_category_path(categories, node["id"])
                if category_path:
                    papers = get_papers_in_category(node["id"], category_path)
                    for paper in papers:
                        if paper.id == paper_id:
                            return paper

                if "children" in node:
                    for child in node["children"]:
                        result = search_paper_file(child)
                        if result:
                            return result

                return None

            paper = None
            for child in categories.get("children", []):
                paper = search_paper_file(child)
                if paper:
                    break

            if not paper:
                return jsonify({"error": "Paper not found"}), 404

        chinese_path = paper.chinese_version_path
        if chinese_path and os.path.exists(chinese_path):
            response = send_file(
                chinese_path,
                as_attachment=False,
                mimetype="application/pdf",
            )
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            return response
        return jsonify({"error": "Chinese version file does not exist"}), 404
