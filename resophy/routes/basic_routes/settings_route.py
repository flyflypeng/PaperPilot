from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any, Dict

from flask import Flask, jsonify, request, send_from_directory
from resophy.database.dao.settings_dao import SettingsDAO

def register_settings_routes(
    app: Flask,
    *,
    user_settings_file: str,
    default_user_settings: Dict[str, Any],
    reading_history_file: str,
    agentic_settings_file: str,
    default_agentic_settings: Dict[str, Any],
    avatars_dir: str,
    start_daily_arxiv_callback=None,
) -> None:

    # ========================================
    # User Settings (name, avatar, heatmap color)
    # ========================================
    @app.route("/api/settings/user", methods=["GET", "POST"])
    def api_user_settings():
        if request.method == "GET":
            try:
                settings = SettingsDAO.get_setting('user_settings', {})
            except Exception as exc:
                print(f"Failed to read user settings: {exc}")
                settings = {}
            merged = default_user_settings.copy()
            merged.update(settings)
            return jsonify(merged)

        data = request.json or {}
        try:
            # Read existing settings
            current = SettingsDAO.get_setting('user_settings', default_user_settings.copy())
            
            # Update settings
            current.update(data)

            SettingsDAO.save_setting('user_settings', current)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Avatar Upload
    # ========================================
    @app.route("/api/settings/avatar", methods=["POST"])
    def api_upload_avatar():
        try:
            data = request.json or {}
            avatar_data = data.get("avatarData")  # Base64 encoded image

            if not avatar_data:
                return jsonify({"success": False, "error": "No avatar data"}), 400

            # parse Base64 data
            if "," in avatar_data:
                header, encoded = avatar_data.split(",", 1)
                # Get file type
                if "jpeg" in header or "jpg" in header:
                    ext = "jpg"
                elif "png" in header:
                    ext = "png"
                elif "gif" in header:
                    ext = "gif"
                else:
                    ext = "jpg"
            else:
                encoded = avatar_data
                ext = "jpg"

            # decode and save
            image_data = base64.b64decode(encoded)
            filename = f"avatar.{ext}"
            filepath = os.path.join(avatars_dir, filename)

            with open(filepath, "wb") as f:
                f.write(image_data)

            # Update user settings
            settings = SettingsDAO.get_setting('user_settings', default_user_settings.copy())
            settings["avatar"] = filename
            SettingsDAO.save_setting('user_settings', settings)

            return jsonify({"success": True, "avatar": filename})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/avatar", methods=["GET"])
    def api_get_avatar():
        """Get avatar picture"""
        try:
            settings = SettingsDAO.get_setting('user_settings', {})
            avatar_file = settings.get("avatar")
            if avatar_file and os.path.exists(os.path.join(avatars_dir, avatar_file)):
                return send_from_directory(avatars_dir, avatar_file)
            return jsonify({"error": "No avatar"}), 404
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ========================================
    # Reading History (daily reading time)
    # ========================================
    @app.route("/api/settings/reading-history", methods=["GET", "POST"])
    def api_reading_history():
        if request.method == "GET":
            try:
                history = SettingsDAO.get_setting('reading_history', {})
            except Exception as exc:
                print(f"Failed to read reading history: {exc}")
                history = {}
            return jsonify(history)

        data = request.json or {}
        try:
            # Read existing history
            current = SettingsDAO.get_setting('reading_history', {})

            # Update history (merged)
            for date, minutes in data.items():
                if date in current:
                    current[date] = current[date] + minutes
                else:
                    current[date] = minutes

            SettingsDAO.save_setting('reading_history', current)
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/record", methods=["POST"])
    def api_record_reading():
        """Record today’s reading time (compatible with new and old formats)"""
        try:
            data = request.json or {}
            minutes = data.get("minutes", 0)
            date = data.get("date")  # YYYY-MM-DD
            paper_id = data.get("paper_id")  # optional, essayID

            if not date:
                from datetime import datetime

                date = datetime.now().strftime("%Y-%m-%d")

            # Read existing history
            history = SettingsDAO.get_setting('reading_history', {})

            # Update reading history (compatible with new and old formats)
            if date in history:
                if isinstance(history[date], dict):
                    # new format
                    history[date]["total"] = history[date].get("total", 0) + minutes
                    if paper_id and paper_id not in history[date].get("papers", []):
                        if "papers" not in history[date]:
                            history[date]["papers"] = []
                        history[date]["papers"].append(paper_id)
                else:
                    # old format, converted to new format
                    old_minutes = history[date]
                    history[date] = {
                        "total": old_minutes + minutes,
                        "papers": [paper_id] if paper_id else [],
                    }
            else:
                history[date] = {
                    "total": minutes,
                    "papers": [paper_id] if paper_id else [],
                }

            SettingsDAO.save_setting('reading_history', history)

            total = (
                history[date]["total"]
                if isinstance(history[date], dict)
                else history[date]
            )
            return jsonify({"success": True, "total": total})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/clear", methods=["POST"])
    def api_clear_reading_history():
        """Clear all reading history"""
        try:
            SettingsDAO.save_setting('reading_history', {})
            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/settings/reading-history/week-papers", methods=["GET"])
    def api_week_papers():
        """Get a list of papers to read this week"""
        try:
            from datetime import datetime, timedelta

            # Read reading history
            history = SettingsDAO.get_setting('reading_history', {})

            # Calculate the date range for this week (Monday to today)
            today = datetime.now().date()
            day_of_week = today.weekday()  # 0 = Monday, 6 = Sunday
            monday = today - timedelta(days=day_of_week)

            # Collect the papers you read this weekID
            week_paper_ids = set()
            current_date = monday
            while current_date <= today:
                date_str = current_date.strftime("%Y-%m-%d")
                if date_str in history:
                    entry = history[date_str]
                    if isinstance(entry, dict):
                        # new format
                        papers = entry.get("papers", [])
                        week_paper_ids.update(papers)
                    # There is no paper in the old formatIDinformation, skip

                current_date += timedelta(days=1)

            return jsonify(
                {
                    "success": True,
                    "papers": list(week_paper_ids),
                    "count": len(week_paper_ids),
                }
            )
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # ========================================
    # Agentic Settings (unifiedAIFunction configuration)
    # ========================================
    @app.route("/api/settings/agentic", methods=["GET", "POST"])
    def api_agentic_settings():
        """
        unifiedAIFunction configuration interface
        include: LLM APIConfiguration, PDFParse service configuration, AIInterpret prompt words, etc.
        """
        if request.method == "GET":
            try:
                settings = SettingsDAO.get_setting('agentic_settings', {})
            except Exception as exc:
                print(f"readAIFunction setting failed: {exc}")
                settings = {}
            merged = default_agentic_settings.copy()
            merged.update(settings)

            # Remove prompt fields as they are no longer customizable
            merged.pop("analysisSystemPrompt", None)
            merged.pop("analysisSystemPromptZh", None)
            merged.pop("analysisSystemPromptEn", None)

            return jsonify(merged)

        data = request.json or {}
        try:
            # examine LLM Is the configuration complete?
            llm_model = data.get("llmModel", "").strip()
            llm_base_url = data.get("llmBaseUrl", "").strip()
            llm_api_key = data.get("llmApiKey", "").strip()
            is_llm_configured = bool(llm_model and llm_base_url and llm_api_key)

            # Read the previous configuration and check whether the configuration was not complete before
            was_llm_configured = False
            old_settings = {}
            try:
                old_settings = SettingsDAO.get_setting('agentic_settings', {})
                old_model = old_settings.get("llmModel", "").strip()
                old_base_url = old_settings.get("llmBaseUrl", "").strip()
                old_api_key = old_settings.get("llmApiKey", "").strip()
                was_llm_configured = bool(
                    old_model and old_base_url and old_api_key
                )
            except Exception as exc:
                print(f"Failed to read old settings: {exc}")
                old_settings = {}

            # Merge old and new configurations (new configuration takes precedence, but fields not provided in the old configuration are retained)
            merged_settings = default_agentic_settings.copy()
            merged_settings.update(old_settings)  # Apply old settings first
            merged_settings.update(data)  # Reapply new settings (overwrite)

            # Prompt customization is no longer supported - always use built-in prompts based on user language selection
            # Remove any existing prompt fields to ensure clean state
            merged_settings.pop("analysisSystemPrompt", None)
            merged_settings.pop("analysisSystemPromptZh", None)
            merged_settings.pop("analysisSystemPromptEn", None)

            # examine LLM Has the configuration changed?
            llm_config_changed = False
            if was_llm_configured and is_llm_configured:
                # Configuration is complete, check if changes have occurred
                old_model = old_settings.get("llmModel", "").strip()
                old_base_url = old_settings.get("llmBaseUrl", "").strip()
                old_api_key = old_settings.get("llmApiKey", "").strip()

                new_model = merged_settings.get("llmModel", "").strip()
                new_base_url = merged_settings.get("llmBaseUrl", "").strip()
                new_api_key = merged_settings.get("llmApiKey", "").strip()

                # If any configuration item changes, the configuration is considered to have changed
                if (
                    old_model != new_model
                    or old_base_url != new_base_url
                    or old_api_key != new_api_key
                ):
                    llm_config_changed = True
                    print(f"[Settings] detected LLM Configuration has changed")

            # Save the merged configuration
            SettingsDAO.save_setting('agentic_settings', merged_settings)
            print(f"[Settings] ✅ Settings saved to DB")

            # if LLM The configuration is complete and changes, or changes from unconfigured to configured, triggering Daily arXiv crawl
            if is_llm_configured and (llm_config_changed or not was_llm_configured):
                try:
                    import threading

                    from resophy.tools.basic_tools.daily_arxiv import get_manager

                    # get Daily arXiv Set file path (from agentic_settings_file infer)
                    papers_dir = os.path.dirname(agentic_settings_file)
                    daily_arxiv_settings_file = os.path.join(
                        papers_dir, "daily_arxiv_settings.json"
                    )
                    temp_papers_dir = os.path.join(papers_dir, ".daily_arxiv_temp")
                    # get manager Instance (singleton mode, the same instance will be returned)
                    manager = get_manager(temp_papers_dir, daily_arxiv_settings_file)

                    # Clear failed status
                    if hasattr(manager, "_llm_api_failed"):
                        manager._llm_api_failed = False
                        manager._llm_api_error_message = ""
                        print("[Settings] cleared Daily arXiv failure status")

                    # Start the scheduler if not already running
                    if not manager._scheduler_running:
                        if start_daily_arxiv_callback:
                            start_daily_arxiv_callback()
                        else:
                            manager.start_scheduler()
                        print(
                            "[Settings] LLM Configuration saved and started Daily arXiv Scheduler (the scheduler will automatically trigger a crawl)"
                        )
                    else:
                        # The scheduler is already running, trigger a crawl manually
                        def trigger_fetch():
                            try:
                                manager._do_scheduled_fetch()
                                print(
                                    "[Settings] LLM Configuration has been saved and triggered once Daily arXiv crawl"
                                )
                            except Exception as e:
                                print(
                                    f"[Settings] trigger Daily arXiv Fetch failed: {e}"
                                )

                        # Trigger the fetch in a background thread to avoid blocking the save response
                        thread = threading.Thread(target=trigger_fetch, daemon=True)
                        thread.start()
                        print(
                            "[Settings] LLM Configuration has been saved and triggered in the background Daily arXiv crawl"
                        )
                except Exception as e:
                    # If an error occurs when triggering the crawl, it will not affect the saved results.
                    print(
                        f"[Settings] trigger Daily arXiv An error occurred while fetching (does not affect saving): {e}"
                    )

            return jsonify({"success": True})
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc)}), 500

    # keep oldAPIendpoint for compatibility (return redirect hint)
    @app.route("/api/settings/translation", methods=["GET", "POST"])
    def api_translation_settings_deprecated():
        """Deprecated, please use /api/settings/agentic"""
        return (
            jsonify(
                {
                    "error": "This endpoint is deprecated. Use /api/settings/agentic instead"
                }
            ),
            410,
        )

    @app.route("/api/settings/analysis", methods=["GET", "POST"])
    def api_analysis_settings_deprecated():
        """Deprecated, please use /api/settings/agentic"""
        return (
            jsonify(
                {
                    "error": "This endpoint is deprecated. Use /api/settings/agentic instead"
                }
            ),
            410,
        )

    # ========================================
    # API Test Endpoints
    # ========================================
    @app.route("/api/settings/test/llm", methods=["POST"])
    def api_test_llm():
        """test LLM API connect"""
        try:
            data = request.json or {}
            llm_model = data.get("llmModel", "").strip()
            llm_base_url = data.get("llmBaseUrl", "").strip()
            llm_api_key = data.get("llmApiKey", "").strip()

            if not llm_model or not llm_base_url or not llm_api_key:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Please fill in the complete LLM API configure(Model、Base URL、API Key）",
                        }
                    ),
                    400,
                )

            # import OpenAI client
            try:
                from openai import OpenAI
            except ImportError:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "OpenAI The library is not installed, please run: pip install openai",
                        }
                    ),
                    500,
                )

            # Create client
            client = OpenAI(
                base_url=llm_base_url,
                api_key=llm_api_key,
                timeout=30.0,  # 30seconds timeout
            )

            # Send test message
            test_message = "Can you see my message, if you can, respond with Yes."
            try:
                response = client.chat.completions.create(
                    model=llm_model,
                    messages=[
                        {"role": "user", "content": test_message},
                    ],
                    max_tokens=50,  # Limit reply length
                )

                # check reply
                if response.choices and len(response.choices) > 0:
                    reply = response.choices[0].message.content.strip()
                    # Check if it contains "Yes"(not case sensitive)
                    if "yes" in reply.lower():
                        # Test successful, clear Daily arXiv failure status and trigger fetching
                        try:
                            import threading

                            from resophy.tools.basic_tools.daily_arxiv import (
                                get_manager,
                            )

                            # get Daily arXiv Set file path (from agentic_settings_file infer)
                            # agentic_settings_file and daily_arxiv_settings_file in the same directory
                            papers_dir = os.path.dirname(agentic_settings_file)
                            daily_arxiv_settings_file = os.path.join(
                                papers_dir, "daily_arxiv_settings.json"
                            )
                            temp_papers_dir = os.path.join(
                                papers_dir, ".daily_arxiv_temp"
                            )
                            # get manager Instance (singleton mode, the same instance will be returned)
                            manager = get_manager(
                                temp_papers_dir, daily_arxiv_settings_file
                            )
                            # Clear failed status
                            if hasattr(manager, "_llm_api_failed"):
                                manager._llm_api_failed = False
                                manager._llm_api_error_message = ""
                                print(
                                    "[Settings] LLM API Test successful, cleared Daily arXiv failure status"
                                )

                            # Start the scheduler if not already running
                            if not manager._scheduler_running:
                                manager.start_scheduler()
                                print(
                                    "[Settings] LLM API Test successful, started Daily arXiv Scheduler (the scheduler will automatically trigger a crawl)"
                                )
                            else:
                                # The scheduler is already running, trigger a crawl manually
                                def trigger_fetch():
                                    try:
                                        manager._do_scheduled_fetch()
                                        print(
                                            "[Settings] LLM API Test successful, triggered once Daily arXiv crawl"
                                        )
                                    except Exception as e:
                                        print(
                                            f"[Settings] trigger Daily arXiv Fetch failed: {e}"
                                        )

                                # Trigger fetching in a background thread to avoid blocking test responses
                                thread = threading.Thread(
                                    target=trigger_fetch, daemon=True
                                )
                                thread.start()
                                print(
                                    "[Settings] LLM API The test is successful and has been triggered in the background Daily arXiv crawl"
                                )
                        except Exception as e:
                            # If an error occurs when handling the failure status, it does not affect the test results.
                            print(
                                f"[Settings] deal with Daily arXiv An error occurred in the failed state (does not affect testing): {e}"
                            )

                        return jsonify(
                            {
                                "success": True,
                                "message": "LLM API Connection successful!",
                                "reply": reply,
                            }
                        )
                    else:
                        return jsonify(
                            {
                                "success": False,
                                "error": f"LLM API A response was returned, but not as expected. Reply content: {reply}",
                                "reply": reply,
                            }
                        )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": "LLM API Returned an empty reply",
                        }
                    )

            except Exception as e:
                error_msg = str(e)
                # Provide friendlier error messages
                if "401" in error_msg or "Unauthorized" in error_msg:
                    return jsonify(
                        {
                            "success": False,
                            "error": "API Key Invalid or unauthorized",
                        }
                    )
                elif "404" in error_msg or "Not Found" in error_msg:
                    return jsonify(
                        {
                            "success": False,
                            "error": "API Endpoint does not exist, please check Base URL Is it correct?",
                        }
                    )
                elif "timeout" in error_msg.lower():
                    return jsonify(
                        {
                            "success": False,
                            "error": "Connection timed out, please check network connection and Base URL",
                        }
                    )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": f"LLM API call failed: {error_msg}",
                        }
                    )

        except Exception as exc:
            return jsonify({"success": False, "error": f"test failed: {str(exc)}"}), 500

    @app.route("/api/settings/test/mineru", methods=["POST"])
    def api_test_mineru():
        """test MinerU local server connect"""
        try:
            import requests

            data = request.json or {}
            mineru_server_url = data.get("mineruServerUrl", "").strip()

            if not mineru_server_url:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Please fill in MinerU Server URL",
                        }
                    ),
                    400,
                )

            # Test health endpoint
            test_url = f"{mineru_server_url.rstrip('/')}/health"
            try:
                response = requests.get(test_url, timeout=10)
                if response.status_code == 200:
                    return jsonify(
                        {
                            "success": True,
                            "message": "MinerU server is accessible",
                            "tested_url": test_url,
                        }
                    )
                else:
                    return jsonify(
                        {
                            "success": False,
                            "error": f"Server returned status {response.status_code}",
                        }
                    )
            except requests.exceptions.ConnectionError:
                return jsonify(
                    {
                        "success": False,
                        "error": f"Cannot connect to {mineru_server_url}",
                    }
                )
            except requests.exceptions.Timeout:
                return jsonify({"success": False, "error": "Connection timeout"})

        except Exception as exc:
            return jsonify({"success": False, "error": f"test failed: {str(exc)}"}), 500

    @app.route("/api/settings/test/mineru-api", methods=["POST"])
    def api_test_mineru_api_token():
        """test MinerU API token"""
        try:
            from resophy.tools.api_test_utils import test_mineru_api_token

            data = request.json or {}
            api_token = data.get("apiToken", "").strip()

            if not api_token:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Please enter API token",
                        }
                    ),
                    400,
                )

            success, error_msg = test_mineru_api_token(api_token)

            if success:
                return jsonify(
                    {
                        "success": True,
                        "message": "API token is valid and working",
                    }
                )
            else:
                return jsonify(
                    {
                        "success": False,
                        "error": error_msg,
                    }
                )

        except Exception as exc:
            return jsonify({"success": False, "error": f"test failed: {str(exc)}"}), 500
