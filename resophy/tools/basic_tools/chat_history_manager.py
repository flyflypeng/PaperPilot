import os
import json
import uuid
import time
from datetime import datetime
from resophy.database.dao.chat_dao import ChatDAO

class ChatHistoryManager:
    """
    Manages chat history persistence for papers using SQLite.
    """

    def __init__(self, paper_store):
        self.paper_store = paper_store

    def _get_chats_dir(self, paper_id):
        """Deprecated: Get the directory where chat sessions are stored for a paper."""
        paper = self.paper_store.get(paper_id)
        if not paper:
            return None
        
        paper_path = paper.file_path
        paper_dir = os.path.dirname(paper_path)
        chats_dir = os.path.join(paper_dir, "chats")
        return chats_dir

    def get_sessions(self, paper_id):
        """Get a list of all chat sessions for a paper."""
        try:
            # Get from DB
            sessions_data = ChatDAO.get_chats_by_paper(paper_id)
            sessions = []
            
            for s in sessions_data:
                sessions.append({
                    'id': s['session_id'],
                    'title': s.get('title', 'New Chat'),
                    'updated_at': s.get('updated_at', 0),
                    'preview': self._get_preview(s.get('history', []))
                })

            # Check for legacy files and migrate if not in DB
            # This might be slow if many files, but it's a one-time migration logic usually
            # But we can't easily check if DB has ALL files without listing files.
            # So we list files, check if in DB, if not migrate.
            chats_dir = self._get_chats_dir(paper_id)
            if chats_dir and os.path.exists(chats_dir):
                 for filename in os.listdir(chats_dir):
                    if filename.endswith(".json"):
                        session_id = filename[:-5]
                        # Check if already in sessions list
                        if not any(sess['id'] == session_id for sess in sessions):
                             # Load and migrate
                             try:
                                 with open(os.path.join(chats_dir, filename), 'r', encoding='utf-8') as f:
                                     file_data = json.load(f)
                                     self._save_session(paper_id, file_data)
                                     # Add to list
                                     sessions.append({
                                        'id': file_data['id'],
                                        'title': file_data.get('title', 'New Chat'),
                                        'updated_at': file_data.get('updated_at', 0),
                                        'preview': self._get_preview(file_data.get('messages', []))
                                    })
                             except Exception as e:
                                 print(f"Error migrating chat {filename}: {e}")

            # Sort by updated_at desc
            sessions.sort(key=lambda x: float(x['updated_at'] or 0), reverse=True)
            return sessions
        except Exception as e:
            print(f"Error getting sessions for paper {paper_id}: {e}")
            return []

    def _get_preview(self, messages):
        """Get a preview text from the last message."""
        if not messages:
            return "No messages"
        last_msg = messages[-1]
        content = last_msg.get('content', '')
        return content[:50] + "..." if len(content) > 50 else content

    def create_session(self, paper_id, title="New Chat"):
        """Create a new chat session."""
        session_id = str(uuid.uuid4())
        session_data = {
            'id': session_id,
            'paper_id': paper_id,
            'title': title,
            'created_at': time.time(),
            'updated_at': time.time(),
            'messages': []
        }
        
        self._save_session(paper_id, session_data)
        return session_data

    def get_session(self, paper_id, session_id):
        """Get a specific chat session with full history."""
        # Try DB
        data = ChatDAO.get_chat(session_id)
        if data:
            if data.get('paper_id') != paper_id:
                return None
            if 'id' not in data:
                data['id'] = data.get('session_id')
            data['messages'] = data.pop('history', [])
            return data

        # Fallback to file
        chats_dir = self._get_chats_dir(paper_id)
        if chats_dir:
            file_path = os.path.join(chats_dir, f"{session_id}.json")
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Auto-migrate
                    self._save_session(paper_id, data)
                    return data
            
        return None

    def save_message(self, paper_id, session_id, role, content):
        """Append a message to a session and update it."""
        session = self.get_session(paper_id, session_id)
        if not session:
            # Create if not exists (shouldn't happen normally if flow is correct)
            session = self.create_session(paper_id)
            if session['id'] != session_id:
                pass

        # Append message
        new_msg = {
            'role': role,
            'content': content,
            'timestamp': time.time()
        }
        session['messages'].append(new_msg)
        session['updated_at'] = time.time()
        
        # Auto-update title if it's the first user message
        if role == 'user' and len([m for m in session['messages'] if m['role'] == 'user']) == 1:
            session['title'] = content[:30] + "..." if len(content) > 30 else content

        self._save_session(paper_id, session)
        return session

    def delete_session(self, paper_id, session_id):
        """Delete a chat session."""
        # Delete from DB
        try:
            ChatDAO.delete_chat(session_id)
        except Exception as e:
            print(f"Error deleting chat {session_id} from DB: {e}")
        
        # Delete file if exists (cleanup legacy files)
        chats_dir = self._get_chats_dir(paper_id)
        if chats_dir:
            file_path = os.path.join(chats_dir, f"{session_id}.json")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting chat file {file_path}: {e}")
        
        return True
        
    def update_session_title(self, paper_id, session_id, new_title):
        """Update the title of a session."""
        session = self.get_session(paper_id, session_id)
        if session:
            session['title'] = new_title
            session['updated_at'] = time.time()
            self._save_session(paper_id, session)
            return True
        return False

    def _save_session(self, paper_id, session_data):
        """Helper to write session to DB."""
        dao_data = session_data.copy()
        dao_data['history'] = dao_data.pop('messages', [])
        ChatDAO.save_chat(session_data['id'], dao_data)
