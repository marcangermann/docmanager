"""
DocManager - Hauptfenster

3-Panel-Layout:
  Links  : TagTree (Kategorien)
  Mitte  : DocumentList
  Rechts : PreviewPanel
"""
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QToolBar, QStatusBar, QLineEdit,
    QFileDialog, QMessageBox, QDialog, QLabel
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QProgressDialog

import config
from database.db import Database
from core.document_manager import DocumentManager
from ui.tag_tree import TagTree
from ui.document_list import DocumentList
from ui.preview_panel import PreviewPanel
from ui.import_dialog import ImportDialog
from ui.scanner_dialog import ScannerDialog
from ui.directory_import_dialog import DirectoryImportDialog


class _ReindexWorker(QThread):
    """Extrahiert Text für alle Dokumente ohne Textinhalt und aktualisiert die DB."""
    progress = pyqtSignal(int, int, str)   # current, total, title
    finished = pyqtSignal(int, int)        # updated, skipped

    def run(self) -> None:
        import config as _cfg
        from database.db import Database as _DB
        from core.ocr_engine import extract_and_suggest

        db = _DB(_cfg.DB_PATH)
        db.connect()
        rows = db.conn.execute(
            "SELECT id, path, title FROM documents "
            "WHERE text_content = '' OR text_content IS NULL"
        ).fetchall()

        total = len(rows)
        updated = skipped = 0
        for i, row in enumerate(rows):
            self.progress.emit(i + 1, total, row["title"])
            p = Path(row["path"])
            if not p.exists():
                import sys
                print(f"[reindex] Datei nicht gefunden: {p}", file=sys.stderr)
                skipped += 1
                continue
            try:
                text, _, _ = extract_and_suggest(p)
                # Auch leere OCR-Ergebnisse speichern (verhindert erneute
                # Verarbeitung und markiert Dokument als "OCR abgeschlossen")
                snippet = text[:500] if text.strip() else " "
                db.conn.execute(
                    "UPDATE documents SET text_content=? WHERE id=?",
                    (snippet, row["id"])
                )
                db.conn.commit()
                updated += 1
            except Exception as exc:
                import sys
                print(f"[reindex] Fehler bei '{row['title']}': {exc}",
                      file=sys.stderr)
                skipped += 1
        db.close()
        self.finished.emit(updated, skipped)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Einstellungen laden
        settings = config.load_settings()
        self._base_dir = Path(settings["base_dir"])

        # DB + Manager initialisieren
        self._db = Database(config.DB_PATH)
        self._db.connect()
        self._doc_manager = DocumentManager(self._db, self._base_dir)

        # Zustand
        self._current_tag_id: Optional[int] = None
        self._current_doc_id: Optional[int] = None
        self._search_query: str = ""

        self.setWindowTitle("DocManager")
        self.resize(1100, 700)

        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._reload_all()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Linkes Panel: Tag-Baum
        self._tag_tree = TagTree(self._db)
        self._tag_tree.tag_selected.connect(self._on_tag_selected)
        splitter.addWidget(self._tag_tree)

        # Mittleres Panel: Dokumenten-Liste
        self._doc_list = DocumentList(self._db)
        self._doc_list.document_selected.connect(self._on_doc_selected)
        self._doc_list.document_activated.connect(self._open_externally)
        self._doc_list.document_deleted.connect(self._delete_document)
        splitter.addWidget(self._doc_list)

        # Rechtes Panel: Vorschau
        self._preview = PreviewPanel()
        splitter.addWidget(self._preview)

        splitter.setSizes([200, 340, 560])
        layout.addWidget(splitter)

    def _setup_toolbar(self) -> None:
        tb = QToolBar("Werkzeuge")
        tb.setMovable(False)
        self.addToolBar(tb)

        # Import (Einzeldatei)
        act_import = QAction("Importieren", self)
        act_import.setShortcut(QKeySequence("Ctrl+O"))
        act_import.triggered.connect(self._import_file)
        tb.addAction(act_import)

        # Verzeichnis-Import
        act_dir_import = QAction("Ordner importieren", self)
        act_dir_import.setShortcut(QKeySequence("Ctrl+Shift+O"))
        act_dir_import.triggered.connect(self._import_directory)
        tb.addAction(act_dir_import)

        # Scannen
        act_scan = QAction("Scannen", self)
        act_scan.triggered.connect(self._scan_document)
        tb.addAction(act_scan)

        # Texte neu indizieren
        act_reindex = QAction("Texte indizieren", self)
        act_reindex.setToolTip(
            "Text aller Dokumente ohne Indexinhalt neu extrahieren (OCR)"
        )
        act_reindex.triggered.connect(self._reindex_documents)
        tb.addAction(act_reindex)

        tb.addSeparator()

        # Einstellungen
        act_settings = QAction("Einstellungen", self)
        act_settings.triggered.connect(self._show_settings)
        tb.addAction(act_settings)

        tb.addSeparator()

        # Suchfeld
        tb.addWidget(QLabel("  Suche: "))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Volltextsuche …")
        self._search_edit.setMinimumWidth(220)
        self._search_edit.setClearButtonEnabled(True)
        self._search_debounce = QTimer()
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(self._do_search)
        self._search_edit.textChanged.connect(
            lambda: self._search_debounce.start()
        )
        tb.addWidget(self._search_edit)

    def _setup_statusbar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status_label = QLabel()
        self._status.addWidget(self._status_label)

    # ── Lade-Logik ────────────────────────────────────────────────────────────

    def _reload_all(self) -> None:
        self._tag_tree.reload()
        self._refresh_doc_list()

    def _refresh_doc_list(self) -> None:
        query = self._search_query.strip()
        if query:
            docs = self._db.search(query)
        elif self._current_tag_id is not None:
            docs = self._db.get_documents_by_tag(self._current_tag_id)
        else:
            docs = self._db.get_all_documents()
        self._doc_list.load_documents(docs)
        total = self._db.get_document_count()
        shown = len(docs)
        self._status_label.setText(
            f"{total} Dokument(e) gesamt  |  {shown} angezeigt"
        )

    # ── Signal-Handler ────────────────────────────────────────────────────────

    @pyqtSlot(object)
    def _on_tag_selected(self, tag_id) -> None:
        self._current_tag_id = tag_id
        self._search_edit.clear()
        self._search_query = ""
        self._refresh_doc_list()

    @pyqtSlot(int)
    def _on_doc_selected(self, doc_id: int) -> None:
        self._current_doc_id = doc_id
        row = self._db.get_document(doc_id)
        if row:
            path = Path(row["path"])
            if path.exists() and path.suffix.lower() == ".pdf":
                self._preview.load_document(path)
                self._status_label.setText(
                    f"{self._db.get_document_count()} Dok. gesamt  |  "
                    f"Ausgewählt: {row['title']}"
                )
            else:
                self._preview.clear()

    def _do_search(self) -> None:
        self._search_query = self._search_edit.text()
        self._current_tag_id = None
        self._refresh_doc_list()

    # ── Aktionen ──────────────────────────────────────────────────────────────

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Dokument importieren",
            str(Path.home()),
            "PDF & Bilder (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)"
        )
        if not path:
            return
        self._run_import_dialog(Path(path))

    def _scan_document(self) -> None:
        dlg = ScannerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pdf_path = dlg.get_pdf_path()
            if pdf_path:
                self._run_import_dialog(pdf_path)

    def _run_import_dialog(self, file_path: Path) -> None:
        dlg = ImportDialog(file_path, self._db, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            title, tag_path, date_str = dlg.get_import_data()
            try:
                doc_id = self._doc_manager.import_document(
                    source_path=file_path,
                    title=title,
                    tag_path=tag_path,
                    date_str=date_str or None,
                    copy=True,
                )
                self._reload_all()
                self._status_label.setText(f"Importiert: {title}")
            except Exception as e:
                QMessageBox.critical(self, "Import-Fehler", str(e))

    def _import_directory(self) -> None:
        dlg = DirectoryImportDialog(self._db, self._doc_manager, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._reload_all()

    def _reindex_documents(self) -> None:
        """Startet OCR/Text-Extraktion für alle Dokumente ohne Textinhalt."""
        pending = self._db.conn.execute(
            "SELECT count(*) FROM documents "
            "WHERE text_content = '' OR text_content IS NULL"
        ).fetchone()[0]

        if pending == 0:
            QMessageBox.information(
                self, "Texte indizieren",
                "Alle Dokumente sind bereits indiziert."
            )
            return

        reply = QMessageBox.question(
            self, "Texte indizieren",
            f"{pending} Dokument(e) ohne Textinhalt gefunden.\n"
            "Text extrahieren und Volltextindex aufbauen?\n\n"
            "(Kann je nach Anzahl und Dokumentgröße mehrere Minuten dauern.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._reindex_progress = QProgressDialog(
            "Texte werden extrahiert …", "Abbrechen", 0, pending, self
        )
        self._reindex_progress.setWindowTitle("Texte indizieren")
        self._reindex_progress.setMinimumDuration(0)
        self._reindex_progress.setModal(True)

        self._reindex_worker = _ReindexWorker()
        self._reindex_worker.progress.connect(self._on_reindex_progress)
        self._reindex_worker.finished.connect(self._on_reindex_finished)
        self._reindex_progress.canceled.connect(self._reindex_worker.terminate)
        self._reindex_worker.start()

    def _on_reindex_progress(self, current: int, total: int, title: str) -> None:
        self._reindex_progress.setMaximum(total)
        self._reindex_progress.setValue(current)
        self._reindex_progress.setLabelText(
            f"[{current}/{total}] {title}"
        )

    def _on_reindex_finished(self, updated: int, skipped: int) -> None:
        self._reindex_progress.close()
        self._reload_all()
        QMessageBox.information(
            self, "Texte indizieren",
            f"Fertig: {updated} Dokument(e) indiziert"
            + (f", {skipped} übersprungen." if skipped else ".")
        )

    def _open_externally(self, doc_id: int) -> None:
        row = self._db.get_document(doc_id)
        if row:
            path = Path(row["path"])
            if path.exists():
                subprocess.Popen(["xdg-open", str(path)])
            else:
                QMessageBox.warning(
                    self, "Datei nicht gefunden",
                    f"Die Datei wurde nicht gefunden:\n{path}"
                )

    def _delete_document(self, doc_id: int) -> None:
        try:
            self._doc_manager.delete_document(doc_id, delete_file=True)
            self._preview.clear()
            self._reload_all()
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Löschen", str(e))

    def _show_settings(self) -> None:
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            settings = config.load_settings()
            self._base_dir = Path(settings["base_dir"])
            self._doc_manager.base_dir = self._base_dir
            self._reload_all()

    # ── Aufräumen ─────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._db.close()
        event.accept()
