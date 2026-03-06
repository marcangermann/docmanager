"""
DocManager – Verzeichnis-Import-Dialog

Importiert einen bestehenden Verzeichnisbaum:
  - Unterordner werden als hierarchische Schlagwörter (Tags) verwendet
  - OCR optional für Volltextindizierung
  - Hintergrund-Worker (QThread), damit die GUI reaktiv bleibt
"""
import html
import re
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QGroupBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

import config
from core.document_manager import DocumentManager, build_target_path
from core.ocr_engine import extract_and_suggest
from database.db import Database

SUPPORTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'}


# ── Hintergrund-Worker ────────────────────────────────────────────────────────

class _ImportWorker(QThread):
    """Importiert Dateien einer Liste sequenziell im Hintergrund."""

    progress  = pyqtSignal(int, int, str)   # current, total, filename
    file_done = pyqtSignal(str, bool, str)  # filename, success, message
    finished  = pyqtSignal(int, int, int)   # success, skipped, errors

    def __init__(self, files: list, base_dir: Path,
                 run_ocr: bool, copy_files: bool, skip_existing: bool):
        super().__init__()
        # files: list of (source_path, title, tag_path, date_str)
        self._files         = files
        self._base_dir      = base_dir
        self._run_ocr       = run_ocr
        self._copy_files    = copy_files
        self._skip_existing = skip_existing
        self._cancelled     = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        # Eigene DB-Verbindung im Worker-Thread (thread-sicher mit WAL-Modus)
        db = Database(config.DB_PATH)
        db.connect()
        doc_manager = DocumentManager(db, self._base_dir)

        success = skipped = errors = 0
        total = len(self._files)

        try:
            for i, (source_path, title, tag_path, date_str) in enumerate(self._files):
                if self._cancelled:
                    break

                self.progress.emit(i + 1, total, source_path.name)

                # Bereits-vorhanden-Prüfung anhand des berechneten Zielpfads
                if self._skip_existing:
                    suffix = source_path.suffix.lower()
                    target = build_target_path(
                        self._base_dir, tag_path, title, date_str, suffix
                    )
                    if target.exists():
                        skipped += 1
                        self.file_done.emit(
                            source_path.name, True,
                            "Übersprungen (Zieldatei bereits vorhanden)"
                        )
                        continue

                try:
                    full_text = ""
                    if self._run_ocr:
                        text, _, _ = extract_and_suggest(source_path)
                        full_text = text

                    doc_manager.import_document(
                        source_path=source_path,
                        title=title,
                        tag_path=tag_path,
                        date_str=date_str or None,
                        full_text=full_text,
                        copy=self._copy_files,
                    )
                    success += 1
                    self.file_done.emit(source_path.name, True, "OK")

                except Exception as exc:
                    errors += 1
                    self.file_done.emit(source_path.name, False, str(exc))

        finally:
            db.close()

        self.finished.emit(success, skipped, errors)


# ── Hilfsfunktion ─────────────────────────────────────────────────────────────

def _parse_filename(filename: str) -> tuple[str, str]:
    """
    Extrahiert Titel und Datum aus Dateinamen der Form YYYY-MM-DD_titel.ext.
    Gibt (title, date_str) zurück; date_str ist "" wenn kein Datum gefunden.
    """
    stem = Path(filename).stem
    m = re.match(r'^(\d{4}-\d{2}-\d{2})[_\s](.*)', stem)
    if m:
        return m.group(2).replace("_", " "), m.group(1)
    return stem.replace("_", " "), ""


# ── Dialog ────────────────────────────────────────────────────────────────────

class DirectoryImportDialog(QDialog):
    """
    Dialog zum Importieren eines bestehenden Verzeichnisbaums.

    Unterordner des gewählten Quellverzeichnisses werden als hierarchische
    Schlagwörter (Tags) verwendet. Jede Datei wird per import_document()
    in den DocManager-Bestand übernommen und für die Volltextsuche indiziert.
    """

    def __init__(self, db: Database, doc_manager: DocumentManager,
                 parent=None) -> None:
        super().__init__(parent)
        self._db          = db
        self._doc_manager = doc_manager
        self._files: list = []           # (source_path, title, tag_path, date_str)
        self._worker: Optional[_ImportWorker] = None
        self._import_started = False

        self.setWindowTitle("Verzeichnis importieren")
        self.setMinimumSize(740, 560)
        self._build_ui()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Quellverzeichnis
        dir_box = QGroupBox("Quellverzeichnis")
        dir_row = QHBoxLayout(dir_box)
        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText("Verzeichnis wählen …")
        self._dir_edit.textChanged.connect(self._on_dir_changed)
        browse_btn = QPushButton("Durchsuchen …")
        browse_btn.clicked.connect(self._browse)
        dir_row.addWidget(self._dir_edit)
        dir_row.addWidget(browse_btn)
        layout.addWidget(dir_box)

        # Optionen
        opt_box = QGroupBox("Optionen")
        opt_col = QVBoxLayout(opt_box)
        self._copy_cb = QCheckBox(
            "Dateien kopieren (Original bleibt im Quellverzeichnis erhalten)"
        )
        self._copy_cb.setChecked(True)
        self._ocr_cb = QCheckBox(
            "OCR durchführen – Text für Volltextsuche extrahieren (kann langsam sein)"
        )
        self._ocr_cb.setChecked(True)
        self._skip_cb = QCheckBox(
            "Dateien überspringen, die bereits im Zielordner vorhanden sind"
        )
        self._skip_cb.setChecked(True)
        opt_col.addWidget(self._copy_cb)
        opt_col.addWidget(self._ocr_cb)
        opt_col.addWidget(self._skip_cb)
        layout.addWidget(opt_box)

        # Vorschau-Baum
        self._preview_box = QGroupBox("Vorschau – 0 Dateien gefunden")
        prev_layout = QVBoxLayout(self._preview_box)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Schlagwörter (Tags)", "Typ"])
        self._tree.setColumnWidth(0, 270)
        self._tree.setColumnWidth(1, 230)
        self._tree.setAlternatingRowColors(True)
        prev_layout.addWidget(self._tree)
        layout.addWidget(self._preview_box, 1)

        # Fortschrittsbalken
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Protokoll-Bereich
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setVisible(False)
        layout.addWidget(self._log)

        # Schaltflächen
        btn_row = QHBoxLayout()
        self._import_btn = QPushButton("Importieren")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._start_import)
        self._close_btn = QPushButton("Abbrechen")
        self._close_btn.clicked.connect(self._on_close)
        btn_row.addStretch()
        btn_row.addWidget(self._import_btn)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

    # ── Verzeichnis scannen ───────────────────────────────────────────────────

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Quellverzeichnis wählen", str(Path.home())
        )
        if path:
            self._dir_edit.setText(path)

    def _on_dir_changed(self, text: str) -> None:
        p = Path(text.strip())
        if p.is_dir():
            self._scan(p)
        else:
            self._files.clear()
            self._tree.clear()
            self._preview_box.setTitle("Vorschau – 0 Dateien gefunden")
            self._import_btn.setEnabled(False)

    def _scan(self, base: Path) -> None:
        """Durchsucht das Verzeichnis und baut den Vorschau-Baum auf."""
        self._files.clear()
        self._tree.clear()

        # Verzeichnis-Knoten merken, um Duplikate zu vermeiden
        dir_nodes: dict[str, QTreeWidgetItem] = {}

        for file_path in sorted(base.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            rel       = file_path.relative_to(base)
            dir_parts = list(rel.parts)[:-1]   # Verzeichniskomponenten → Tags
            tag_path  = dir_parts
            title, date_str = _parse_filename(file_path.name)

            self._files.append((file_path, title, tag_path, date_str))

            # Verzeichnis-Knoten im Baum anlegen (wiederverwendend)
            parent_item: Optional[QTreeWidgetItem] = None
            for depth, part in enumerate(dir_parts):
                key = "/".join(dir_parts[: depth + 1])
                if key not in dir_nodes:
                    node = QTreeWidgetItem([part, "", "Ordner"])
                    node.setForeground(0, QColor("#555555"))
                    node.setForeground(2, QColor("#888888"))
                    if parent_item is None:
                        self._tree.addTopLevelItem(node)
                    else:
                        parent_item.addChild(node)
                    dir_nodes[key] = node
                parent_item = dir_nodes[key]

            # Datei-Blattknoten
            tag_label = " / ".join(tag_path) if tag_path else "(Hauptverzeichnis)"
            ext       = file_path.suffix.upper().lstrip(".")
            leaf      = QTreeWidgetItem([file_path.name, tag_label, ext])
            leaf.setForeground(1, QColor("#0055aa"))

            if parent_item is None:
                self._tree.addTopLevelItem(leaf)
            else:
                parent_item.addChild(leaf)

        self._tree.expandAll()
        n = len(self._files)
        self._preview_box.setTitle(f"Vorschau – {n} Datei(en) gefunden")
        self._import_btn.setEnabled(n > 0)

    # ── Import-Ablauf ─────────────────────────────────────────────────────────

    def _start_import(self) -> None:
        if not self._files:
            return

        self._import_started = True
        self._import_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._files))
        self._progress.setValue(0)
        self._log.setVisible(True)

        settings = config.load_settings()
        base_dir = Path(settings["base_dir"])

        self._worker = _ImportWorker(
            files=list(self._files),
            base_dir=base_dir,
            run_ocr=self._ocr_cb.isChecked(),
            copy_files=self._copy_cb.isChecked(),
            skip_existing=self._skip_cb.isChecked(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, current: int, total: int, name: str) -> None:
        self._progress.setValue(current)
        self._log.append(
            f'<span style="color:#333333">'
            f'[{current}/{total}]&nbsp;{html.escape(name)}'
            f'</span>'
        )

    def _on_file_done(self, name: str, ok: bool, msg: str) -> None:
        if ok:
            color = "#007700" if msg == "OK" else "#996600"
            self._log.append(
                f'<span style="color:{color}">'
                f'&nbsp;&nbsp;&#10003;&nbsp;{html.escape(msg)}'
                f'</span>'
            )
        else:
            self._log.append(
                f'<span style="color:#cc0000">'
                f'&nbsp;&nbsp;&#10007;&nbsp;Fehler: {html.escape(msg)}'
                f'</span>'
            )

    def _on_finished(self, success: int, skipped: int, errors: int) -> None:
        color = "#0033cc" if errors == 0 else "#cc0000"
        self._log.append(
            f'<br><span style="color:{color}"><b>'
            f'Fertig: {success} importiert, '
            f'{skipped} übersprungen, '
            f'{errors} Fehler'
            f'</b></span>'
        )
        self._close_btn.setText("Schließen")
        self._worker = None

    # ── Schließen ─────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        # accept() signalisiert dem Hauptfenster, die Ansicht zu aktualisieren
        if self._import_started:
            self.accept()
        else:
            self.reject()
