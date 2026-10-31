"""Append-only per-job funnel ledger (Phase 1 observability).

The YieldTracker records per-board COUNTS only; when the curator prints
"110 low match" those jobs vanish with no per-job audit trail, and
skipped boards were indistinguishable from empty boards. This module
records EVERY job as INSERT-only rows per stage event, never overwrites:

    raw_fetched         every job before is_valid_dev_job
    dev_filter_drop     dropped by is_valid_dev_job
    country_drop        dropped by is_allowed_location
    date_drop           dropped by SCRAPER_MAX_AGE_DAYS
    dedup_missing_url   no apply_url
    dedup_url_dup       apply_url already seen
    dedup_cross_board   (title, company) duplicate
    dedup_fingerprint   content fingerprint duplicate
    legacy_rejected     rejection engine
    legacy_low_match    below MIN_SCORE
    legacy_passed       written toward the sheet

Fingerprint/score columns make the funnel queryable; sources, titles and
companies stay honest even for jobs dropped before fingerprints existed
(a deterministic fingerprint is derived on the fly in that case).

Board statuses use the taxonomy
    ok | empty_confirmed | parse_zero | timeout | blocked | fetch_failed |
    skipped_js | skipped_duplicate | skipped_disabled | skipped_breaker | error
so "empty" never means "we did not try": skipped boards keep their skip
cause, HTML fetched but parsed zero is parse_zero, and a request that
never produced a body is timeout/blocked/fetch_failed — not empty.

data/pipeline_ledger.db is gitignored, like every other data/ artifact.
PIPELINE_LEDGER_DB overrides the location (e2e/CI isolation).
"""
import os
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "pipeline_ledger.db"

BOARD_STATUSES = {
    "ok", "empty_confirmed", "parse_zero", "timeout", "blocked", "fetch_failed",
    "skipped_js", "skipped_duplicate", "skipped_disabled", "skipped_breaker",
    "error",
}
# A board run did not produce a usable body or any listed jobs.
# skipped_* means the board did NOT run this pass (duplicate/js/disabled/
# breaker), so it neither failed nor returned zero — break the streak and
# never count it as a bad attempt.
BOARD_BAD_STATUSES = {"empty_confirmed", "parse_zero", "timeout", "blocked",
                      "fetch_failed", "error"}

TERMINAL_STAGES = (
    "dev_filter_drop", "country_drop", "date_drop",
    "dedup_missing_url", "dedup_url_dup", "dedup_cross_board", "dedup_fingerprint",
    "legacy_rejected", "legacy_low_match", "legacy_passed",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ledger_fingerprint(job: dict) -> str:
    """Existing fingerprint, else deterministic fallback; never invent data."""
    value = job.get("job_fingerprint")
    if value:
        return value
    try:
        from tools.deduplicator import job_fingerprint
        return job_fingerprint(job)
    except Exception:
        return ""


class PipelineLedger:
    """SQLite seam for the per-job funnel; INSERT-only by construction."""

    def __init__(self, path=None, run_id=None):
        if path is None:
            # Env override keeps e2e/CI runs isolated; default stays the
            # gitignored data/ ledger.
            path = os.getenv("PIPELINE_LEDGER_DB", DEFAULT_DB)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS stage_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL, ts TEXT NOT NULL,
                    job_fingerprint TEXT, source TEXT, title TEXT, company TEXT,
                    stage TEXT NOT NULL, reason_code TEXT,
                    score REAL, breakdown TEXT);
                CREATE TABLE IF NOT EXISTS board_runs (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL, ts TEXT NOT NULL,
                    board TEXT NOT NULL, status TEXT NOT NULL,
                    fetched INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS idx_stage_run
                    ON stage_events(run_id, stage);
                CREATE INDEX IF NOT EXISTS idx_board_run
                    ON board_runs(run_id);
            ''')

    @staticmethod
    def new_run_id() -> str:
        import uuid
        return uuid.uuid4().hex[:12]

    def _connect(self):
        # isolation is per-statement; the ledger is append-only so no
        # read-modify-write exists that could need a transaction.
        return sqlite3.connect(self.path)

    def record_jobs(self, jobs, stage: str, reason_code: str = None,
                    score_of=None) -> int:
        """Record one stage event per job. Returns rows appended.

        `score_of(job)` -> (score, breakdown_dict | None) for scored stages;
        never a parallel heuristic. Failures are per-job: one bad row does
        not abort its batch (the shadow learned that lesson the hard way).
        """
        rows = []
        for job in jobs:
            score = None
            breakdown = None
            if score_of is not None:
                try:
                    score, breakdown = score_of(job)
                except Exception:
                    score, breakdown = None, None
            try:
                breakdown_json = json.dumps(breakdown, sort_keys=True) if breakdown else None
            except (TypeError, ValueError):
                breakdown_json = None
            rows.append((
                self._run_id(), _utc_now(),
                _ledger_fingerprint(job),
                str(job.get("source") or "") or None,
                str(job.get("job_title") or "") or None,
                str(job.get("company") or "") or None,
                stage, reason_code,
                float(score) if isinstance(score, (int, float)) else None,
                breakdown_json,
            ))
        with self._connect() as db:
            db.executemany(
                '''INSERT INTO stage_events
                   (run_id, ts, job_fingerprint, source, title, company,
                    stage, reason_code, score, breakdown)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
        return len(rows)

    def record_board(self, board: str, status: str, fetched: int = 0):
        if status not in BOARD_STATUSES:
            raise ValueError(
                f"board status {status!r} outside taxonomy {sorted(BOARD_STATUSES)}")
        with self._connect() as db:
            db.execute(
                '''INSERT INTO board_runs (run_id, ts, board, status, fetched)
                   VALUES (?, ?, ?, ?, ?)''',
                (self._run_id(), _utc_now(), board, status, int(fetched)))

    def _run_id(self) -> str:
        if not self.run_id:
            self.run_id = self.new_run_id()
        return self.run_id

    def reconcile(self, run_id: str = None) -> dict:
        """Stage counts for one run plus terminal-sum reconciliation.

        A run is complete when exactly one terminal row exists per distinct
        job fingerprint seen at raw_fetched. Multiple terminal rows for one
        fingerprint or a terminal-less fingerprint are reported, never
        hidden.
        """
        run_id = run_id or self.run_id
        with self._connect() as db:
            stages = dict(db.execute(
                '''SELECT stage, COUNT(*) FROM stage_events WHERE run_id=?
                   GROUP BY stage''', (run_id,)).fetchall())
            raw = db.execute(
                '''SELECT DISTINCT job_fingerprint FROM stage_events
                   WHERE run_id=? AND stage='raw_fetched' ''',
                (run_id,)).fetchall()
            terminals = db.execute(
                '''SELECT job_fingerprint, COUNT(*) c, MIN(stage) s
                   FROM stage_events WHERE run_id=? AND stage IN
                   ({marks}) GROUP BY job_fingerprint'''.format(
                       marks=",".join("?" * len(TERMINAL_STAGES))),
                (run_id, *TERMINAL_STAGES)).fetchall()
        raw_ids = {row[0] for row in raw if row[0]}
        terminal_by_id = {row[0]: (row[2], row[1]) for row in terminals if row[0]}
        duplicated = sorted(k for k, v in terminal_by_id.items() if v[1] > 1)
        missing = sorted(raw_ids - set(terminal_by_id))
        return {
            "run_id": self.run_id or run_id,
            "stages": stages,
            "raw_fetched": len(raw_ids),
            "terminal_sum": sum(stages.get(s, 0) for s in TERMINAL_STAGES),
            "complete": not missing and not duplicated,
            "missing_terminal": missing,
            "duplicated_terminal": duplicated,
        }

    def board_status_for_run(self, run_id: str = None) -> dict:
        run_id = run_id or self.run_id
        with self._connect() as db:
            rows = db.execute(
                '''SELECT board, status, fetched FROM board_runs
                   WHERE run_id=? ORDER BY seq''', (run_id,)).fetchall()
        return {row[0]: {"status": row[1], "fetched": row[2]} for row in rows}

    def board_history(self) -> dict:
        """Per-board status history, oldest first, across all runs."""
        with self._connect() as db:
            rows = db.execute(
                '''SELECT board, status FROM board_runs ORDER BY board, seq''').fetchall()
        history: dict = {}
        for board, status in rows:
            history.setdefault(board, []).append(status)
        return history


def consecutive_bad_boards(board_rows: dict, min_streak: int = 3):
    """Boards whose LAST min_streak runs were all bad (zero or failure).

    `board_rows` maps board -> list of statuses, oldest first (as persisted
    in board_runs). The health flag is derived state, printed per run; the
    breaker stays the only mechanism that SKIPS work.
    """
    flagged = {}
    for board, statuses in board_rows.items():
        streak = 0
        for status in reversed(statuses[-min_streak:]):
            if status in BOARD_BAD_STATUSES:
                streak += 1
            else:
                break
        if streak >= min_streak:
            flagged[board] = streak
    return flagged
