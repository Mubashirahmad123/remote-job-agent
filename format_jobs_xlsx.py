"""
format_jobs_xlsx.py — Production Excel formatter for Remote Job Agent exports

Takes the raw xlsx export from Google Sheets and applies clean formatting:
  - Wrapped text + sane row heights
  - Frozen header row
  - Bold styled header with background color
  - Auto-sized columns (capped at sensible max widths)
  - Clickable hyperlinks for apply_url
  - Color-coded match_score bands (🔥 Top / ✅ Good / 🟡 Potential / ❌ Reject)
  - Truncated summary preview (full text still in cell, just visually capped via wrap)

Usage:
    python format_jobs_xlsx.py input.xlsx output.xlsx
    python format_jobs_xlsx.py input.xlsx              # overwrites input in place
"""

import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


# ─── Style constants ───────────────────────────────────────────────────────────
HEADER_FILL = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

TOP_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")     # green
GOOD_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")    # yellow
POTENTIAL_FILL = PatternFill(start_color="FFE0B2", end_color="FFE0B2", fill_type="solid")  # orange
REJECT_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")  # red

LINK_FONT = Font(name="Calibri", size=10, color="2563EB", underline="single")
BODY_FONT = Font(name="Calibri", size=10)

THIN_BORDER = Border(
    left=Side(style="thin", color="D1D5DB"),
    right=Side(style="thin", color="D1D5DB"),
    top=Side(style="thin", color="D1D5DB"),
    bottom=Side(style="thin", color="D1D5DB"),
)

# Score thresholds — tuned for the local keyword-based scorer (see cv_matcher.py)
SCORE_BANDS = [
    (80, 101, TOP_FILL),        # 80-100  → Top match
    (60, 80, GOOD_FILL),        # 60-79   → Good match
    (45, 60, POTENTIAL_FILL),   # 45-59   → Potential match
    (0, 45, REJECT_FILL),       # 0-44    → Reject
]

# Column width caps — prevents one long URL/summary from blowing out the sheet
MAX_COL_WIDTH = 60
MIN_COL_WIDTH = 10
WRAP_COLUMNS = {"summary", "job_title", "tech_stack", "match_reason", "company"}
TRUNCATE_DISPLAY_COLUMNS = {"summary": 180}  # chars shown before wrap kicks in fully


def _fill_for_score(score) -> PatternFill | None:
    try:
        score = int(float(score))
    except (TypeError, ValueError):
        return None
    for lo, hi, fill in SCORE_BANDS:
        if lo <= score < hi:
            return fill
    return None


def _autosize_columns(ws: Worksheet, header: list[str]):
    """Set sensible column widths based on header name and content sampling."""
    for col_idx, col_name in enumerate(header, start=1):
        letter = get_column_letter(col_idx)
        name = (col_name or "").lower()

        if name in ("apply_url",):
            width = 28  # show as "Apply →" link width, not full URL
        elif name in ("summary",):
            width = 50
        elif name in ("job_fingerprint", "scraped_at", "posted_date_iso", "applied_at"):
            width = 18
        elif name in ("match_reason", "tech_stack"):
            width = 40
        elif name in ("job_title", "company"):
            width = 28
        elif name in ("match_score",):
            width = 10
        else:
            width = 16

        ws.column_dimensions[letter].width = min(max(width, MIN_COL_WIDTH), MAX_COL_WIDTH)


def _style_header(ws: Worksheet, header: list[str]):
    for col_idx in range(1, len(header) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"


def _style_body(ws: Worksheet, header: list[str], max_row: int):
    name_to_idx = {name: i + 1 for i, name in enumerate(header)}
    url_idx = name_to_idx.get("apply_url")
    score_idx = name_to_idx.get("match_score")

    for row_idx in range(2, max_row + 1):
        # Determine row fill based on match_score (if present)
        row_fill = None
        if score_idx:
            score_val = ws.cell(row=row_idx, column=score_idx).value
            row_fill = _fill_for_score(score_val)

        for col_idx, col_name in enumerate(header, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            name = (col_name or "").lower()

            cell.font = BODY_FONT
            cell.border = THIN_BORDER
            cell.alignment = Alignment(
                wrap_text=name in WRAP_COLUMNS,
                vertical="top",
                horizontal="left",
            )

            if row_fill and name == "match_score":
                cell.fill = row_fill
                cell.font = Font(name="Calibri", size=10, bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center")

        # Hyperlink the apply_url column
        if url_idx:
            url_cell = ws.cell(row=row_idx, column=url_idx)
            url_val = url_cell.value
            if url_val and isinstance(url_val, str) and url_val.startswith("http"):
                url_cell.hyperlink = url_val
                url_cell.value = "Apply →"
                url_cell.font = LINK_FONT
                url_cell.alignment = Alignment(horizontal="center", vertical="center")

        # Row height — enough for wrapped summary text without being huge
        ws.row_dimensions[row_idx].height = 60


def format_worksheet(ws: Worksheet):
    """Apply full formatting to a single worksheet."""
    if ws.max_row < 1:
        return

    header = [c.value for c in ws[1]]
    if not header or all(h is None for h in header):
        return

    print(f"  Formatting '{ws.title}' ({ws.max_row - 1} data rows)...")

    _autosize_columns(ws, header)
    _style_header(ws, header)

    if ws.max_row > 1:
        _style_body(ws, header, ws.max_row)


def format_workbook(input_path: str, output_path: str):
    print(f"📂 Loading {input_path}...")
    wb = openpyxl.load_workbook(input_path)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        format_worksheet(ws)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"✅ Saved formatted workbook to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python format_jobs_xlsx.py input.xlsx [output.xlsx]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file

    format_workbook(input_file, output_file)