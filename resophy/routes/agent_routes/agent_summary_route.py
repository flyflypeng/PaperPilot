from __future__ import annotations

import mimetypes
import os
import posixpath
import subprocess
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request, send_file

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store
from resophy.database.dao.settings_dao import SettingsDAO
from resophy.tools.agent_tools.summary_pdf import (
    AnalysisDependencies,
    analyze_paper_task,
)
from resophy.tools.api_test_utils import test_llm_api, test_mineru_api

CategoryPath = List[str]


def register_agent_summary_routes(
    app,
    *,
    analysis_tasks: Dict[str, Dict[str, Any]],
    analysis_tasks_lock: threading.Lock,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], CategoryPath | None],
    get_papers_in_category: Callable[[str, CategoryPath], List[Paper]],
    save_paper_metadata: Callable[[str, Any], None],
    agentic_settings_file: str,
) -> None:
    @app.route("/api/paper/analyze", methods=["POST"])
    def api_analyze_paper():
        """AI InterpretationPDFpaper - Start background task"""
        try:
            import json

            data = request.json or {}
            paper_id = data.get("paper_id")
            openai_base_url = data.get("openai_base_url")
            openai_api_key = data.get("openai_api_key")
            system_prompt = data.get(
                "system_prompt", ""
            )  # Allow empty, use default value

            if not paper_id or not openai_base_url or not openai_api_key:
                return (
                    jsonify({"success": False, "error": "Missing required parameters"}),
                    400,
                )

            agentic_settings: Dict[str, Any] = {}
            try:
                agentic_settings = SettingsDAO.get_setting("agentic_settings", {}) or {}
            except Exception:
                agentic_settings = {}

            if not agentic_settings and os.path.exists(agentic_settings_file):
                try:
                    with open(agentic_settings_file, "r", encoding="utf-8") as f:
                        agentic_settings = json.load(f) or {}
                except Exception:
                    agentic_settings = {}

            use_api = agentic_settings.get("mineruUseApi", False)
            mineru_config = {
                "useApi": use_api,
                "serverUrl": (
                    agentic_settings.get("mineruServerUrl", "") if not use_api else ""
                ),
                "apiToken": (
                    agentic_settings.get("mineruApiToken", "") if use_api else ""
                ),
            }

            # Validate based on mode
            if use_api:
                if not mineru_config["apiToken"]:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "MinerU API token is required. Please configure it in settings.",
                            }
                        ),
                        400,
                    )
            else:
                if not mineru_config["serverUrl"]:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "MinerU Server URL is required. Please configure it in settings.",
                            }
                        ),
                        400,
                    )

            # Test before starting a task API connect
            # test LLM API - If no model name is provided in the request, read from the configuration file
            llm_model = data.get("openai_model", "").strip()
            if not llm_model and agentic_settings_file:
                try:
                    llm_configs = agentic_settings.get("llmConfigs")
                    if isinstance(llm_configs, dict) and isinstance(
                        llm_configs.get("interpret"), dict
                    ):
                        llm_model = (llm_configs.get("interpret") or {}).get(
                            "llmModel", ""
                        ).strip()
                    else:
                        llm_model = (agentic_settings.get("llmModel") or "").strip()
                except Exception:
                    pass

            if not llm_model:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Lack LLM Model name, please provide it in the request openai_model Or configure in settings llmModel",
                        }
                    ),
                    400,
                )

            llm_success, llm_error = test_llm_api(
                llm_model, openai_base_url, openai_api_key
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

            # test MinerU based on mode
            if use_api:
                # Test API token
                from resophy.tools.api_test_utils import test_mineru_api_token

                mineru_success, mineru_error = test_mineru_api_token(
                    mineru_config["apiToken"]
                )
            else:
                # Test local server
                mineru_success, mineru_error = test_mineru_api(
                    mineru_config["serverUrl"]
                )

            if not mineru_success:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"MinerU test failed: {mineru_error}",
                        }
                    ),
                    400,
                )

            with analysis_tasks_lock:
                for task_id, task_info in analysis_tasks.items():
                    if (
                        task_info["paper_id"] == paper_id
                        and task_info["status"] == "running"
                    ):
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "There is already an interpretation task running for this paper",
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
                return (
                    jsonify({"success": False, "error": "PDFFile does not exist"}),
                    404,
                )

            pdf_dir = os.path.dirname(pdf_path)
            pdf_filename = os.path.basename(pdf_path)

            task_id = str(uuid.uuid4())

            with analysis_tasks_lock:
                analysis_tasks[task_id] = {
                    "paper_id": paper_id,
                    "status": "queued",
                    "step": None,
                    "logs": [],
                    "log_lock": threading.Lock(),
                    "process": None,
                    "start_time": datetime.now().isoformat(),
                    "result": None,
                }

            deps = AnalysisDependencies(
                analysis_tasks=analysis_tasks,
                analysis_tasks_lock=analysis_tasks_lock,
                get_categories=get_categories,
                get_category_path=get_category_path,
                get_papers_in_category=get_papers_in_category,
                save_paper_metadata=save_paper_metadata,
            )

            ai_language = data.get("ai_language", "zh")

            thread = threading.Thread(
                target=analyze_paper_task,
                args=(
                    task_id,
                    paper_id,
                    pdf_path,
                    pdf_dir,
                    pdf_filename,
                    mineru_config,
                    openai_base_url,
                    openai_api_key,
                    system_prompt,
                    ai_language,
                    deps,
                ),
            )
            thread.daemon = True
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": "Interpretation task has started",
                    "task_id": task_id,
                }
            )

        except Exception as exc:  # noqa: BLE001
            print(f"Failed to start interpretation task: {exc}")
            import traceback

            traceback.print_exc()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Failed to start interpretation task: {str(exc)}",
                    }
                ),
                500,
            )

    @app.route("/api/paper/analyze/active", methods=["GET"])
    def api_get_active_analysis():
        """Get all ongoing interpretation tasks"""
        with analysis_tasks_lock:
            active_tasks = []
            for task_id, task_info in analysis_tasks.items():
                if task_info["status"] in ["queued", "running"]:
                    active_tasks.append(
                        {
                            "task_id": task_id,
                            "paper_id": task_info["paper_id"],
                            "status": task_info["status"],
                            "step": task_info.get("step"),
                            "start_time": task_info["start_time"],
                        }
                    )
            return jsonify({"success": True, "tasks": active_tasks})

    @app.route("/api/paper/analyze/<task_id>/logs", methods=["GET"])
    def api_get_analysis_logs(task_id):
        """Get the log of the interpretation task"""
        with analysis_tasks_lock:
            if task_id not in analysis_tasks:
                return jsonify({"success": False, "error": "Task does not exist"}), 404

            task_info = analysis_tasks[task_id]
            with task_info["log_lock"]:
                logs = task_info["logs"].copy()

            return jsonify(
                {
                    "success": True,
                    "status": task_info["status"],
                    "step": task_info.get("step"),
                    "logs": logs,
                    "start_time": task_info["start_time"],
                    "result": task_info.get("result"),
                }
            )

    @app.route("/api/paper/analyze/<task_id>/cancel", methods=["POST"])
    def api_cancel_analysis(task_id):
        """Cancel interpretation task"""
        with analysis_tasks_lock:
            if task_id not in analysis_tasks:
                return jsonify({"success": False, "error": "Task does not exist"}), 404

            task_info = analysis_tasks[task_id]

            if task_info["status"] in ["completed", "failed", "cancelled"]:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "The task has ended and cannot be canceled",
                        }
                    ),
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
            task_info["result"] = {"success": False, "error": "Interpretation canceled"}

            return jsonify(
                {"success": True, "message": "Interpretation task has been canceled"}
            )

    @app.route("/api/paper/<paper_id>/analysis/result")
    def api_get_analysis_result(paper_id):
        """Get interpretation result file"""
        # First try from paper_store Find papers in（support _ReadingListTemp Table of contents）
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
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
                return jsonify({"error": "Paper not found"}), 404

            paper, _ = result
        pdf_path = paper.file_path

        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"error": "PDFFile does not exist"}), 404

        pdf_dir = os.path.dirname(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        outputs_dir = os.path.join(pdf_dir, "outputs")

        result_file = None
        if os.path.exists(outputs_dir):
            exact_result = os.path.join(outputs_dir, base_name, "vlm", "result.md")
            if os.path.exists(exact_result):
                result_file = exact_result
            else:
                for item in os.listdir(outputs_dir):
                    item_path = os.path.join(outputs_dir, item)
                    if os.path.isdir(item_path):
                        vlm_dir = os.path.join(item_path, "vlm")
                        if os.path.exists(vlm_dir):
                            potential_result = os.path.join(vlm_dir, "result.md")
                            if os.path.exists(potential_result):
                                result_file = potential_result
                                break

        if not result_file or not os.path.exists(result_file):
            return jsonify({"error": "Interpretation results file does not exist"}), 404

        try:
            with open(result_file, "r", encoding="utf-8") as f:
                content = f.read()
            return jsonify(
                {"success": True, "content": content, "file_path": result_file}
            )
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Failed to read result file: {str(exc)}"}), 500

    @app.route("/api/paper/<paper_id>/analysis/image")
    def api_get_analysis_image(paper_id):
        """Get pictures from interpretation results"""
        # First try from paper_store Find papers in（support _ReadingListTemp Table of contents）
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
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
                return jsonify({"error": "Paper not found"}), 404

            paper, _ = result
        pdf_path = paper.file_path

        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({"error": "PDFFile does not exist"}), 404

        image_path = (request.args.get("path") or "").strip()
        if not image_path:
            return jsonify({"error": "Image path not provided"}), 400

        normalized = image_path.replace("\\", "/")
        normalized = posixpath.normpath(normalized).lstrip("/")
        if not normalized or normalized == ".":
            return jsonify({"error": "Invalid image path"}), 400
        parts = [p for p in normalized.split("/") if p]
        if any(p == ".." for p in parts):
            return jsonify({"error": "Invalid image path"}), 400

        pdf_dir = os.path.dirname(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        outputs_dir = os.path.join(pdf_dir, "outputs")

        image_file = None
        if os.path.exists(outputs_dir):
            rel = normalized
            rel_in_images = rel[len("images/") :] if rel.startswith("images/") else rel
            requested_name = posixpath.basename(rel)
            requested_stem, _ = os.path.splitext(requested_name)

            def try_candidate(path: str) -> str | None:
                if path and os.path.exists(path) and os.path.isfile(path):
                    return path
                return None

            def iter_base_dirs() -> List[str]:
                bases: List[str] = []
                bases.append(os.path.join(outputs_dir, base_name, "vlm"))
                bases.append(os.path.join(outputs_dir, base_name))
                bases.append(outputs_dir)
                try:
                    for item in os.listdir(outputs_dir):
                        item_path = os.path.join(outputs_dir, item)
                        if not os.path.isdir(item_path):
                            continue
                        bases.append(item_path)
                        bases.append(os.path.join(item_path, "vlm"))
                except Exception:
                    pass
                seen: set[str] = set()
                deduped: List[str] = []
                for b in bases:
                    b_norm = os.path.normpath(b)
                    if b_norm in seen:
                        continue
                    seen.add(b_norm)
                    deduped.append(b_norm)
                return deduped

            for base_dir in iter_base_dirs():
                if not base_dir or not os.path.exists(base_dir):
                    continue
                candidates = [
                    os.path.join(base_dir, rel),
                    os.path.join(base_dir, rel_in_images),
                    os.path.join(base_dir, "images", rel),
                    os.path.join(base_dir, "images", rel_in_images),
                    os.path.join(base_dir, requested_name),
                    os.path.join(base_dir, "images", requested_name),
                    os.path.join(base_dir, "assets", rel),
                    os.path.join(base_dir, "assets", rel_in_images),
                    os.path.join(base_dir, "assets", "images", rel_in_images),
                ]
                for candidate in candidates:
                    found = try_candidate(candidate)
                    if found:
                        image_file = found
                        break
                if image_file:
                    break

            if not image_file:
                suffixes = [
                    rel,
                    f"images/{rel_in_images}",
                    rel_in_images,
                ]
                suffixes = [s.replace("\\", "/").lstrip("/") for s in suffixes if s]

                best: tuple[int, str] | None = None
                for root, dirs, files in os.walk(outputs_dir):
                    rel_root = os.path.relpath(root, outputs_dir)
                    depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
                    if depth > 6:
                        dirs[:] = []
                        continue
                    for fname in files:
                        full = os.path.join(root, fname)
                        rel_full = os.path.relpath(full, outputs_dir).replace(os.sep, "/")
                        score = 0
                        if any(rel_full.endswith(suf) for suf in suffixes):
                            score = 300
                        elif fname == requested_name:
                            score = 200
                        elif requested_stem and os.path.splitext(fname)[0] == requested_stem:
                            score = 100
                        if score:
                            if "images/" in rel_full:
                                score += 5
                            if best is None or score > best[0]:
                                best = (score, full)
                    if best and best[0] >= 300:
                        break
                if best:
                    image_file = best[1]

        if not image_file or not os.path.exists(image_file):
            return jsonify({"error": "Image file does not exist"}), 404

        mime_type, _ = mimetypes.guess_type(image_file)
        return send_file(image_file, mimetype=mime_type or "application/octet-stream")
