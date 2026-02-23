"""
DocManager - Import-Dialog

Zeigt:
- Miniatur-Vorschau der zu importierenden Datei
- Titelfeld (vorausgefüllt aus Dateiname)
- Erkanntes Datum
- OCR-Vorschläge als anklickbare Chips
- Hierarchische Tag-Eingabe (Pfad wie "Finanzen/Steuern")
"""
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QDialogButtonBox,
    QScrollArea, QWidget, QGroupBox, QCheckBox,
    QSplitter, QTextEdit, QCompleter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStringListModel
from PyQt6.QtGui import QPixmap, QFont

from core.pdf_utils import render_page_to_pixmap
from core.ocr_engine import extract_and_suggest
from database.db import Database


# ── Worker für OCR im Hintergrund ────────────────────────────────────────────

class OcrWorker(QThread):
    finished = pyqtSignal(str, list, str)  # text, keywords, date

    def __init__(self, file_path: Path, force_ocr: bool = False):
        super().__init__()
        self.file_path = file_path
        self.force_ocr = force_ocr

    def run(self):
        text, keywords, date = extract_and_suggest(
            self.file_path, force_ocr=self.force_ocr
        )
        self.finished.emit(text, keywords, date)


# ── Keyword-Chip ──────────────────────────────────────────────────────────────

class KeywordChip(QPushButton):
    def __init__(self, word: str, parent=None):
        super().__init__(word, parent)
        self.setCheckable(True)
        self.setStyleSheet(
            "QPushButton { border: 1px solid palette(mid); border-radius: 10px;"
            " padding: 2px 8px; font-size: 11px; }"
            "QPushButton:checked { background: palette(highlight);"
            " color: palette(highlighted-text); border-color: palette(highlight); }"
        )


# ── Import-Dialog ─────────────────────────────────────────────────────────────

class ImportDialog(QDialog):
    def __init__(self, file_path: Path, db: Database, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.db = db
        self._ocr_worker: Optional[OcrWorker] = None
        self._keyword_chips: List[KeywordChip] = []

        self.setWindowTitle("Dokument importieren")
        self.resize(750, 550)
        self._setup_ui()
        self._prefill()
        self._start_ocr()

    # ── UI-Aufbau ─────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer = QHBoxLayout(self)

        # Linke Seite: Vorschau
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._preview_label.setMinimumWidth(200)
        self._preview_label.setMaximumWidth(250)
        self._preview_label.setStyleSheet("background: #888; border: 1px solid palette(mid);")
        outer.addWidget(self._preview_label)

        # Rechte Seite: Felder
        right = QVBoxLayout()
        outer.addLayout(right, 1)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._title_edit = QLineEdit()
        form.addRow("Titel:", self._title_edit)

        self._date_edit = QLineEdit()
        self._date_edit.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Datum:", self._date_edit)

        # Tag-Pfad
        self._tag_edit = QLineEdit()
        self._tag_edit.setPlaceholderText("Finanzen/Steuern  oder  Medizin")
        # Autovervollständigung
        all_tags = self.db.get_all_tag_names()
        completer = QCompleter(all_tags, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._tag_edit.setCompleter(completer)
        form.addRow("Kategorie-Pfad:", self._tag_edit)

        right.addLayout(form)

        # OCR-Status
        self._ocr_status = QLabel("OCR läuft …")
        self._ocr_status.setStyleSheet("color: gray; font-size: 11px;")
        right.addWidget(self._ocr_status)

        # Keyword-Chips
        kw_group = QGroupBox("Keyword-Vorschläge (klicken zum Auswählen als Tags)")
        kw_layout = QVBoxLayout(kw_group)
        self._chips_area = QWidget()
        self._chips_layout = _FlowLayout(self._chips_area)
        self._chips_area.setLayout(self._chips_layout)
        scroll = QScrollArea()
        scroll.setWidget(self._chips_area)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(110)
        kw_layout.addWidget(scroll)
        right.addWidget(kw_group)

        # Manuelle Tag-Eingabe via Chips → Button
        add_chip_row = QHBoxLayout()
        self._chip_input = QLineEdit()
        self._chip_input.setPlaceholderText("Eigenes Schlagwort eingeben …")
        self._chip_input.returnPressed.connect(self._add_manual_chip)
        btn_add = QPushButton("Hinzufügen")
        btn_add.clicked.connect(self._add_manual_chip)
        add_chip_row.addWidget(self._chip_input)
        add_chip_row.addWidget(btn_add)
        right.addLayout(add_chip_row)

        # OCR-Checkbox
        self._ocr_cb = QCheckBox("OCR erzwingen (auch bei Text-PDFs)")
        self._ocr_cb.stateChanged.connect(self._restart_ocr)
        right.addWidget(self._ocr_cb)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addStretch()
        right.addWidget(buttons)

    # ── Vorausfüllen ──────────────────────────────────────────────────────────

    def _prefill(self) -> None:
        import re
        from datetime import datetime
        stem = self.file_path.stem
        # Datum aus Dateiname extrahieren
        m = re.match(r'^(\d{4}-\d{2}-\d{2})_(.*)', stem)
        if m:
            self._date_edit.setText(m.group(1))
            self._title_edit.setText(m.group(2).replace("_", " "))
        else:
            self._title_edit.setText(stem.replace("_", " "))
            self._date_edit.setText(datetime.now().strftime("%Y-%m-%d"))

        # Vorschau
        pixmap = render_page_to_pixmap(self.file_path, 0, zoom=1.2)
        if pixmap:
            scaled = pixmap.scaledToWidth(
                230, Qt.TransformationMode.SmoothTransformation
            )
            self._preview_label.setPixmap(scaled)
        else:
            self._preview_label.setText("Keine Vorschau")

    # ── OCR ───────────────────────────────────────────────────────────────────

    def _start_ocr(self) -> None:
        if self._ocr_worker and self._ocr_worker.isRunning():
            self._ocr_worker.quit()
        self._ocr_worker = OcrWorker(
            self.file_path, self._ocr_cb.isChecked()
        )
        self._ocr_worker.finished.connect(self._on_ocr_done)
        self._ocr_worker.start()
        self._ocr_status.setText("OCR läuft …")

    def _restart_ocr(self) -> None:
        self._start_ocr()

    def _on_ocr_done(self, text: str, keywords: List[str], date: str) -> None:
        self._ocr_status.setText(
            f"OCR abgeschlossen ({len(text)} Zeichen erkannt)"
        )
        if date and not self._date_edit.text():
            self._date_edit.setText(date)
        elif date:
            # Nur setzen wenn Feld noch leer
            pass
        self._populate_chips(keywords)

    def _populate_chips(self, keywords: List[str]) -> None:
        # Bestehende Chips entfernen
        for chip in self._keyword_chips:
            self._chips_layout.removeWidget(chip)
            chip.deleteLater()
        self._keyword_chips = []

        for kw in keywords:
            chip = KeywordChip(kw)
            self._chips_layout.addWidget(chip)
            self._keyword_chips.append(chip)
        self._chips_area.adjustSize()

    def _add_manual_chip(self) -> None:
        word = self._chip_input.text().strip()
        if not word:
            return
        chip = KeywordChip(word)
        chip.setChecked(True)
        self._chips_layout.addWidget(chip)
        self._keyword_chips.append(chip)
        self._chip_input.clear()
        self._chips_area.adjustSize()

    # ── Ergebnis abfragen ─────────────────────────────────────────────────────

    def get_import_data(self) -> Tuple[str, List[str], str]:
        """
        Rückgabe: (title, tag_path_list, date_str)
        tag_path_list kommt aus dem Tag-Pfad-Feld + ausgewählten Chips.
        """
        title = self._title_edit.text().strip() or self.file_path.stem
        date_str = self._date_edit.text().strip()

        # Tag-Pfad aus Eingabefeld
        raw = self._tag_edit.text().strip()
        if raw:
            tag_path = [t.strip() for t in raw.replace("\\", "/").split("/")
                        if t.strip()]
        else:
            tag_path = []

        # Ausgewählte Chips als zusätzliche Tags (ohne Hierarchie, flach)
        selected_chips = [c.text() for c in self._keyword_chips if c.isChecked()]
        # Chips ergänzen nur wenn kein Pfad angegeben
        if not tag_path and selected_chips:
            tag_path = selected_chips

        return title, tag_path, date_str


# ── Einfaches Flow-Layout ─────────────────────────────────────────────────────

class _FlowLayout(QHBoxLayout):
    """Minimales horizontales Layout für Chips (ohne echtes Wrapping)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(4, 4, 4, 4)
        self.setSpacing(4)
        self.addStretch()
