import os
import json
from datetime import datetime
from typing import Optional

APPLIED_HEADERS = [
    "job_title", "company", "apply_url", "match_score",
    "applied_date", "status", "follow_up_date", "notes",
    "source", "salary", "contact", "last_updated",
    # 13th column: who wrote the row (username, or "automation"). Appended last
    # so every pre-existing positional reader of columns A-L is unaffected.
    "created_by",
]

CREATED_BY_COL = len(APPLIED_HEADERS)  # 1-indexed position of `created_by`


def get_applied_sheet(sheets_client):
    """Get or create the APPLIED tab in Google Sheets."""
    try:
        return sheets_client.worksheet("APPLIED")
    except Exception:
        sheet = sheets_client.add_worksheet(
            title="APPLIED", rows=1000, cols=len(APPLIED_HEADERS)
        )
        sheet.append_row(list(APPLIED_HEADERS))
        return sheet


def _ensure_created_by_header(sheet) -> bool:
    """Make sure row 1 has a `created_by` header before writing into that column.

    Returns True when the column is safe to write. Every failure mode returns
    False rather than raising: this is a live user spreadsheet, and losing the
    attribution is strictly better than failing to record an application.

    An existing APPLIED tab predates the column, so the header cell is written
    only when it is genuinely empty — never overwriting a column the user may
    already be using for something else.
    """
    try:
        rows = sheet.get_all_values()
    except Exception:
        return False
    if not rows:
        return False
    header = rows[0]
    existing = [str(h).strip().lower() for h in header]
    if "created_by" in existing:
        return True
    if len(header) >= CREATED_BY_COL:
        # Something else already occupies that column — do not clobber it.
        return False
    try:
        sheet.update_cell(1, CREATED_BY_COL, "created_by")
        return True
    except Exception:
        return False


def mark_applied(
    sheets_client,
    apply_url: str,
    job_title: str = "",
    company: str = "",
    match_score: int = 0,
    notes: str = "",
    source: str = "",
    salary: str = "",
    contact: str = "",
    follow_up_days: int = 7,
    created_by: str = "",
) -> dict:
    """
    Mark a job as applied. Adds a row to the APPLIED sheet.
    Returns the entry dict.

    `created_by` is the attributed actor. It is written as the 13th column when
    the header can be secured, and silently omitted otherwise — a spreadsheet
    whose layout this code cannot safely extend must still get the application
    row. Attribution is best-effort by design; the record is not.
    """
    sheet = get_applied_sheet(sheets_client)

    now = datetime.now()
    follow_up = datetime(now.year, now.month, now.day)
    # Simple follow-up date: today + follow_up_days
    from datetime import timedelta
    follow_up_date = (now + timedelta(days=follow_up_days)).strftime("%Y-%m-%d")

    entry = [
        job_title,
        company,
        apply_url,
        match_score,
        now.strftime("%Y-%m-%d %H:%M"),
        "applied",
        follow_up_date,
        notes,
        source,
        salary,
        contact,
        now.strftime("%Y-%m-%d %H:%M"),
    ]
    actor = (created_by or "").strip()
    # Only extend the row when the header is actually in place; appending a 13th
    # value under an unheaded column would be worse than not writing it.
    if actor and _ensure_created_by_header(sheet):
        entry.append(actor)
    sheet.append_row(entry)
    return {
        "job_title": job_title,
        "company": company,
        "apply_url": apply_url,
        "applied_date": entry[4],
        "follow_up_date": follow_up_date,
        "status": "applied",
        # Echoed only when it was really written, so a caller cannot render an
        # attribution the sheet does not hold.
        **({"created_by": actor} if len(entry) > 12 else {}),
    }


def update_status(sheets_client, apply_url: str, new_status: str, notes: str = "") -> bool:
    """
    Update the status of an application by URL.
    Valid statuses: applied, interviewing, offer, rejected, withdrawn, ghosted
    """
    VALID_STATUSES = {"applied", "interviewing", "offer", "rejected", "withdrawn", "ghosted"}
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{new_status}'. Choose from: {', '.join(VALID_STATUSES)}")

    sheet = get_applied_sheet(sheets_client)
    rows = sheet.get_all_values()

    if not rows:
        return False

    # Find column indices from header (case/whitespace tolerant, no crash on missing)
    headers = [h.strip().lower() for h in rows[0]]
    col = {name: idx + 1 for idx, name in enumerate(headers)}  # 1-indexed for gspread
    url_col = col.get("apply_url")
    status_col = col.get("status")
    notes_col = col.get("notes")
    # Timestamp column is optional: tracker header uses `last_updated`, while
    # the sheet_writer APPLIED_COLUMNS fork (COLUMNS + applied_at/notes) has
    # no last_updated column. Don't fail in that case — just skip the stamp
    # so PATCH /api/tracker works on both header forks.
    updated_col = col.get("last_updated")

    if not url_col or not status_col:
        return False

    for i, row in enumerate(rows[1:], start=2):  # start=2 because row 1 is header
        if len(row) > url_col - 1 and row[url_col - 1] == apply_url:
            sheet.update_cell(i, status_col, new_status)
            if updated_col:
                sheet.update_cell(i, updated_col, datetime.now().strftime("%Y-%m-%d %H:%M"))
            if notes and notes_col:
                existing_notes = row[notes_col - 1] if len(row) >= notes_col else ""
                new_notes = f"{existing_notes} | {notes}".strip(" |")
                sheet.update_cell(i, notes_col, new_notes)
            return True

    return False  # URL not found


def get_stats(sheets_client) -> dict:
    """Return a summary of application pipeline stats."""
    sheet = get_applied_sheet(sheets_client)
    rows = sheet.get_all_values()

    if len(rows) <= 1:
        return {"total": 0, "by_status": {}, "this_week": 0, "response_rate": "0%"}

    headers = [h.strip().lower() for h in rows[0]]
    data = rows[1:]

    status_col = headers.index("status") if "status" in headers else -1
    date_col = -1
    for col_name in ["applied_date", "applied_at", "date", "created_at", "scraped_at"]:
        if col_name in headers:
            date_col = headers.index(col_name)
            break

    status_counts = {}
    this_week = 0
    now = datetime.now()

    for row in data:
        if not row:
            continue
        status = row[status_col] if (status_col != -1 and len(row) > status_col and row[status_col]) else "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

        # Count applications in the last 7 days
        if date_col != -1 and len(row) > date_col and row[date_col]:
            try:
                date_str = str(row[date_col]).strip()[:10]
                applied_date = datetime.strptime(date_str, "%Y-%m-%d")
                if (now - applied_date).days <= 7:
                    this_week += 1
            except Exception:
                pass

    total = len(data)
    responded = sum(v for k, v in status_counts.items() if k in {"interviewing", "offer", "rejected"})
    response_rate = f"{round(responded / total * 100)}%" if total > 0 else "0%"

    return {
        "total": total,
        "by_status": status_counts,
        "this_week": this_week,
        "response_rate": response_rate,
    }


def list_applications(sheets_client, status_filter: Optional[str] = None) -> list:
    """List all applications, optionally filtered by status."""
    sheet = get_applied_sheet(sheets_client)
    rows = sheet.get_all_values()

    if len(rows) <= 1:
        return []

    headers = rows[0]
    data = rows[1:]

    result = []
    for row in data:
        if not row:
            continue
        entry = dict(zip(headers, row))
        if status_filter is None or entry.get("status") == status_filter:
            result.append(entry)

    return result