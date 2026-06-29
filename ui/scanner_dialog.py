"""
DocManager - Scanner-Dialog

Ermöglicht die Auswahl des Scanners, Quelle (Flatbed/ADF), DPI, Farbmodus
und Papierformat. Unterstützt mehrseitiges Scannen, Seiten anhängen und
manuellen Duplex (Rückseiten verschachteln).
"""
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QSpinBox, QLabel, QPushButton,
    QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

import config
from core.scanner import (
    list_scanners, get_scanner_sources, scan_to_pdf,
    append_pdfs, interleave_pdfs,
)


# ── Hilfsfunktion ─────────────────────────────────────────────────────────────

def _pdf_page_count(path: Path) -> int:
    try:
        import fitz
        return fitz.open(str(path)).page_count
    except Exception:
        return 0


# ── Scan-Worker ───────────────────────────────────────────────────────────────

class ScanWorker(QThread):
    finished = pyqtSignal(object)  # Path oder None

    def __init__(self, device: str, dpi: int, mode: str,
                 source: Optional[str], paper: Optional[str],
                 output_path: Optional[Path] = None):
        super().__init__()
        self.device = device
        self.dpi = dpi
        self.mode = mode
        self.source = source
        self.paper = paper
        self.output_path = output_path

    def run(self):
        result = scan_to_pdf(self.device, self.dpi, self.mode,
                             self.source, self.paper, self.output_path)
        self.finished.emit(result)


class _SourcesWorker(QThread):
    """Fragt die Quellen eines Geräts ab (scanimage --help) abseits des GUI-Threads."""
    done = pyqtSignal(str, list)  # device, sources

    def __init__(self, device: str):
        super().__init__()
        self.device = device

    def run(self):
        self.done.emit(self.device, get_scanner_sources(self.device))


# ── Scanner-Dialog ────────────────────────────────────────────────────────────

class ScannerDialog(QDialog):
    # Klassenvar.: Scanner-Cache (bleibt über Dialog-Instanzen erhalten)
    _scanner_cache: Optional[List[Tuple[str, str]]] = None
    # Klassenvar.: Quellen je Gerät zwischenspeichern (vermeidet erneutes --help)
    _sources_cache: dict = {}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dokument scannen")
        self.setMinimumWidth(420)
        self._result_path: Optional[Path] = None
        self._worker: Optional[ScanWorker] = None
        self._src_workers: list = []   # laufende Quellen-Worker (Referenz halten)
        self._next_action: str = "initial"  # "initial" | "append" | "duplex"
        self._settings = config.load_settings()
        self._setup_ui()
        self._load_scanners()
        # Beim Schließen laufende Quellen-Worker sauber abwarten
        self.finished.connect(self._await_src_workers)

    # ── UI-Aufbau ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # Scanner-Auswahl
        self._scanner_combo = QComboBox()
        self._scanner_combo.currentIndexChanged.connect(self._on_scanner_changed)
        self._refresh_btn = QPushButton("Aktualisieren")
        self._refresh_btn.clicked.connect(self._refresh_scanners)
        scanner_row = QHBoxLayout()
        scanner_row.addWidget(self._scanner_combo, 1)
        scanner_row.addWidget(self._refresh_btn)
        form.addRow("Scanner:", scanner_row)

        # Dokumentenquelle
        self._source_combo = QComboBox()
        form.addRow("Quelle:", self._source_combo)

        # Auflösung
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(75, 1200)
        self._dpi_spin.setSingleStep(75)
        self._dpi_spin.setValue(
            self._settings.get("scanner_dpi", config.SCANNER_DEFAULT_DPI))
        self._dpi_spin.setSuffix(" DPI")
        form.addRow("Auflösung:", self._dpi_spin)

        # Farbmodus
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Color", "Gray", "Lineart"])
        idx = self._mode_combo.findText(
            self._settings.get("scanner_mode", config.SCANNER_DEFAULT_MODE))
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        form.addRow("Modus:", self._mode_combo)

        # Papierformat
        self._paper_combo = QComboBox()
        for name in config.PAPER_SIZES:
            self._paper_combo.addItem(name, name)
        pidx = self._paper_combo.findText(
            self._settings.get("scanner_paper", config.SCANNER_DEFAULT_PAPER))
        if pidx >= 0:
            self._paper_combo.setCurrentIndex(pidx)
        form.addRow("Papierformat:", self._paper_combo)

        layout.addLayout(form)

        # Status & Fortschritt
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._page_label = QLabel("")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_label.setVisible(False)
        layout.addWidget(self._page_label)

        # Button-Leiste
        btn_layout = QHBoxLayout()

        self._cancel_btn = QPushButton("Abbrechen")
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        btn_layout.addStretch()

        self._append_btn = QPushButton("Seiten hinzufügen")
        self._append_btn.clicked.connect(self._on_append)
        self._append_btn.setVisible(False)
        btn_layout.addWidget(self._append_btn)

        self._duplex_btn = QPushButton("Rückseiten (Duplex)")
        self._duplex_btn.clicked.connect(self._on_duplex)
        self._duplex_btn.setVisible(False)
        btn_layout.addWidget(self._duplex_btn)

        self._scan_btn = QPushButton("Scannen")
        self._scan_btn.clicked.connect(self._start_scan)
        self._scan_btn.setDefault(True)
        btn_layout.addWidget(self._scan_btn)

        self._finish_btn = QPushButton("Fertig →")
        self._finish_btn.clicked.connect(self.accept)
        self._finish_btn.setVisible(False)
        btn_layout.addWidget(self._finish_btn)

        layout.addLayout(btn_layout)

    # ── Scanner laden ──────────────────────────────────────────────────────────

    def _load_scanners(self) -> None:
        """Nutzt den Klassen-Cache; sucht nur beim ersten Aufruf oder nach Refresh."""
        if ScannerDialog._scanner_cache is not None:
            self._populate_scanner_combo(ScannerDialog._scanner_cache)
        else:
            self._refresh_scanners()

    def _refresh_scanners(self) -> None:
        """Sucht explizit nach Scannern und aktualisiert den Cache."""
        self._scanner_combo.blockSignals(True)
        self._scanner_combo.clear()
        self._source_combo.clear()
        self._scanner_combo.blockSignals(False)
        self._status_label.setText("Suche Scanner …")
        scanners = list_scanners()
        ScannerDialog._scanner_cache = scanners
        self._populate_scanner_combo(scanners)

    def _populate_scanner_combo(self, scanners: List[Tuple[str, str]]) -> None:
        self._scanner_combo.blockSignals(True)
        self._scanner_combo.clear()
        if scanners:
            last_device = self._settings.get("scanner_last_device")
            select_idx = 0
            for i, (device, desc) in enumerate(scanners):
                self._scanner_combo.addItem(f"{desc} [{device}]", device)
                if device == last_device:
                    select_idx = i
            self._scanner_combo.setCurrentIndex(select_idx)
            self._status_label.setText(f"{len(scanners)} Scanner gefunden")
        else:
            self._scanner_combo.addItem("Kein Scanner gefunden", None)
            self._status_label.setText("Kein Scanner erkannt. SANE installiert?")
        self._scan_btn.setEnabled(bool(scanners))
        self._scanner_combo.blockSignals(False)
        self._on_scanner_changed()

    def _on_scanner_changed(self) -> None:
        device = self._scanner_combo.currentData()
        self._source_combo.clear()
        if not device:
            self._source_combo.addItem("–", None)
            return
        # Aus Cache sofort, sonst im Hintergrund laden (kein GUI-Freeze)
        if device in ScannerDialog._sources_cache:
            self._populate_sources(device, ScannerDialog._sources_cache[device])
            return
        self._source_combo.addItem("Lade Quellen …", None)
        self._source_combo.setEnabled(False)
        worker = _SourcesWorker(device)
        worker.done.connect(self._on_sources_loaded)
        worker.finished.connect(lambda w=worker: self._src_workers.remove(w)
                                if w in self._src_workers else None)
        self._src_workers.append(worker)
        worker.start()

    def _on_sources_loaded(self, device: str, sources: list) -> None:
        ScannerDialog._sources_cache[device] = sources
        # Nur anwenden, wenn der Nutzer das Gerät nicht inzwischen gewechselt hat
        if self._scanner_combo.currentData() == device:
            self._populate_sources(device, sources)

    def _await_src_workers(self) -> None:
        """Wartet beim Dialog-Ende auf noch laufende Quellen-Worker."""
        for w in list(self._src_workers):
            try:
                w.done.disconnect()
            except Exception:
                pass
            w.wait(11000)
        self._src_workers.clear()

    def _populate_sources(self, device: str, sources: list) -> None:
        self._source_combo.setEnabled(True)
        self._source_combo.clear()
        last_source = self._settings.get("scanner_last_source")
        if sources:
            select_idx = 0
            for i, s in enumerate(sources):
                self._source_combo.addItem(s, s)
                if s == last_source:
                    select_idx = i
            self._source_combo.setCurrentIndex(select_idx)
        else:
            self._source_combo.addItem("Standard", None)

    # ── Scan-Aktionen ──────────────────────────────────────────────────────────

    def _start_scan(self) -> None:
        if not self._scanner_combo.currentData():
            QMessageBox.warning(self, "Kein Scanner",
                                "Bitte einen gültigen Scanner auswählen.")
            return
        self._next_action = "initial"
        self._run_worker()

    def _on_append(self) -> None:
        self._next_action = "append"
        self._run_worker()

    def _on_duplex(self) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("Rückseiten scannen")
        msg.setText(
            "Bitte den Stapel umdrehen (letzte Seite zuerst in den ADF),\n"
            'dann auf "Scannen" klicken.'
        )
        msg.setIcon(QMessageBox.Icon.Information)
        scan_action = msg.addButton("Scannen", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() != scan_action:
            return
        self._next_action = "duplex"
        self._run_worker()

    def _run_worker(self) -> None:
        device = self._scanner_combo.currentData()
        dpi = self._dpi_spin.value()
        mode = self._mode_combo.currentText()
        source = self._source_combo.currentData()
        paper = self._paper_combo.currentData()

        # Append/Duplex-Scans in separate Datei, damit scan_temp.pdf (Basis) erhalten bleibt
        if self._next_action == "initial":
            output_path = config.TEMP_DIR / "scan_temp.pdf"
        else:
            output_path = config.TEMP_DIR / "scan_extra.pdf"

        self._set_scanning_state(True)
        self._worker = ScanWorker(device, dpi, mode, source, paper, output_path)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _set_scanning_state(self, scanning: bool) -> None:
        self._progress.setVisible(scanning)
        self._scan_btn.setEnabled(not scanning)
        self._append_btn.setEnabled(not scanning)
        self._duplex_btn.setEnabled(not scanning)
        self._finish_btn.setEnabled(not scanning)
        if scanning:
            self._status_label.setText("Scan läuft …")

    def _on_scan_done(self, result) -> None:
        self._set_scanning_state(False)

        if not result:
            self._status_label.setText("Scan fehlgeschlagen.")
            QMessageBox.critical(
                self, "Scan-Fehler",
                "Der Scan konnte nicht durchgeführt werden.\n"
                "Bitte Verbindung und Papiereinzug prüfen."
            )
            return

        new_path = Path(result)
        action = self._next_action

        if action == "initial":
            self._result_path = new_path

        elif action == "append":
            merged = append_pdfs(self._result_path, new_path)
            if not merged:
                self._status_label.setText("Fehler beim Anhängen der Seiten.")
                return
            self._result_path = merged

        elif action == "duplex":
            out = config.TEMP_DIR / "scan_duplex.pdf"
            merged = interleave_pdfs(self._result_path, new_path, out)
            if not merged:
                self._status_label.setText("Duplex-Verschachtelung fehlgeschlagen.")
                return
            self._result_path = merged

        # Seitenzahl anzeigen
        pages = _pdf_page_count(self._result_path)
        self._page_label.setText(f"{pages} Seite(n) gescannt")
        self._page_label.setVisible(True)

        # Auf Phase 2 wechseln (falls noch nicht geschehen)
        self._scan_btn.setVisible(False)
        self._scan_btn.setDefault(False)
        self._append_btn.setVisible(True)
        self._duplex_btn.setVisible(True)
        self._finish_btn.setVisible(True)
        self._finish_btn.setDefault(True)

        self._status_label.setText("Scan erfolgreich.")
        self._save_settings()

    # ── Einstellungen ──────────────────────────────────────────────────────────

    def _save_settings(self) -> None:
        self._settings["scanner_dpi"] = self._dpi_spin.value()
        self._settings["scanner_mode"] = self._mode_combo.currentText()
        self._settings["scanner_paper"] = self._paper_combo.currentText()
        self._settings["scanner_last_device"] = self._scanner_combo.currentData()
        self._settings["scanner_last_source"] = self._source_combo.currentData()
        config.save_settings(self._settings)

    # ── Ergebnis ───────────────────────────────────────────────────────────────

    def get_pdf_path(self) -> Optional[Path]:
        """Gibt den Pfad zur fertigen PDF zurück (nach accept())."""
        return self._result_path
