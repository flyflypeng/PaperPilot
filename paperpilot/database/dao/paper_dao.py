import json
import sqlite3
from ..connection import get_db

class PaperDAO:
    COLUMN_MAP = {
        'id': 'id',
        'title': 'title',
        'authors': 'authors',
        'abstract': 'abstract',
        'arxiv_published_date': 'published_date',
        'arxiv_url': 'url',
        'arxiv_id': 'arxiv_id',
        'subject': 'category',
        'upload_date': 'download_date',
        'file_path': 'file_path',
        'starred': 'starred',
        'read_time': 'read_time',
        'translation_status': 'translation_status',
        'analysis_status': 'analysis_status',
        'is_daily': 'is_daily',
        'daily_date': 'daily_date',
        'thumbnail_path': 'thumbnail_path'
    }

    @staticmethod
    def _dict_to_row(paper_dict):
        row = {}
        metadata = paper_dict.copy()
        
        for field, col in PaperDAO.COLUMN_MAP.items():
            val = metadata.pop(field, None)
            row[col] = val
        
        # Handle special cases or defaults
        if row.get('starred') is not None:
            row['starred'] = 1 if row['starred'] else 0
        else:
            row['starred'] = 0
            
        row['metadata'] = json.dumps(metadata)
        return row

    @staticmethod
    def _row_to_dict(row):
        d = {}
        row_dict = dict(row)
        
        # Extract metadata first
        if row_dict.get('metadata'):
            try:
                d.update(json.loads(row_dict['metadata']))
            except:
                pass
        
        # Overwrite with column values
        for field, col in PaperDAO.COLUMN_MAP.items():
            if col in row_dict and row_dict[col] is not None:
                d[field] = row_dict[col]
                
        # Boolean conversion
        d['starred'] = bool(d.get('starred'))
        d['is_daily'] = bool(d.get('is_daily'))
        
        return d

    @staticmethod
    def save_paper(paper_data):
        try:
            db = get_db()
            row = PaperDAO._dict_to_row(paper_data)
            
            cols = list(row.keys())
            placeholders = ', '.join(['?'] * len(cols))
            sql = f'INSERT OR REPLACE INTO papers ({", ".join(cols)}) VALUES ({placeholders})'
            
            db.execute(sql, list(row.values()))
            db.commit()
        except Exception as e:
            print(f"Error saving paper {paper_data.get('id')}: {e}")
            raise

    @staticmethod
    def get_paper(paper_id):
        db = get_db()
        row = db.execute('SELECT * FROM papers WHERE id = ?', (paper_id,)).fetchone()
        if row:
            return PaperDAO._row_to_dict(row)
        return None

    @staticmethod
    def get_paper_by_arxiv_id(arxiv_id):
        db = get_db()
        row = db.execute('SELECT * FROM papers WHERE arxiv_id = ?', (arxiv_id,)).fetchone()
        if row:
            return PaperDAO._row_to_dict(row)
        return None

    @staticmethod
    def get_paper_by_path(file_path):
        db = get_db()
        row = db.execute('SELECT * FROM papers WHERE file_path = ?', (file_path,)).fetchone()
        if row:
            return PaperDAO._row_to_dict(row)
        return None

    @staticmethod
    def list_papers(filter_dict=None):
        db = get_db()
        sql = 'SELECT * FROM papers'
        params = []
        if filter_dict:
            clauses = []
            for k, v in filter_dict.items():
                col = PaperDAO.COLUMN_MAP.get(k, k) # Try mapped name, else use key (might fail if not column)
                # Simple SQL construction - valid for internal use
                clauses.append(f"{col} = ?")
                params.append(v)
            if clauses:
                sql += ' WHERE ' + ' AND '.join(clauses)
        
        rows = db.execute(sql, params).fetchall()
        return [PaperDAO._row_to_dict(row) for row in rows]
        
    @staticmethod
    def delete_paper(paper_id):
        db = get_db()
        db.execute('DELETE FROM papers WHERE id = ?', (paper_id,))
        db.commit()

    @staticmethod
    def get_all_papers():
        db = get_db()
        rows = db.execute('SELECT * FROM papers').fetchall()
        return [PaperDAO._row_to_dict(row) for row in rows]

    @staticmethod
    def get_daily_papers(date, category=None):
        db = get_db()
        sql = 'SELECT * FROM papers WHERE is_daily = 1 AND daily_date = ?'
        params = [date]
        if category:
            sql += ' AND category = ?'
            params.append(category)
        rows = db.execute(sql, params).fetchall()
        return [PaperDAO._row_to_dict(row) for row in rows]

    @staticmethod
    def get_available_daily_dates():
        db = get_db()
        rows = db.execute('SELECT DISTINCT daily_date FROM papers WHERE is_daily = 1 ORDER BY daily_date DESC').fetchall()
        return [row['daily_date'] for row in rows if row['daily_date']]

    @staticmethod
    def delete_old_daily_papers(cutoff_date):
        db = get_db()
        # Delete papers where is_daily=1 and daily_date < cutoff_date
        # Note: string comparison works for YYYY-MM-DD
        db.execute('DELETE FROM papers WHERE is_daily = 1 AND daily_date < ?', (cutoff_date,))
        db.commit()
