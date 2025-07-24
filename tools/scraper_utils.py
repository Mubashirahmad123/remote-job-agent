import re
from datetime import datetime, timedelta

def clean_text(tag_or_str):
    """Return trimmed text or empty string."""
    if tag_or_str is None:
        return ""
    if hasattr(tag_or_str, "get_text"):
        return re.sub(r"\s+", " ", tag_or_str.get_text(strip=True))
    return re.sub(r"\s+", " ", str(tag_or_str).strip())

def days_ago(date_str):
    """Convert fuzzy date strings like '2d ago', '2024-07-10' → int days."""
    date_str = str(date_str).lower()
    today = datetime.utcnow().date()

    # handle "Xh ago", "Xd ago", "Xw ago"
    m = re.search(r"(\d+)\s*(hour|day|week)", date_str)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if "hour" in unit:
            return 0
        if "day" in unit:
            return n
        if "week" in unit:
            return n * 7
    # handle ISO dates
    try:
        return (today - datetime.strptime(date_str[:10], "%Y-%m-%d").date()).days
    except Exception:
        return 999  # unknown → skip