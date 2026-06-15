"""
clean_jobs.py — Cleans LIVE_Remote_Jobs_Tracker.xlsx

Fixes:
  1. Extracts company name from URL when company is 'Unknown' or blank
  2. Strips HTML tags from summary column → plain text (truncated to 300 chars)
  3. Removes 'Listing from X' placeholder summaries → blank
  4. Deduplicates tags (e.g. 'Developer, Developer, git, git' → 'Developer, git')
  5. Flags and removes senior/lead/director roles (saved to separate sheet)

Usage:
  python clean_jobs.py
  python clean_jobs.py --input path/to/file.xlsx --output cleaned.xlsx --keep-senior
"""

import re
import html
import argparse
from urllib.parse import urlparse
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from copy import copy

# ── Config ────────────────────────────────────────────────────────────────────

SENIOR_PATTERN = re.compile(
    r'\b(senior|sr\.|lead|principal|staff|architect|director|manager|'
    r'vp|head\s+of|cto|ceo|founder|co-founder)\b',
    re.IGNORECASE
)

# URL patterns to extract company name from
URL_EXTRACTORS = [
    # arbeitnow: /companies/<slug>/
    (re.compile(r'arbeitnow\.com/jobs/companies/([^/]+)/'), 'arbeitnow'),
    # landing.jobs: /at/<company-slug>/
    (re.compile(r'landing\.jobs/at/([^/]+)/'), 'landing.jobs'),
    # arc.dev: /remote-jobs/j/<company>-<title>  (trickier, skip)
    # wellfound/angel.co: /company/<slug>
    (re.compile(r'wellfound\.com/jobs/at/([^/]+)/'), 'wellfound'),
    (re.compile(r'angel\.co/company/([^/]+)/'), 'angel'),
    # remotive: /remote-jobs/<cat>/<title>  — company in data, skip
    # jobspresso: /remote-work/<title>  — no company in URL
    # himalayas: /jobs/<company>/<title>
    (re.compile(r'himalayas\.app/jobs/([^/]+)/'), 'himalayas'),
    # remoteok company sometimes in URL
    (re.compile(r'remoteok\.com/remote-jobs/([^-\d][^/]+)/'), 'remoteok'),
]


def extract_company_from_url(url: str) -> str:
    """Try to extract a readable company name from a job URL."""
    if not url:
        return ""
    for pattern, _ in URL_EXTRACTORS:
        m = pattern.search(url)
        if m:
            slug = m.group(1)
            # Convert slug to title case, remove trailing numbers
            name = re.sub(r'-\d+$', '', slug)
            name = name.replace('-', ' ').replace('_', ' ').title()
            # Clean common junk
            name = re.sub(r'\s+(Gmbh|Ltd|Llc|Inc|Corp|Pvt)$', 
                         lambda x: ' ' + x.group(1).upper(), name, flags=re.I)
            return name.strip()
    return ""


def clean_html(text: str, max_len: int = 300) -> str:
    """Strip HTML tags and return clean plain text."""
    if not text:
        return ""
    # Unescape HTML entities
    text = html.unescape(text)
    # Replace block tags with spaces
    text = re.sub(r'<(br|p|div|li|h\d)[^>]*>', ' ', text, flags=re.I)
    # Remove all remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Truncate
    if len(text) > max_len:
        text = text[:max_len].rsplit(' ', 1)[0] + '…'
    return text


def clean_tags(tags: str) -> str:
    """Remove duplicate tags while preserving order."""
    if not tags:
        return ""
    parts = [t.strip() for t in tags.split(',')]
    seen = set()
    unique = []
    for p in parts:
        key = p.lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return ', '.join(unique)


def is_senior_role(title: str) -> bool:
    return bool(title and SENIOR_PATTERN.search(title))


def style_header_row(ws):
    """Apply header styling."""
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, name="Arial", size=10)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)


# ── Main ──────────────────────────────────────────────────────────────────────

def clean_jobs(input_path: str, output_path: str, keep_senior: bool = False):
    print(f"\n📂 Loading: {input_path}")
    wb = openpyxl.load_workbook(input_path)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    headers = list(rows[0])
    data = rows[1:]

    print(f"   {len(data)} rows found")

    # Column indices
    col = {name: i for i, name in enumerate(headers)}
    JOB_TITLE   = col.get('job_title', 0)
    COMPANY     = col.get('company', 1)
    TECH_STACK  = col.get('tech_stack', 3)
    APPLY_URL   = col.get('apply_url', 5)
    SUMMARY     = col.get('summary', 6)

    cleaned = []
    senior_rows = []

    stats = {
        'company_fixed': 0,
        'html_cleaned': 0,
        'placeholder_cleared': 0,
        'tags_deduped': 0,
        'senior_removed': 0,
    }

    for row in data:
        row = list(row)

        # 1. Fix unknown company
        company = str(row[COMPANY]).strip() if row[COMPANY] else ''
        if company.lower() in ('unknown', '', 'none'):
            extracted = extract_company_from_url(str(row[APPLY_URL] or ''))
            if extracted:
                row[COMPANY] = extracted
                stats['company_fixed'] += 1

        # 2. Clean summary
        summary = str(row[SUMMARY]).strip() if row[SUMMARY] else ''
        if summary.startswith('<'):
            row[SUMMARY] = clean_html(summary)
            stats['html_cleaned'] += 1
        elif summary.startswith('Listing from'):
            row[SUMMARY] = ''
            stats['placeholder_cleared'] += 1

        # 3. Deduplicate tags
        tags = str(row[TECH_STACK]).strip() if row[TECH_STACK] else ''
        cleaned_tags = clean_tags(tags)
        if cleaned_tags != tags:
            row[TECH_STACK] = cleaned_tags
            stats['tags_deduped'] += 1

        # 4. Flag senior roles
        title = str(row[JOB_TITLE]).strip() if row[JOB_TITLE] else ''
        if is_senior_role(title):
            senior_rows.append(row)
            stats['senior_removed'] += 1
            if keep_senior:
                cleaned.append(row)
        else:
            cleaned.append(row)

    # ── Write output ──────────────────────────────────────────────────────────

    wb_out = openpyxl.Workbook()

    # Main sheet
    ws_main = wb_out.active
    ws_main.title = "JOBS CLEANED"
    ws_main.append(headers)
    for row in cleaned:
        ws_main.append(row)

    # Senior roles sheet (for reference)
    if senior_rows:
        ws_senior = wb_out.create_sheet("SENIOR ROLES (Removed)")
        ws_senior.append(headers)
        for row in senior_rows:
            ws_senior.append(row)
        style_header_row(ws_senior)
        # Style senior sheet header red
        red_fill = PatternFill(start_color="C00000", end_color="C00000", fill_type="solid")
        for cell in ws_senior[1]:
            cell.fill = red_fill

    # Style main header
    style_header_row(ws_main)

    # Column widths
    col_widths = {
        'job_title': 40, 'company': 25, 'salary': 15,
        'tech_stack': 35, 'timezone': 12, 'apply_url': 50,
        'summary': 60, 'posted_date_iso': 15, 'Source': 20
    }
    for i, col_name in enumerate(headers, 1):
        width = col_widths.get(col_name, 20)
        ws_main.column_dimensions[
            openpyxl.utils.get_column_letter(i)
        ].width = width

    # Freeze header row
    ws_main.freeze_panes = "A2"

    wb_out.save(output_path)

    # ── Stats ─────────────────────────────────────────────────────────────────
    print(f"\n✅ Done! Saved to: {output_path}")
    print(f"\n📊 Cleanup Summary:")
    print(f"   Original rows       : {len(data)}")
    print(f"   Cleaned rows        : {len(cleaned)}")
    print(f"   Companies fixed     : {stats['company_fixed']}")
    print(f"   HTML summaries fixed: {stats['html_cleaned']}")
    print(f"   Placeholders cleared: {stats['placeholder_cleared']}")
    print(f"   Tags deduplicated   : {stats['tags_deduped']}")
    print(f"   Senior roles removed: {stats['senior_removed']} (saved to 'SENIOR ROLES' sheet)")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean Remote Jobs Tracker xlsx")
    parser.add_argument("--input",  default="LIVE_Remote_Jobs_Tracker.xlsx")
    parser.add_argument("--output", default="LIVE_Remote_Jobs_Tracker_CLEANED.xlsx")
    parser.add_argument("--keep-senior", action="store_true",
                        help="Keep senior/lead roles instead of moving them out")
    args = parser.parse_args()

    clean_jobs(args.input, args.output, keep_senior=args.keep_senior)