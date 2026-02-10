import json
from ..connection import get_db

class ReadingHistoryDAO:
    @staticmethod
    def add_history(date, duration, paper_id, timestamp):
        db = get_db()
        db.execute('INSERT INTO reading_history (date, duration, paper_id, timestamp) VALUES (?, ?, ?, ?)',
                   (date, duration, paper_id, timestamp))
        db.commit()

    @staticmethod
    def get_history(limit=None):
        db = get_db()
        sql = 'SELECT * FROM reading_history ORDER BY timestamp DESC'
        if limit:
            sql += f' LIMIT {limit}'
        rows = db.execute(sql).fetchall()
        return [dict(row) for row in rows]
        
    @staticmethod
    def get_history_by_date(date):
        db = get_db()
        rows = db.execute('SELECT * FROM reading_history WHERE date = ?', (date,)).fetchall()
        return [dict(row) for row in rows]

class ReadingListDAO:
    @staticmethod
    def add_item(paper_id, added_at, status='unread'):
        db = get_db()
        db.execute('INSERT OR REPLACE INTO reading_list (paper_id, added_at, status) VALUES (?, ?, ?)',
                   (paper_id, added_at, status))
        db.commit()

    @staticmethod
    def get_list():
        db = get_db()
        rows = db.execute('SELECT * FROM reading_list ORDER BY added_at DESC').fetchall()
        return [dict(row) for row in rows]
        
    @staticmethod
    def remove_item(paper_id):
        db = get_db()
        db.execute('DELETE FROM reading_list WHERE paper_id = ?', (paper_id,))
        db.commit()
