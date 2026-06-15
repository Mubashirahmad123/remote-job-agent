#!/usr/bin/env python3
"""
Application Tracker CLI
-----------------------
Usage:
  python track.py --apply URL [options]     # Mark a job as applied
  python track.py --status URL STATUS       # Update application status
  python track.py --list [--filter STATUS]  # List applications
  python track.py --stats                   # Show pipeline summary
  python track.py --followups               # Show jobs due for follow-up

Examples:
  python track.py --apply "https://job.url" --title "Backend Dev" --company "Acme" --score 88
  python track.py --status "https://job.url" interviewing --note "Phone screen scheduled"
  python track.py --list --filter interviewing
  python track.py --stats
  python track.py --followups
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── Google Sheets client setup ────────────────────────────────────────────────

def get_sheets_client():
    import gspread
    from google.oauth2.service_account import Credentials

    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT", "keys.json")
    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    sheet_id = os.getenv("GOOGLE_SHEETS_ID")
    return client.open_by_key(sheet_id)


# ── Pretty print helpers ──────────────────────────────────────────────────────

def print_header(text):
    print(f"\n{'─' * 50}")
    print(f"  {text}")
    print(f"{'─' * 50}")

def print_job(entry, index=None):
    prefix = f"[{index}] " if index is not None else ""
    score = entry.get("match_score", "—")
    score_str = f" (score: {score})" if score and score != "0" else ""
    status = entry.get("status", "").upper()
    status_colors = {
        "APPLIED":      "\033[94m",   # blue
        "INTERVIEWING": "\033[93m",   # yellow
        "OFFER":        "\033[92m",   # green
        "REJECTED":     "\033[91m",   # red
        "WITHDRAWN":    "\033[90m",   # gray
        "GHOSTED":      "\033[90m",   # gray
    }
    reset = "\033[0m"
    color = status_colors.get(status, "")

    print(f"\n{prefix}{entry.get('job_title', 'Unknown Role')} @ {entry.get('company', '?')}{score_str}")
    print(f"  Status      : {color}{status}{reset}")
    print(f"  Applied     : {entry.get('applied_date', '—')}")
    print(f"  Follow-up   : {entry.get('follow_up_date', '—')}")
    if entry.get("notes"):
        print(f"  Notes       : {entry['notes']}")
    print(f"  URL         : {entry.get('apply_url', '—')}")


def print_stats(stats):
    print_header("📊 Application Pipeline Stats")
    print(f"  Total applications : {stats['total']}")
    print(f"  Applied this week  : {stats['this_week']}")
    print(f"  Response rate      : {stats['response_rate']}")
    print(f"\n  By Status:")
    for status, count in sorted(stats["by_status"].items()):
        bar = "█" * count
        print(f"    {status:<14} {bar} ({count})")


# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_apply(args, sheets):
    from tools.application_tracker import mark_applied
    result = mark_applied(
        sheets_client=sheets,
        apply_url=args.apply,
        job_title=args.title or "",
        company=args.company or "",
        match_score=args.score or 0,
        notes=args.note or "",
        source=args.source or "",
        salary=args.salary or "",
        contact=args.contact or "",
        follow_up_days=args.followup_days or 7,
    )
    print_header("✅ Application Logged")
    print(f"  Role        : {result['job_title']} @ {result['company']}")
    print(f"  Applied on  : {result['applied_date']}")
    print(f"  Follow-up   : {result['follow_up_date']}")
    print(f"  URL         : {result['apply_url']}")
    print(f"\n  Saved to Google Sheets → APPLIED tab ✓")


def cmd_status(args, sheets):
    from tools.application_tracker import update_status
    found = update_status(
        sheets_client=sheets,
        apply_url=args.status[0],
        new_status=args.status[1],
        notes=args.note or "",
    )
    if found:
        print(f"\n✅ Updated status to '{args.status[1]}' for:\n   {args.status[0]}")
    else:
        print(f"\n❌ URL not found in APPLIED sheet:\n   {args.status[0]}")
        print("   Run `python track.py --list` to see tracked URLs.")


def cmd_list(args, sheets):
    from tools.application_tracker import list_applications
    status_filter = args.filter if hasattr(args, "filter") else None
    apps = list_applications(sheets, status_filter=status_filter)

    if not apps:
        label = f" with status '{status_filter}'" if status_filter else ""
        print(f"\n  No applications found{label}.")
        return

    label = f" — {status_filter.upper()}" if status_filter else ""
    print_header(f"📋 Applications{label} ({len(apps)} total)")
    for i, entry in enumerate(apps, 1):
        print_job(entry, index=i)
    print()


def cmd_stats(args, sheets):
    from tools.application_tracker import get_stats
    stats = get_stats(sheets)
    print_stats(stats)
    print()


def cmd_followups(args, sheets):
    from tools.application_tracker import list_applications
    apps = list_applications(sheets)
    today = datetime.now().date()

    due = []
    for app in apps:
        if app.get("status") in ("applied", "interviewing"):
            try:
                follow_up = datetime.strptime(app["follow_up_date"], "%Y-%m-%d").date()
                if follow_up <= today:
                    days_overdue = (today - follow_up).days
                    app["_days_overdue"] = days_overdue
                    due.append(app)
            except Exception:
                pass

    if not due:
        print("\n  ✅ No follow-ups due today.")
        return

    due.sort(key=lambda x: x["_days_overdue"], reverse=True)
    print_header(f"⏰ Follow-ups Due ({len(due)} jobs)")
    for app in due:
        overdue = app["_days_overdue"]
        label = "today" if overdue == 0 else f"{overdue}d overdue"
        print(f"\n  [{label}] {app.get('job_title', '?')} @ {app.get('company', '?')}")
        print(f"    Status  : {app.get('status', '—')}")
        print(f"    URL     : {app.get('apply_url', '—')}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Remote Job Agent — Application Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Commands (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply",    metavar="URL",           help="Mark a job as applied")
    group.add_argument("--status",   metavar=("URL", "STATUS"), nargs=2, help="Update status for a URL")
    group.add_argument("--list",     action="store_true",     help="List all applications")
    group.add_argument("--stats",    action="store_true",     help="Show pipeline summary")
    group.add_argument("--followups",action="store_true",     help="Show jobs due for follow-up")

    # Options for --apply
    parser.add_argument("--title",        help="Job title")
    parser.add_argument("--company",      help="Company name")
    parser.add_argument("--score",        type=int, help="Match score (0-100)")
    parser.add_argument("--note",         help="Notes to attach")
    parser.add_argument("--source",       help="Job board source")
    parser.add_argument("--salary",       help="Salary range")
    parser.add_argument("--contact",      help="Recruiter/contact name")
    parser.add_argument("--followup-days",type=int, default=7, dest="followup_days",
                        help="Days until follow-up reminder (default: 7)")

    # Options for --list
    parser.add_argument("--filter",  metavar="STATUS",
                        help="Filter by status: applied|interviewing|offer|rejected|withdrawn|ghosted")

    args = parser.parse_args()

    try:
        sheets = get_sheets_client()
    except Exception as e:
        print(f"\n❌ Could not connect to Google Sheets: {e}")
        print("   Check your keys.json and GOOGLE_SHEETS_ID in .env")
        sys.exit(1)

    if args.apply:
        cmd_apply(args, sheets)
    elif args.status:
        cmd_status(args, sheets)
    elif args.list:
        cmd_list(args, sheets)
    elif args.stats:
        cmd_stats(args, sheets)
    elif args.followups:
        cmd_followups(args, sheets)


if __name__ == "__main__":
    main()