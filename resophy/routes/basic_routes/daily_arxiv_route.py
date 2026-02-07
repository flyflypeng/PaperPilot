"""
Daily arXiv routing module

supply Daily arXiv functional API interface
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from flask import Flask, jsonify, request, send_file

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store
from resophy.tools.basic_tools.daily_arxiv import (
    DailyArxivManager,
    extract_affiliations_with_llm,
    extract_pdf_first_page_text,
    get_manager,
    get_today_arxiv_date,
)
from resophy.tools.basic_tools.upload_paper import fetch_bibtex_from_dblp


def register_daily_arxiv_routes(
    app: Flask,
    *,
    daily_arxiv_settings_file: str,
    default_daily_arxiv_settings: Dict[str, Any],
    temp_papers_dir: str,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], List[str] | None],
    create_category_folder: Callable[[List[str]], str],
    save_paper_metadata: Callable[[str, Any], None],
    reading_list_file: str,
    reading_list_temp_dir: str,
    agentic_settings_file: str = None,
) -> None:
    """
    register Daily arXiv Related routes
    """

    def _fetch_bibtex_background(
        paper_id: str,
        title: str,
        authors: str,
        arxiv_id: str,
        file_path: str,
        category_id: str,
        category_path: List[str],
    ):
        """Background acquisition BibTeX and update the paper"""
        try:
            print(f"[Backstage BibTeX] Start getting BibTeX: {title[:50]}...")
            bibtex = fetch_bibtex_from_dblp(title, authors, arxiv_id)

            if bibtex:
                paper = paper_store.get(paper_id)
                if paper:
                    paper.bibtex = bibtex
                    paper_store.upsert(
                        paper, category_id=category_id, category_path=category_path
                    )
                    save_paper_metadata(file_path, paper)
                    print(f"[Backstage BibTeX] ✅ BibTeX updated: {paper_id}")
                else:
                    print(f"[Backstage BibTeX] ❌ Paper not found: {paper_id}")
            else:
                print(f"[Backstage BibTeX] ❌ Not obtained BibTeX")
        except Exception as exc:
            print(f"[Backstage BibTeX] ❌ get BibTeX fail: {exc}")

    # Make sure the temporary directory exists
    os.makedirs(temp_papers_dir, exist_ok=True)

    # Get the manager instance (singleton mode, if already in app.py If created in, the same instance will be returned)
    manager = get_manager(temp_papers_dir, daily_arxiv_settings_file)

    def is_daily_arxiv_enabled() -> bool:
        try:
            settings = manager.get_settings()
            return bool(settings.get("enabled", False))
        except Exception:
            return False

    # set up LLM Configure callbacks (if not set up already)
    def get_llm_config():
        if agentic_settings_file:
            try:
                with open(agentic_settings_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}

    # Only set if the callback is not already set (avoids overriding app.py settings in)
    if manager._get_llm_config is None:
        manager.set_llm_config_callback(get_llm_config)

    # examine LLM Is the configuration complete?
    def is_llm_configured() -> bool:
        """examine LLM Is the configuration complete?"""
        llm_config = get_llm_config()
        return bool(
            llm_config.get("llmBaseUrl")
            and llm_config.get("llmApiKey")
            and llm_config.get("llmModel")
        )

    # ========================================
    # Check LLM Configuration
    # ========================================
    @app.route("/api/daily-arxiv/check-llm-config", methods=["GET"])
    def api_check_llm_config():
        """examine LLM Is the configuration complete?"""
        try:
            llm_config = get_llm_config()
            is_configured = is_llm_configured()

            # If the configuration is complete, retest LLM API, instead of returning the historical status directly
            # This can avoid the problem of historical failure status still being displayed after the configuration is repaired in the settings.
            llm_api_failed = False
            llm_api_error_message = ""

            if is_configured:
                # Configuration is complete, retest LLM API
                from resophy.tools.api_test_utils import test_llm_api

                llm_model = llm_config.get("llmModel", "").strip()
                llm_base_url = llm_config.get("llmBaseUrl", "").strip()
                llm_api_key = llm_config.get("llmApiKey", "").strip()

                if llm_model and llm_base_url and llm_api_key:
                    try:
                        success, error_msg = test_llm_api(
                            llm_model, llm_base_url, llm_api_key
                        )
                        if not success:
                            # Test failed, update manager state
                            manager._llm_api_failed = True
                            manager._llm_api_error_message = error_msg
                            llm_api_failed = True
                            llm_api_error_message = error_msg
                        else:
                            # Test successful, clear failure status
                            manager._llm_api_failed = False
                            manager._llm_api_error_message = ""
                            llm_api_failed = False
                            llm_api_error_message = ""
                    except Exception as e:
                        # Test exception, update status
                        manager._llm_api_failed = True
                        manager._llm_api_error_message = str(e)
                        llm_api_failed = True
                        llm_api_error_message = str(e)
            else:
                # Configuration is incomplete, check historical status (but do not show errors because the configuration itself is incomplete)
                if hasattr(manager, "_llm_api_failed"):
                    # Even if there is a historical failure status, if the configuration is incomplete, no error will be displayed
                    # Because the user may be configuring
                    llm_api_failed = False
                    llm_api_error_message = ""

            return jsonify(
                {
                    "success": True,
                    "is_configured": is_configured,
                    "llm_api_failed": llm_api_failed,
                    "llm_api_error_message": llm_api_error_message,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Daily arXiv Settings
    # ========================================
    @app.route("/api/settings/daily-arxiv", methods=["GET", "POST"])
    def api_daily_arxiv_settings():
        """Get or set Daily arXiv Configuration"""
        if request.method == "GET":
            try:
                with open(daily_arxiv_settings_file, "r", encoding="utf-8") as fp:
                    settings = json.load(fp)
            except FileNotFoundError:
                settings = {}
            except Exception as exc:
                print(f"read Daily arXiv Setup failed: {exc}")
                settings = {}
            # Merge default settings, but for categories, if the settings file is empty, the default value will be used
            merged = default_daily_arxiv_settings.copy()
            for key, value in settings.items():
                if key == "categories":
                    # Only if user sets categories Overwrite when not empty
                    if value and len(value) > 0:
                        merged[key] = value
                else:
                    merged[key] = value
            return jsonify(merged)

        # POST: Save settings
        data = request.json or {}
        try:
            with open(daily_arxiv_settings_file, "w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Get Available Dates
    # ========================================
    @app.route("/api/daily-arxiv/dates", methods=["GET"])
    def api_get_available_dates():
        """Get a list of dates with papers"""
        try:
            if not is_daily_arxiv_enabled():
                today = get_today_arxiv_date()
                return jsonify(
                    {
                        "success": True,
                        "enabled": False,
                        "dates": [],
                        "today": today,
                    }
                )
            dates = manager.get_available_dates()
            today = get_today_arxiv_date()
            return jsonify(
                {
                    "success": True,
                    "enabled": True,
                    "dates": dates,
                    "today": today,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Get Papers for Date
    # ========================================
    @app.route("/api/daily-arxiv/papers/<date_str>", methods=["GET"])
    def api_get_papers_for_date(date_str: str):
        """Get papers of a certain date"""
        try:
            category = request.args.get("category")
            if not is_daily_arxiv_enabled():
                return jsonify(
                    {
                        "success": True,
                        "enabled": False,
                        "papers": [],
                        "date": date_str,
                        "category": category,
                    }
                )
            papers = manager.get_papers_for_date(date_str, category)

            # Add for each paper paper_id(if already in the library)
            for paper in papers:
                arxiv_id = paper.get("arxiv_id")
                if arxiv_id:
                    # from paper_store Find papers in
                    entry = paper_store.get_by_arxiv_id(arxiv_id)
                    if entry:
                        paper["paper_id"] = entry.paper.id

            return jsonify(
                {
                    "success": True,
                    "enabled": True,
                    "papers": papers,
                    "date": date_str,
                    "category": category,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Fetch Papers (Trigger Manual Fetch)
    # ========================================
    @app.route("/api/daily-arxiv/fetch", methods=["POST"])
    def api_fetch_daily_arxiv():
        """Manually trigger the crawling of papers (automatically crawl all papers on a specified date)"""
        try:
            if not is_daily_arxiv_enabled():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Daily arXiv 已在设置中关闭（Enable Daily arXiv = off），无法抓取。",
                        }
                    ),
                    400,
                )
            # examine LLM Configuration
            if not is_llm_configured():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Please configure it in settings first LLM API（Model、Base URL、API Key）",
                        }
                    ),
                    400,
                )

            data = request.json or {}
            category = data.get("category")
            date_str = data.get("date", get_today_arxiv_date())
            force = data.get("force", False)

            if not category:
                return jsonify({"success": False, "error": "Please specify arXiv Partition"}), 400

            # Execute the crawl in a background thread
            def do_fetch():
                manager.fetch_papers(
                    category,
                    date_str=date_str,
                    force=force,
                )
                # Clear thumbnail cache after scraping is complete
                with _thumbnail_cache_lock:
                    cache_key = f"{date_str}_{category}"
                    _thumbnail_cache.pop(cache_key, None)

            thread = threading.Thread(target=do_fetch, daemon=True)
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": f"Start crawling {category} paper",
                    "category": category,
                    "date": date_str,
                }
            )

        except Exception as exc:
            print(f"get Daily arXiv Thesis failed: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Get Fetch Progress
    # ========================================
    @app.route("/api/daily-arxiv/progress/<category>", methods=["GET"])
    def api_get_fetch_progress(category: str):
        """Get crawling progress"""
        try:
            progress = manager.get_progress(category)
            return jsonify(
                {
                    "success": True,
                    "progress": progress,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Fetch All Categories
    # ========================================
    @app.route("/api/daily-arxiv/fetch-all", methods=["POST"])
    def api_fetch_all_categories():
        """Crawl all configured partitions (automatically crawl all papers today)"""
        try:
            if not is_daily_arxiv_enabled():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Daily arXiv 已在设置中关闭（Enable Daily arXiv = off），无法抓取。",
                        }
                    ),
                    400,
                )
            # examine LLM Configuration
            if not is_llm_configured():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Please configure it in settings first LLM API（Model、Base URL、API Key）",
                        }
                    ),
                    400,
                )

            data = request.json or {}
            force = data.get("force", False)
            date_str = data.get(
                "date", get_today_arxiv_date()
            )  # Use if a date is specified, otherwise use today's date

            settings = manager.get_settings()
            categories = settings.get("categories", [])

            if not categories:
                return jsonify({"success": False, "error": "No partition configured"}), 400

            # Execute the crawl in a background thread
            def do_fetch_all():
                for cat in categories:
                    manager.fetch_papers(
                        cat,
                        date_str=date_str,
                        force=force,
                    )
                # Clear all thumbnail caches after crawling is complete
                with _thumbnail_cache_lock:
                    _thumbnail_cache.clear()

            thread = threading.Thread(target=do_fetch_all, daemon=True)
            thread.start()

            return jsonify(
                {
                    "success": True,
                    "message": f"Start crawling {len(categories)} partitions",
                    "categories": categories,
                    "date": date_str,
                }
            )

        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Add Paper to Library
    # ========================================
    @app.route("/api/daily-arxiv/add-to-library", methods=["POST"])
    def api_add_arxiv_to_library():
        """Will arXiv Add paper to library"""
        try:
            data = request.json or {}
            arxiv_id = data.get("arxiv_id")
            category_id = data.get("category_id")
            date_str = data.get("date", get_today_arxiv_date())
            fetch_category = data.get("fetch_category")
            use_temp_dir = data.get("use_temp_dir", False)  # Whether to use the temporary directory of the to-be-read list

            if not arxiv_id:
                return jsonify({"success": False, "error": "Lack arxiv_id"}), 400

            # If using temp Directory, use directly temp directory path
            if use_temp_dir:
                folder_path = reading_list_temp_dir
                category_path = ["Root", "_ReadingListTemp"]
                category_id = "reading_list_temp"  # Use special ID
            else:
                if not category_id:
                    return jsonify({"success": False, "error": "Please select target category"}), 400

                # Get classification path
                categories = get_categories()
                category_path = get_category_path(categories, category_id)
                if not category_path:
                    return jsonify({"success": False, "error": "Category does not exist"}), 404

                # Create category folders
                folder_path = create_category_folder(category_path[1:])

            # Get paper information from storage
            paper_info = None
            papers = manager.get_papers_for_date(date_str, fetch_category)
            for p in papers:
                if p.get("arxiv_id") == arxiv_id:
                    paper_info = p
                    break

            if not paper_info:
                return jsonify({"success": False, "error": "Paper information not found"}), 404

            # Construct safe file names
            safe_title = paper_info.get("title", arxiv_id)
            for char in ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
                safe_title = safe_title.replace(char, "")
            safe_title = safe_title[:100].strip()

            pdf_filename = f"{safe_title}.pdf"
            target_path = os.path.join(folder_path, pdf_filename)

            # Check if it already exists: if it already exists, reuse the existing one Paper, instead of reporting an error
            if os.path.exists(target_path):
                # try at paper_store Find the corresponding paper in (via arxiv_id or file_path）
                existing_paper = None
                try:
                    all_papers = paper_store.iter_all()
                    for p in all_papers:
                        if (
                            getattr(p, "arxiv_id", None) == arxiv_id
                            or getattr(p, "file_path", None) == target_path
                        ):
                            existing_paper = p
                            break
                except Exception as e:
                    print(f"Failed to find existing papers: {e}")

                if existing_paper:
                    # Make sure the paper is registered under the specified category
                    paper_store.upsert(
                        existing_paper,
                        category_id=category_id,
                        category_path=category_path,
                    )

                    # If using temp Table of contents, add to to-read list
                    if use_temp_dir:
                        try:
                            # Load to-read list
                            with open(reading_list_file, "r", encoding="utf-8") as f:
                                reading_list_data = json.load(f)
                            paper_ids = reading_list_data.get("papers", [])

                            # If the paper ID Not in the list, add it
                            if existing_paper.id not in paper_ids:
                                paper_ids.append(existing_paper.id)
                                with open(
                                    reading_list_file, "w", encoding="utf-8"
                                ) as f:
                                    json.dump(
                                        {"papers": paper_ids},
                                        f,
                                        ensure_ascii=False,
                                        indent=2,
                                    )
                        except Exception as e:
                            print(f"Failed to add to to-read list: {e}")

                    return jsonify(
                        {
                            "success": True,
                            "paper_id": existing_paper.id,
                            "file_path": existing_paper.file_path,
                            "message": f"This paper already exists in {'/'.join(category_path[1:])}",
                        }
                    )

                # No corresponding found Paper, then the original error reporting logic is maintained.
                return (
                    jsonify({"success": False, "error": "This paper already exists in the target category"}),
                    400,
                )

            # Copy or download PDF
            source_pdf = paper_info.get("local_pdf_path")
            if source_pdf and os.path.exists(source_pdf):
                import shutil

                shutil.copy2(source_pdf, target_path)
            else:
                # download
                import urllib.request

                pdf_url = (
                    paper_info.get("pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                )
                print(f"[DailyArxiv] Download the paper to the library: {arxiv_id} -> {target_path}")
                urllib.request.urlretrieve(pdf_url, target_path)

            # Create article metadata
            import uuid

            paper = Paper(
                id=str(uuid.uuid4()),
                filename=pdf_filename,
                original_filename=pdf_filename,
                file_path=target_path,
                upload_date=datetime.now().isoformat(),
                title=paper_info.get("title", ""),
                authors=paper_info.get("authors", ""),
                abstract=paper_info.get("abstract", ""),
                arxiv_id=arxiv_id,
                arxiv_url=f"https://arxiv.org/abs/{arxiv_id}",
                arxiv_published_date=paper_info.get("published"),
                github=paper_info.get("github"),
                homepage=paper_info.get("homepage"),
                upload_source="daily_arxiv",
            )

            # Save metadata
            save_paper_metadata(target_path, paper)

            # Register to paper_store
            paper_store.upsert(
                paper,
                category_id=category_id,
                category_path=category_path,
            )

            # If using temp Table of contents, add to to-read list
            if use_temp_dir:
                try:
                    # Load to-read list
                    with open(reading_list_file, "r", encoding="utf-8") as f:
                        reading_list_data = json.load(f)
                    paper_ids = reading_list_data.get("papers", [])

                    # If the paper ID Not in the list, add it
                    if paper.id not in paper_ids:
                        paper_ids.append(paper.id)
                        with open(reading_list_file, "w", encoding="utf-8") as f:
                            json.dump(
                                {"papers": paper_ids}, f, ensure_ascii=False, indent=2
                            )
                except Exception as e:
                    print(f"Failed to add to to-read list: {e}")

            # 【Background acquisition BibTeX(priority DBLP, use after failure arXiv）】
            if paper.title:
                thread = threading.Thread(
                    target=_fetch_bibtex_background,
                    args=(
                        paper.id,
                        paper.title,
                        paper.authors or "",  # authors Can be empty
                        arxiv_id,
                        target_path,
                        category_id,
                        category_path,
                    ),
                    daemon=True,
                )
                thread.start()
                print(f"[DailyArxiv] Paper has been added,BibTeX Getting in the background...")

            return jsonify(
                {
                    "success": True,
                    "paper_id": paper.id,
                    "file_path": target_path,
                    "message": f"has been added to {'/'.join(category_path[1:])}",
                    "is_temp": use_temp_dir,  # Is the mark in temp Table of contents
                }
            )

        except Exception as exc:
            print(f"Failed to add paper to library: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Extract Affiliations
    # ========================================
    @app.route("/api/daily-arxiv/extract-affiliations", methods=["POST"])
    def api_extract_affiliations():
        """Manually extract paper institution information,homepage and github"""
        try:
            data = request.json or {}
            arxiv_id = data.get("arxiv_id")
            date_str = data.get("date", get_today_arxiv_date())
            fetch_category = data.get("fetch_category")

            if not arxiv_id:
                return jsonify({"success": False, "error": "Lack arxiv_id"}), 400

            # from Agentic Settings get LLM Configuration
            llm_config = get_llm_config()
            openai_base_url = llm_config.get("llmBaseUrl")
            openai_api_key = llm_config.get("llmApiKey")

            if not openai_base_url or not openai_api_key:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Please configure it in settings first Agentic Settings of LLM API",
                        }
                    ),
                    400,
                )

            # Get paper information
            papers = manager.get_papers_for_date(date_str, fetch_category)
            paper_info = None
            for p in papers:
                if p.get("arxiv_id") == arxiv_id:
                    paper_info = p
                    break

            if not paper_info:
                return jsonify({"success": False, "error": "Paper information not found"}), 404

            # getPDFpath
            pdf_path = paper_info.get("local_pdf_path")
            if not pdf_path or not os.path.exists(pdf_path):
                return jsonify({"success": False, "error": "PDFFile does not exist"}), 404

            # Get custom prompt
            settings = manager.get_settings()
            affiliation_prompt = settings.get("affiliationPrompt")

            # extraction mechanism,homepage and github
            extraction_result = extract_affiliations_with_llm(
                extract_pdf_first_page_text(pdf_path) or "",
                openai_base_url,
                openai_api_key,
                prompt=affiliation_prompt,
                settings_file=daily_arxiv_settings_file,
            )

            if not extraction_result:
                return (
                    jsonify({"success": False, "error": "Extraction failed, results cannot be obtained"}),
                    500,
                )

            # Update paper information
            paper_info["affiliations"] = extraction_result.get("affiliations", [])
            paper_info["countries"] = extraction_result.get("countries", [])
            paper_info["homepage"] = extraction_result.get("homepage")
            paper_info["github"] = extraction_result.get("github")
            paper_info["affiliations_extracted"] = True

            # Save updated paper information
            safe_id = arxiv_id.replace("/", "_").replace(":", "_")
            if fetch_category:
                paper_cat_dir = manager.get_category_dir(date_str, fetch_category)
            else:
                # If no partition is specified, try to get it from the paper information
                paper_cat_dir = os.path.dirname(pdf_path)

            json_path = os.path.join(paper_cat_dir, f"{safe_id}.json")
            if os.path.exists(json_path):
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(paper_info, f, ensure_ascii=False, indent=2)

            return jsonify(
                {
                    "success": True,
                    "affiliations": extraction_result.get("affiliations", []),
                    "countries": extraction_result.get("countries", []),
                    "homepage": extraction_result.get("homepage"),
                    "github": extraction_result.get("github"),
                }
            )

        except Exception as exc:
            print(f"Failed to extract organization information: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": f"Failed to extract: {str(exc)}"}), 500

    # ========================================
    # Get Thumbnail
    # ========================================
    # Cache: date+Partition -> Mapping of paper lists
    _thumbnail_cache = {}
    _thumbnail_cache_lock = threading.Lock()

    @app.route("/api/daily-arxiv/clear-thumbnail-cache", methods=["POST"])
    def api_clear_thumbnail_cache():
        """Clear thumbnail cache (called when recrawling the paper)"""
        try:
            with _thumbnail_cache_lock:
                _thumbnail_cache.clear()
            return jsonify({"success": True, "message": "cache cleared"})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/daily-arxiv/thumbnail/<date_str>/<category>/<arxiv_id>")
    def api_get_thumbnail(date_str: str, category: str, arxiv_id: str):
        """Get paper thumbnails (with cache optimization)"""
        try:
            # URLdecoding
            from urllib.parse import unquote

            category = unquote(category)
            arxiv_id = unquote(arxiv_id)

            # Use caching to avoid repeated reading of the paper list
            cache_key = f"{date_str}_{category}"

            with _thumbnail_cache_lock:
                if cache_key not in _thumbnail_cache:
                    # First request: read and cache the paper list
                    papers = manager.get_papers_for_date(date_str, category)
                    # build arxiv_id -> paper mapping
                    _thumbnail_cache[cache_key] = {
                        p.get("arxiv_id"): p for p in papers if p.get("arxiv_id")
                    }
                    # Limit cache size to keep only the most recent20dates+partitioned data
                    if len(_thumbnail_cache) > 20:
                        # Delete the oldest entry
                        oldest_key = next(iter(_thumbnail_cache))
                        del _thumbnail_cache[oldest_key]

                paper_map = _thumbnail_cache.get(cache_key, {})

            paper = paper_map.get(arxiv_id)

            # If the paper is not found in the cache, re-read the file system (there may be new papers added during the crawling process)
            if not paper:
                print(f"[DailyArxiv] Paper not found in cache {arxiv_id}, reread the file system...")
                papers = manager.get_papers_for_date(date_str, category)
                # Update cache
                with _thumbnail_cache_lock:
                    paper_map = {
                        p.get("arxiv_id"): p for p in papers if p.get("arxiv_id")
                    }
                    _thumbnail_cache[cache_key] = paper_map

                paper = paper_map.get(arxiv_id)
                if not paper:
                    return jsonify({"success": False, "error": "Paper not found"}), 404

            thumbnail_path = paper.get("thumbnail_path")
            if not thumbnail_path:
                return jsonify({"success": False, "error": "Thumbnail does not exist"}), 404

            # Make sure the path is absolute
            if not os.path.isabs(thumbnail_path):
                thumbnail_path = os.path.abspath(thumbnail_path)

            if not os.path.exists(thumbnail_path):
                return jsonify({"success": False, "error": "Thumbnail file does not exist"}), 404

            # Add a cache header to let the browser cache the image (7sky)
            response = send_file(
                thumbnail_path, mimetype="image/jpeg", as_attachment=False
            )
            response.headers["Cache-Control"] = (
                "public, max-age=604800"  # 7sky = 7*24*60*60
            )
            response.headers["ETag"] = (
                f'"{arxiv_id}-{date_str}"'  # use arxiv_id and date as ETag
            )
            return response
        except Exception as exc:
            print(f"Failed to get thumbnail: {exc}")
            import traceback

            traceback.print_exc()
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Cleanup Old Papers
    # ========================================
    @app.route("/api/daily-arxiv/cleanup", methods=["POST"])
    def api_cleanup_old_papers():
        """Clean up expired papers"""
        try:
            data = request.json or {}
            retention_days = data.get("retention_days")

            if retention_days is None:
                settings = manager.get_settings()
                retention_days = settings.get("retentionDays", 7)

            manager.cleanup_old_papers(retention_days)

            return jsonify(
                {"success": True, "message": f"Cleaned {retention_days} Papers written a few days ago"}
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Scheduler Control
    # ========================================
    @app.route("/api/daily-arxiv/scheduler/start", methods=["POST"])
    def api_start_scheduler():
        """Manually start the scheduler"""
        try:
            if not is_llm_configured():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "LLM The configuration is incomplete, please configure it in the settings first LLM API（Model、Base URL、API Key）",
                        }
                    ),
                    400,
                )

            if manager._scheduler_running:
                return jsonify(
                    {
                        "success": True,
                        "message": "Scheduler is already running",
                        "is_running": True,
                    }
                )

            manager.start_scheduler()
            print("[DailyArxiv] Scheduler has been started manually")
            return jsonify(
                {
                    "success": True,
                    "message": "Scheduler started",
                    "is_running": True,
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500
