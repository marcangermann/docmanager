"""
DocManager - OCR-Engine (Tesseract via pytesseract)

Funktionen:
- is_text_pdf(): prüft ob PDF bereits Text enthält
- run_ocr(): OCR auf Bild oder bildhaftem PDF
- extract_and_suggest(): kombiniert Text-Extraktion + Keyword-Vorschläge
"""
from pathlib import Path
from typing import Tuple, List
import sys

import config
from core.pdf_utils import extract_text, suggest_keywords, extract_date_from_text


def is_text_pdf(pdf_path: Path, min_chars: int = 50) -> bool:
    """Gibt True zurück, wenn das PDF nativ extrahierbaren Text enthält."""
    text = extract_text(pdf_path, max_pages=2)
    return len(text.strip()) >= min_chars


def run_ocr_on_image(image_path: Path, lang: str = None) -> str:
    """
    Führt Tesseract-OCR auf einer Bilddatei durch.
    Gibt den erkannten Text zurück.
    """
    if lang is None:
        lang = config.OCR_LANGUAGES
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(str(image_path))
        text = pytesseract.image_to_string(img, lang=lang)
        return text
    except ImportError:
        print("pytesseract oder Pillow nicht installiert.", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"OCR-Fehler: {e}", file=sys.stderr)
        return ""


def run_ocr_on_pdf(pdf_path: Path, lang: str = None,
                   max_pages: int = 5) -> str:
    """
    Führt OCR auf einem (bild-haften) PDF durch: rendert Seiten und erkennt Text.
    """
    if lang is None:
        lang = config.OCR_LANGUAGES
    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(str(pdf_path))
        pages_to_ocr = min(doc.page_count, max_pages)
        all_text = []
        for i in range(pages_to_ocr):
            page = doc[i]
            mat = fitz.Matrix(2.0, 2.0)  # 2× Zoom für bessere OCR-Qualität
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            text = pytesseract.image_to_string(img, lang=lang)
            all_text.append(text)
        doc.close()
        return "\n".join(all_text)
    except ImportError:
        print("PyMuPDF, pytesseract oder Pillow nicht installiert.",
              file=sys.stderr)
        return ""
    except Exception as e:
        print(f"PDF-OCR-Fehler: {e}", file=sys.stderr)
        return ""


def extract_and_suggest(file_path: Path,
                        force_ocr: bool = False) -> Tuple[str, List[str], str]:
    """
    Extrahiert Text aus PDF oder Bild, schlägt Keywords vor.

    Rückgabe: (full_text, keyword_list, date_str_or_empty)
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        if not force_ocr and is_text_pdf(path):
            text = extract_text(path)
        else:
            # Erst nativen Text versuchen, dann OCR
            text = extract_text(path)
            if len(text.strip()) < 50:
                text = run_ocr_on_pdf(path)
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        text = run_ocr_on_image(path)
    else:
        text = ""

    keywords = suggest_keywords(text)
    date = extract_date_from_text(text) or ""
    return text, keywords, date
