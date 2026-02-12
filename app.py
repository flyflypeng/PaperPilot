import argparse
import json
import os
import threading
import time
from datetime import datetime
from functools import partial
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

import requests
from flask import Flask, g, jsonify, render_template, request

from paperpilot.core.base_paper import Paper
from paperpilot.core.paper_store import paper_store
from paperpilot.core.search_index import SearchIndex
from paperpilot.database.connection import DB_PATH
from paperpilot.database.connection import init_db as register_db_teardown
from paperpilot.database.dao.settings_dao import SettingsDAO
from paperpilot.database.db_manager import init_db_schema
from paperpilot.routes.agent_routes.agent_summary_route import (
    register_agent_summary_routes,
)
from paperpilot.routes.agent_routes.agent_chat_route import (
    register_agent_chat_routes,
)
from paperpilot.routes.agent_routes.agent_translate_route import (
    register_agent_translate_routes,
)
from paperpilot.routes.basic_routes.category_tree_route import register_category_routes
from paperpilot.routes.basic_routes.daily_arxiv_route import register_daily_arxiv_routes
from paperpilot.routes.basic_routes.export_route import register_export_routes
from paperpilot.routes.basic_routes.import_route import register_import_routes
from paperpilot.routes.basic_routes.institution_mapping_route import (
    register_institution_mapping_routes,
)
from paperpilot.routes.basic_routes.paper_operation_route import (
    register_paper_operation_routes,
)
from paperpilot.routes.basic_routes.search_route import register_search_routes
from paperpilot.routes.basic_routes.settings_route import register_settings_routes
from paperpilot.routes.basic_routes.update_from_url_route import (
    register_update_from_url_routes,
)
from paperpilot.routes.basic_routes.upload_from_pdf_route import (
    register_upload_from_pdf_routes,
)
from paperpilot.tools.basic_tools import category_manager, paper_repository

parser = argparse.ArgumentParser(description="PaperPilot")
parser.add_argument(
    "--papers-dir",
    type=str,
    default="./papers",
    help="PaperPilot papers directory path (default: ./papers)",
)
parser.add_argument(
    "--host",
    type=str,
    default="0.0.0.0",
    help="Server listening address (default: 0.0.0.0)",
)
parser.add_argument(
    "--port", type=int, default=7191, help="Server listening port (default: 7191)"
)
parser.add_argument("--debug", action="store_true", help="Enable debug mode")

app = Flask(__name__)
register_db_teardown(app)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max file size

_auth_cache: dict[str, tuple[float, str]] = {}
_auth_cache_lock = threading.Lock()


def _verify_supabase_access_token(access_token: str) -> str | None:
    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not (supabase_url and supabase_anon_key):
        return None

    now = time.time()
    with _auth_cache_lock:
        cached = _auth_cache.get(access_token)
        if cached and cached[0] > now:
            return cached[1]

    try:
        resp = requests.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": supabase_anon_key,
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        email = (data.get("email") or "").strip().lower()
        if not email:
            return None

        with _auth_cache_lock:
            _auth_cache[access_token] = (now + 60.0, email)
        return email
    except Exception:
        return None


@app.before_request
def _require_auth_for_api():
    if not request.path.startswith("/api/"):
        return None

    # Whitelist for paths that do not require authentication (static resources, downloads)
    if (
        request.path.startswith("/api/daily-arxiv/thumbnail/")
        or request.path.startswith("/api/export/download/")
        or request.path.startswith("/api/paper/")
        or request.path.startswith("/api/categories/")
    ):
        return None

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not (supabase_url and supabase_anon_key):
        return (
            jsonify(
                {
                    "error": "Supabase后端鉴权未配置，请设置 SUPABASE_URL / SUPABASE_ANON_KEY",
                }
            ),
            500,
        )

    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return jsonify({"error": "未登录"}), 401

    access_token = auth.split(" ", 1)[1].strip()
    if not access_token:
        return jsonify({"error": "未登录"}), 401

    email = _verify_supabase_access_token(access_token)
    if not email:
        return jsonify({"error": "登录已失效"}), 401

    g.user_email = email
    return None

# Configuration file storage path (will be set in main function according to parameters)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = None  # Will be set in main
CATEGORIES_FILE = None  # Will be set in main
READING_LIST_FILE = None  # Will be set in main
USER_SETTINGS_FILE = None  # User settings (name, avatar, etc.)
READING_HISTORY_FILE = None  # Daily reading history
AGENTIC_SETTINGS_FILE = None  # AI feature settings (uniform LLM configuration)
DAILY_ARXIV_SETTINGS_FILE = None  # Daily arXiv settings
AVATARS_DIR = None  # Avatar image directory
TEMP_PAPERS_DIR = None  # Daily arXiv temporary paper directory
READING_LIST_TEMP_DIR = None  # Reading list temporary paper directory
SEARCH_INDEX_DB = None  # Search index database path
search_index = None  # Search index instance
# No longer use the unified papers_db.json file, use one JSON file for each PDF
# Default user settings
DEFAULT_USER_SETTINGS = {
    "name": "Paper Reader",
    "avatar": None,  # Avatar file name, e.g. "avatar.jpg"
    "heatmapColorScheme": "green",
    "onboardingDontShow": False,  # Whether to no longer show the新手教程
    "aiLanguage": "zh",  # AI output language (en/zh), applies to AI translation, AI interpretation, and Daily arXiv summary
}

# Default Agentic settings (uniform AI feature configuration)
DEFAULT_AGENTIC_SETTINGS = {
    "llmConfigs": {
        "translate": {
            "llmModel": "",
            "llmBaseUrl": "",
            "llmApiKey": "",
        },
        "interpret": {
            "llmModel": "",
            "llmBaseUrl": "",
            "llmApiKey": "",
        },
        "dailyArxiv": {
            "llmModel": "",
            "llmBaseUrl": "",
            "llmApiKey": "",
        },
    },
    "mineruServerUrl": "",  # PDF parsing service address (for local mode)
    "mineruUseApi": False,  # Toggle between local CLI mode and cloud API mode
    "mineruApiToken": "",  # MinerU cloud API token (for API mode)
    # Note: System prompts are now built-in and selected based on user's aiLanguage setting
    # Custom prompts are no longer supported
}

# Default Daily arXiv settings
DEFAULT_DAILY_ARXIV_SETTINGS = {
    "enabled": False,  # Default to disabled
    "categories": ["cs.CV"],  # arXiv category list
    "checkIntervalMinutes": 30,  # Check interval (minutes)
    "retentionDays": 2,  # Retention days for papers
    "maxKeywords": 2,  # Maximum number of keywords (1-3)
    "keywordList": [
        "LLM",
        "MLLM",
        "Agent",
        "Image Generation",
        "Video Generation",
        "3D Generation",
        "2D Perception",
        "3D Perception",
        "Embodied AI & Robotics",
        "Audio & Speech",
        "ML Fundamentals & RL",
    ],  # Keyword list
    "affiliationPrompt": """I will provide you with the first-page information of a paper. You need to extract all affiliations (institution names) from it and also extract the homepage and GitHub repo URL if there is. For affiliations, do not include author names. If an affiliation includes details such as region, department, school, or college, those should be omitted. Only keep the main institution name (e.g., School of Computer Science, Fudan University → Fudan University).

Additional rules:

If the institution is well-known and has a commonly used abbreviation (e.g., University of Illinois Urbana–Champaign → UIUC), return the abbreviation instead of the full name. If the institution is not well-known or does not have a standard abbreviation, keep the full name.

You must also return the nationality (country) for each affiliation, in the same order.

Output the result directly in JSON format, and make sure it is valid JSON. The structure should be:

{
"affiliations": ["Affiliation1", "Affiliation2", ...],
"countries": ["Country_of_Affiliation1", "Country_of_Affiliation2", ...],
"homepage": "homepage_url_or_null",
"github": "github_url_or_null"
}

Notes:
1. If there is no homepage or github url, use the JSON value null (not the string "null" and not Python None).
2. Do NOT add a trailing comma after the last field.
3. Do not include any explanation or extra text, only output the JSON object.

Now the input is:
""",
    # Summary prompts - language-specific (built-in, not customizable)
    "summaryPromptZh": """我会给你一篇 AI 文章的英文摘要，以及一个可选关键词列表（英文）。你需要：

用中文简要总结这篇文章在解决什么问题、如何解决的，字数控制在 100-200 字。

从我提供的关键词列表中挑选最能代表文章类型的关键词（英文）

按如下 JSON 格式输出结果：

{"summary": "这篇文章主要解决...的问题。作者提出...方法，通过...实现了...", "keywords": ["Keyword"]}

注意

summary 必须中文，简洁、客观。

keywords 必须来自我提供的关键词列表：[{keyword_list}], 最多{max_keywords}个关键词。一定要是符合这篇文章的关键词，不能随意猜测。

直接输出 JSON，不要有其他解释。

现在输入的摘要是：
""",
    "summaryPromptEn": """I will give you an English abstract of an AI paper, and an optional keyword list (in English). You need to:

Briefly summarize in English what problem this paper solves and how it solves it, keep it within 100-200 words.

Select keywords (in English) from the keyword list I provide that best represent the type of paper.

Output the result in the following JSON format:

{"summary": "This paper mainly solves...problem. The authors propose...method, through...achieved...", "keywords": ["Keyword"]}

Notes:

summary must be in English, concise and objective.

keywords must come from the keyword list I provide: [{keyword_list}], at most {max_keywords} keywords. They must be keywords that match this paper, do not guess randomly.

Output JSON directly, no other explanations.

Now the input abstract is:
""",
}

# Global variables (will be initialized in init_app)
init_categories = None
get_categories = None
save_categories = None
create_category_folder = None
find_category_node = category_manager.find_category_node
get_category_path = category_manager.get_category_path
add_pdf_counts_to_categories = category_manager.add_pdf_counts_to_categories
get_category_pdf_count = category_manager.get_category_pdf_count

get_papers_in_category = None
get_paper_json_path = paper_repository.get_paper_json_path
load_paper_metadata = paper_repository.load_paper_metadata
scan_papers_in_directory = paper_repository.scan_papers_in_directory


def save_paper_metadata(pdf_path: str, paper_data) -> None:
    """Save paper metadata and update search index"""
    paper_repository.save_paper_metadata(pdf_path, paper_data)

    # Update search index
    if search_index:
        try:
            if isinstance(paper_data, Paper):
                paper = paper_data
            else:
                paper = Paper.from_dict(paper_data) if paper_data else None

            if paper:
                # First try to get the latest category ID from paper_store (most accurate)
                category_id = None
                entry = paper_store.get_entry(paper.id)
                if entry:
                    category_id = entry.category_id

                # If paper_store does not have it, try to get it from the paper data
                if not category_id:
                    if hasattr(paper, "category_id") and paper.category_id:
                        category_id = paper.category_id
                    elif isinstance(paper_data, dict):
                        category_id = paper_data.get("category_id")

                search_index.index_paper(paper, category_id)
        except Exception as e:
            print(f"Failed to update search index: {e}")


def delete_paper_files(pdf_path: str) -> None:
    """Delete paper files and remove from search index"""
    # First try to get the paper ID (if possible)
    paper_id = None
    try:
        paper = load_paper_metadata(pdf_path)
        if paper:
            paper_id = paper.id
    except Exception:
        pass

    # Delete files
    paper_repository.delete_paper_files(pdf_path)

    # Remove from search index
    if paper_id and search_index:
        try:
            search_index.remove_paper(paper_id)
        except Exception as e:
            print(f"Failed to remove from search index: {e}")


def init_app(papers_dir=None):
    """Initialize application configuration and directories"""
    # Initialize DB Schema
    try:
        os.makedirs(os.path.join(os.getcwd(), 'db'), exist_ok=True)
        init_db_schema()
    except Exception as e:
        print(f"Failed to initialize database schema: {e}")

    global UPLOAD_FOLDER, CATEGORIES_FILE, READING_LIST_FILE
    global USER_SETTINGS_FILE, READING_HISTORY_FILE, AGENTIC_SETTINGS_FILE, AVATARS_DIR
    global DAILY_ARXIV_SETTINGS_FILE, TEMP_PAPERS_DIR, READING_LIST_TEMP_DIR
    global SEARCH_INDEX_DB, search_index
    global init_categories, get_categories, save_categories, create_category_folder, get_papers_in_category

    # Set paper directory
    if papers_dir:
        # If a relative path is specified, it is relative to the current working directory
        if not os.path.isabs(papers_dir):
            UPLOAD_FOLDER = os.path.abspath(papers_dir)
        else:
            UPLOAD_FOLDER = papers_dir
    else:
        UPLOAD_FOLDER = os.path.join(BASE_DIR, "papers")

    # Configuration files are all in the paper directory
    CATEGORIES_FILE = os.path.join(UPLOAD_FOLDER, "categories.json")
    READING_LIST_FILE = os.path.join(UPLOAD_FOLDER, "reading_list.json")
    USER_SETTINGS_FILE = os.path.join(UPLOAD_FOLDER, "user_settings.json")
    READING_HISTORY_FILE = os.path.join(UPLOAD_FOLDER, "reading_history.json")
    AGENTIC_SETTINGS_FILE = os.path.join(UPLOAD_FOLDER, "agentic_settings.json")
    DAILY_ARXIV_SETTINGS_FILE = os.path.join(UPLOAD_FOLDER, "daily_arxiv_settings.json")
    AVATARS_DIR = os.path.join(UPLOAD_FOLDER, ".avatars")
    TEMP_PAPERS_DIR = os.path.join(UPLOAD_FOLDER, ".daily_arxiv_temp")
    READING_LIST_TEMP_DIR = os.path.join(UPLOAD_FOLDER, "_ReadingListTemp")
    SEARCH_INDEX_DB = os.path.join(UPLOAD_FOLDER, ".search_index.db")

    # Ensure necessary directories exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(AVATARS_DIR, exist_ok=True)
    os.makedirs(TEMP_PAPERS_DIR, exist_ok=True)
    os.makedirs(READING_LIST_TEMP_DIR, exist_ok=True)

    # Initialize search index
    search_index = SearchIndex(SEARCH_INDEX_DB)

    # Initialize Daily arXiv settings file (still file-based)
    if not os.path.exists(DAILY_ARXIV_SETTINGS_FILE):
        with open(DAILY_ARXIV_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DAILY_ARXIV_SETTINGS, f, ensure_ascii=False, indent=2)


    # Bind basic tool functions
    init_categories = partial(category_manager.init_categories, CATEGORIES_FILE)
    get_categories = partial(category_manager.get_categories, CATEGORIES_FILE)
    save_categories = partial(category_manager.save_categories, CATEGORIES_FILE)
    create_category_folder = partial(
        category_manager.create_category_folder, UPLOAD_FOLDER
    )
    get_papers_in_category = partial(
        paper_repository.get_papers_in_category, UPLOAD_FOLDER
    )

    print(f"Paper directory: {UPLOAD_FOLDER}")
    print(f"SQLite database: {DB_PATH}")
    print("Settings storage: SQLite (user_settings / reading_history / agentic_settings)")
    print(f"Category configuration (file): {CATEGORIES_FILE}")
    print(f"Daily arXiv settings (file): {DAILY_ARXIV_SETTINGS_FILE}")
    print(f"Avatar directory: {AVATARS_DIR}")
    print(f"Daily arXiv temporary directory: {TEMP_PAPERS_DIR}")
    print(f"Search index database: {SEARCH_INDEX_DB}")


# Translation task management
translation_tasks = (
    {}
)  # {task_id: {paper_id, process, logs, status, start_time, log_lock}}
translation_tasks_lock = threading.Lock()  # Protect translation task dictionary

# AI interpretation task management
analysis_tasks = (
    {}
)  # {task_id: {paper_id, process, logs, status, start_time, log_lock, step}}
analysis_tasks_lock = threading.Lock()  # Protect interpretation task dictionary


@app.route("/")
def index():
    return render_template(
        "index.html",
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
    )


def register_routes():
    """Register all routes (must be called after init_app)"""
    register_category_routes(
        app,
        get_categories=get_categories,
        save_categories=save_categories,
        find_category_node=find_category_node,
        get_category_path=get_category_path,
        get_papers_in_category=get_papers_in_category,
        add_pdf_counts_to_categories=add_pdf_counts_to_categories,
        get_category_pdf_count=get_category_pdf_count,
        paper_store=paper_store,
        upload_folder=UPLOAD_FOLDER,
    )

    register_search_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        upload_folder=UPLOAD_FOLDER,
        search_index=search_index,
    )

    # First register Daily arXiv routes, get manager instance
    from paperpilot.tools.basic_tools.daily_arxiv import get_manager

    daily_arxiv_manager = get_manager(TEMP_PAPERS_DIR, DAILY_ARXIV_SETTINGS_FILE)

    # Set LLM configuration callback
    def get_llm_config():
        try:
            cfg = SettingsDAO.get_setting("agentic_settings", {}) or {}
            llm_configs = cfg.get("llmConfigs")
            if isinstance(llm_configs, dict) and isinstance(
                llm_configs.get("dailyArxiv"), dict
            ):
                picked = llm_configs.get("dailyArxiv") or {}
                return {
                    "llmModel": (picked.get("llmModel") or "").strip(),
                    "llmBaseUrl": (picked.get("llmBaseUrl") or "").strip(),
                    "llmApiKey": (picked.get("llmApiKey") or "").strip(),
                }
            return {
                "llmModel": (cfg.get("llmModel") or "").strip(),
                "llmBaseUrl": (cfg.get("llmBaseUrl") or "").strip(),
                "llmApiKey": (cfg.get("llmApiKey") or "").strip(),
            }
        except Exception:
            return {}

    daily_arxiv_manager.set_llm_config_callback(get_llm_config)

    # Set user settings callback (for getting aiLanguage)
    def get_user_settings():
        try:
            return SettingsDAO.get_setting("user_settings", {}) or {}
        except Exception:
            return {}

    daily_arxiv_manager.set_user_settings_callback(get_user_settings)

    # Check if LLM configuration is complete
    def is_llm_configured() -> bool:
        llm_config = get_llm_config()
        return bool(
            llm_config.get("llmBaseUrl")
            and llm_config.get("llmApiKey")
            and llm_config.get("llmModel")
        )

    # Start Daily arXiv callback function
    def start_daily_arxiv_if_configured():
        """If LLM configuration is complete, start Daily arXiv scheduler"""
        if is_llm_configured() and not daily_arxiv_manager._scheduler_running:
            daily_arxiv_manager.start_scheduler()
            print(
                "[DailyArxiv] LLM configuration is complete, scheduler has been started"
            )

    # Only start scheduler if LLM configuration is complete
    if is_llm_configured():
        daily_arxiv_manager.start_scheduler()
        print("[DailyArxiv] LLM configuration is complete, scheduler has been started")
    else:
        print(
            "[DailyArxiv] LLM configuration is incomplete, scheduler has not been started. Please configure LLM API in settings and start manually."
        )

    register_daily_arxiv_routes(
        app,
        daily_arxiv_settings_file=DAILY_ARXIV_SETTINGS_FILE,
        default_daily_arxiv_settings=DEFAULT_DAILY_ARXIV_SETTINGS,
        temp_papers_dir=TEMP_PAPERS_DIR,
        get_categories=get_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        reading_list_temp_dir=READING_LIST_TEMP_DIR,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
    )

    register_settings_routes(
        app,
        user_settings_file=USER_SETTINGS_FILE,
        default_user_settings=DEFAULT_USER_SETTINGS,
        reading_history_file=READING_HISTORY_FILE,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
        default_agentic_settings=DEFAULT_AGENTIC_SETTINGS,
        avatars_dir=AVATARS_DIR,
        start_daily_arxiv_callback=start_daily_arxiv_if_configured,
    )

    register_paper_operation_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        find_category_node=find_category_node,
        get_papers_in_category=get_papers_in_category,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        get_paper_json_path=get_paper_json_path,
        delete_paper_files=delete_paper_files,
        extract_pdf_metadata=None,  # No longer needed, use new upload_paper module
        search_arxiv_by_title=None,  # No longer needed, use new upload_paper module
        reading_list_file=READING_LIST_FILE,
        upload_folder=UPLOAD_FOLDER,
        paper_store=paper_store,
    )

    register_upload_from_pdf_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        paper_store=paper_store,
    )

    register_update_from_url_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        reading_list_temp_dir=READING_LIST_TEMP_DIR,
        paper_store=paper_store,
    )

    register_agent_summary_routes(
        app,
        analysis_tasks=analysis_tasks,
        analysis_tasks_lock=analysis_tasks_lock,
        get_categories=get_categories,
        get_category_path=get_category_path,
        get_papers_in_category=get_papers_in_category,
        save_paper_metadata=save_paper_metadata,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
    )

    register_agent_chat_routes(
        app,
        get_categories=get_categories,
        get_category_path=get_category_path,
        get_papers_in_category=get_papers_in_category,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
    )

    register_agent_translate_routes(
        app,
        translation_tasks=translation_tasks,
        translation_tasks_lock=translation_tasks_lock,
        get_categories=get_categories,
        get_category_path=get_category_path,
        get_papers_in_category=get_papers_in_category,
        save_paper_metadata=save_paper_metadata,
        agentic_settings_file=AGENTIC_SETTINGS_FILE,
    )

    register_import_routes(
        app,
        get_categories=get_categories,
        save_categories=save_categories,
        get_category_path=get_category_path,
        create_category_folder=create_category_folder,
        save_paper_metadata=save_paper_metadata,
        reading_list_file=READING_LIST_FILE,
        paper_store=paper_store,
        upload_folder=UPLOAD_FOLDER,
    )

    register_export_routes(
        app,
        papers_dir=UPLOAD_FOLDER,
    )

    register_institution_mapping_routes(
        app,
        daily_arxiv_settings_file=DAILY_ARXIV_SETTINGS_FILE,
    )


@app.route("/viewer/<paper_id>")
def pdf_viewer(paper_id):
    """PDF reader page"""
    use_chinese = request.args.get("chinese", "false").lower() == "true"
    paper_title = None
    paper = paper_store.get(paper_id)
    if paper:
        paper_title = paper.title or paper.filename or paper.original_filename
    return render_template(
        "pdf_viewer.html",
        paper_id=paper_id,
        use_chinese=use_chinese,
        paper_title=paper_title,
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
    )


@app.route("/viewer/analysis/<paper_id>")
def analysis_viewer(paper_id):
    """AI interpretation Markdown full-screen view page"""
    return render_template(
        "analysis_viewer.html",
        paper_id=paper_id,
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
    )


if __name__ == "__main__":
    # Parse command line arguments
    args = parser.parse_args()

    # Initialize application (configure paper directory etc.)
    init_app(papers_dir=args.papers_dir)

    # Register routes (must be called after init_app)
    register_routes()

    # Initialize category system
    init_categories()

    # Rebuild search index (in background thread to avoid blocking startup)
    def rebuild_search_index():
        """Rebuild search index in background thread to avoid blocking startup"""
        import threading
        import time

        def _rebuild():
            time.sleep(1)  # Wait 1 second to ensure other initialization is complete
            print("Start rebuilding search index...")
            try:
                categories = get_categories()
                papers_with_categories = []

                def collect_papers(node, category_path):
                    """Recursively collect all papers"""
                    node_path = get_category_path(categories, node.get("id"))
                    if node_path and len(node_path) > 1:
                        directory_path = os.path.join(UPLOAD_FOLDER, *node_path[1:])
                        if os.path.exists(directory_path):
                            papers = scan_papers_in_directory(
                                directory_path,
                                category_id=node.get("id"),
                                category_path=node_path,
                            )
                            for paper in papers:
                                papers_with_categories.append((paper, node.get("id")))

                    for child in node.get("children", []):
                        collect_papers(child, node_path or [])

                for child in categories.get("children", []):
                    collect_papers(child, [])

                if papers_with_categories:
                    print(
                        f"Start rebuilding search index, {len(papers_with_categories)} papers..."
                    )
                    search_index.rebuild_index(papers_with_categories)
                    # Information completed in rebuild_index, no need to repeat here
                else:
                    print("No papers found, skip index reconstruction")
            except Exception as e:
                print(f"Failed to rebuild search index: {e}")
                import traceback

                traceback.print_exc()

        thread = threading.Thread(target=_rebuild, daemon=True)
        thread.start()

    # Set rebuild index callback (after defining rebuild_search_index)
    if search_index:
        search_index.set_rebuild_callback(rebuild_search_index)

    # Rebuild search index
    rebuild_search_index()

    # Add API to get papers directory path
    @app.route("/api/papers-dir", methods=["GET"])
    def get_papers_dir():
        """Get absolute path of papers directory"""
        return jsonify({"success": True, "path": os.path.abspath(UPLOAD_FOLDER)})

    # Paper data is now directly stored in the JSON file next to the PDF file
    print(f"Start server: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
