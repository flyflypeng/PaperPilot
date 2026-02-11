from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Callable, Dict, List, Generator

from flask import Response, jsonify, request, stream_with_context
from openai import OpenAI

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import paper_store
from paperpilot.database.dao.settings_dao import SettingsDAO
from paperpilot.tools.basic_tools.chat_history_manager import ChatHistoryManager

CategoryPath = List[str]

# Initialize ChatHistoryManager
chat_history_manager = ChatHistoryManager(paper_store)

def register_agent_chat_routes(
    app,
    *,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], CategoryPath | None],
    get_papers_in_category: Callable[[str, CategoryPath], List[Paper]],
    agentic_settings_file: str,
) -> None:
    
    @app.route("/api/paper/chat/sessions", methods=["GET"])
    def api_get_chat_sessions():
        """Get all chat sessions for a paper"""
        try:
            paper_id = request.args.get("paper_id")
            if not paper_id:
                return jsonify({"success": False, "error": "Missing paper_id"}), 400
                
            sessions = chat_history_manager.get_sessions(paper_id)
            return jsonify({"success": True, "sessions": sessions})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/paper/chat/session", methods=["GET"])
    def api_get_chat_session():
        """Get a specific chat session details"""
        try:
            paper_id = request.args.get("paper_id")
            session_id = request.args.get("session_id")
            
            if not paper_id or not session_id:
                return jsonify({"success": False, "error": "Missing parameters"}), 400
                
            session = chat_history_manager.get_session(paper_id, session_id)
            if not session:
                return jsonify({"success": False, "error": "Session not found"}), 404
                
            return jsonify({"success": True, "session": session})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/paper/chat/session", methods=["POST"])
    def api_create_chat_session():
        """Create a new chat session"""
        try:
            data = request.json or {}
            paper_id = data.get("paper_id")
            title = data.get("title", "New Chat")
            
            if not paper_id:
                return jsonify({"success": False, "error": "Missing paper_id"}), 400
                
            session = chat_history_manager.create_session(paper_id, title)
            return jsonify({"success": True, "session": session})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
            
    @app.route("/api/paper/chat/session", methods=["DELETE"])
    def api_delete_chat_session():
        """Delete a chat session"""
        try:
            paper_id = request.args.get("paper_id")
            session_id = request.args.get("session_id")
            
            if not paper_id or not session_id:
                return jsonify({"success": False, "error": "Missing parameters"}), 400

            session = chat_history_manager.get_session(paper_id, session_id)
            if not session:
                return jsonify({"success": False, "error": "Session not found"}), 404
                
            success = chat_history_manager.delete_session(paper_id, session_id)
            return jsonify({"success": success})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/paper/chat", methods=["POST"])
    def api_chat_paper():
        """Chat with paper context - Streaming response"""
        try:
            data = request.json or {}
            paper_id = data.get("paper_id")
            messages = data.get("messages", [])
            session_id = data.get("session_id")
            
            if not paper_id or not messages:
                missing: List[str] = []
                if not paper_id:
                    missing.append("paper_id")
                if not messages:
                    missing.append("messages")
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Missing required parameters: {', '.join(missing)}",
                        }
                    ),
                    400,
                )

            # Ensure session belongs to this paper
            if session_id:
                existing_session = chat_history_manager.get_session(paper_id, session_id)
                if not existing_session:
                    session = chat_history_manager.create_session(paper_id)
                    session_id = session['id']
            else:
                session = chat_history_manager.create_session(paper_id)
                session_id = session['id']
            
            # Save user message
            last_msg = messages[-1]
            if last_msg['role'] == 'user':
                 chat_history_manager.save_message(paper_id, session_id, 'user', last_msg['content'])

            # 1. Load LLM Settings
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

            llm_cfg: Dict[str, Any] = {}
            llm_configs = agentic_settings.get("llmConfigs")
            if isinstance(llm_configs, dict) and isinstance(
                llm_configs.get("interpret"), dict
            ):
                llm_cfg = llm_configs.get("interpret") or {}
            else:
                llm_cfg = agentic_settings

            openai_base_url = (llm_cfg.get("llmBaseUrl") or "").strip()
            openai_api_key = (llm_cfg.get("llmApiKey") or "").strip()
            llm_model = (llm_cfg.get("llmModel") or "").strip()

            if not openai_base_url or not openai_api_key or not llm_model:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "LLM settings not configured. Please fill in Agentic Settings (Model/Base URL/API Key).",
                        }
                    ),
                    400,
                )

            # 2. Find Paper
            entry = paper_store.get_entry(paper_id)
            if entry:
                paper = entry.paper
            else:
                # Fallback search
                categories = get_categories()
                def search_paper_recursive(node):
                    category_path = get_category_path(categories, node["id"])
                    if category_path:
                        papers = get_papers_in_category(node["id"], category_path)
                        for paper in papers:
                            if paper.id == paper_id:
                                return paper
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
                paper = result

            pdf_path = paper.file_path
            if not pdf_path or not os.path.exists(pdf_path):
                return jsonify({"success": False, "error": "PDF file not found"}), 404

            # 3. Find Parsed Markdown
            pdf_dir = os.path.dirname(pdf_path)
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            outputs_dir = os.path.join(pdf_dir, "outputs")
            
            # Search logic similar to summary route but looking for source markdown
            md_file = None
            if os.path.exists(outputs_dir):
                # Try standard vlm path first
                vlm_dir = os.path.join(outputs_dir, base_name, "vlm")
                if os.path.exists(vlm_dir):
                    for item in os.listdir(vlm_dir):
                        if item.endswith(".md") and item != "result.md":
                            md_file = os.path.join(vlm_dir, item)
                            break
                
                # If not found, look in other dirs that still match this paper's basename.
                if not md_file:
                    candidate_dirs: List[str] = []
                    for item in os.listdir(outputs_dir):
                        item_path = os.path.join(outputs_dir, item)
                        if not os.path.isdir(item_path):
                            continue
                        if item == base_name or item.startswith(base_name + "_") or item.startswith(base_name + "-"):
                            candidate_dirs.append(item_path)

                    candidate_dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                    for item_path in candidate_dirs:
                        vlm_dir = os.path.join(item_path, "vlm")
                        if not os.path.exists(vlm_dir):
                            continue
                        for f in os.listdir(vlm_dir):
                            if f.endswith(".md") and f != "result.md":
                                md_file = os.path.join(vlm_dir, f)
                                break
                        if md_file:
                            break
            markdown_content = ""
            if md_file and os.path.exists(md_file):
                with open(md_file, "r", encoding="utf-8") as f:
                    markdown_content = f.read()

                # Remove references if possible to save tokens
                references_pattern = re.compile(r"^#\s+references?\s*$", re.IGNORECASE | re.MULTILINE)
                match = references_pattern.search(markdown_content)
                if match:
                    markdown_content = markdown_content[: match.start()]

            def _meta_line(label: str, value: Any) -> str | None:
                if value is None:
                    return None
                text = str(value).strip()
                if not text:
                    return None
                return f"{label}: {text}"

            paper_metadata_lines: List[str] = []
            paper_metadata_lines.append(_meta_line("Title", paper.title or paper.filename) or "Title: (unknown)")
            for line in (
                _meta_line("Authors", paper.authors),
                _meta_line("Affiliation", paper.affiliation),
                _meta_line("Year", paper.year),
                _meta_line("Journal", paper.journal),
                _meta_line("Abstract", paper.abstract),
                _meta_line("Keywords", paper.keywords),
                _meta_line("Subject", paper.subject),
                _meta_line("arXiv", paper.arxiv_id),
                _meta_line("arXiv URL", paper.arxiv_url),
                _meta_line("Homepage", paper.homepage),
                _meta_line("GitHub", paper.github),
            ):
                if line:
                    paper_metadata_lines.append(line)

            paper_metadata = "\n".join(paper_metadata_lines)

            # 4. Construct Prompt
            if markdown_content.strip():
                system_prompt = f"""You are a helpful AI research assistant. You are chatting with a user about a paper.

Paper metadata:
<PAPER_METADATA>
{paper_metadata}
</PAPER_METADATA>

Here is the content of the paper in Markdown format:
<PAPER_CONTENT>
{markdown_content}
</PAPER_CONTENT>

Answer the user's questions based on the paper content. If the answer is not in the paper, say so.
"""
            else:
                system_prompt = f"""You are a helpful AI research assistant. You are chatting with a user about a paper.

Paper metadata:
<PAPER_METADATA>
{paper_metadata}
</PAPER_METADATA>

The full paper content is not available yet (no parsed Markdown found). Answer the user's questions using the metadata and your general knowledge.
If the user asks for details that require the paper text, say you don't know and suggest running AI Interpretation first.
"""
            
            # Prepare messages for OpenAI
            chat_messages = [{"role": "system", "content": system_prompt}]
            # Append user history (limit length if needed, but for now take all)
            chat_messages.extend(messages)

            # 5. Call OpenAI and Stream
            client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)

            def generate():
                full_response = ""
                try:
                    stream = client.chat.completions.create(
                        model=llm_model,
                        messages=chat_messages,
                        stream=True,
                        temperature=0.7
                    )
                    
                    # Yield session ID first
                    yield json.dumps({"session_id": session_id}) + "\n"
                    
                    for chunk in stream:
                        if chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            full_response += content
                            yield content
                            
                    # Save AI response after stream completes
                    chat_history_manager.save_message(paper_id, session_id, 'assistant', full_response)
                            
                except Exception as e:
                    yield f"Error: {str(e)}"

            return Response(stream_with_context(generate()), mimetype='text/plain')

        except Exception as e:
            print(f"Chat error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
