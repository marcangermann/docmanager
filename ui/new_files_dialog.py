"""
DocManager – Dialog für neu gefundene Dateien

Wird beim Programmstart angezeigt, wenn im Dokumenten-Verzeichnisbaum PDFs
liegen, die noch nicht in der Datenbank registriert sind (z.B. manuell
hineinkopiert). Die Dateien werden in-place registriert:
  - Tags aus der Ordnerstruktur
  - Titel/Datum aus dem Dateinamen
  - optional OCR für die Volltextsuche
Die Dateien werden NICHT verschoben oder kopiert.
"""
import html
import re
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QTextEdit, QCheckBox, QTreeWidget, QTreeWidgetItem,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

import config
from core.document_manager import DocumentManager
from database.db import Database


# ── Hintergrund-Worker ────────────────────────────────────────────────────────

class _RegisterWorker(QThread):
    """Registriert eine Liste bereits vorhandener PDFs sequenziell in der DB."""

    progress  = pyqtSignal(int, int, str)   # current, total, filename
    file_done = pyqtSignal(str, bool, str)  # filename, success, message
    finished  = pyqtSignal(int, int)        # success, errors

    def __init__(self, files: List[Path], base_dir: Path, run_ocr: bool):
        super().__init__()
        self._files     = files
        self._base_dir  = base_dir
        self._run_ocr   = run_ocr
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        # Eigene DB-Verbindung im Worker-Thread (thread-sicher mit WAL-Modus)
        db = Database(config.DB_PATH)
        db.connect()
        doc_manager = DocumentManager(db, self._base_dir)

        success = errors = 0
        total = len(self._files)
        try:
            for i, path in enumerate(self._files):
                if self._cancelled:
                    break
                self.progress.emit(i + 1, total, path.name)
                try:
                    doc_manager.register_file(path, run_ocr=self._run_ocr)
                    success += 1
                    self.file_done.emit(path.name, True, "OK")
                except Exception as exc:
                    errors += 1
                    self.file_done.emit(path.name, False, str(exc))
        finally:
            db.close()
        self.finished.emit(success, errors)


# ── Dialog ────────────────────────────────────────────────────────────────────

class NewFilesDialog(QDialog):
    """
    Listet neu im Verzeichnisbaum gefundene PDFs auf und bietet an, sie
    in-place in die Verwaltung aufzunehmen. Tags werden aus der Ordnerstruktur
    abgeleitet, Titel/Datum aus dem Dateinamen.
    """

    def __init__(self, files: List[Path], base_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self._base_dir = base_dir
        self._files    = list(files)
        self._worker: Optional[_RegisterWorker] = None
        self._registered = False

        self.setWindowTitle("Neue Dateien gefunden")
        self.setMinimumSize(720, 520)
        self._build_ui()
        self._populate()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            f"Im Dokumenten-Verzeichnis wurden "
            f"<b>{len(self._files)}</b> Datei(en) gefunden, die noch nicht "
            f"verwaltet werden.<br>Sollen sie aufgenommen werden? "
            f"(Dateien bleiben an ihrem Speicherort.)"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Datei-Liste mit Auswahl-Häkchen
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Datei", "Schlagwörter (Tags)", "Datum"])
        self._tree.setColumnWidth(0, 300)
        self._tree.setColumnWidth(1, 230)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(False)
        layout.addWidget(self._tree, 1)

        # Auswahl-Schnellzugriff + Optionen
        sel_row = QHBoxLayout()
        all_btn = QPushButton("Alle")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn = QPushButton("Keine")
        none_btn.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        self._ocr_cb = QCheckBox(
            "OCR durchführen – Text für Volltextsuche extrahieren (kann langsam sein)"
        )
        self._ocr_cb.setChecked(True)
        sel_row.addWidget(self._ocr_cb)
        layout.addLayout(sel_row)

        # Fortschritt + Protokoll
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setVisible(False)
        layout.addWidget(self._log)

        # Schaltflächen
        btn_row = QHBoxLayout()
        self._import_btn = QPushButton("Aufnehmen")
        self._import_btn.clicked.connect(self._start)
        self._close_btn = QPushButton("Später")
        self._close_btn.clicked.connect(self._on_close)
        btn_row.addStretch()
        btn_row.addWidget(self._import_btn)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

    def _populate(self) -> None:
        for path in self._files:
            rel = path.parent.relative_to(self._base_dir)
            tag_label = " / ".join(rel.parts) if rel.parts else "(Hauptverzeichnis)"
            stem = path.stem
            m = re.match(r'^(\d{4}-\d{2}-\d{2})[_\s](.*)', stem)
            date_str = m.group(1) if m else ""
            item = QTreeWidgetItem([path.name, tag_label, date_str])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            item.setForeground(1, QColor("#0055aa"))
            self._tree.addTopLevelItem(item)

    # ── Auswahl-Helfer ────────────────────────────────────────────────────────

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, state)

    def _selected_paths(self) -> List[Path]:
        paths: List[Path] = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                paths.append(item.data(0, Qt.ItemDataRole.UserRole))
        return paths

    # ── Ablauf ────────────────────────────────────────────────────────────────

    def _start(self) -> None:
        paths = self._selected_paths()
        if not paths:
            self.reject()
            return

        self._import_btn.setEnabled(False)
        self._tree.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(paths))
        self._progress.setValue(0)
        self._log.setVisible(True)

        self._worker = _RegisterWorker(
            files=paths,
            base_dir=self._base_dir,
            run_ocr=self._ocr_cb.isChecked(),
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
            self._log.append(
                '<span style="color:#007700">'
                '&nbsp;&nbsp;&#10003;&nbsp;OK</span>'
            )
        else:
            self._log.append(
                f'<span style="color:#cc0000">'
                f'&nbsp;&nbsp;&#10007;&nbsp;Fehler: {html.escape(msg)}'
                f'</span>'
            )

    def _on_finished(self, success: int, errors: int) -> None:
        self._registered = success > 0
        color = "#0033cc" if errors == 0 else "#cc0000"
        self._log.append(
            f'<br><span style="color:{color}"><b>'
            f'Fertig: {success} aufgenommen, {errors} Fehler'
            f'</b></span>'
        )
        self._close_btn.setText("Schließen")
        self._worker = None

    # ── Schließen ─────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        if self._registered:
            self.accept()
        else:
            self.reject()

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
        event.accept()
