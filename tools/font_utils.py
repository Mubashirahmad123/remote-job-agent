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
    """FPDF wrapper with Unicode font support and ATS-friendly design utilities."""

    # Color Palette (Slate/Navy theme)
    COLOR_PRIMARY = (15, 23, 42)      # Deep Slate/Navy (#0F172A)
    COLOR_SECONDARY = (30, 58, 138)  # Accent Blue (#1E3A8A)
    COLOR_TEXT = (51, 65, 85)         # Body Text (#334155)
    COLOR_MUTED = (100, 116, 139)     # Subtitle/Dates (#64748B)
    COLOR_DIVIDER = (203, 213, 225)   # Horizontal Line (#CBD5E1)

    def __init__(self, margin=12):
        from fpdf import FPDF

        self.pdf = FPDF()
        self.margin = margin
        self.pdf.set_margins(margin, margin, margin)
        self.pdf.set_auto_page_break(auto=True, margin=margin)
        self.pdf.add_page()

        regular, bold, name = resolve_font_paths()
        if name == "DejaVu":
            try:
                self.pdf.add_font("DejaVu", "", regular, uni=True)
                self.pdf.add_font("DejaVu", "B", bold, uni=True)
                self.pdf.add_font("DejaVu", "I", regular, uni=True) # Italic fallback to regular if needed
                self.font_name = "DejaVu"
            except Exception:
                self.font_name = "Helvetica"
                print("Warning: DejaVu font registration failed. Using Helvetica (ASCII only).")
        else:
            self.font_name = "Helvetica"
            print("Warning: DejaVu font not found. Using Helvetica (ASCII only).")

        self.set_normal(10)
        self.use_text_color(self.COLOR_TEXT)

    def get_printable_width(self):
        """Get width between margins."""
        return self.pdf.w - (2 * self.margin)

    def use_text_color(self, color_tuple):
        """Set text RGB color."""
        self.pdf.set_text_color(*color_tuple)

    def use_draw_color(self, color_tuple):
        """Set drawing RGB color for lines."""
        self.pdf.set_draw_color(*color_tuple)

    def set_bold(self, size=11):
        self.pdf.set_font(self.font_name, "B", size)

    def set_normal(self, size=10):
        self.pdf.set_font(self.font_name, "", size)

    def set_italic(self, size=10):
        # Fall back gracefully if italic isn't loaded separately
        try:
            self.pdf.set_font(self.font_name, "I", size)
        except Exception:
            self.pdf.set_font(self.font_name, "", size)

    def _sanitize(self, txt: str) -> str:
        if self.font_name == "Helvetica":
            return txt.encode("ascii", "ignore").decode("ascii")
        return txt

    def multi_cell(self, w, h, txt, align='L'):
        txt = self._sanitize(txt)
        self.pdf.multi_cell(w, h, txt, align=align, new_x="LMARGIN", new_y="NEXT")

    def cell(self, w, h, txt, align='L', new_line=False):
        txt = self._sanitize(txt)
        new_x = "LMARGIN" if new_line else "RIGHT"
        new_y = "NEXT" if new_line else "TOP"
        self.pdf.cell(w, h, txt, align=align, new_x=new_x, new_y=new_y)

    def ln(self, h=2):
        self.pdf.ln(h)

    def draw_divider_line(self, thickness=0.4, color=None):
        """Draw a horizontal divider line across printable width."""
        color = color or self.COLOR_DIVIDER
        self.use_draw_color(color)
        self.pdf.set_line_width(thickness)
        y = self.pdf.get_y()
        x1 = self.margin
        x2 = self.pdf.w - self.margin
        self.pdf.line(x1, y, x2, y)

    def add_header(self, name, title="", contact_info=None):
        """Render prominent ATS candidate name and contact bar."""
        # Candidate Name
        self.set_bold(18)
        self.use_text_color(self.COLOR_PRIMARY)
        self.cell(0, 8, name.upper(), align='C', new_line=True)
        
        # Subtitle / Professional Title
        if title:
            self.set_normal(10.5)
            self.use_text_color(self.COLOR_SECONDARY)
            self.cell(0, 5, title, align='C', new_line=True)
            self.ln(1)

        # Contact Info Bar (e.g. Email | Phone | Location | LinkedIn)
        if contact_info:
            if isinstance(contact_info, list):
                contact_str = "  |  ".join([c for c in contact_info if c])
            else:
                contact_str = str(contact_info)
            self.set_normal(9)
            self.use_text_color(self.COLOR_MUTED)
            self.cell(0, 5, contact_str, align='C', new_line=True)

        self.ln(3)
        self.draw_divider_line(0.5, self.COLOR_PRIMARY)
        self.ln(4)

    def add_section_header(self, title):
        """Render ATS standard uppercase section header with horizontal rule."""
        self.ln(2)
        self.set_bold(11)
        self.use_text_color(self.COLOR_SECONDARY)
        self.cell(0, 6, title.upper(), align='L', new_line=True)
        self.ln(1)
        self.draw_divider_line(0.3, self.COLOR_DIVIDER)
        self.ln(3)

    def add_experience_header(self, role, company, dates="", location=""):
        """Render role/company on left, dates/location right-aligned."""
        printable_w = self.get_printable_width()
        
        # Left side: Role (Bold), Company (Regular/Italic)
        self.set_bold(10)
        self.use_text_color(self.COLOR_PRIMARY)
        role_txt = self._sanitize(role)
        
        comp_txt = f"  •  {self._sanitize(company)}" if company else ""
        left_txt = f"{role_txt}{comp_txt}"
        
        # Right side: Dates & Location
        right_parts = [p for p in [dates, location] if p]
        right_txt = self._sanitize(" | ".join(right_parts))
        
        # Compute widths
        self.set_bold(10)
        left_w = self.pdf.get_string_width(left_txt) + 4
        self.set_normal(9)
        right_w = self.pdf.get_string_width(right_txt) + 4
        
        # Draw Left
        self.set_bold(10)
        self.use_text_color(self.COLOR_PRIMARY)
        self.pdf.cell(left_w, 5, left_txt, align='L')
        
        # Draw Right (aligned to right margin)
        if right_txt:
            self.set_normal(9)
            self.use_text_color(self.COLOR_MUTED)
            remaining_w = printable_w - left_w
            if remaining_w > right_w:
                self.pdf.cell(remaining_w, 5, right_txt, align='R', new_x="LMARGIN", new_y="NEXT")
            else:
                self.pdf.ln(5)
                self.pdf.cell(0, 4, right_txt, align='R', new_x="LMARGIN", new_y="NEXT")
        else:
            self.pdf.ln(5)
        self.ln(1)

    def add_bullet(self, text, bullet_char="•", font_size=9.5, line_height=4.2):
        """Render bullet point with proper hanging indent."""
        self.set_normal(font_size)
        self.use_text_color(self.COLOR_TEXT)
        
        bullet_indent = 4
        bullet_w = 4
        text_w = self.get_printable_width() - bullet_indent - bullet_w
        
        y_start = self.pdf.get_y()
        # Draw bullet character
        self.pdf.set_x(self.margin + bullet_indent)
        self.pdf.cell(bullet_w, line_height, self._sanitize(bullet_char), align='L')
        
        # Draw bullet text with hanging indent
        self.pdf.set_x(self.margin + bullet_indent + bullet_w)
        self.multi_cell(text_w, line_height, text, align='L')
        self.ln(1)

    @property
    def page_count(self):
        return len(self.pdf.pages)

    def output(self, path):
        self.pdf.output(path)

