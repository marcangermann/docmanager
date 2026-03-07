"""
DocManager - PDF-Vorschau (rechtes Panel)

Rendert PDF-Seiten via PyMuPDF und zeigt sie in einem scrollbaren Label.
"""
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                              QLabel, QPushButton, QScrollArea,
                              QSizePolicy)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap

from core.pdf_utils import render_page_to_pixmap, get_page_count


class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_path: Optional[Path] = None
        self._page_num: int = 0
        self._page_count: int = 0
        self._zoom: float = 1.5
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Navigationsleiste
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("◀")
        self._btn_prev.setFixedWidth(36)
        self._btn_prev.clicked.connect(self._prev_page)
        self._page_label = QLabel("–")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_next = QPushButton("▶")
        self._btn_next.setFixedWidth(36)
        self._btn_next.clicked.connect(self._next_page)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(28)
        btn_zoom_in.clicked.connect(self._zoom_in)
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedWidth(28)
        btn_zoom_out.clicked.connect(self._zoom_out)

        nav.addWidget(self._btn_prev)
        nav.addWidget(self._page_label, 1)
        nav.addWidget(self._btn_next)
        nav.addSpacing(8)
        nav.addWidget(btn_zoom_out)
        nav.addWidget(btn_zoom_in)
        layout.addLayout(nav)

        # Scroll-Bereich für das Bild
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self._img_label.setStyleSheet("background: #888;")
        self._scroll.setWidget(self._img_label)
        layout.addWidget(self._scroll, 1)

        self._set_nav_enabled(False)

    def load_document(self, pdf_path: Path) -> None:
        """Lädt ein PDF und zeigt die erste Seite."""
        self._pdf_path = pdf_path
        self._page_num = 0
        self._page_count = get_page_count(pdf_path)
        self._render_page()

    def clear(self) -> None:
        self._pdf_path = None
        self._page_num = 0
        self._page_count = 0
        self._img_label.setPixmap(QPixmap())
        self._img_label.setText("Kein Dokument ausgewählt")
        self._page_label.setText("–")
        self._set_nav_enabled(False)

    def _render_page(self) -> None:
        if not self._pdf_path:
            return
        pixmap = render_page_to_pixmap(
            self._pdf_path, self._page_num, self._zoom
        )
        if pixmap:
            self._img_label.setPixmap(pixmap)
            self._img_label.resize(pixmap.size())
            self._img_label.setText("")
        else:
            self._img_label.setText("Vorschau nicht verfügbar")
        self._page_label.setText(
            f"Seite {self._page_num + 1} / {self._page_count}"
        )
        self._set_nav_enabled(True)
        self._btn_prev.setEnabled(self._page_num > 0)
        self._btn_next.setEnabled(self._page_num < self._page_count - 1)

    def _prev_page(self) -> None:
        if self._page_num > 0:
            self._page_num -= 1
            self._render_page()

    def _next_page(self) -> None:
        if self._page_num < self._page_count - 1:
            self._page_num += 1
            self._render_page()

    def _zoom_in(self) -> None:
        self._zoom = min(self._zoom + 0.25, 4.0)
        self._render_page()

    def _zoom_out(self) -> None:
        self._zoom = max(self._zoom - 0.25, 0.5)
        self._render_page()

    def _set_nav_enabled(self, enabled: bool) -> None:
        self._btn_prev.setEnabled(enabled)
        self._btn_next.setEnabled(enabled)
