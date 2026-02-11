"""
SQLite Search index module

Provides database management functions for paper search and indexing, using SQLite FTS5 Full text search.
Database files are stored in papers-dir directory.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

from paperpilot.core.base_paper import Paper


class SearchIndex:
    """Thread safe SQLite Search Index Manager"""

    def __init__(self, db_path: str):
        """
        Initialize search index

        Args:
            db_path: SQLite Database file path
        """
        self.db_path = db_path
        self._lock = threading.RLock()
        self._rebuild_callback = None  # Rebuild index callback function
        self._is_rebuilding = False  # Whether the index is being rebuilt
        self._rebuild_lock = threading.Lock()  # Rebuild operation lock
        self._last_checkpoint_time = 0  # last time checkpoint timestamp
        self._checkpoint_interval = 300  # Every 5 Execute once every minute checkpoint
        self._init_database()

    def set_rebuild_callback(self, callback):
        """Set the callback function for rebuilding the index"""
        self._rebuild_callback = callback

    def _maybe_checkpoint(self, force: bool = False) -> None:
        """
        Execute regularly WAL checkpoint,prevent WAL Database corruption due to excessive file size

        Args:
            force: Whether to enforce checkpoint（Ignore time interval）
        """
        import time

        current_time = time.time()

        # If it's been a long time since last time checkpoint Exceeds the interval time, or enforces execution
        if (
            force
            or (current_time - self._last_checkpoint_time) >= self._checkpoint_interval
        ):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                try:
                    # Execution passive checkpoint（Does not block other connections）
                    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    self._last_checkpoint_time = current_time
                finally:
                    conn.close()
            except Exception as e:
                # checkpoint Failure does not affect the main operation, only logs are recorded
                print(f"WAL checkpoint fail: {e}")

    def _extract_context_snippet(
        self, text: str, query: str, context_chars: int = 150
    ) -> str:
        """
        Extract context fragments containing keywords

        Args:
            text: original text
            query: Search keywords
            context_chars: The number of characters extracted before and after the keyword（default150）

        Returns:
            A context fragment containing the keyword, or returning to the beginning of the text if the keyword is not found
        """
        if not text or not query:
            return text[: context_chars * 2] if text else ""

        text_lower = text.lower()
        query_lower = query.lower().strip()

        # First try to find the complete query phrase
        match = None
        escaped_query = re.escape(query_lower)
        match = re.search(escaped_query, text_lower)

        # If you can't find the complete phrase, try to find where all the words occur
        if not match:
            query_words = [w.strip() for w in query_lower.split() if w.strip()]
            if len(query_words) > 1:
                # Find all occurrences of a word（There can be other characters between words）
                # Building regular expressions: words1...word2...word3（appear sequentially）
                pattern = r"\b.*\b".join(re.escape(w) for w in query_words)
                match = re.search(pattern, text_lower, re.IGNORECASE)

            # If still not found, try to find the first word
            if not match and query_words:
                first_word = query_words[0]
                match = re.search(re.escape(first_word), text_lower)

        # For Chinese, if it still cannot be found, try to find Chinese characters（No distinction between order）
        if not match:
            # Detect whether it contains Chinese characters
            chinese_chars = [
                char for char in query_lower if "\u4e00" <= char <= "\u9fff"
            ]
            if chinese_chars:
                # Try to find the position of the first Chinese character
                first_char = chinese_chars[0]
                match = re.search(re.escape(first_char), text_lower)

        # If still not found, return to the beginning of the text
        if not match:
            return (
                text[: context_chars * 2] + "..."
                if len(text) > context_chars * 2
                else text
            )

        # Get matching position
        start_pos = match.start()
        end_pos = match.end()

        # Compute context scope
        snippet_start = max(0, start_pos - context_chars)
        snippet_end = min(len(text), end_pos + context_chars)

        # Extract fragments
        snippet = text[snippet_start:snippet_end]

        # If the fragment does not start at the beginning of the text, add an ellipsis
        if snippet_start > 0:
            snippet = "..." + snippet
        # If the fragment does not go to the end of the text, add an ellipsis
        if snippet_end < len(text):
            snippet = snippet + "..."

        return snippet

    def _check_database_integrity(self) -> bool:
        """Check database integrity"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            try:
                cursor = conn.cursor()
                # Perform integrity check
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                return result and result[0] == "ok"
            finally:
                conn.close()
        except Exception:
            return False

    def _try_repair_fts5_index(self) -> bool:
        """
        try to fix FTS5 Index synchronization problem（Lightweight fix）

        Returns:
            True If the repair is successful,False If repair fails a complete rebuild is required
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            try:
                cursor = conn.cursor()
                # Delete old triggers
                cursor.execute("DROP TRIGGER IF EXISTS papers_fts_insert")
                cursor.execute("DROP TRIGGER IF EXISTS papers_fts_delete")
                cursor.execute("DROP TRIGGER IF EXISTS papers_fts_update")

                # Try deleting and rebuilding FTS5 index
                cursor.execute("DROP TABLE IF EXISTS papers_fts")
                cursor.execute(
                    """
                    CREATE VIRTUAL TABLE papers_fts USING fts5(
                        id UNINDEXED,
                        title,
                        authors,
                        abstract,
                        notes,
                        content='papers',
                        content_rowid='rowid'
                    )
                    """
                )

                # Re-create trigger, update automatically FTS index
                cursor.execute(
                    """
                    CREATE TRIGGER papers_fts_insert AFTER INSERT ON papers BEGIN
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        VALUES (new.rowid, new.id, new.title, new.authors, new.abstract, new.notes);
                    END
                    """
                )
                cursor.execute(
                    """
                    CREATE TRIGGER papers_fts_delete AFTER DELETE ON papers BEGIN
                        DELETE FROM papers_fts WHERE rowid = old.rowid;
                    END
                    """
                )
                cursor.execute(
                    """
                    CREATE TRIGGER papers_fts_update AFTER UPDATE ON papers BEGIN
                        DELETE FROM papers_fts WHERE rowid = old.rowid;
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        VALUES (new.rowid, new.id, new.title, new.authors, new.abstract, new.notes);
                    END
                    """
                )

                # Restart from papers table filling FTS5 index
                cursor.execute(
                    """
                    INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                    SELECT rowid, id, title, authors, abstract, notes FROM papers
                    """
                )
                conn.commit()
                print("FTS5 Index synchronization repair successful")
                return True
            finally:
                conn.close()
        except Exception as e:
            print(f"FTS5 Index repair failed and requires a full rebuild: {e}")
            return False

    def _repair_database(self) -> None:
        """Repair a damaged database: try a lightweight repair first, delete and rebuild if that fails"""
        # If already rebuilding, skip
        with self._rebuild_lock:
            if self._is_rebuilding:
                return

            print(f"Database problem detected, trying to fix it: {self.db_path}")
            try:
                # Try a lightweight fix first（Repair only FTS5 Index synchronization problem）
                if self._try_repair_fts5_index():
                    print("Index sync issue fixed")
                    return

                # If lightweight repair fails, perform a full rebuild
                print("Lightweight repair failed, perform a full rebuild...")

                # Back up corrupted database
                if os.path.exists(self.db_path):
                    backup_path = self.db_path + ".corrupted"
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                    os.rename(self.db_path, backup_path)
                    print(f"The corrupted database has been backed up to: {backup_path}")

                # Delete corrupt database files
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)

                # Reinitialize the database
                self._init_database()
                print("The database repair is completed and the index needs to be rebuilt.")

                # If there is a rebuild callback, call it（Asynchronous, non-blocking）
                if self._rebuild_callback:
                    print("Trigger index rebuild（background execution）...")
                    import threading

                    threading.Thread(target=self._rebuild_callback, daemon=True).start()
            except Exception as e:
                print(f"Repair database failed: {e}")
                import traceback

                traceback.print_exc()

    def _init_database(self) -> None:
        """Initialize database table structure"""
        with self._lock:
            # use WAL Patterns improve concurrency performance
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            try:
                # enable WAL model（Write-Ahead Logging）
                conn.execute("PRAGMA journal_mode=WAL")
                # Set the sync mode to FULL（More secure against data corruption）
                conn.execute("PRAGMA synchronous=FULL")
                # Set cache size
                conn.execute("PRAGMA cache_size=-64000")  # 64MB
                # set up WAL automatic checkpoint（when WAL File exceeds 10MB automatically checkpoint）
                conn.execute("PRAGMA wal_autocheckpoint=10000")  # 10MB
                cursor = conn.cursor()

                # Create a paper metadata table（Include notes Field for full-text search notes）
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS papers (
                        id TEXT PRIMARY KEY,
                        title TEXT,
                        authors TEXT,
                        abstract TEXT,
                        notes TEXT,
                        filename TEXT,
                        category_id TEXT,
                        file_path TEXT,
                        updated_at TEXT
                    )
                    """
                )

                # If it is an old version database, it may not be available yet notes Column, do a lightweight migration here
                cursor.execute("PRAGMA table_info(papers)")
                columns = [row[1] for row in cursor.fetchall()]  # The second column is the column name
                if "notes" not in columns:
                    cursor.execute("ALTER TABLE papers ADD COLUMN notes TEXT")

                # Create a full-text search virtual table（FTS5）, including the remarks field
                # old version papers_fts probably not notes column, check first
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_fts'"
                )
                has_fts = cursor.fetchone() is not None
                if has_fts:
                    cursor.execute("PRAGMA table_info(papers_fts)")
                    fts_columns = [row[1] for row in cursor.fetchall()]
                    if "notes" not in fts_columns:
                        # old-fashioned FTS table no notes, delete directly, re-create and rebuild the index later
                        cursor.execute("DROP TABLE IF EXISTS papers_fts")

                cursor.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                        id UNINDEXED,
                        title,
                        authors,
                        abstract,
                        notes,
                        content='papers',
                        content_rowid='rowid'
                    )
                    """
                )

                # Create triggers to update automatically FTS index
                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS papers_fts_insert AFTER INSERT ON papers BEGIN
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        VALUES (new.rowid, new.id, new.title, new.authors, new.abstract, new.notes);
                    END
                    """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS papers_fts_delete AFTER DELETE ON papers BEGIN
                        DELETE FROM papers_fts WHERE rowid = old.rowid;
                    END
                    """
                )

                cursor.execute(
                    """
                    CREATE TRIGGER IF NOT EXISTS papers_fts_update AFTER UPDATE ON papers BEGIN
                        DELETE FROM papers_fts WHERE rowid = old.rowid;
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        VALUES (new.rowid, new.id, new.title, new.authors, new.abstract, new.notes);
                    END
                    """
                )

                # Create indexes to speed up queries
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_papers_category ON papers(category_id)"
                )

                conn.commit()
            finally:
                conn.close()

    def index_paper(self, paper: Paper, category_id: Optional[str] = None) -> None:
        """
        Index a paper

        Args:
            paper: Paper object
            category_id: Category of the paperID
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO papers 
                        (id, title, authors, abstract, notes, filename, category_id, file_path, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (
                            paper.id,
                            paper.title or "",
                            paper.authors or "",
                            paper.abstract or "",
                            getattr(paper, "notes", "") or "",
                            paper.filename or "",
                            category_id or "",
                            paper.file_path or "",
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                # Execute regularly checkpoint to prevent WAL File too large
                self._maybe_checkpoint()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                is_db_error = (
                    "malformed" in error_msg
                    or "corrupt" in error_msg
                    or "missing row" in error_msg
                    or "fts5" in error_msg
                )
                if is_db_error:
                    print(f"Database problem detected while indexing papers（Maybe the index is out of sync）: {e}")
                    self._repair_database()
                else:
                    raise

    def remove_paper(self, paper_id: str) -> None:
        """
        Remove paper from index

        Args:
            paper_id: paperID
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
                    conn.commit()
                finally:
                    conn.close()
                self._maybe_checkpoint()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                is_db_error = (
                    "malformed" in error_msg
                    or "corrupt" in error_msg
                    or "missing row" in error_msg
                    or "fts5" in error_msg
                )
                if is_db_error:
                    print(f"Database problem detected when deleting paper（Maybe the index is out of sync）: {e}")
                    self._repair_database()
                else:
                    raise

    def update_paper_category(self, paper_id: str, category_id: Optional[str]) -> None:
        """
        Update the classification of the paper

        Args:
            paper_id: paperID
            category_id: new categoryID
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE papers SET category_id = ?, updated_at = datetime('now') WHERE id = ?",
                        (category_id or "", paper_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
                self._maybe_checkpoint()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                is_db_error = (
                    "malformed" in error_msg
                    or "corrupt" in error_msg
                    or "missing row" in error_msg
                    or "fts5" in error_msg
                )
                if is_db_error:
                    print(f"Database issue detected while updating categories（Maybe the index is out of sync）: {e}")
                    self._repair_database()
                else:
                    raise

    def search(
        self,
        query: str,
        category_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Search papers

        Args:
            query: Search keywords
            category_id: Limit search categoriesID（Optional）
            limit: Limit on the number of results returned

        Returns:
            List of search results, each result contains:
            - id: paperID
            - title: title
            - authors: author
            - abstract: summary
            - filename: file name
            - category_id: ClassificationID
            - matched_fields: List of matching fields
            - similarity: similarity score
        """
        with self._lock:
            conn = None
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                cursor = conn.cursor()

                # build FTS Query
                query_cleaned = query.strip()

                # If the query is empty, empty results will be returned directly.
                if not query_cleaned:
                    return []

                # Detect whether it contains Chinese characters
                has_chinese = any(
                    "\u4e00" <= char <= "\u9fff" for char in query_cleaned
                )

                # Escape special characters in queries
                # FTS5 Special characters in:", *, AND, OR, NOT, NEAR
                query_cleaned_escaped = query_cleaned.replace('"', '""')

                # For Chinese queries, use LIKE Query（FTS5 Poor support for Chinese）
                # For English queries, use FTS5 Full text search
                if has_chinese:
                    # use LIKE Query, supports partial matching
                    # escape LIKE Special characters in:%, _
                    like_query = query_cleaned.replace("%", "\\%").replace("_", "\\_")

                    if category_id:
                        sql = """
                            SELECT 
                                papers.id,
                                papers.title,
                                papers.authors,
                                papers.abstract,
                                papers.notes,
                                papers.filename,
                                papers.category_id,
                                0.0 as rank
                            FROM papers
                            WHERE papers.category_id = ?
                                AND (
                                    papers.title LIKE ? 
                                    OR papers.authors LIKE ?
                                    OR papers.abstract LIKE ?
                                    OR papers.notes LIKE ?
                                )
                            ORDER BY 
                                CASE 
                                    WHEN papers.title LIKE ? THEN 1
                                    WHEN papers.authors LIKE ? THEN 2
                                    WHEN papers.abstract LIKE ? THEN 3
                                    WHEN papers.notes LIKE ? THEN 4
                                    ELSE 5
                                END,
                                length(papers.title) ASC
                            LIMIT ?
                        """
                        like_pattern = f"%{like_query}%"
                        params = (
                            category_id,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            limit,
                        )
                    else:
                        sql = """
                            SELECT 
                                papers.id,
                                papers.title,
                                papers.authors,
                                papers.abstract,
                                papers.notes,
                                papers.filename,
                                papers.category_id,
                                0.0 as rank
                            FROM papers
                            WHERE (
                                papers.title LIKE ? 
                                OR papers.authors LIKE ?
                                OR papers.abstract LIKE ?
                                OR papers.notes LIKE ?
                            )
                            ORDER BY 
                                CASE 
                                    WHEN papers.title LIKE ? THEN 1
                                    WHEN papers.authors LIKE ? THEN 2
                                    WHEN papers.abstract LIKE ? THEN 3
                                    WHEN papers.notes LIKE ? THEN 4
                                    ELSE 5
                                END,
                                length(papers.title) ASC
                            LIMIT ?
                        """
                        like_pattern = f"%{like_query}%"
                        params = (
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            like_pattern,
                            limit,
                        )

                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                else:
                    # For English queries, use FTS5 Full text search（Keep the original logic）
                    fts_query = f'"{query_cleaned_escaped}"'

                    if category_id:
                        sql = """
                            SELECT 
                                papers.id,
                                papers.title,
                                papers.authors,
                                papers.abstract,
                                papers.notes,
                                papers.filename,
                                papers.category_id,
                                bm25(papers_fts) as rank
                            FROM papers_fts
                            JOIN papers ON papers.id = papers_fts.id
                            WHERE papers_fts MATCH ? 
                                AND papers.category_id = ?
                            ORDER BY rank ASC, length(papers.title) ASC
                            LIMIT ?
                        """
                        params = (fts_query, category_id, limit)
                    else:
                        sql = """
                            SELECT 
                                papers.id,
                                papers.title,
                                papers.authors,
                                papers.abstract,
                                papers.notes,
                                papers.filename,
                                papers.category_id,
                                bm25(papers_fts) as rank
                            FROM papers_fts
                            JOIN papers ON papers.id = papers_fts.id
                            WHERE papers_fts MATCH ?
                            ORDER BY rank ASC, length(papers.title) ASC
                            LIMIT ?
                        """
                        params = (fts_query, limit)

                    cursor.execute(sql, params)
                    rows = cursor.fetchall()

                # Processing results
                query_lower = query.lower()
                results = []
                for row in rows:
                    pid, title, authors, abstract, notes, filename, cat_id, rank = row

                    # Determine the field of the true hit（Include notes notes）
                    matched_fields = []
                    abstract_snippet = None
                    notes_snippet = None
                    if title and query_lower in (title or "").lower():
                        matched_fields.append("title")
                    if authors and query_lower in (authors or "").lower():
                        matched_fields.append("authors")
                    if abstract and query_lower in (abstract or "").lower():
                        matched_fields.append("abstract")
                        # Extract context fragments containing keywords
                        abstract_snippet = self._extract_context_snippet(
                            abstract, query, context_chars=150
                        )
                    if notes and query_lower in (notes or "").lower():
                        matched_fields.append("notes")
                        # Extract context fragments containing keywords
                        notes_snippet = self._extract_context_snippet(
                            notes, query, context_chars=150
                        )

                    # no more"Hit by default title"of fallback，
                    # This is what you see on the front end matched_fields It must truly contain query set of fields

                    similarity = max(0.5, 1.0 - abs(rank) / 20.0) if rank else 0.5

                    result_item = {
                        "id": pid,
                        "title": title or "",
                        "authors": authors or "",
                        "abstract": abstract or "",
                        "notes": notes or "",
                        "filename": filename or "",
                        "category_id": cat_id or None,
                        "matched_fields": matched_fields,
                        "similarity": similarity,
                    }
                    # If a snippet was extracted, add it to the results
                    if abstract_snippet:
                        result_item["abstract_snippet"] = abstract_snippet
                    # If the note fragment is extracted, add it to the result
                    if notes_snippet:
                        result_item["notes_snippet"] = notes_snippet

                    results.append(result_item)

                return results

            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                # Detect database corruption or FTS5 Index out of sync error
                is_db_error = (
                    "malformed" in error_msg
                    or "corrupt" in error_msg
                    or "missing row" in error_msg  # FTS5 Sync error
                    or "fts5" in error_msg  # FTS5 Related errors
                )
                if is_db_error:
                    # Database corruption or index out-of-sync is encountered during search, and reconstruction is not triggered immediately.（avoid blocking）
                    # Only log errors and return empty results, rebuilding will occur in the background
                    if not self._is_rebuilding:
                        print(f"Database problem detected while searching（Maybe the index is out of sync）: {e}")
                        print("The database is being repaired and indexes are being rebuilt in the background, please try the search again later....")
                        # Trigger repair and rebuild asynchronously without blocking searches
                        import threading

                        threading.Thread(
                            target=self._repair_database, daemon=True
                        ).start()
                    return []
                else:
                    raise
            finally:
                if conn:
                    conn.close()

    def rebuild_index(self, papers: List[Tuple[Paper, Optional[str]]]) -> None:
        """
        Rebuild the entire index

        Args:
            papers: list of papers, each element is (Paper, category_id) tuple
        """
        # Prevent repeated rebuilds
        with self._rebuild_lock:
            if self._is_rebuilding:
                print("Index rebuild is already in progress, skip this rebuild")
                return
            self._is_rebuilding = True

        try:
            with self._lock:
                # If the database is damaged, repair it first
                if not self._check_database_integrity():
                    print("Database corruption detected, repair first...")
                    self._repair_database()

            try:
                conn = sqlite3.connect(
                    self.db_path, timeout=60.0
                )  # Rebuilding indexes takes longer
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()

                    # Clear existing data
                    cursor.execute("DELETE FROM papers")
                    cursor.execute("DELETE FROM papers_fts")

                    # Batch insert
                    for paper, category_id in papers:
                        cursor.execute(
                            """
                            INSERT INTO papers 
                            (id, title, authors, abstract, notes, filename, category_id, file_path, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                            """,
                            (
                                paper.id,
                                paper.title or "",
                                paper.authors or "",
                                paper.abstract or "",
                                getattr(paper, "notes", "") or "",
                                paper.filename or "",
                                category_id or "",
                                paper.file_path or "",
                            ),
                        )

                    # reconstruction FTS index
                    cursor.execute(
                        """
                        INSERT INTO papers_fts(rowid, id, title, authors, abstract, notes)
                        SELECT rowid, id, title, authors, abstract, notes FROM papers
                        """
                    )

                    conn.commit()
                    # Complete execution after rebuilding checkpoint
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    print(f"Search index reconstruction completed, total indexing {len(papers)} papers")
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                is_db_error = (
                    "malformed" in error_msg
                    or "corrupt" in error_msg
                    or "missing row" in error_msg
                    or "fts5" in error_msg
                )
                if is_db_error:
                    print(f"Database problem detected while rebuilding index（Maybe the index is out of sync）: {e}")
                    self._repair_database()
                    # Repair and try again（Called recursively after resetting the flag）
                    if papers:
                        with self._rebuild_lock:
                            self._is_rebuilding = False
                        self.rebuild_index(papers)
                    return  # Return directly after the recursive call and no longer execute finally
                else:
                    raise
        finally:
            # reset rebuild flag（Make sure it resets regardless of success or failure）
            with self._rebuild_lock:
                self._is_rebuilding = False

    def get_paper_count(self, category_id: Optional[str] = None) -> int:
        """
        Get the number of papers

        Args:
            category_id: ClassificationID（Optional）

        Returns:
            Number of papers
        """
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    if category_id:
                        cursor.execute(
                            "SELECT COUNT(*) FROM papers WHERE category_id = ?",
                            (category_id,),
                        )
                    else:
                        cursor.execute("SELECT COUNT(*) FROM papers")
                    return cursor.fetchone()[0]
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                is_db_error = (
                    "malformed" in error_msg
                    or "corrupt" in error_msg
                    or "missing row" in error_msg
                    or "fts5" in error_msg
                )
                if is_db_error:
                    print(f"Database issue detected when getting number of papers（Maybe the index is out of sync）: {e}")
                    self._repair_database()
                    return 0
                else:
                    raise

    def clear(self) -> None:
        """Clear all index data"""
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                try:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM papers")
                    cursor.execute("DELETE FROM papers_fts")
                    conn.commit()
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    conn.close()
            except sqlite3.DatabaseError as e:
                error_msg = str(e).lower()
                is_db_error = (
                    "malformed" in error_msg
                    or "corrupt" in error_msg
                    or "missing row" in error_msg
                    or "fts5" in error_msg
                )
                if is_db_error:
                    print(f"Database problem detected when clearing index（Maybe the index is out of sync）: {e}")
                    self._repair_database()
                else:
                    raise
