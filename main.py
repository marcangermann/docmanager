#!/usr/bin/env python3
"""
DocManager - Einstiegspunkt

Startet die PyQt6-Anwendung.
"""
import sys
from pathlib import Path

# Projektverzeichnis zum Python-Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

import config
from ui.main_window import MainWindow


def main():
    # Temp-Verzeichnis anlegen
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName("DocManager")
    app.setOrganizationName("DocManager")

    # KDE/Qt-Stil übernehmen (systemweit gesetzt)
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
