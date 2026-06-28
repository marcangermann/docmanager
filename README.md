# DocManager

Lokale Dokumentenverwaltung für Linux/KDE. Dokumente werden eingescannt oder
importiert, per OCR durchsuchbar gemacht und als PDF in einem hierarchischen
Verzeichnisbaum nach Schlagwörtern (Tags) abgelegt – kein Cloud-Zwang, alle
Daten bleiben lokal.

## Funktionen

- **Scannen** direkt aus der Anwendung über SANE (`scanimage`), mit Auswahl von
  Gerät, DPI, Farbmodus und Papierformat (inkl. ADF-Unterstützung).
- **Import** einzelner Dateien oder ganzer Verzeichnisbäume; Unterordner werden
  automatisch als hierarchische Tags übernommen.
- **OCR** per Tesseract (Sprachen frei wählbar, Standard `deu+eng`) – läuft im
  Hintergrund-Thread, die Oberfläche bleibt bedienbar.
- **Volltextsuche** über SQLite FTS5 mit Debounce und LIKE-Fallback.
- **Tag-Baum** mit beliebiger Verschachtelung; Faltzustand wird gespeichert.
- **PDF-Vorschau** mit Zoom, Seiten-Navigation und Bildlauf.
- **Start-Scan**: beim Programmstart werden manuell in den Dokumentenordner
  kopierte PDFs erkannt und zur Aufnahme angeboten (in-place, ohne Verschieben).

## Speicherung

Dokumente werden physisch als PDF abgelegt:

```
{base_dir}/{tag1}/{tag2}/.../YYYY-MM-DD_titel.pdf
```

Der Verzeichnisbaum *ist* die Tag-Hierarchie. Metadaten und der Volltextindex
liegen in einer SQLite-Datenbank (`~/.docmanager.db`), die Einstellungen unter
`~/.config/docmanager/settings.json`. Beide werden nicht versioniert und können
jederzeit aus dem Dateibestand neu aufgebaut werden.

## Tech-Stack

| Bereich            | Verwendet                                   |
|--------------------|---------------------------------------------|
| GUI                | Python 3.10+, PyQt6 (Qt6)                    |
| PDF-Rendering/Text | PyMuPDF (`fitz`)                             |
| OCR                | pytesseract / Tesseract                      |
| Scan → PDF         | img2pdf, Pillow                              |
| Scanner-Zugriff    | SANE (`scanimage`)                           |
| Datenbank / Suche  | SQLite + FTS5                                |

## Installation

Systemabhängigkeiten (Debian/Ubuntu):

```bash
sudo apt install tesseract-ocr tesseract-ocr-deu sane-utils
```

Python-Abhängigkeiten:

```bash
pip install -r requirements.txt
```

Auf Debian ohne virtuelle Umgebung ggf.:

```bash
pip install --user --break-system-packages -r requirements.txt
```

## Start

```bash
python main.py
```

Optional als Desktop-Anwendung: `docmanager.sh` als Startskript und
`docmanager.desktop` als Menüeintrag (Pfade darin ggf. anpassen).

## Konfiguration

Beim ersten Start wird der Dokumentenordner (`base_dir`) auf
`~/Dokumente/DocManager` gesetzt. Über **Einstellungen** lassen sich Ordner und
OCR-Sprachen ändern. Zeigt `base_dir` auf einen bestehenden Dokumentenbaum,
bietet der Start-Scan an, vorhandene PDFs in die Verwaltung aufzunehmen.

## Lizenz

[GNU General Public License v3.0](LICENSE) (GPLv3).
