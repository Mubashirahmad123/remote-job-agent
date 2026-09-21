import os
import json
from datetime import datetime
from typing import Optional

def get_applied_sheet(sheets_client):
    """Get or create the APPLIED tab in Google Sheets."""
    try:
        return sheets_client.worksheet("APPLIED")
    except Exception:
        sheet = sheets_client.add_worksheet(title="APPLIED", rows=1000, cols=12)
        headers = [
            "job_title", "company", "apply_url", "match_score",
            "applied_date", "status", "follow_up_date", "notes",
            "source", "salary", "contact", "last_updated"
        ]
        sheet.append_row(headers)
        return sheet


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
) -> dict:
    """
    Mark a job as applied. Adds a row to the APPLIED sheet.
    Returns the entry dict.
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
    sheet.append_row(entry)
    return {
        "job_title": job_title,
        "company": company,
        "apply_url": apply_url,
        "applied_date": entry[4],
        "follow_up_date": follow_up_date,
        "status": "applied",
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
    updated_col = col.get("last_updated")

    if not url_col or not status_col or not updated_col:
        return False

    for i, row in enumerate(rows[1:], start=2):  # start=2 because row 1 is header
        if len(row) > url_col - 1 and row[url_col - 1] == apply_url:
            sheet.update_cell(i, status_col, new_status)
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