"""
DocManager - Scanner-Dialog

Ermöglicht die Auswahl des Scanners, DPI und Farbmodus.
Startet den Scan und gibt den Pfad zur erzeugten PDF zurück.
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QSpinBox, QDialogButtonBox, QLabel,
    QPushButton, QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

import config
from core.scanner import list_scanners, scan_to_pdf


# ── Scan-Worker ───────────────────────────────────────────────────────────────

class ScanWorker(QThread):
    finished = pyqtSignal(object)  # Path oder None

    def __init__(self, device: str, dpi: int, mode: str):
        super().__init__()
        self.device = device
        self.dpi = dpi
        self.mode = mode

    def run(self):
        result = scan_to_pdf(self.device, self.dpi, self.mode)
        self.finished.emit(result)


# ── Scanner-Dialog ────────────────────────────────────────────────────────────

class ScannerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dokument scannen")
        self.setMinimumWidth(380)
        self._result_path: Optional[Path] = None
        self._worker: Optional[ScanWorker] = None
        self._setup_ui()
        self._load_scanners()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # Scanner-Auswahl
        self._scanner_combo = QComboBox()
        self._refresh_btn = QPushButton("Aktualisieren")
        self._refresh_btn.clicked.connect(self._load_scanners)
        scanner_row = QHBoxLayout()
        scanner_row.addWidget(self._scanner_combo, 1)
        scanner_row.addWidget(self._refresh_btn)
        form.addRow("Scanner:", scanner_row)

        # DPI
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(75, 1200)
        self._dpi_spin.setSingleStep(75)
        self._dpi_spin.setValue(config.SCANNER_DEFAULT_DPI)
        self._dpi_spin.setSuffix(" DPI")
        form.addRow("Auflösung:", self._dpi_spin)

        # Farbmodus
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Color", "Gray", "Lineart"])
        default_idx = self._mode_combo.findText(config.SCANNER_DEFAULT_MODE)
        if default_idx >= 0:
            self._mode_combo.setCurrentIndex(default_idx)
        form.addRow("Modus:", self._mode_combo)

        layout.addLayout(form)

        # Status
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # Indeterminiert
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Buttons
        self._buttons = QDialogButtonBox()
        self._scan_btn = self._buttons.addButton(
            "Scannen", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._scan_btn.clicked.connect(self._start_scan)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _load_scanners(self) -> None:
        self._scanner_combo.clear()
        self._status_label.setText("Suche Scanner …")
        scanners = list_scanners()
        if scanners:
            for device, desc in scanners:
                self._scanner_combo.addItem(f"{desc} [{device}]", device)
            self._status_label.setText(
                f"{len(scanners)} Scanner gefunden"
            )
        else:
            self._scanner_combo.addItem("Kein Scanner gefunden", None)
            self._status_label.setText(
                "Kein Scanner erkannt. SANE installiert?"
            )
        self._scan_btn.setEnabled(bool(scanners))

    def _start_scan(self) -> None:
        device = self._scanner_combo.currentData()
        if not device:
            QMessageBox.warning(self, "Kein Scanner",
                                "Bitte einen gültigen Scanner auswählen.")
            return

        dpi = self._dpi_spin.value()
        mode = self._mode_combo.currentText()

        self._progress.setVisible(True)
        self._scan_btn.setEnabled(False)
        self._status_label.setText("Scan läuft …")

        self._worker = ScanWorker(device, dpi, mode)
        self._worker.finished.connect(self._on_scan_done)
        self._worker.start()

    def _on_scan_done(self, result) -> None:
        self._progress.setVisible(False)
        self._scan_btn.setEnabled(True)
        if result:
            self._result_path = Path(result)
            self._status_label.setText("Scan erfolgreich.")
            self.accept()
        else:
            self._status_label.setText("Scan fehlgeschlagen.")
            QMessageBox.critical(
                self, "Scan-Fehler",
                "Der Scan konnte nicht durchgeführt werden.\n"
                "Bitte Verbindung und Papiereinzug prüfen."
            )

    def get_pdf_path(self) -> Optional[Path]:
        """Gibt den Pfad zur gescannten PDF zurück (nach accept())."""
        return self._result_path
