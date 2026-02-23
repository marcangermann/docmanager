"""
DocManager - Konfiguration
"""
import os
from pathlib import Path

# Basis-Verzeichnis für Dokumente (anpassbar über Einstellungen)
DEFAULT_BASE_DIR = Path.home() / "Dokumente" / "DocManager"

# Datenbank
DB_PATH = Path.home() / ".docmanager.db"

# Temporäres Verzeichnis für Scans
TEMP_DIR = Path.home() / ".cache" / "docmanager"

# OCR-Sprachen (Tesseract-Sprachcodes, z.B. "deu", "eng", "deu+eng")
OCR_LANGUAGES = "deu+eng"

# Scanner-Standardeinstellungen
SCANNER_DEFAULT_DPI = 300
SCANNER_DEFAULT_MODE = "Color"  # "Color", "Gray", "Lineart"

# Datumformat für Dateinamen
DATE_FORMAT = "%Y-%m-%d"

# Einstellungsdatei
SETTINGS_FILE = Path.home() / ".config" / "docmanager" / "settings.json"


def load_settings() -> dict:
    """Lädt gespeicherte Einstellungen, gibt Defaults zurück wenn nicht vorhanden."""
    import json
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "base_dir": str(DEFAULT_BASE_DIR),
        "ocr_languages": OCR_LANGUAGES,
        "scanner_dpi": SCANNER_DEFAULT_DPI,
        "scanner_mode": SCANNER_DEFAULT_MODE,
    }


def save_settings(settings: dict) -> None:
    """Speichert Einstellungen persistent."""
    import json
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
