import json
from ..connection import get_db

class SettingsDAO:
    @staticmethod
    def get_setting(key, default=None):
        try:
            db = get_db()
            row = db.execute('SELECT value FROM user_settings WHERE key = ?', (key,)).fetchone()
            if row:
                try:
                    return json.loads(row['value'])
                except:
                    return row['value']
            return default
        except Exception as e:
            print(f"Error getting setting {key}: {e}")
            return default

    @staticmethod
    def save_setting(key, value):
        try:
            db = get_db()
            db.execute('INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)', (key, json.dumps(value)))
            db.commit()
        except Exception as e:
            print(f"Error saving setting {key}: {e}")
