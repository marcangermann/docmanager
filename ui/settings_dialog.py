"""
DocManager - Einstellungs-Dialog
"""
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QDialogButtonBox,
    QFileDialog, QSpinBox, QComboBox, QLabel
)

import config


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(420)
        self._settings = config.load_settings()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Basis-Verzeichnis
        dir_row = QHBoxLayout()
        self._base_dir_edit = QLineEdit(self._settings.get("base_dir", ""))
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(self._base_dir_edit)
        dir_row.addWidget(browse_btn)
        form.addRow("Dokumenten-Ordner:", dir_row)

        # OCR-Sprachen
        self._ocr_lang_edit = QLineEdit(
            self._settings.get("ocr_languages", config.OCR_LANGUAGES)
        )
        self._ocr_lang_edit.setPlaceholderText("z.B. deu+eng")
        form.addRow("OCR-Sprachen:", self._ocr_lang_edit)

        # Scanner DPI
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(75, 1200)
        self._dpi_spin.setValue(
            self._settings.get("scanner_dpi", config.SCANNER_DEFAULT_DPI)
        )
        self._dpi_spin.setSuffix(" DPI")
        form.addRow("Scanner-Standard-DPI:", self._dpi_spin)

        # Scanner-Modus
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Color", "Gray", "Lineart"])
        mode = self._settings.get("scanner_mode", config.SCANNER_DEFAULT_MODE)
        idx = self._mode_combo.findText(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        form.addRow("Scanner-Standard-Modus:", self._mode_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Dokumenten-Ordner wählen",
            self._base_dir_edit.text() or str(Path.home())
        )
        if d:
            self._base_dir_edit.setText(d)

    def _save_and_accept(self) -> None:
        self._settings["base_dir"] = self._base_dir_edit.text().strip()
        self._settings["ocr_languages"] = self._ocr_lang_edit.text().strip()
        self._settings["scanner_dpi"] = self._dpi_spin.value()
        self._settings["scanner_mode"] = self._mode_combo.currentText()
        config.save_settings(self._settings)
        self.accept()
