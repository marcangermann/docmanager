"""
DocManager - Dokumentenverwaltung

Kernlogik für Import, Speichern, Umbenennen und Löschen von Dokumenten.
"""
import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import config
from database.db import Database
from core.pdf_utils import get_page_count, extract_text
from core.ocr_engine import extract_and_suggest


def _sanitize_filename(name: str) -> str:
    """Entfernt unerlaubte Zeichen aus Datei-/Ordnernamen."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = name.strip(". ")
    return name or "dokument"


def build_target_path(base_dir: Path, tag_path: List[str],
                      title: str, date_str: Optional[str] = None,
                      suffix: str = ".pdf") -> Path:
    """
    Berechnet den Ziel-Pfad:
      {base_dir}/{tag1}/{tag2}/.../YYYY-MM-DD_titel.pdf
    Falls kein Datum, wird das heutige verwendet.
    """
    if not date_str:
        date_str = datetime.now().strftime(config.DATE_FORMAT)
    safe_tags = [_sanitize_filename(t) for t in tag_path]
    safe_title = _sanitize_filename(title)
    filename = f"{date_str}_{safe_title}{suffix}"
    dir_path = base_dir.joinpath(*safe_tags) if safe_tags else base_dir
    return dir_path / filename


def _unique_path(path: Path) -> Path:
    """Fügt einen Zähler ein, falls der Pfad bereits existiert."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class DocumentManager:
    def __init__(self, db: Database, base_dir: Optional[Path] = None):
        self.db = db
        settings = config.load_settings()
        self.base_dir = base_dir or Path(settings["base_dir"])
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def import_document(self, source_path: Path, title: str,
                        tag_path: List[str], date_str: Optional[str] = None,
                        full_text: str = "", copy: bool = True) -> int:
        """
        Importiert ein Dokument:
        1. Berechnet Ziel-Pfad
        2. Kopiert/verschiebt Datei
        3. Legt DB-Eintrag an
        4. Gibt doc_id zurück
        """
        source_path = Path(source_path)
        suffix = source_path.suffix.lower()

        target = build_target_path(self.base_dir, tag_path, title,
                                   date_str, suffix)
        target = _unique_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        if copy:
            shutil.copy2(str(source_path), str(target))
        else:
            shutil.move(str(source_path), str(target))

        page_count = get_page_count(target) if suffix == ".pdf" else 1
        file_size = target.stat().st_size

        if not full_text:
            full_text = extract_text(target) if suffix == ".pdf" else ""

        doc_id = self.db.add_document(
            path=str(target),
            title=title,
            page_count=page_count,
            file_size=file_size,
            text_content=full_text,
            date_doc=date_str,
        )

        tag_ids = self.db.get_tag_path_ids(tag_path)
        if tag_ids:
            self.db.assign_tags(doc_id, tag_ids)

        return doc_id

    def move_document(self, doc_id: int, new_tag_path: List[str],
                      new_title: Optional[str] = None,
                      new_date: Optional[str] = None) -> Path:
        """
        Verschiebt ein Dokument in einen neuen Tag-Pfad:
        - Datei physisch verschieben
        - DB-Pfad aktualisieren
        - Tags neu zuweisen
        """
        row = self.db.get_document(doc_id)
        if not row:
            raise FileNotFoundError(f"Dokument {doc_id} nicht gefunden")

        old_path = Path(row["path"])
        title = new_title or row["title"]
        date_str = new_date or row["date_doc"]

        target = build_target_path(self.base_dir, new_tag_path, title,
                                   date_str, old_path.suffix)
        target = _unique_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(old_path), str(target))

        self.db.update_document_path(doc_id, str(target))

        tag_ids = self.db.get_tag_path_ids(new_tag_path)
        self.db.assign_tags(doc_id, tag_ids)

        # Alten leeren Ordner entfernen
        self._cleanup_empty_dirs(old_path.parent)

        return target

    def delete_document(self, doc_id: int, delete_file: bool = True) -> None:
        """Löscht Dokument aus DB und optional vom Dateisystem."""
        row = self.db.get_document(doc_id)
        if not row:
            return
        old_path = Path(row["path"])
        self.db.delete_document(doc_id)
        if delete_file and old_path.exists():
            old_path.unlink()
            self._cleanup_empty_dirs(old_path.parent)

    def analyze_file(self, file_path: Path,
                     force_ocr: bool = False) -> Tuple[str, List[str], str]:
        """
        Analysiert eine Datei vor dem Import.
        Rückgabe: (full_text, suggested_keywords, detected_date)
        """
        return extract_and_suggest(file_path, force_ocr=force_ocr)

    def _cleanup_empty_dirs(self, directory: Path) -> None:
        """Entfernt leere Unterordner bis zum base_dir."""
        try:
            while directory != self.base_dir and directory.is_dir():
                if not any(directory.iterdir()):
                    directory.rmdir()
                    directory = directory.parent
                else:
                    break
        except Exception:
            pass

    def find_untracked_files(self) -> List[Path]:
        """
        Gibt alle PDFs im base_dir zurück, die noch nicht in der DB stehen
        (z.B. manuell hineinkopierte Dateien). Sortiert nach Pfad.
        """
        existing_paths = {
            row["path"] for row in self.db.get_all_documents()
        }
        return [
            p for p in sorted(self.base_dir.rglob("*.pdf"))
            if str(p) not in existing_paths
        ]

    def register_file(self, pdf_path: Path, run_ocr: bool = False) -> int:
        """
        Registriert eine bereits im base_dir liegende PDF in der DB (in-place,
        ohne Kopieren/Verschieben):
          - Tag-Pfad aus der Verzeichnisstruktur ableiten
          - Titel und Datum aus dem Dateinamen (YYYY-MM-DD_titel)
          - Text per extract_text; bei leerem Ergebnis und run_ocr=True per OCR
        Gibt die neue doc_id zurück.
        """
        pdf_path = Path(pdf_path)

        # Tag-Pfad aus Verzeichnisstruktur ableiten
        rel = pdf_path.parent.relative_to(self.base_dir)
        tag_path = list(rel.parts)

        # Titel und Datum aus Dateiname
        stem = pdf_path.stem
        date_str: Optional[str] = None
        title = stem
        m = re.match(r'^(\d{4}-\d{2}-\d{2})[_\s](.*)', stem)
        if m:
            date_str = m.group(1)
            title = m.group(2).replace("_", " ")

        text = extract_text(pdf_path)
        if run_ocr and not text.strip():
            text, _, _ = extract_and_suggest(pdf_path)

        page_count = get_page_count(pdf_path)
        file_size = pdf_path.stat().st_size

        doc_id = self.db.add_document(
            path=str(pdf_path),
            title=title,
            page_count=page_count,
            file_size=file_size,
            text_content=text,
            date_doc=date_str,
        )
        if tag_path:
            tag_ids = self.db.get_tag_path_ids(tag_path)
            self.db.assign_tags(doc_id, tag_ids)
        return doc_id

    def rebuild_from_filesystem(self) -> int:
        """
        Scannt base_dir nach PDFs und fügt fehlende zur DB hinzu.
        Nützlich nach manuellem Datei-Kopieren.
        Gibt Anzahl neu hinzugefügter Dokumente zurück.
        """
        added = 0
        for pdf_path in self.find_untracked_files():
            self.register_file(pdf_path, run_ocr=False)
            added += 1
        return added
