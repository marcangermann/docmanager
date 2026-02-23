"""
DocManager - Dokumenten-Liste (mittleres Panel)

Zeigt Dokumente als Liste mit Titel, Datum und Tags.
Sendet Signale bei Auswahl und Doppelklick.
"""
from typing import List, Optional
import sqlite3

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QListWidget,
                              QListWidgetItem, QLabel, QMenu, QMessageBox)
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QFont, QColor

from database.db import Database


class DocumentList(QWidget):
    # Signale
    document_selected = pyqtSignal(int)   # doc_id
    document_activated = pyqtSignal(int)  # doc_id (Doppelklick → extern öffnen)
    document_deleted = pyqtSignal(int)    # doc_id

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._doc_ids: List[int] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._count_label = QLabel("0 Dokumente")
        self._count_label.setStyleSheet(
            "padding: 4px 8px; background: palette(mid); font-size: 11px;"
        )
        layout.addWidget(self._count_label)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSpacing(2)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._list)

    def load_documents(self, docs: List[sqlite3.Row]) -> None:
        """Füllt die Liste mit den gegebenen Dokumenten."""
        self._list.clear()
        self._doc_ids = []
        for doc in docs:
            item = self._make_item(doc)
            self._list.addItem(item)
            self._doc_ids.append(doc["id"])
        count = len(docs)
        self._count_label.setText(
            f"{count} Dokument{'e' if count != 1 else ''}"
        )

    def _make_item(self, doc: sqlite3.Row) -> QListWidgetItem:
        date_str = doc["date_doc"] or doc["date_added"][:10]
        size_kb = (doc["file_size"] or 0) // 1024
        pages = doc["page_count"] or 0
        display = f"{doc['title']}\n{date_str}  ·  {pages} S.  ·  {size_kb} KB"
        item = QListWidgetItem(display)
        item.setSizeHint(QSize(0, 52))
        return item

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._doc_ids):
            self.document_selected.emit(self._doc_ids[row])

    def _on_double_click(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._doc_ids):
            self.document_activated.emit(self._doc_ids[row])

    def current_doc_id(self) -> Optional[int]:
        row = self._list.currentRow()
        if 0 <= row < len(self._doc_ids):
            return self._doc_ids[row]
        return None

    def _show_context_menu(self, pos) -> None:
        doc_id = self.current_doc_id()
        if doc_id is None:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Extern öffnen")
        show_action = menu.addAction("Im Dateimanager anzeigen")
        menu.addSeparator()
        delete_action = menu.addAction("Löschen...")

        action = menu.exec(self._list.mapToGlobal(pos))
        if action == open_action:
            self.document_activated.emit(doc_id)
        elif action == show_action:
            self._show_in_filemanager(doc_id)
        elif action == delete_action:
            self._confirm_delete(doc_id)

    def _show_in_filemanager(self, doc_id: int) -> None:
        row = self.db.get_document(doc_id)
        if row:
            import subprocess
            from pathlib import Path
            path = Path(row["path"])
            if path.exists():
                subprocess.Popen(["xdg-open", str(path.parent)])

    def _confirm_delete(self, doc_id: int) -> None:
        row = self.db.get_document(doc_id)
        if not row:
            return
        reply = QMessageBox.question(
            self, "Dokument löschen",
            f"'{row['title']}' wirklich löschen?\n\n"
            "Die Datei wird vom Dateisystem entfernt.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.document_deleted.emit(doc_id)
