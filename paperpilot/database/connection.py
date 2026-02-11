import sqlite3
import os
import threading
from flask import g, has_app_context

DB_PATH = os.path.join(os.getcwd(), 'db', 'paperpilot.db')

_thread_local = threading.local()

def get_db():
    if has_app_context():
        db = getattr(g, '_database', None)
        if db is None:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            db = g._database = sqlite3.connect(DB_PATH)
            db.row_factory = sqlite3.Row
        return db

    db = getattr(_thread_local, 'db', None)
    if db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        db = _thread_local.db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def close_db(e=None):
    if has_app_context():
        db = getattr(g, '_database', None)
        if db is not None:
            db.close()
            try:
                delattr(g, '_database')
            except Exception:
                pass
        return

    db = getattr(_thread_local, 'db', None)
    if db is not None:
        db.close()
        try:
            delattr(_thread_local, 'db')
        except Exception:
            pass

def init_db(app):
    app.teardown_appcontext(close_db)
