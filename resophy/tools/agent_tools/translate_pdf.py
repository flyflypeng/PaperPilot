from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List

import fitz

from resophy.core.base_paper import Paper
from resophy.core.paper_store import paper_store

PaperList = List[Paper]
CategoryPath = List[str]

_PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3})(?:\.\d+)?\s*%")
_PAGE_FRACTION_RE = re.compile(r"(?i)\bpages?\b\D{0,20}(\d+)\s*/\s*(\d+)\b")
_OF_FRACTION_RE = re.compile(r"(?i)\bpages?\b\D{0,20}(\d+)\s+of\s+(\d+)\b")
_GENERIC_FRACTION_RE = re.compile(r"(?<!\d)(\d{1,5})\s*/\s*(\d{1,5})(?!\d)")


def _extract_progress_from_text(text: str) -> int | None:
    if not text:
        return None

    percent_candidates = [int(m.group(1)) for m in _PERCENT_RE.finditer(text)]
    if percent_candidates:
        value = percent_candidates[-1]
        if 0 <= value <= 100:
            return value
        return max(0, min(100, value))

    for pattern in (_PAGE_FRACTION_RE, _OF_FRACTION_RE):
        m = pattern.search(text)
        if not m:
            continue
        cur = int(m.group(1))
        total = int(m.group(2))
        if total <= 0:
            continue
        value = int(cur * 100 / total)
        return max(0, min(100, value))

    m = _GENERIC_FRACTION_RE.search(text)
    if m:
        cur = int(m.group(1))
        total = int(m.group(2))
        if total > 0 and cur >= 0 and total >= cur:
            value = int(cur * 100 / total)
            return max(0, min(100, value))

    return None


@dataclass
class TranslationDependencies:
    translation_tasks: Dict[str, Dict[str, Any]]
    translation_tasks_lock: threading.Lock
    get_categories: Callable[[], dict]
    get_category_path: Callable[[dict, str], CategoryPath | None]
    get_papers_in_category: Callable[[str, CategoryPath], PaperList]
    save_paper_metadata: Callable[[str, Paper], None]


def _sanitize_pdf_for_babeldoc(src_path: str, dst_path: str) -> None:
    if os.path.exists(dst_path):
        os.remove(dst_path)
    doc = fitz.open(src_path)
    try:
        doc.save(dst_path, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()


def _redact_openai_api_key(cmd: List[str]) -> List[str]:
    redacted = list(cmd)
    try:
        key_flag_index = redacted.index("--openai-api-key")
    except ValueError:
        return redacted
    if key_flag_index + 1 < len(redacted):
        redacted[key_flag_index + 1] = "***"
    return redacted


def translate_paper_task(
    task_id: str,
    paper_id: str,
    pdf_path: str,
    pdf_dir: str,
    pdf_filename: str,
    openai_model: str,
    openai_base_url: str,
    openai_api_key: str,
    deps: TranslationDependencies,
) -> None:
    """Background translation tasks"""
    start_time = datetime.now()  # Recording start time
    with deps.translation_tasks_lock:
        task_info = deps.translation_tasks[task_id]
        task_info["status"] = "running"
        task_info.setdefault("progress", 0)
        log_lines = task_info["logs"]
        log_lock = task_info["log_lock"]
        process = None
        task_info.setdefault("font_xobj_parse_errors", 0)

    def read_output(pipe, label):
        """Read subprocess output in real time"""
        try:
            for line in iter(pipe.readline, ""):
                if line:
                    line = line.rstrip()
                    print(f"[{label}] {line}")
                    with log_lock:
                        log_lines.append(f"[{label}] {line}")
                        if (
                            "failed to parse font xobj" in line
                            or "FT_Exception" in line
                            or "font xobj" in line
                        ):
                            task_info["font_xobj_parse_errors"] = int(
                                task_info.get("font_xobj_parse_errors") or 0
                            ) + 1
                        progress = _extract_progress_from_text(line)
                        if progress is not None:
                            task_info["progress"] = max(
                                int(task_info.get("progress") or 0), progress
                            )
        except Exception as e:  # noqa: BLE001
            print(f"Error while reading output: {e}")
        finally:
            pipe.close()

    original_cwd = os.getcwd()
    try:
        os.chdir(pdf_dir)
        base_name = os.path.splitext(pdf_filename)[0]
        sanitized_pdf_filename: str | None = None
        attempt_pdf_filename = pdf_filename
        attempt_base_name = base_name
        return_code = 1
        enable_compatibility = False

        for attempt_index in range(2):
            with deps.translation_tasks_lock:
                deps.translation_tasks[task_id]["progress"] = int(
                    deps.translation_tasks[task_id].get("progress") or 0
                )

            cmd = [
                "babeldoc",
                "--openai",
                "--openai-model",
                openai_model,
                "--openai-base-url",
                openai_base_url,
                "--openai-api-key",
                openai_api_key,
            ]
            if enable_compatibility:
                cmd.append("--enhance-compatibility")
            cmd.extend(["--files", attempt_pdf_filename])

            print(f"Execute translation command: {' '.join(_redact_openai_api_key(cmd))}")
            print(f"working directory: {pdf_dir}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            with deps.translation_tasks_lock:
                deps.translation_tasks[task_id]["process"] = process

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

            produced_dual_file = os.path.join(
                pdf_dir, f"{attempt_base_name}.zh.dual.pdf"
            )
            if os.path.exists(produced_dual_file):
                return_code = 0
                break

            if return_code == 0:
                break

            font_error_count = int(task_info.get("font_xobj_parse_errors") or 0)
            if attempt_index == 0 and font_error_count > 0 and sanitized_pdf_filename is None:
                with log_lock:
                    log_lines.append(
                        "[RESOPHY] Detected PDF font XObject parse errors; trying to sanitize PDF and retry."
                    )
                sanitized_pdf_filename = f"{base_name}.resophy.sanitized.pdf"
                sanitized_pdf_path = os.path.join(pdf_dir, sanitized_pdf_filename)
                _sanitize_pdf_for_babeldoc(pdf_path, sanitized_pdf_path)
                attempt_pdf_filename = sanitized_pdf_filename
                attempt_base_name = os.path.splitext(sanitized_pdf_filename)[0]
                enable_compatibility = True
                continue

            break

        with deps.translation_tasks_lock:
            if return_code == 0:
                dual_file = os.path.join(pdf_dir, f"{base_name}.zh.dual.pdf")
                mono_file = os.path.join(pdf_dir, f"{base_name}.zh.mono.pdf")

                if attempt_base_name != base_name:
                    produced_dual = os.path.join(
                        pdf_dir, f"{attempt_base_name}.zh.dual.pdf"
                    )
                    produced_mono = os.path.join(
                        pdf_dir, f"{attempt_base_name}.zh.mono.pdf"
                    )
                    if os.path.exists(produced_dual):
                        os.replace(produced_dual, dual_file)
                    if os.path.exists(produced_mono):
                        os.replace(produced_mono, mono_file)

                if os.path.exists(dual_file):
                    if os.path.exists(mono_file):
                        os.remove(mono_file)

                    # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
                    entry = paper_store.get_entry(paper_id)
                    if entry:
                        paper = entry.paper
                        paper.mark_chinese_version(dual_file)
                        target_path = paper.file_path or pdf_path
                        if target_path:
                            deps.save_paper_metadata(target_path, paper)
                    else:
                        # if paper_store Not found in , use recursive search of classification tree
                        categories = deps.get_categories()

                        def search_and_update_paper(node):
                            category_path = deps.get_category_path(categories, node["id"])
                            if category_path:
                                papers = deps.get_papers_in_category(
                                    node["id"], category_path
                                )
                                for paper in papers:
                                    if paper.id == paper_id:
                                        paper.mark_chinese_version(dual_file)
                                        target_path = paper.file_path or pdf_path
                                        if target_path:
                                            deps.save_paper_metadata(target_path, paper)
                                        return True
                            if "children" in node:
                                for child in node["children"]:
                                    if search_and_update_paper(child):
                                        return True
                            return False

                        for child in categories.get("children", []):
                            if search_and_update_paper(child):
                                break

                    log_file = os.path.join(pdf_dir, f"{base_name}.translate.log")
                    try:
                        with open(log_file, "w", encoding="utf-8") as f:
                            f.write("\n".join(log_lines))
                    except Exception as e:  # noqa: BLE001
                        print(f"Failed to save log file: {e}")

                    end_time = datetime.now()
                    translation_duration = int((end_time - start_time).total_seconds())

                    # First try from paper_store Find papers in (supports _ReadingListTemp Table of contents)
                    entry = paper_store.get_entry(paper_id)
                    if entry:
                        paper = entry.paper
                        paper.translation_time = max(
                            getattr(paper, "translation_time", 0),
                            translation_duration,
                        )
                        path = paper.file_path
                        if path and os.path.exists(path):
                            deps.save_paper_metadata(path, paper)
                    else:
                        # if paper_store Not found in , use recursive search of classification tree
                        categories = deps.get_categories()

                        def search_and_update_time(node):
                            category_path = deps.get_category_path(categories, node["id"])
                            if category_path:
                                papers = deps.get_papers_in_category(
                                    node["id"], category_path
                                )
                                for paper in papers:
                                    if paper.id == paper_id:
                                        paper.translation_time = max(
                                            getattr(paper, "translation_time", 0),
                                            translation_duration,
                                        )
                                        path = paper.file_path
                                        if path and os.path.exists(path):
                                            deps.save_paper_metadata(path, paper)
                                        return True
                            if "children" in node:
                                for child in node["children"]:
                                    if search_and_update_time(child):
                                        return True
                            return False

                        for child in categories.get("children", []):
                            if search_and_update_time(child):
                                break

                    deps.translation_tasks[task_id]["status"] = "completed"
                    deps.translation_tasks[task_id]["progress"] = 100
                    deps.translation_tasks[task_id]["result"] = {
                        "success": True,
                        "chinese_version_path": dual_file,
                        "log_file": log_file,
                    }
                else:
                    deps.translation_tasks[task_id]["status"] = "failed"
                    deps.translation_tasks[task_id]["result"] = {
                        "success": False,
                        "error": "Translation file not generated",
                    }
            else:
                font_error_count = int(task_info.get("font_xobj_parse_errors") or 0)
                if font_error_count > 0:
                    error_message = (
                        "PDF 字体对象解析失败（FreeType invalid argument）。"
                        "建议用浏览器/Acrobat“另存为 PDF”或“打印到 PDF”生成新文件后重试。"
                    )
                else:
                    error_message = f"翻译失败（退出码: {return_code}）"
                deps.translation_tasks[task_id]["status"] = "failed"
                deps.translation_tasks[task_id]["result"] = {
                    "success": False,
                    "error": error_message,
                }

    except subprocess.TimeoutExpired:
        with deps.translation_tasks_lock:
            deps.translation_tasks[task_id]["status"] = "failed"
            deps.translation_tasks[task_id]["result"] = {
                "success": False,
                "error": "Translation timeout",
            }
        if process:
            process.kill()
    except Exception as e:  # noqa: BLE001
        print(f"An error occurred during translation: {str(e)}")
        import traceback

        traceback.print_exc()
        with deps.translation_tasks_lock:
            deps.translation_tasks[task_id]["status"] = "failed"
            deps.translation_tasks[task_id]["result"] = {
                "success": False,
                "error": f"Translation failed: {str(e)}",
            }
        if process:
            process.kill()
    finally:
        try:
            sanitized_pdf_path = os.path.join(
                pdf_dir, f"{os.path.splitext(pdf_filename)[0]}.resophy.sanitized.pdf"
            )
            with deps.translation_tasks_lock:
                task_status = deps.translation_tasks.get(task_id, {}).get("status")
            if os.path.exists(sanitized_pdf_path) and task_status == "completed":
                os.remove(sanitized_pdf_path)
        except Exception:  # noqa: BLE001
            pass
        os.chdir(original_cwd)
