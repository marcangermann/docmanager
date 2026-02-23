"""
DocManager - Datenbankschicht (SQLite + FTS5)

Schema:
  documents     - Dokument-Metadaten
  tags          - Hierarchische Tags
  document_tags - Zuordnung Dokument ↔ Tag
  documents_fts - FTS5 Volltextindex
"""
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _create_schema(self) -> None:
        assert self.conn
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                path        TEXT NOT NULL UNIQUE,
                title       TEXT NOT NULL,
                date_added  TEXT NOT NULL,
                date_doc    TEXT,
                page_count  INTEGER DEFAULT 0,
                file_size   INTEGER DEFAULT 0,
                text_snippet TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS tags (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT NOT NULL,
                parent_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
                UNIQUE(name, parent_id)
            );

            CREATE TABLE IF NOT EXISTS document_tags (
                doc_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                is_primary INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (doc_id, tag_id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                USING fts5(title, text_content, content='documents', content_rowid='id');

            CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, title, text_content)
                VALUES (new.id, new.title, new.text_snippet);
            END;

            CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, text_content)
                VALUES ('delete', old.id, old.title, old.text_snippet);
            END;

            CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, text_content)
                VALUES ('delete', old.id, old.title, old.text_snippet);
                INSERT INTO documents_fts(rowid, title, text_content)
                VALUES (new.id, new.title, new.text_snippet);
            END;
        """)
        self.conn.commit()

    # ── Dokument-Operationen ──────────────────────────────────────────────────

    def add_document(self, path: str, title: str, page_count: int,
                     file_size: int, text_content: str,
                     date_doc: Optional[str] = None) -> int:
        """Fügt ein Dokument zur DB hinzu und gibt die neue ID zurück."""
        assert self.conn
        now = datetime.now().isoformat()
        snippet = text_content[:500] if text_content else ""
        cur = self.conn.execute(
            """INSERT INTO documents (path, title, date_added, date_doc,
               page_count, file_size, text_snippet)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (path, title, now, date_doc, page_count, file_size, snippet)
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    def update_document_path(self, doc_id: int, new_path: str) -> None:
        assert self.conn
        self.conn.execute("UPDATE documents SET path=? WHERE id=?",
                          (new_path, doc_id))
        self.conn.commit()

    def delete_document(self, doc_id: int) -> None:
        assert self.conn
        self.conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        self.conn.commit()

    def get_document(self, doc_id: int) -> Optional[sqlite3.Row]:
        assert self.conn
        return self.conn.execute(
            "SELECT * FROM documents WHERE id=?", (doc_id,)
        ).fetchone()

    def get_all_documents(self) -> List[sqlite3.Row]:
        assert self.conn
        return self.conn.execute(
            "SELECT * FROM documents ORDER BY date_added DESC"
        ).fetchall()

    def get_documents_by_tag(self, tag_id: int,
                              include_subtags: bool = True) -> List[sqlite3.Row]:
        """Gibt alle Dokumente zurück, die dem Tag (und optionalen Sub-Tags) zugeordnet sind."""
        assert self.conn
        if include_subtags:
            tag_ids = self._get_tag_subtree(tag_id)
        else:
            tag_ids = [tag_id]
        placeholders = ",".join("?" * len(tag_ids))
        return self.conn.execute(
            f"""SELECT DISTINCT d.* FROM documents d
                JOIN document_tags dt ON dt.doc_id = d.id
                WHERE dt.tag_id IN ({placeholders})
                ORDER BY d.date_added DESC""",
            tag_ids
        ).fetchall()

    def _get_tag_subtree(self, tag_id: int) -> List[int]:
        """Gibt tag_id + alle Kinder-IDs (rekursiv) zurück."""
        assert self.conn
        result = [tag_id]
        children = self.conn.execute(
            "SELECT id FROM tags WHERE parent_id=?", (tag_id,)
        ).fetchall()
        for child in children:
            result.extend(self._get_tag_subtree(child["id"]))
        return result

    # ── Tag-Operationen ────────────────────────────────────────────────────────

    def get_or_create_tag(self, name: str,
                           parent_id: Optional[int] = None) -> int:
        """Gibt vorhandene Tag-ID zurück oder erstellt einen neuen Tag."""
        assert self.conn
        row = self.conn.execute(
            "SELECT id FROM tags WHERE name=? AND parent_id IS ?",
            (name, parent_id)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO tags (name, parent_id) VALUES (?, ?)",
            (name, parent_id)
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    def get_tag_path_ids(self, tag_names: List[str]) -> List[int]:
        """Erstellt/holt eine hierarchische Tag-Kette und gibt alle IDs zurück."""
        ids = []
        parent_id = None
        for name in tag_names:
            tid = self.get_or_create_tag(name, parent_id)
            ids.append(tid)
            parent_id = tid
        return ids

    def assign_tags(self, doc_id: int, tag_ids: List[int]) -> None:
        """Weist einem Dokument Tags zu (ersetzt vorhandene Zuordnungen)."""
        assert self.conn
        self.conn.execute("DELETE FROM document_tags WHERE doc_id=?", (doc_id,))
        for i, tag_id in enumerate(tag_ids):
            self.conn.execute(
                "INSERT OR IGNORE INTO document_tags (doc_id, tag_id, is_primary) VALUES (?, ?, ?)",
                (doc_id, tag_id, 1 if i == len(tag_ids) - 1 else 0)
            )
        self.conn.commit()

    def get_tags_for_document(self, doc_id: int) -> List[sqlite3.Row]:
        assert self.conn
        return self.conn.execute(
            """SELECT t.* FROM tags t
               JOIN document_tags dt ON dt.tag_id = t.id
               WHERE dt.doc_id=? ORDER BY t.name""",
            (doc_id,)
        ).fetchall()

    def get_root_tags(self) -> List[sqlite3.Row]:
        assert self.conn
        return self.conn.execute(
            "SELECT * FROM tags WHERE parent_id IS NULL ORDER BY name"
        ).fetchall()

    def get_child_tags(self, parent_id: int) -> List[sqlite3.Row]:
        assert self.conn
        return self.conn.execute(
            "SELECT * FROM tags WHERE parent_id=? ORDER BY name",
            (parent_id,)
        ).fetchall()

    def delete_tag_if_empty(self, tag_id: int) -> None:
        """Löscht Tag, wenn keine Dokumente und keine Kinder mehr vorhanden."""
        assert self.conn
        doc_count = self.conn.execute(
            "SELECT COUNT(*) FROM document_tags WHERE tag_id=?", (tag_id,)
        ).fetchone()[0]
        child_count = self.conn.execute(
            "SELECT COUNT(*) FROM tags WHERE parent_id=?", (tag_id,)
        ).fetchone()[0]
        if doc_count == 0 and child_count == 0:
            self.conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
            self.conn.commit()

    def get_all_tag_names(self) -> List[str]:
        """Alle Tag-Namen (für Autovervollständigung)."""
        assert self.conn
        rows = self.conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    # ── Volltextsuche ──────────────────────────────────────────────────────────

    def search(self, query: str) -> List[sqlite3.Row]:
        """FTS5 Volltextsuche. Gibt Dokumente sortiert nach Relevanz zurück."""
        assert self.conn
        if not query.strip():
            return self.get_all_documents()
        try:
            return self.conn.execute(
                """SELECT d.* FROM documents d
                   JOIN documents_fts fts ON fts.rowid = d.id
                   WHERE documents_fts MATCH ?
                   ORDER BY rank""",
                (query,)
            ).fetchall()
        except sqlite3.OperationalError:
            # Ungültige FTS5-Syntax → LIKE-Fallback
            like = f"%{query}%"
            return self.conn.execute(
                """SELECT * FROM documents
                   WHERE title LIKE ? OR text_snippet LIKE ?
                   ORDER BY date_added DESC""",
                (like, like)
            ).fetchall()

    def get_document_count(self) -> int:
        assert self.conn
        return self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
