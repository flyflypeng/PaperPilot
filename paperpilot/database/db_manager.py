from .connection import get_db, init_db
from .models import SCHEMA_SCRIPT
import sqlite3
import json


def _migrate_agentic_settings_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    row = cursor.execute(
        "SELECT value FROM user_settings WHERE key = ?",
        ("agentic_settings",),
    ).fetchone()
    if not row or not row[0]:
        return

    try:
        settings = json.loads(row[0])
    except Exception:
        return

    if not isinstance(settings, dict):
        return

    llm_configs = settings.get("llmConfigs")
    if isinstance(llm_configs, dict) and all(
        isinstance(llm_configs.get(k), dict)
        for k in ("translate", "interpret", "dailyArxiv")
    ):
        return

    legacy_cfg = {
        "llmModel": (settings.get("llmModel") or "").strip(),
        "llmBaseUrl": (settings.get("llmBaseUrl") or "").strip(),
        "llmApiKey": (settings.get("llmApiKey") or "").strip(),
    }

    new_llm_configs: dict = {}
    if isinstance(llm_configs, dict):
        new_llm_configs.update(llm_configs)

    for k in ("translate", "interpret", "dailyArxiv"):
        if not isinstance(new_llm_configs.get(k), dict):
            new_llm_configs[k] = legacy_cfg.copy()
        else:
            cfg = new_llm_configs[k]
            cfg.setdefault("llmModel", legacy_cfg.get("llmModel", ""))
            cfg.setdefault("llmBaseUrl", legacy_cfg.get("llmBaseUrl", ""))
            cfg.setdefault("llmApiKey", legacy_cfg.get("llmApiKey", ""))

    settings["llmConfigs"] = new_llm_configs
    settings.pop("llmModel", None)
    settings.pop("llmBaseUrl", None)
    settings.pop("llmApiKey", None)

    cursor.execute(
        "INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)",
        ("agentic_settings", json.dumps(settings, ensure_ascii=False)),
    )

def init_db_schema():
    conn = sqlite3.connect('db/paperpilot.db') # Use direct connection for initialization script outside request context
    cursor = conn.cursor()
    cursor.executescript(SCHEMA_SCRIPT)
    _migrate_agentic_settings_schema(conn)
    conn.commit()
    conn.close()
