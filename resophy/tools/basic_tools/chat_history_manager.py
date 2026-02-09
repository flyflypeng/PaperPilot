import os
import json
import uuid
import time
from datetime import datetime

class ChatHistoryManager:
    """
    Manages chat history persistence for papers.
    Chats are stored in a 'chats' subdirectory under the paper's directory.
    Each session is a separate JSON file: {session_id}.json
    """

    def __init__(self, paper_store):
        self.paper_store = paper_store

    def _get_chats_dir(self, paper_id):
        """Get the directory where chat sessions are stored for a paper."""
        paper = self.paper_store.get(paper_id)
        if not paper:
            raise ValueError(f"Paper with ID {paper_id} not found")
        
        paper_path = paper.file_path
        paper_dir = os.path.dirname(paper_path)
        chats_dir = os.path.join(paper_dir, "chats")
        
        if not os.path.exists(chats_dir):
            os.makedirs(chats_dir)
            
        return chats_dir

    def get_sessions(self, paper_id):
        """Get a list of all chat sessions for a paper."""
        try:
            chats_dir = self._get_chats_dir(paper_id)
            sessions = []
            
            for filename in os.listdir(chats_dir):
                if filename.endswith(".json"):
                    file_path = os.path.join(chats_dir, filename)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            session_data = json.load(f)
                            # Basic validation
                            if 'id' in session_data and 'title' in session_data:
                                sessions.append({
                                    'id': session_data['id'],
                                    'title': session_data.get('title', 'New Chat'),
                                    'updated_at': session_data.get('updated_at', 0),
                                    'preview': self._get_preview(session_data.get('messages', []))
                                })
                    except Exception as e:
                        print(f"Error loading chat session {filename}: {e}")
            
            # Sort by updated_at desc
            sessions.sort(key=lambda x: x['updated_at'], reverse=True)
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
        chats_dir = self._get_chats_dir(paper_id)
        file_path = os.path.join(chats_dir, f"{session_id}.json")
        
        if not os.path.exists(file_path):
            return None
            
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_message(self, paper_id, session_id, role, content):
        """Append a message to a session and update it."""
        session = self.get_session(paper_id, session_id)
        if not session:
            # Create if not exists (shouldn't happen normally if flow is correct)
            session = self.create_session(paper_id)
            if session['id'] != session_id:
                # If we were passed a specific ID but it didn't exist, we might want to respect it
                # But for simplicity, we assume session exists or we create a new one
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
        chats_dir = self._get_chats_dir(paper_id)
        file_path = os.path.join(chats_dir, f"{session_id}.json")
        
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
        
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
        """Helper to write session to disk."""
        chats_dir = self._get_chats_dir(paper_id)
        file_path = os.path.join(chats_dir, f"{session_data['id']}.json")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
