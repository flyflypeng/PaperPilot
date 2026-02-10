from .connection import get_db, init_db
from .models import SCHEMA_SCRIPT
import sqlite3

def init_db_schema():
    conn = sqlite3.connect('db/resophy.db') # Use direct connection for initialization script outside request context
    cursor = conn.cursor()
    cursor.executescript(SCHEMA_SCRIPT)
    conn.commit()
    conn.close()
