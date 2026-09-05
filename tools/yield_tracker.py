"""
tools/yield_tracker.py
Per-board yield logging: which boards earn their keep.

Tracks each pipeline run as one JSON line in logs/board_yield.jsonl:
    {"run_at": ..., "boards": {"Remotive": {"fetched": 12, "status": "ok", ...}, ...}}

Stages recorded per board/source:
    fetched       → raw jobs returned by the board parser
    dev_filter    → survived is_valid_dev_job (scraper)
    country       → survived is_allowed_location (scraper)
    curated_in    → entered curate()
    post_dedup    → survived URL + fingerprint dedup
    post_country  → survived curate() country filter
    saved         → passed scoring and written to sheet
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "board_yield.jsonl"


def count_by_source(jobs: list) -> dict:
    """Count jobs grouped by their 'source' field."""
    return dict(Counter(j.get("source", "unknown") or "unknown" for j in jobs))


class YieldTracker:
    def __init__(self):
        self.boards: dict = {}

    def _entry(self, board: str) -> dict:
        return self.boards.setdefault(board, {"status": "unknown"})

    def scrape(self, board: str, status: str, fetched: int = 0):
        """Record a board fetch: status is ok | empty | error."""
        e = self._entry(board)
        e["status"] = status
        e["fetched"] = fetched

    def stage(self, stage: str, per_source: dict):
        """Record a pipeline stage (dev_filter, country, curated_in, ...)."""
        for source, count in per_source.items():
            self._entry(source)[stage] = count

    def save(self) -> Path | None:
        """Append this run to the JSONL log. Returns log path or None."""
        try:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "run_at": datetime.now().isoformat(timespec="seconds"),
                    "boards": self.boards,
                }) + "\n")
            return LOG_PATH
        except Exception as e:
            print(f"  Yield log save failed: {e}")
            return None

    def print_table(self):
        """Print per-board yield sorted by saved desc."""
        print(f"\n=== BOARD YIELD ===")
        print(f"  {'Board':<22} {'fetch':>5} {'dev':>5} {'ctry':>5} {'dedup':>5} {'saved':>5}  status")
        rows = sorted(
            self.boards.items(),
            key=lambda kv: kv[1].get("saved", kv[1].get("country", 0)),
            reverse=True,
        )
        for board, s in rows:
            print(f"  {board:<22} "
                  f"{s.get('fetched', '-'):>5} "
                  f"{s.get('dev_filter', '-'):>5} "
                  f"{s.get('country', s.get('post_country', '-')):>5} "
                  f"{s.get('post_dedup', '-'):>5} "
                  f"{s.get('saved', '-'):>5}  {s.get('status', '')}")
