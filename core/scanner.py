"""
DocManager - Scanner-Integration (SANE via scanimage CLI)

Funktionen:
- list_scanners(): verfügbare Scanner ermitteln
- get_scanner_sources(): verfügbare Quellen (Flatbed, ADF …) für ein Gerät
- scan_to_pdf(): Seite(n) scannen und als PDF speichern
"""
import re
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


def _get_device_help(device: str) -> str:
    """Gibt die --help-Ausgabe eines Scanners zurück (stdout + stderr)."""
    try:
        r = subprocess.run(
            ["scanimage", f"--device={device}", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout + r.stderr
    except Exception:
        return ""


def get_scanner_sources(device: str) -> List[str]:
    """
    Gibt die verfügbaren Dokumentenquellen (Flatbed, ADF, …) für ein Gerät zurück.
    Leer wenn das Backend keine explizite --source-Option anbietet.
    """
    output = _get_device_help(device)
    try:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped.startswith("--source"):
                continue
            # Format: --source Flatbed|ADF [Flatbed]
            # oder:   --source Flatbed|ADF[Single-sided]|ADF[Duplex] [Flatbed]
            m = re.match(r"--source\s+([\w][\w\s\[\]]*(?:[|,][\w\s\[\]]+)+)", stripped)
            if m:
                parts = re.split(r"[|,]", m.group(1))
                sources = []
                for p in parts:
                    # Standard-Marker [Flatbed] entfernen
                    p = re.sub(r"\s*\[(?![A-Z]{2}[a-z]).*?\]\s*$", "", p).strip()
                    if p:
                        sources.append(p)
                if sources:
                    return sources
        return []
    except Exception as e:
        print(f"Quellenabfrage fehlgeschlagen: {e}", file=sys.stderr)
        return []


def _geometry_params(device: str, width_mm: float, height_mm: float) -> List[str]:
    """
    Gibt die richtigen scanimage-Parameter für die Scan-Fläche zurück.
    Prüft anhand der --help-Ausgabe welche Optionen das Backend unterstützt.
    Priorität: --br-x/--br-y > --page-width/--page-height > -x/-y
    Integer-Werte für maximale Backend-Kompatibilität.
    """
    help_text = _get_device_help(device)
    w = str(int(width_mm))
    h = str(int(height_mm))
    if "--br-x" in help_text:
        return [f"--br-x={w}", f"--br-y={h}"]
    if "--page-width" in help_text:
        return [f"--page-width={w}", f"--page-height={h}"]
    # Short-form -x / -y (ältere Backends)
    if re.search(r"(?m)^\s*-x\b", help_text):
        return ["-x", w, "-y", h]
    print(f"Kein Papierformat-Parameter für {device} gefunden, ignoriert.",
          file=sys.stderr)
    return []


def scan_to_png(device: str, dpi: int = 300, mode: str = "Color",
                output_path: Optional[Path] = None,
                source: Optional[str] = None,
                paper: Optional[str] = None) -> Optional[Path]:
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
    if source:
        cmd.append(f"--source={source}")
    dims = config.PAPER_SIZES.get(paper) if paper else None
    if dims:
        cmd += _geometry_params(device, dims[0], dims[1])

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
    """Konvertiert ein PNG zu PDF. Gibt den PDF-Pfad zurück oder None bei Fehler."""
    if pdf_path is None:
        pdf_path = png_path.with_suffix(".pdf")
    return _pngs_to_pdf([png_path], pdf_path)


def _pngs_to_pdf(png_paths: List[Path], pdf_path: Path) -> Optional[Path]:
    """Konvertiert eine Liste von PNGs zu einer mehrseitigen PDF."""
    try:
        import img2pdf
        with open(str(pdf_path), "wb") as f:
            f.write(img2pdf.convert([str(p) for p in png_paths]))
        return pdf_path
    except ImportError:
        try:
            from PIL import Image
            imgs = [Image.open(str(p)).convert("RGB") for p in png_paths]
            imgs[0].save(str(pdf_path), "PDF", save_all=True, append_images=imgs[1:])
            return pdf_path
        except Exception as e:
            print(f"PNG→PDF-Konvertierung fehlgeschlagen: {e}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"img2pdf-Fehler: {e}", file=sys.stderr)
        return None


def _is_adf_source(source: Optional[str]) -> bool:
    if not source:
        return False
    lower = source.lower()
    return any(k in lower for k in ("adf", "feeder", "automatic document"))


def scan_to_pdf(device: str, dpi: int = 300,
                mode: str = "Color",
                source: Optional[str] = None,
                paper: Optional[str] = None,
                output_path: Optional[Path] = None) -> Optional[Path]:
    """
    Vollständiger Scan-Workflow: Gerät → PNG(s) → PDF.
    Bei ADF-Quellen wird automatisch der Batch-Modus verwendet (alle Seiten).
    Gibt den Pfad zur temporären PDF-Datei zurück.
    """
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = output_path or (config.TEMP_DIR / "scan_temp.pdf")

    dims = config.PAPER_SIZES.get(paper) if paper else None

    if _is_adf_source(source):
        # Alte Batch-Dateien bereinigen
        for f in config.TEMP_DIR.glob("scan_batch_*.png"):
            f.unlink(missing_ok=True)

        batch_pattern = str(config.TEMP_DIR / "scan_batch_%04d.png")
        cmd = [
            "scanimage",
            f"--device={device}",
            f"--resolution={dpi}",
            f"--mode={mode}",
            f"--source={source}",
            "--format=png",
            f"--batch={batch_pattern}",
        ]
        if dims:
            cmd += _geometry_params(device, dims[0], dims[1])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            # Rückgabewert 7 = ADF leer (normales Ende)
            if result.returncode not in (0, 7):
                print(f"scanimage-Fehler: {result.stderr}", file=sys.stderr)
                return None
        except subprocess.TimeoutExpired:
            print("Scan-Timeout", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Scan-Fehler: {e}", file=sys.stderr)
            return None

        pages = sorted(config.TEMP_DIR.glob("scan_batch_*.png"))
        if not pages:
            return None
        return _pngs_to_pdf(pages, pdf_path)

    else:
        # Einzelseite (Flatbed oder keine explizite Quelle)
        png_path = config.TEMP_DIR / "scan_temp.png"
        png = scan_to_png(device, dpi, mode, png_path, source, paper)
        if not png:
            return None
        return _pngs_to_pdf([png], pdf_path)


def append_pdfs(base_pdf: Path, extra_pdf: Path) -> Optional[Path]:
    """
    Hängt extra_pdf an base_pdf an.
    Gibt base_pdf zurück oder None bei Fehler.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(base_pdf))
        extra = fitz.open(str(extra_pdf))
        doc.insert_pdf(extra)
        # Nicht auf die geöffnete Quelldatei speichern → Temp-Datei, dann ersetzen
        tmp = base_pdf.with_suffix(".tmp.pdf")
        doc.save(str(tmp))
        doc.close()
        extra.close()
        tmp.replace(base_pdf)
        return base_pdf
    except Exception as e:
        print(f"PDF-Anhängen fehlgeschlagen: {e}", file=sys.stderr)
        return None


def interleave_pdfs(front_pdf: Path, back_pdf: Path,
                    output_pdf: Path) -> Optional[Path]:
    """
    Verschachtelt Vorder- und Rückseiten für manuellen Duplex-Scan.
    Erwartet, dass die Rückseiten in umgekehrter Reihenfolge vorliegen
    (Stapel wurde zum Scannen umgedreht).
    Ergebnis: F1, B1, F2, B2, …
    """
    try:
        import fitz
        front = fitz.open(str(front_pdf))
        back = fitz.open(str(back_pdf))
        result = fitz.open()

        # Rückseiten-Indizes umkehren: letztes Blatt im ADF = erste Rückseite
        back_indices = list(range(back.page_count - 1, -1, -1))

        for i in range(front.page_count):
            result.insert_pdf(front, from_page=i, to_page=i)
            if i < len(back_indices):
                bi = back_indices[i]
                result.insert_pdf(back, from_page=bi, to_page=bi)

        result.save(str(output_pdf))
        return output_pdf
    except Exception as e:
        print(f"Duplex-Verschachtelung fehlgeschlagen: {e}", file=sys.stderr)
        return None
