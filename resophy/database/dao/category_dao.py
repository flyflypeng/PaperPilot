from ..connection import get_db

class CategoryDAO:
    @staticmethod
    def get_all_categories():
        db = get_db()
        rows = db.execute('SELECT * FROM categories').fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def save_category(id, name, parent_id=None, display_name=None):
        db = get_db()
        db.execute('INSERT OR REPLACE INTO categories (id, name, parent_id, display_name) VALUES (?, ?, ?, ?)', 
                   (id, name, parent_id, display_name))
        db.commit()
            
    @staticmethod
    def clear_categories():
        db = get_db()
        db.execute('DELETE FROM categories')
        db.commit()
