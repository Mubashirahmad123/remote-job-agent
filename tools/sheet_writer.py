import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so that 'tools' package is importable
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import gspread
from google.oauth2.service_account import Credentials
import traceback
from datetime import datetime
from dotenv import load_dotenv
from tools.deduplicator import add_job_fingerprint, job_fingerprint, normalize_url
from datetime import datetime, timedelta


load_dotenv()

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Updated columns to match scraper output
COLUMNS = [
    "job_title", "company", "salary", "tech_stack", "timezone", "apply_url", "summary", "posted_date_iso",
    "source", "match_score", "match_reason", "scraped_at", "status", "job_fingerprint"
]

ALL_JOBS_SHEET = "ALL JOBS"
TOP_MATCHES_SHEET = "TOP MATCHES"
GOOD_MATCHES_SHEET = "GOOD MATCHES"
APPLIED_SHEET = "APPLIED"
STATS_SHEET = "STATS"
LEGACY_SHEET = "LIVE Remote Jobs Tracker"

APPLIED_COLUMNS = COLUMNS + ["applied_at", "notes"]
STATS_COLUMNS = ["run_at", "total_processed", "new_jobs_added", "duplicates_skipped", "top_matches", "good_matches"]



DATE_PARSE_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%b %d, %Y",
    "%B %d, %Y",
]

def _parse_date_cell(value):
    """Try multiple date formats; return a datetime or None."""
    if not value or not value.strip():
        return None
    s = value.strip()
    for fmt in DATE_PARSE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        from dateutil import parser
        return parser.parse(s)
    except Exception:
        return None


def remove_old_jobs_from_sheet(worksheet, days=30):
    """
    Remove jobs older than X days based on posted_date_iso.
    Keeps header row intact. Rows with unparseable/missing dates are kept.
    """

    data = worksheet.get_all_values()

    if len(data) <= 1:
        return

    header = data[0]

    try:
        date_idx = header.index("posted_date_iso")
    except ValueError:
        print("posted_date_iso column not found")
        return

    cutoff = datetime.now() - timedelta(days=days)

    kept = [header]
    removed = 0

    for row in data[1:]:
        try:
            if len(row) <= date_idx:
                kept.append(row)
                continue

            date_str = row[date_idx].strip() if row[date_idx] else ""
            if not date_str:
                kept.append(row)
                continue

            posted_date = _parse_date_cell(date_str)

            if posted_date is None:
                kept.append(row)
                continue

            if posted_date >= cutoff:
                kept.append(row)
            else:
                removed += 1

        except Exception:
            kept.append(row)
            continue

    if removed > 0:
        worksheet.clear()
        worksheet.append_rows(kept)
        print(f"[CLEANUP] Removed {removed} jobs older than {days} days")

def test_environment():
    """Test if environment variables are properly set"""
    print("🔍 Testing environment setup...")
    
    service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT")
    sheets_id = os.getenv("GOOGLE_SHEETS_ID")
    
    print(f"Google Service Account: {service_account}")
    print(f"Google Sheets ID: {sheets_id}")
    
    if not service_account:
        print("❌ GOOGLE_SERVICE_ACCOUNT environment variable not set!")
        return False
    
    if not sheets_id:
        print("❌ GOOGLE_SHEETS_ID environment variable not set!")
        return False
    
    if not os.path.exists(service_account):
        print(f"❌ Service account file not found: {service_account}")
        return False
    
    print("✅ Environment variables are properly set!")
    return True

def get_sheet():
    """Get the Google Sheet connection"""
    try:
        creds = Credentials.from_service_account_file(
            os.getenv("GOOGLE_SERVICE_ACCOUNT"), scopes=SCOPE
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(os.getenv("GOOGLE_SHEETS_ID"))
        print(f"✅ Connected to spreadsheet: {sheet.title}")
        return sheet
    except Exception as e:
        print(f"❌ Failed to connect to Google Sheet: {e}")
        raise

def get_or_create_worksheet(spreadsheet, title, rows=1000, cols=20):
    """Get existing worksheet or create new one"""
    try:
        worksheet = spreadsheet.worksheet(title)
        print(f"✅ Found existing worksheet: {title}")
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        print(f"⚠️ Worksheet '{title}' not found. Creating it...")
        worksheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
        print(f"✅ Created new worksheet: {title}")
        return worksheet

def ensure_header(worksheet, columns):
    """Ensure a worksheet has the expected header row."""
    existing = worksheet.get_all_values()
    if not existing:
        worksheet.insert_row(columns, index=1)
        return [columns]

    header_correct = len(existing[0]) >= len(columns) and all(col in existing[0] for col in columns)
    if not header_correct:
        worksheet.update('A1:' + chr(ord('A') + len(columns) - 1) + '1', [columns])
        existing[0] = columns

    return existing

def ensure_dashboard_tabs(spreadsheet):
    """Create the Smart Sheet dashboard tabs and headers."""
    worksheets = {
        TOP_MATCHES_SHEET: get_or_create_worksheet(spreadsheet, TOP_MATCHES_SHEET),
        GOOD_MATCHES_SHEET: get_or_create_worksheet(spreadsheet, GOOD_MATCHES_SHEET),
        ALL_JOBS_SHEET: get_or_create_worksheet(spreadsheet, ALL_JOBS_SHEET),
        APPLIED_SHEET: get_or_create_worksheet(spreadsheet, APPLIED_SHEET),
        STATS_SHEET: get_or_create_worksheet(spreadsheet, STATS_SHEET),
    }

    for title in (TOP_MATCHES_SHEET, GOOD_MATCHES_SHEET, ALL_JOBS_SHEET):
        ensure_header(worksheets[title], COLUMNS)
    ensure_header(worksheets[APPLIED_SHEET], APPLIED_COLUMNS)
    ensure_header(worksheets[STATS_SHEET], STATS_COLUMNS)

    return worksheets

def score_as_int(job):
    """Return a numeric match score, or 0 when score is missing/invalid."""
    try:
        return int(job.get("match_score") or 0)
    except (TypeError, ValueError):
        return 0

def prepare_job_for_sheet(job, timestamp):
    """Fill dashboard metadata before converting a job to a sheet row."""
    add_job_fingerprint(job)
    job.setdefault("source", "")
    job.setdefault("scraped_at", timestamp)
    job.setdefault("status", "new")
    return job

def job_to_row(job):
    """Convert a job dictionary to a Google Sheets row."""
    row_data = []
    for col in COLUMNS:
        value = job.get(col, "")
        if value is None:
            value = ""
        else:
            value = str(value).strip()
        row_data.append(value)
    return row_data

def test_connection():
    """Test the Google Sheets connection"""
    print("\n🔗 Testing Google Sheets connection...")
    
    try:
        if not test_environment():
            return False
        
        sheet = get_sheet()
        worksheets = ensure_dashboard_tabs(sheet)
        worksheet = worksheets[ALL_JOBS_SHEET]
        
        # Try to read current data
        data = worksheet.get_all_values()
        print(f"📊 Current sheet has {len(data)} rows")
        
        if data:
            print(f"📋 Header row: {data[0] if data else 'No data'}")
        
        print("✅ Connection test successful!")
        return True
        
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        traceback.print_exc()
        return False

def append_rows(rows):
    """
    Add job rows to Google Sheet with comprehensive error handling and duplicate checking
    """
    print(f"\n📊 Processing {len(rows)} jobs for Google Sheet...")
    
    if not rows:
        print("❌ No rows received to process!")
        return
    
    # Validate first job structure
    if rows:
        sample_job = rows[0]
        print(f"📋 Sample job keys: {list(sample_job.keys())}")
        missing_cols = [col for col in COLUMNS if col not in sample_job]
        if missing_cols:
            print(f"⚠️ Warning: Missing columns in job data: {missing_cols}")
    
    try:
        # Test connection first
        if not test_environment():
            print("❌ Environment test failed - cannot proceed")
            return
        
        # Get sheet and dashboard worksheets
        sheet = get_sheet()
        worksheets = ensure_dashboard_tabs(sheet)
        worksheet = worksheets[ALL_JOBS_SHEET]
        
        # Get existing data
        existing = worksheet.get_all_values()
        print(f"📋 Sheet currently has {len(existing)} rows")
        
        # Handle empty sheet
        if not existing:
            print("🟢 Empty sheet - adding header row...")
            worksheet.insert_row(COLUMNS, index=1)
            existing = [COLUMNS]
            print(f"✅ Header added: {COLUMNS}")
            # Initialize empty URL set for new sheet
            present_urls = set()
            present_fingerprints = set()
            url_idx = COLUMNS.index("apply_url")
        else:
            # Check header correctness
            header_correct = len(existing[0]) >= len(COLUMNS) and all(col in existing[0] for col in COLUMNS)
            
            if not header_correct:
                print("🟢 Fixing header row...")
                # Update only the header row, don't touch data
                worksheet.update('A1:' + chr(ord('A') + len(COLUMNS) - 1) + '1', [COLUMNS])
                existing[0] = COLUMNS  # Update header in memory, keep all other rows
                print(f"✅ Header updated: {COLUMNS}")
            
            # Find the index of apply_url column for duplicate checking
            try:
                url_idx = existing[0].index("apply_url")
                print(f"🔍 Found apply_url at column index: {url_idx}")
            except ValueError:
                print("❌ 'apply_url' column not found in header!")
                return

            try:
                fingerprint_idx = existing[0].index("job_fingerprint")
                print(f"Found job_fingerprint at column index: {fingerprint_idx}")
            except ValueError:
                fingerprint_idx = None
            
            # Build set of existing URLs and fingerprints
            present_urls = set()
            present_fingerprints = set()
            for i, row in enumerate(existing[1:], 2):  # Skip header, start from row 2
                if row and len(row) > url_idx and row[url_idx]:
                    # Normalize URL by removing query parameters
                    normalized_url = normalize_url(row[url_idx])
                    if normalized_url:
                        present_urls.add(normalized_url)

                if fingerprint_idx is not None and row and len(row) > fingerprint_idx and row[fingerprint_idx]:
                    present_fingerprints.add(row[fingerprint_idx].strip())
                elif row:
                    existing_job = {
                        existing[0][col_idx]: value
                        for col_idx, value in enumerate(row)
                        if col_idx < len(existing[0])
                    }
                    if existing_job.get("job_title") or existing_job.get("apply_url"):
                        present_fingerprints.add(job_fingerprint(existing_job))
            
            print(f"🔍 Found {len(present_urls)} existing unique URLs in sheet")

        # Process new jobs
        new_values = []
        new_jobs = []
        duplicates = 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for i, job in enumerate(rows, 1):
            prepare_job_for_sheet(job, timestamp)
            job_title = job.get("job_title", "No Title")
            job_url = normalize_url(job.get("apply_url", ""))
            fingerprint = job.get("job_fingerprint", "")
            
            if not job_url:
                print(f"⚠️ Job {i}: '{job_title}' - No URL, skipping")
                continue
                
            if job_url in present_urls:
                print(f"⚠️ Job {i}: '{job_title}' - DUPLICATE (URL exists)")
                duplicates += 1
                continue
            
            if fingerprint in present_fingerprints:
                print(f"Job {i}: '{job_title}' - DUPLICATE (fingerprint exists)")
                duplicates += 1
                continue

            row_data = job_to_row(job)
            
            new_values.append(row_data)
            new_jobs.append(job)
            present_urls.add(job_url)  # Add to set to avoid duplicates within this batch
            present_fingerprints.add(fingerprint)
            print(f"✅ Job {i}: '{job_title}' - ADDED")

        # Add new jobs to sheet
        if new_values:
            print(f"\n📝 Attempting to add {len(new_values)} new jobs to sheet...")
            
            print(f"⏰ Timestamp: {timestamp}")
            
            # Append rows in batches to avoid API limits
            batch_size = 100
            for i in range(0, len(new_values), batch_size):
                batch = new_values[i:i + batch_size]
                worksheet.append_rows(batch)
                print(f"📤 Added batch {i//batch_size + 1}: {len(batch)} rows")
                if i + batch_size < len(new_values):
                    import time
                    time.sleep(1)

            top_jobs = sorted(
                [job for job in new_jobs if score_as_int(job) >= 85],
                key=score_as_int,
                reverse=True,
            )
            good_jobs = sorted(
                [job for job in new_jobs if 70 <= score_as_int(job) < 85],
                key=score_as_int,
                reverse=True,
            )

            if top_jobs:
                worksheets[TOP_MATCHES_SHEET].append_rows([job_to_row(job) for job in top_jobs])
                print(f"Added {len(top_jobs)} jobs to {TOP_MATCHES_SHEET}")

            if good_jobs:
                worksheets[GOOD_MATCHES_SHEET].append_rows([job_to_row(job) for job in good_jobs])
                print(f"Added {len(good_jobs)} jobs to {GOOD_MATCHES_SHEET}")

            worksheets[STATS_SHEET].append_row([
                timestamp,
                len(rows),
                len(new_values),
                duplicates,
                len(top_jobs),
                len(good_jobs),
            ])
            
            print(f"✅ Successfully added {len(new_values)} new jobs to Google Sheet!")
            
        else:
            print("ℹ️ No new unique jobs to add")

        # Always clean old jobs, even when no new jobs were added
        for ws_name in (ALL_JOBS_SHEET, TOP_MATCHES_SHEET, GOOD_MATCHES_SHEET):
            ws = worksheets[ws_name]
            remove_old_jobs_from_sheet(ws, days=30)

        # Also clean legacy sheet if it still exists
        try:
            legacy_ws = sheet.worksheet(LEGACY_SHEET)
            remove_old_jobs_from_sheet(legacy_ws, days=30)
        except gspread.exceptions.WorksheetNotFound:
            pass

        # Apply formatting
        try:
            format_dashboard_worksheets(worksheets, sheet)
        except Exception as e:
            print(f"⚠️ Formatting failed (non-fatal): {e}")

        # Summary
        print(f"\n📊 SUMMARY:")
        print(f"   • Total jobs processed: {len(rows)}")
        print(f"   • New jobs added: {len(new_values)}")
        print(f"   • Duplicates skipped: {duplicates}")
        print(f"   • Sheet now has: {len(existing) + len(new_values)} total rows")
            
    except Exception as e:
        print(f"❌ Error in append_rows: {e}")
        traceback.print_exc()

def append_rows_simple(rows):
    """
    Simple version - adds all jobs without duplicate checking (for testing)
    """
    print(f"📊 Simple mode: Adding {len(rows)} jobs...")
    
    if not rows:
        print("No jobs to add!")
        return
    
    try:
        # Connect to sheet
        sheet = get_sheet()
        worksheets = ensure_dashboard_tabs(sheet)
        worksheet = worksheets[ALL_JOBS_SHEET]
        
        # Get existing data
        existing_data = worksheet.get_all_values()
        
        # Add header if sheet is empty
        if not existing_data:
            worksheet.insert_row(COLUMNS, 1)
            print("Added header row")
        
        # Convert jobs to rows
        new_rows = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for job in rows:
            prepare_job_for_sheet(job, timestamp)
            new_rows.append(job_to_row(job))
        
        if new_rows:
            worksheet.append_rows(new_rows)
            print(f"✅ Added {len(new_rows)} jobs to sheet! (Simple mode)")
        
    except Exception as e:
        print(f"❌ Simple mode error: {e}")
        traceback.print_exc()

def get_all_rows():
    """
    Fetch all rows from the Google Sheet.
    Returns a list of lists, where each inner list is a row.
    """
    try:
        spreadsheet = get_sheet()
        all_jobs_sheet = get_or_create_worksheet(spreadsheet, ALL_JOBS_SHEET)
        data = all_jobs_sheet.get_all_values()

        if not data:
            try:
                legacy_sheet = spreadsheet.worksheet(LEGACY_SHEET)
                data = legacy_sheet.get_all_values()
            except gspread.exceptions.WorksheetNotFound:
                data = []
        print(f"📊 Retrieved {len(data)} rows from sheet")
        return data
    except Exception as e:
        print(f"❌ Error getting rows: {e}")
        return []

def clear_sheet():
    """
    Clear all data from the sheet (useful for testing)
    """
    try:
        sheet = get_sheet()
        worksheet = get_or_create_worksheet(sheet, "LIVE Remote Jobs Tracker")
        worksheet.clear()
        print("✅ Sheet cleared successfully!")
    except Exception as e:
        print(f"❌ Error clearing sheet: {e}")

def get_sheet_stats():
    """
    Get statistics about the current sheet
    """
    try:
        data = get_all_rows()
        if not data:
            print("📊 Sheet is empty")
            return
        
        print(f"📊 SHEET STATISTICS:")
        print(f"   • Total rows: {len(data)}")
        print(f"   • Header: {data[0] if data else 'None'}")
        
        if len(data) > 1:
            print(f"   • Job entries: {len(data) - 1}")
            print(f"   • Sample job: {data[1][:3] if len(data[1]) >= 3 else data[1]}")
        
        # Count jobs by company
        if len(data) > 1:
            companies = {}
            try:
                company_idx = data[0].index("company") if "company" in data[0] else 1
                for row in data[1:]:
                    if len(row) > company_idx:
                        company = row[company_idx] or "Unknown"
                        companies[company] = companies.get(company, 0) + 1
                
                print(f"   • Top companies: {sorted(companies.items(), key=lambda x: x[1], reverse=True)[:5]}")
            except (ValueError, IndexError):
                print("   • Company stats: Unable to calculate")
        
    except Exception as e:
        print(f"❌ Error getting stats: {e}")

def test_duplicate_detection():
    """
    Test duplicate detection functionality
    """
    print("🧪 Testing duplicate detection...")
    
    # Sample test jobs
    test_jobs = [
        {
            "job_title": "Test Frontend Developer",
            "company": "Test Company A",
            "salary": "$60,000",
            "tech_stack": "React, JavaScript",
            "timezone": "UTC",
            "apply_url": "https://test.com/job/1",
            "summary": "Great opportunity for frontend development",
            "posted_date_iso": "2024-01-01"
        },
        {
            "job_title": "Test Backend Developer", 
            "company": "Test Company B",
            "salary": "",
            "tech_stack": "Python, Django",
            "timezone": "UTC",
            "apply_url": "https://test.com/job/2",
            "summary": "Backend development role",
            "posted_date_iso": "2024-01-01"
        },
        # Duplicate of first job
        {
            "job_title": "Test Frontend Developer (Duplicate)", 
            "company": "Test Company A",
            "salary": "$65,000",
            "tech_stack": "React, JavaScript",
            "timezone": "UTC",
            "apply_url": "https://test.com/job/1",  # Same URL as first job
            "summary": "This should be detected as duplicate",
            "posted_date_iso": "2024-01-01"
        }
    ]
    
    print(f"Adding {len(test_jobs)} test jobs (including 1 duplicate)...")
    append_rows(test_jobs)

# ─── Sheet Formatting ──────────────────────────────────────────────────────────

def format_dashboard_worksheets(worksheets, sheet):
    """Apply professional formatting to all dashboard worksheets."""
    for ws_name in (ALL_JOBS_SHEET, TOP_MATCHES_SHEET, GOOD_MATCHES_SHEET):
        ws = worksheets.get(ws_name)
        if ws:
            _format_single_worksheet(ws)

    try:
        legacy_ws = sheet.worksheet(LEGACY_SHEET)
        _format_single_worksheet(legacy_ws)
    except gspread.exceptions.WorksheetNotFound:
        pass


def _format_single_worksheet(ws):
    """Apply formatting: frozen header, column widths, score colors, hyperlinks."""
    data = ws.get_all_values()
    if not data or len(data) < 1:
        return

    header = data[0]
    num_cols = len(header)
    num_rows = len(data)

    ws.freeze(rows=1)

    col_names = {name.lower(): i for i, name in enumerate(header)}
    end_col = chr(ord("A") + num_cols - 1)

    # 1. Style header row
    ws.format(f"A1:{end_col}1", {
        "backgroundColor": {"red": 0.12, "green": 0.16, "blue": 0.22},
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}, "fontSize": 11},
        "horizontalAlignment": "CENTER",
        "verticalAlignment": "MIDDLE",
    })

    if num_rows <= 1:
        return

    # 2. Style body — font, vertical alignment
    ws.format(f"A2:{end_col}{num_rows}", {
        "textFormat": {"fontSize": 10},
        "verticalAlignment": "TOP",
    })

    # 3. Wrapped-text columns
    for col_name in ("summary", "job_title", "tech_stack", "match_reason", "company"):
        idx = col_names.get(col_name)
        if idx is not None:
            col_letter = chr(ord("A") + idx)
            ws.format(f"{col_letter}2:{col_letter}{num_rows}", {"wrapStrategy": "WRAP"})

    # 4. Style apply_url as a clickable link (keep original URL, just format as link)
    url_idx = col_names.get("apply_url")
    if url_idx is not None:
        url_letter = chr(ord("A") + url_idx)
        ws.format(f"{url_letter}2:{url_letter}{num_rows}", {
            "textFormat": {
                "foregroundColor": {"red": 0.15, "green": 0.39, "blue": 0.92},
                "fontSize": 10,
                "underline": True,
            },
            "horizontalAlignment": "LEFT",
            "verticalAlignment": "MIDDLE",
        })

    # 5. Color-coded rows by match_score
    score_idx = col_names.get("match_score")
    if score_idx is not None:
        score_letter = chr(ord("A") + score_idx)
        score_values = ws.col_values(score_idx + 1)[1:]

        bands = {"top": [], "good": [], "potential": [], "reject": []}
        for i, s in enumerate(score_values):
            row_num = i + 2
            try:
                score = float(s) if s else -1
            except (ValueError, TypeError):
                continue
            if score >= 80:
                bands["top"].append(row_num)
            elif score >= 60:
                bands["good"].append(row_num)
            elif score >= 45:
                bands["potential"].append(row_num)
            else:
                bands["reject"].append(row_num)

        band_styles = [
            ("top",  {"red": 0.78, "green": 0.94, "blue": 0.84}),
            ("good",  {"red": 1.0, "green": 0.92, "blue": 0.61}),
            ("potential", {"red": 1.0, "green": 0.88, "blue": 0.70}),
            ("reject", {"red": 1.0, "green": 0.78, "blue": 0.81}),
        ]
        for band_name, bg in band_styles:
            rows = bands[band_name]
            if not rows:
                continue
            # Compress contiguous rows into ranges to minimise API calls
            ranges = []
            start = end = rows[0]
            for r in rows[1:]:
                if r == end + 1:
                    end = r
                else:
                    ranges.append((start, end))
                    start = end = r
            ranges.append((start, end))

            for start_row, end_row in ranges:
                rng = f"A{start_row}:{end_col}{end_row}"
                ws.format(rng, {"backgroundColor": bg})
            # Bold + centre the score cell for each band row
            for row_num in rows:
                ws.format(f"{score_letter}{row_num}", {
                    "textFormat": {"bold": True},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                })

    # 6. Column widths (pixel approximations) via batch_update
    col_width_px = {
        "apply_url": 120, "summary": 350, "job_fingerprint": 130,
        "scraped_at": 130, "posted_date_iso": 100, "applied_at": 100,
        "match_reason": 250, "tech_stack": 250, "job_title": 200,
        "company": 180, "match_score": 60, "source": 100,
        "salary": 100, "timezone": 100, "status": 80, "notes": 200,
    }
    requests = []
    for col_name, width in col_width_px.items():
        idx = col_names.get(col_name)
        if idx is not None:
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": idx,
                        "endIndex": idx + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            })
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def run_cleanup(days=30):
    """
    Standalone cleanup: remove old jobs from ALL sheets (including legacy).
    Can be called directly or via CLI: python tools/sheet_writer.py --cleanup [days]
    """
    print(f"\n[CLEANUP] Running standalone cleanup - removing jobs older than {days} days...")

    if not test_environment():
        print("[CLEANUP] Environment test failed")
        return

    sheet = get_sheet()
    worksheets = ensure_dashboard_tabs(sheet)

    # Clean main dashboard sheets
    for ws_name in (ALL_JOBS_SHEET, TOP_MATCHES_SHEET, GOOD_MATCHES_SHEET):
        ws = worksheets[ws_name]
        remove_old_jobs_from_sheet(ws, days=days)

    # Clean legacy sheet if it exists
    try:
        legacy_ws = sheet.worksheet(LEGACY_SHEET)
        remove_old_jobs_from_sheet(legacy_ws, days=days)
    except gspread.exceptions.WorksheetNotFound:
        print("[CLEANUP] Legacy sheet not found - skipping")

    # Apply formatting
    try:
        format_dashboard_worksheets(worksheets, sheet)
    except Exception as e:
        print(f"[CLEANUP] Formatting failed (non-fatal): {e}")

    print("[CLEANUP] Cleanup complete!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cleanup":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        run_cleanup(days=days)
    else:
        # Test the connection
        print("🧪 TESTING GOOGLE SHEETS INTEGRATION")
        print("=" * 50)
        
        # Test 1: Environment and connection
        if test_connection():
            print("\n✅ Connection test passed!")
            
            # Test 2: Get current stats
            get_sheet_stats()
            
            # Test 3: Test duplicate detection (uncomment to test)
            # print("\n🧪 Testing duplicate detection...")
            # test_duplicate_detection()
            
        else:
            print("\n❌ Connection test failed!")
            print("Please check your environment variables and service account file.")
