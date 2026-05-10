from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import paper_store

PaperList = List[Paper]
CategoryPath = List[str]


@dataclass
class AnalysisDependencies:
    analysis_tasks: Dict[str, Dict[str, Any]]
    analysis_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]


def analyze_paper_task(
    task_id: str,
    paper_id: str,
    pdf_path: str,
    pdf_dir: str,
    pdf_filename: str,
    mineru_config: dict,
    openai_model: str,
    openai_base_url: str,
    openai_api_key: str,
    system_prompt: str,
    ai_language: str,
    deps: AnalysisDependencies,
) -> None:
    """Background AI interpretation task - two steps: PDF2MD -> LLM interpretation."""
    # If no system_prompt is provided, select language-specific default prompt.
    if not system_prompt:
        # Chinese default prompt
        zh_prompt = """请以中文 markdown 的形式为这篇文章写一个公众号风格的包含有详细内容的长推文，内容要详细且丰富，

实验内容也要充分，比如包括消融实验。注意你一定要使用原始markdown 中的图片和表格来让你的公众号文章更加清晰，

图片，比如模型结构，teaser，或者一些结果图，阐释图直接插入到正文对应位置之中，不要放到最后。图片对于一个公众号文章来说很重要

INPUT: <MARKDOWN>"""

        # English default prompt
        en_prompt = """Please write a long, detailed, interested and attractive promotional post for this paper, using English Markdown format. The content must be detailed and rich, and the experimental content must be sufficient, including, for example, ablation studies. Note that you must use original Markdown syntax for images and tables to make your public account article clearer. Images, such as the model structure, a teaser figure, or some result figures and explanatory diagrams, must be inserted directly into the corresponding position within the main body of the text, and should not be placed at the end. Images are very important for a public account style article.

INPUT: <MARKDOWN>"""

        if ai_language and ai_language.lower().startswith("zh"):
            system_prompt = zh_prompt
        else:
            system_prompt = en_prompt

    start_time = datetime.now()  # Recording start time
    with deps.analysis_tasks_lock:
        task_info = deps.analysis_tasks[task_id]
        task_info["status"] = "running"
        task_info["step"] = "pdf2md"
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]
        process = None

    def update_progress(progress: int):
        with deps.analysis_tasks_lock:
            if task_id in deps.analysis_tasks:
                deps.analysis_tasks[task_id]["progress"] = progress

    def read_output(pipe, label):
        """Read subprocess output in real time"""
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    line = line.rstrip()
                    print(f"[{label}] {line}")
                    with log_lock:
                        log_lines.append(f"[{label}] {line}")
        except Exception as e:  # noqa: BLE001
            print(f"Error while reading output: {e}")
        finally:
            pipe.close()

    original_cwd = os.getcwd()
    try:
        update_progress(5)
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["step"] = "pdf2md"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("Step one: start toPDFparsed asMarkdown...")
                log_lines.append("=" * 50)
        
        update_progress(10)

        base_name = os.path.splitext(pdf_filename)[0]
        pdf_output_dir = os.path.join(pdf_dir, "outputs", base_name, "vlm")

        # Check if using API mode or local CLI mode
        use_api = mineru_config.get("useApi", False)

        if use_api:
            # API Mode: Use MinerU cloud API
            with log_lock:
                log_lines.append("Using MinerU Cloud API mode")

            from paperpilot.tools.basic_tools.mineru_api_client import MinerUAPIClient

            api_token = mineru_config.get("apiToken", "")
            if not api_token:
                raise Exception("MinerU API token is not configured")

            client = MinerUAPIClient(api_token)

            # Progress callback
            def on_progress(state, extracted_pages, total_pages):
                with log_lock:
                    if state == "waiting-file":
                        log_lines.append("Waiting for file upload...")
                    elif state == "pending":
                        log_lines.append("In queue...")
                    elif state == "running":
                        log_lines.append(
                            f"Parsing progress: {extracted_pages}/{total_pages} pages"
                        )
                        # Map parsing progress to 10-50%
                        if total_pages > 0:
                            p = 10 + int((extracted_pages / total_pages) * 40)
                            update_progress(p)
                    elif state == "converting":
                        log_lines.append("Format converting...")

            # Create output directory
            os.makedirs(pdf_output_dir, exist_ok=True)

            # Parse PDF to Markdown using API
            md_file = client.parse_pdf_to_markdown(
                pdf_path=pdf_path,
                output_dir=pdf_output_dir,
                progress_callback=on_progress,
            )

            if not md_file:
                raise Exception("API parsing failed")
            
            update_progress(50)

            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append(
                    "The first step is completed:PDFhas been parsed asMarkdown"
                )
                log_lines.append(f"Markdowndocument: {md_file}")
                log_lines.append("=" * 50)
        else:
            # Local CLI Mode: Use mineru command
            with log_lock:
                log_lines.append("Using Local MinerU CLI mode")

            mineru_server_url = mineru_config.get("serverUrl", "")
            if not mineru_server_url:
                raise Exception("MinerU Server URL is not configured")

            os.chdir(pdf_dir)

            cmd = [
                "mineru",
                "-p",
                pdf_filename,
                "-o",
                "outputs",
                "-b",
                "vlm-http-client",
                "-u",
                mineru_server_url,
            ]

            print(f"implementPDF2MDOrder: {' '.join(cmd)}")
            print(f"working directory: {pdf_dir}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            with deps.analysis_tasks_lock:
                deps.analysis_tasks[task_id]["process"] = process

            stdout_thread = threading.Thread(
                target=read_output, args=(process.stdout, "STDOUT")
            )
            stderr_thread = threading.Thread(
                target=read_output, args=(process.stderr, "STDERR")
            )
            stdout_thread.daemon = True
            stderr_thread.daemon = True
            stdout_thread.start()
            stderr_thread.start()

            return_code = process.wait(timeout=3600)

            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

            if return_code != 0:
                raise Exception(f"PDF2MDfail (exit code: {return_code})")

            outputs_dir = os.path.join(pdf_dir, "outputs")

            if not os.path.exists(pdf_output_dir):
                candidate = None
                for item in os.listdir(outputs_dir):
                    item_path = os.path.join(outputs_dir, item)
                    if os.path.isdir(item_path) and base_name in item:
                        vlm_dir = os.path.join(item_path, "vlm")
                        if os.path.exists(vlm_dir):
                            candidate = vlm_dir
                            break
                if candidate:
                    pdf_output_dir = candidate

            if not pdf_output_dir or not os.path.exists(pdf_output_dir):
                raise Exception("not foundPDFparse output directory")

            with log_lock:
                log_lines.append(f"Find the output directory: {pdf_output_dir}")

            vlm_items = os.listdir(pdf_output_dir)
            md_file = None
            for item in vlm_items:
                item_path = os.path.join(pdf_output_dir, item)
                if item == "images" and os.path.isdir(item_path):
                    continue
                elif item.endswith(".md") and os.path.isfile(item_path):
                    md_file = item_path
                    continue
                else:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        with log_lock:
                            log_lines.append(f"delete directory: {item}")
                    else:
                        os.remove(item_path)
                        with log_lock:
                            log_lines.append(f"Delete files: {item}")

            if not md_file:
                raise Exception("Generated not foundMarkdowndocument")

            update_progress(50)

            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append(
                    "The first step is completed:PDFhas been parsed asMarkdown"
                )
                log_lines.append(f"Markdowndocument: {md_file}")
                log_lines.append("=" * 50)

        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["step"] = "llm_analysis"
            with log_lock:
                log_lines.append("=" * 50)
                log_lines.append("Step 2: StartLLMInterpretation...")
                log_lines.append("=" * 50)
        
        update_progress(55)

        with open(md_file, "r", encoding="utf-8") as f:
            markdown_content = f.read()

        # 1. Remove # References Everything after (case insensitive)
        references_pattern = re.compile(
            r"^#\s+references?\s*$", re.IGNORECASE | re.MULTILINE
        )
        match = references_pattern.search(markdown_content)
        if match:
            markdown_content = markdown_content[: match.start()]
            with log_lock:
                log_lines.append(
                    f"Removed References part (from section {match.start()} characters starting)"
                )

        from openai import OpenAI

        client = OpenAI(
            api_key=openai_api_key,
            base_url=openai_base_url,
        )

        model = (openai_model or "").strip()
        if not model:
            raise Exception("LLM model name is not configured")

        # 2. Try to get the maximum length of the model (only truncate if successful)
        max_input_tokens = None
        try:
            models = client.models.list()
            # Try to get from model information context_length / max_model_len / max_tokens
            model_info = None
            for m in models.data:
                if m.id == model:
                    model_info = m
                    break

            if model_info:
                # different API Provider field names may differ
                if hasattr(model_info, "context_length"):
                    max_input_tokens = model_info.context_length
                elif hasattr(model_info, "max_model_len"):
                    max_input_tokens = model_info.max_model_len
                elif hasattr(model_info, "max_tokens"):
                    max_input_tokens = model_info.max_tokens
        except Exception as e:  # noqa: BLE001
            with log_lock:
                log_lines.append(
                    f"Unable to get maximum length from model information: {e}, will skip the truncation logic"
                )

        # Only after successfully obtaining max_input_tokens Truncated only when；Otherwise, it will not be truncated at all.
        if max_input_tokens is not None:
            # Calculate the maximum number of text characters (token number * 3, rough estimate:1 token ≈ 3-4 character, conservatively 3）
            max_text_chars = max_input_tokens * 3

            # Estimate system_prompt The number of characters (excluding <MARKDOWN> placeholder)
            system_prompt_without_placeholder = system_prompt.replace("<MARKDOWN>", "")
            system_prompt_chars = len(system_prompt_without_placeholder)

            # calculate markdown Maximum number of characters allowed for content
            max_markdown_chars = (
                max_text_chars - system_prompt_chars - 100
            )  # Keep 100 character buffer

            original_markdown_length = len(markdown_content)
            if original_markdown_length > max_markdown_chars:
                # Truncate markdown content
                markdown_content = markdown_content[:max_markdown_chars]
                with log_lock:
                    log_lines.append(
                        f"Markdown Content is too long ({original_markdown_length} characters), truncated to {max_markdown_chars} character"
                    )
                    log_lines.append(
                        f"Model maximum input token: {max_input_tokens}, estimating the maximum number of text characters: {max_text_chars}"
                    )
            else:
                with log_lock:
                    log_lines.append(
                        f"Markdown content length: {original_markdown_length} characters, within limits (maximum: {max_markdown_chars} character)"
                    )
        else:
            with log_lock:
                log_lines.append(
                    "Failed to get maximum length from model information, will not be correct Markdown The content is truncated (there may be risks of overlength)"
                )

        prompt = system_prompt.replace("<MARKDOWN>", markdown_content)
        messages = [{"role": "user", "content": prompt}]

        with log_lock:
            log_lines.append(f"Use model: {model}")
            log_lines.append("Start callingLLM API...")

        update_progress(60)

        chat_completion = client.chat.completions.create(
            messages=messages,
            model=model,
        )
        
        update_progress(90)

        result_content = chat_completion.choices[0].message.content
        result_content = re.sub(
            r"<think>[\s\S]*?</think>", "", result_content, flags=re.IGNORECASE
        )
        result_file = os.path.join(pdf_output_dir, "result.md")
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(result_content)

        with log_lock:
            log_lines.append("=" * 50)
            log_lines.append("The second step is completed:LLMInterpretation completed")
            log_lines.append(f"result file: {result_file}")
            log_lines.append("=" * 50)

        # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
            paper.mark_analysis_result(result_file)
            deps.save_paper_metadata(pdf_path, paper)
        else:
            # if paper_store Not found in , use recursive search of classification tree
            categories = deps.get_categories()

            def search_and_update_paper(node):
                category_path = deps.get_category_path(categories, node["id"])
                if category_path:
                    papers_list = deps.get_papers_in_category(node["id"], category_path)
                    for paper in papers_list:
                        if paper.id == paper_id:
                            paper.mark_analysis_result(result_file)
                            deps.save_paper_metadata(pdf_path, paper)
                            return True
                if "children" in node:
                    for child in node["children"]:
                        if search_and_update_paper(child):
                            return True
                return False

            for child in categories.get("children", []):
                if search_and_update_paper(child):
                    break

        end_time = datetime.now()
        analysis_duration = int((end_time - start_time).total_seconds())

        # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
        entry = paper_store.get_entry(paper_id)
        if entry:
            paper = entry.paper
            paper.analysis_time = max(
                getattr(paper, "analysis_time", 0), analysis_duration
            )
            path = paper.file_path
            if path and os.path.exists(path):
                deps.save_paper_metadata(path, paper)
        else:
            # if paper_store Not found in , use recursive search of classification tree
            categories = deps.get_categories()

            def search_and_update_analysis_time(node):
                category_path = deps.get_category_path(categories, node["id"])
                if category_path:
                    papers = deps.get_papers_in_category(node["id"], category_path)
                    for paper in papers:
                        if paper.id == paper_id:
                            paper.analysis_time = max(
                                getattr(paper, "analysis_time", 0), analysis_duration
                            )
                            path = paper.file_path
                            if path and os.path.exists(path):
                                deps.save_paper_metadata(path, paper)
                            return True
                if "children" in node:
                    for child in node["children"]:
                        if search_and_update_analysis_time(child):
                            return True
                return False

            for child in categories.get("children", []):
                if search_and_update_analysis_time(child):
                    break

        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "completed"
            deps.analysis_tasks[task_id]["progress"] = 100
            deps.analysis_tasks[task_id]["result"] = {
                "success": True,
                "result_file": result_file,
                "markdown_file": md_file,
            }

    except subprocess.TimeoutExpired:
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "failed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": "Interpretation timeout",
            }
        if process:
            process.kill()
    except Exception as e:  # noqa: BLE001
        print(f"An error occurred during interpretation: {str(e)}")
        import traceback

        traceback.print_exc()
        with deps.analysis_tasks_lock:
            deps.analysis_tasks[task_id]["status"] = "failed"
            deps.analysis_tasks[task_id]["result"] = {
                "success": False,
                "error": f"Interpretation failed: {str(e)}",
            }
        if process:
            process.kill()
    finally:
        os.chdir(original_cwd)
