from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Callable, Dict, List, Generator

from flask import Response, jsonify, request, stream_with_context
from openai import OpenAI

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store

CategoryPath = List[str]

def register_agent_chat_routes(
    app,
    *,
    get_categories: Callable[[], dict],
    get_category_path: Callable[[dict, str], CategoryPath | None],
    get_papers_in_category: Callable[[str, CategoryPath], List[Paper]],
    agentic_settings_file: str,
) -> None:
    @app.route("/api/paper/chat", methods=["POST"])
    def api_chat_paper():
        """Chat with paper context - Streaming response"""
        try:
            data = request.json or {}
            paper_id = data.get("paper_id")
            messages = data.get("messages", [])
            
            if not paper_id or not messages:
                return jsonify({"success": False, "error": "Missing required parameters"}), 400

            # 1. Load LLM Settings
            if not os.path.exists(agentic_settings_file):
                return jsonify({"success": False, "error": "Agentic settings not found"}), 500
                
            with open(agentic_settings_file, "r", encoding="utf-8") as f:
                agentic_settings = json.load(f)

            openai_base_url = agentic_settings.get("llmBaseUrl")
            openai_api_key = agentic_settings.get("llmApiKey")
            llm_model = agentic_settings.get("llmModel")

            if not openai_base_url or not openai_api_key or not llm_model:
                 return jsonify({"success": False, "error": "LLM settings not configured"}), 400

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
                
                # If not found, look in other dirs
                if not md_file:
                    for item in os.listdir(outputs_dir):
                        item_path = os.path.join(outputs_dir, item)
                        if os.path.isdir(item_path):
                            vlm_dir = os.path.join(item_path, "vlm")
                            if os.path.exists(vlm_dir):
                                for f in os.listdir(vlm_dir):
                                    if f.endswith(".md") and f != "result.md":
                                        md_file = os.path.join(vlm_dir, f)
                                        break
                        if md_file: break

            if not md_file:
                 return jsonify({"success": False, "error": "Parsed content not found. Please run AI Interpretation first."}), 404

            with open(md_file, "r", encoding="utf-8") as f:
                markdown_content = f.read()

            # Remove references if possible to save tokens
            references_pattern = re.compile(r"^#\s+references?\s*$", re.IGNORECASE | re.MULTILINE)
            match = references_pattern.search(markdown_content)
            if match:
                markdown_content = markdown_content[: match.start()]

            # 4. Construct Prompt
            # System prompt with context
            system_prompt = f"""You are a helpful AI research assistant. You are chatting with a user about a paper.
Here is the content of the paper in Markdown format:

<PAPER_CONTENT>
{markdown_content}
</PAPER_CONTENT>

Answer the user's questions based on the paper content. If the answer is not in the paper, say so.
"""
            
            # Prepare messages for OpenAI
            chat_messages = [{"role": "system", "content": system_prompt}]
            # Append user history (limit length if needed, but for now take all)
            chat_messages.extend(messages)

            # 5. Call OpenAI and Stream
            client = OpenAI(api_key=openai_api_key, base_url=openai_base_url)

            def generate():
                try:
                    stream = client.chat.completions.create(
                        model=llm_model,
                        messages=chat_messages,
                        stream=True,
                        temperature=0.7
                    )
                    
                    for chunk in stream:
                        if chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                            
                except Exception as e:
                    yield f"Error: {str(e)}"

            return Response(stream_with_context(generate()), mimetype='text/plain')

        except Exception as e:
            print(f"Chat error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": str(e)}), 500
