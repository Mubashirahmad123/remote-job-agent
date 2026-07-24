"""
tools/font_utils.py
Cross-platform Unicode font resolution for fpdf2 PDF generation.
Downloads DejaVu fonts from official GitHub releases if not found locally.
"""

import os
import sys
import zipfile
import io
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
DEJAVU_VERSION = "2_37"
DEJAVU_ZIP_URL = (
    f"https://github.com/dejavu-fonts/dejavu-fonts/releases/download/"
    f"version_{DEJAVU_VERSION}/dejavu-fonts-ttf-2.37.zip"
)
DEJAVU_REGULAR_PATH = FONTS_DIR / "DejaVuSans.ttf"
DEJAVU_BOLD_PATH = FONTS_DIR / "DejaVuSans-Bold.ttf"


def _find_system_paths():
    """Check common OS-specific font directories for DejaVu fonts."""
    if sys.platform == "win32":
        base = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
        candidates = [
            base / "DejaVuSans.ttf",
            base / "DejaVuSans-Bold.ttf",
            base / "dejavu" / "DejaVuSans.ttf",
        ]
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Fonts"
        candidates = [
            base / "DejaVuSans.ttf",
            Path("/Library/Fonts/DejaVuSans.ttf"),
            Path("/System/Library/Fonts/DejaVuSans.ttf"),
        ]
    else:
        base = Path("/usr/share/fonts")
        candidates = [
            base / "truetype/dejavu/DejaVuSans.ttf",
            base / "dejavu/DejaVuSans.ttf",
            Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        ]

    regular = None
    bold = None
    for p in candidates:
        if p.exists():
            if "Bold" in p.name or "-Bold" in p.name:
                if bold is None:
                    bold = p
            else:
                if regular is None:
                    regular = p
        if regular and bold:
            break

    return regular, bold


def _download_fonts():
    """Download DejaVu fonts from GitHub release zip to project fonts/."""
    import requests

    FONTS_DIR.mkdir(parents=True, exist_ok=True)

    if DEJAVU_REGULAR_PATH.exists() and DEJAVU_BOLD_PATH.exists():
        return True

    try:
        print(f"Downloading DejaVu fonts v{DEJAVU_VERSION.replace('_', '.')}...")
        resp = requests.get(DEJAVU_ZIP_URL, timeout=60)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            for name in z.namelist():
                if name.endswith(".ttf"):
                    z.extract(name, FONTS_DIR)

        for f in FONTS_DIR.rglob("*.ttf"):
            target = FONTS_DIR / f.name
            if not target.exists():
                f.rename(target)

        for subdir in list(FONTS_DIR.iterdir()):
            if subdir.is_dir():
                for f in subdir.rglob("*"):
                    f.unlink()
                subdir.rmdir()

        if DEJAVU_REGULAR_PATH.exists() and DEJAVU_BOLD_PATH.exists():
            print("DejaVu fonts ready.")
            return True

        print("Warning: DejaVu zip extracted but TTF files not found.")
        return False
    except Exception as e:
        print(f"DejaVu font download failed: {e}")
        return False


def resolve_font_paths():
    """
    Returns (regular_path, bold_path, font_name).
    Checks project fonts/ first, then system paths, then downloads.
    """
    # 1. Check project-local fonts/
    if DEJAVU_REGULAR_PATH.exists() and DEJAVU_BOLD_PATH.exists():
        return str(DEJAVU_REGULAR_PATH), str(DEJAVU_BOLD_PATH), "DejaVu"

    # 2. Check system paths
    regular, bold = _find_system_paths()
    if regular and bold:
        return str(regular), str(bold), "DejaVu"

    # 3. Download
    if _download_fonts():
        if DEJAVU_REGULAR_PATH.exists() and DEJAVU_BOLD_PATH.exists():
            return str(DEJAVU_REGULAR_PATH), str(DEJAVU_BOLD_PATH), "DejaVu"

    return None, None, "Helvetica"


class UnicodePDF:
    """FPDF wrapper with Unicode font support (cross-platform)."""

    def __init__(self):
        from fpdf import FPDF

        self.pdf = FPDF()
        self.pdf.add_page()

        regular, bold, name = resolve_font_paths()
        if name == "DejaVu":
            try:
                self.pdf.add_font("DejaVu", "", regular, uni=True)
                self.pdf.add_font("DejaVu", "B", bold, uni=True)
                self.font_name = "DejaVu"
            except Exception:
                self.font_name = "Helvetica"
                print("Warning: DejaVu font registration failed. Using Helvetica (ASCII only).")
        else:
            self.font_name = "Helvetica"
            print("Warning: DejaVu font not found. Using Helvetica (ASCII only).")

        self.pdf.set_font(self.font_name, size=11)

    def set_bold(self, size=12):
        self.pdf.set_font(self.font_name, "B", size)

    def set_normal(self, size=11):
        self.pdf.set_font(self.font_name, "", size)

    def multi_cell(self, w, h, txt):
        if self.font_name == "Helvetica":
            txt = txt.encode("ascii", "ignore").decode("ascii")
        self.pdf.multi_cell(w, h, txt, new_x="LMARGIN", new_y="NEXT")

    def ln(self, h):
        self.pdf.ln(h)

    def output(self, path):
        self.pdf.output(path)
