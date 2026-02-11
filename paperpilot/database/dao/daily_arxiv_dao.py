import json
from ..connection import get_db

class DailyArxivDAO:
    @staticmethod
    def save_task(date, category, status, metadata=None):
        db = get_db()
        metadata_json = json.dumps(metadata) if metadata else None
        db.execute('INSERT OR REPLACE INTO daily_arxiv_tasks (date, category, status, metadata) VALUES (?, ?, ?, ?)',
                   (date, category, status, metadata_json))
        db.commit()

    @staticmethod
    def get_task(date, category):
        db = get_db()
        row = db.execute('SELECT * FROM daily_arxiv_tasks WHERE date = ? AND category = ?', (date, category)).fetchone()
        if row:
            d = dict(row)
            if d['metadata']:
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except:
                    pass
            return d
        return None
