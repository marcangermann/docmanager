"""
DocManager - Scanner-Integration (SANE via scanimage CLI)

Funktionen:
- list_scanners(): verfügbare Scanner ermitteln
- scan_to_pdf(): Seite scannen und als PDF speichern
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import config


def list_scanners() -> List[Tuple[str, str]]:
    """
    Gibt eine Liste von (device_name, description) zurück.
    Beispiel: [("brother4:net1;dev0", "Brother MFC-...")]
    """
    try:
        result = subprocess.run(
            ["scanimage", "-L"],
            capture_output=True, text=True, timeout=10
        )
        scanners = []
        for line in result.stdout.splitlines():
            # Format: "device `name' is a Description"
            if line.startswith("device"):
                import re
                m = re.match(r"device `([^']+)' is a (.+)", line)
                if m:
                    scanners.append((m.group(1), m.group(2)))
        return scanners
    except FileNotFoundError:
        print("scanimage nicht gefunden (SANE nicht installiert?)",
              file=sys.stderr)
        return []
    except subprocess.TimeoutExpired:
        return []
    except Exception as e:
        print(f"Scanner-Auflistung fehlgeschlagen: {e}", file=sys.stderr)
        return []


def scan_to_png(device: str, dpi: int = 300, mode: str = "Color",
                output_path: Optional[Path] = None) -> Optional[Path]:
    """
    Scannt eine Seite als PNG.
    Gibt den Pfad zur erzeugten PNG-Datei zurück oder None bei Fehler.
    """
    if output_path is None:
        config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        output_path = config.TEMP_DIR / "scan_temp.png"

    cmd = [
        "scanimage",
        f"--device={device}",
        f"--resolution={dpi}",
        f"--mode={mode}",
        "--format=png",
        f"--output-file={output_path}",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f"scanimage-Fehler: {result.stderr}", file=sys.stderr)
            return None
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        return None
    except subprocess.TimeoutExpired:
        print("Scan-Timeout", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Scan-Fehler: {e}", file=sys.stderr)
        return None


def png_to_pdf(png_path: Path, pdf_path: Optional[Path] = None) -> Optional[Path]:
    """
    Konvertiert ein PNG zu PDF mit img2pdf.
    Gibt den PDF-Pfad zurück oder None bei Fehler.
    """
    if pdf_path is None:
        pdf_path = png_path.with_suffix(".pdf")
    try:
        import img2pdf
        with open(str(pdf_path), "wb") as f:
            f.write(img2pdf.convert(str(png_path)))
        return pdf_path
    except ImportError:
        # Fallback: Pillow
        try:
            from PIL import Image
            img = Image.open(str(png_path))
            img.save(str(pdf_path), "PDF")
            return pdf_path
        except Exception as e:
            print(f"PNG→PDF-Konvertierung fehlgeschlagen: {e}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"img2pdf-Fehler: {e}", file=sys.stderr)
        return None


def scan_to_pdf(device: str, dpi: int = 300,
                mode: str = "Color") -> Optional[Path]:
    """
    Vollständiger Scan-Workflow: Gerät → PNG → PDF.
    Gibt den Pfad zur temporären PDF-Datei zurück.
    """
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    png_path = config.TEMP_DIR / "scan_temp.png"
    pdf_path = config.TEMP_DIR / "scan_temp.pdf"

    png = scan_to_png(device, dpi, mode, png_path)
    if not png:
        return None
    return png_to_pdf(png, pdf_path)
