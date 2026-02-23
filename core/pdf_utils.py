"""
DocManager - PDF-Hilfsfunktionen

Verwendet PyMuPDF (fitz) für:
- Text aus PDFs extrahieren
- Seitenzahl ermitteln
- Seiten als QPixmap rendern (für Vorschau)
"""
from pathlib import Path
from typing import Optional, List
import re


def get_page_count(pdf_path: Path) -> int:
    """Gibt die Anzahl der Seiten zurück."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        count = doc.page_count
        doc.close()
        return count
    except Exception:
        return 0


def extract_text(pdf_path: Path, max_pages: int = 10) -> str:
    """
    Extrahiert Text aus einem PDF (erste max_pages Seiten).
    Gibt leeren String zurück bei Fehler oder bildhaftem PDF.
    """
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        pages_to_read = min(doc.page_count, max_pages)
        texts = []
        for i in range(pages_to_read):
            page = doc[i]
            texts.append(page.get_text())
        doc.close()
        return "\n".join(texts)
    except Exception:
        return ""


def render_page_to_pixmap(pdf_path: Path, page_num: int = 0,
                           zoom: float = 1.5):
    """
    Rendert eine PDF-Seite als PyQt6 QPixmap.
    Gibt None zurück bei Fehler.
    """
    try:
        import fitz
        from PyQt6.QtGui import QPixmap, QImage
        doc = fitz.open(str(pdf_path))
        if page_num >= doc.page_count:
            doc.close()
            return None
        page = doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height,
                     pix.stride, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img)
        doc.close()
        return pixmap
    except Exception:
        return None


def extract_date_from_text(text: str) -> Optional[str]:
    """
    Versucht ein Datum aus dem Text zu extrahieren.
    Gibt ISO-Datum (YYYY-MM-DD) oder None zurück.
    """
    # Deutsche und internationale Datumsformate
    patterns = [
        (r'\b(\d{4})-(\d{2})-(\d{2})\b', lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
        (r'\b(\d{2})\.(\d{2})\.(\d{4})\b', lambda m: f"{m[3]}-{m[2]}-{m[1]}"),
        (r'\b(\d{1,2})\.\s*(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})\b',
         None),
    ]
    month_map = {
        "januar": "01", "februar": "02", "märz": "03", "april": "04",
        "mai": "05", "juni": "06", "juli": "07", "august": "08",
        "september": "09", "oktober": "10", "november": "11", "dezember": "12",
    }
    # Einfache Muster
    for pattern, formatter in patterns[:2]:
        m = re.search(pattern, text)
        if m and formatter:
            try:
                date_str = formatter(m.groups())
                # Validierung
                from datetime import datetime
                datetime.strptime(date_str, "%Y-%m-%d")
                return date_str
            except ValueError:
                continue
    # Deutsches Langformat
    m = re.search(r'\b(\d{1,2})\.\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+(\d{4})\b',
                  text.lower())
    if m:
        day, month_name, year = m.group(1), m.group(2), m.group(3)
        month = month_map.get(month_name)
        if month:
            return f"{year}-{month}-{int(day):02d}"
    return None


def suggest_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """
    Einfache Keyword-Extraktion: häufige Wörter (>= 4 Zeichen, keine Stoppwörter).
    """
    stopwords = {
        "dass", "sich", "auch", "eine", "einen", "einem", "einer", "eines",
        "sind", "wird", "werden", "wurde", "haben", "hatte", "nicht", "oder",
        "aber", "noch", "nach", "über", "unter", "beim", "beim", "dieser",
        "diese", "dieses", "diesen", "diesem", "their", "from", "with",
        "this", "that", "have", "been", "they", "will", "your", "the",
        "and", "for", "are", "was", "has", "all", "can", "her",
    }
    words = re.findall(r'\b[A-Za-zÄÖÜäöüß]{4,}\b', text)
    freq: dict = {}
    for w in words:
        wl = w.lower()
        if wl not in stopwords:
            freq[wl] = freq.get(wl, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: -x[1])
    return [w for w, _ in sorted_words[:max_keywords]]
