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
import hashlib
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


def _ledger_job_uid(job: dict, fingerprint: str) -> str:
    """Per-INSTANCE identity for reconciliation.

    The content fingerprint is shared by genuinely different postings (same
    title/company/description on two boards), so it cannot be the identity
    key: the 2026-10-31 live run produced 331 raw rows over 315 distinct
    fingerprints. The instance key adds the URL and source, so every fetched
    job instance has exactly one terminal row.
    """
    url = str(job.get("apply_url") or "").strip()
    source = str(job.get("source") or "").strip()
    key = "|".join((fingerprint or "", url, source))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


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
                CREATE TABLE IF NOT EXISTS job_texts (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    job_uid TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    description TEXT NOT NULL,
                    description_sha256 TEXT NOT NULL,
                    fetched_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS idx_stage_run
                    ON stage_events(run_id, stage);
                CREATE INDEX IF NOT EXISTS idx_board_run
                    ON board_runs(run_id);
                CREATE INDEX IF NOT EXISTS idx_job_texts_run
                    ON job_texts(run_id);
                CREATE INDEX IF NOT EXISTS idx_job_texts_uid
                    ON job_texts(job_uid);
            ''')
            # job_uid (2026-10-31): the content fingerprint is NOT unique —
            # the live run showed 331 raw rows collapsing to 315 distinct
            # fingerprints (one fingerprint appeared 5 times), because
            # fingerprint ignores the URL/board. Reconciliation therefore
            # keys on a per-INSTANCE id (fingerprint + url + source), while
            # the fingerprint stays a queryable attribute.
            columns = {row[1] for row in db.execute("PRAGMA table_info(stage_events)")}
            if "job_uid" not in columns:
                db.execute("ALTER TABLE stage_events ADD COLUMN job_uid TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS idx_stage_uid "
                       "ON stage_events(run_id, job_uid)")

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

        Also persists raw job text (title, company, url, source, description)
        capped at 20000 chars with SHA-256, so a run is re-evaluable offline.
        """
        rows = []
        text_rows = []
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
            fingerprint = _ledger_fingerprint(job)
            uid = _ledger_job_uid(job, fingerprint)
            rows.append((
                self._run_id(), _utc_now(),
                fingerprint,
                uid,
                str(job.get("source") or "") or None,
                str(job.get("job_title") or "") or None,
                str(job.get("company") or "") or None,
                stage, reason_code,
                float(score) if isinstance(score, (int, float)) else None,
                breakdown_json,
            ))
            # Persist raw job text for offline re-evaluation
            description = job.get("description") or job.get("summary") or ""
            description = description[:20000]
            desc_sha = hashlib.sha256(description.encode("utf-8")).hexdigest()
            text_rows.append((
                self._run_id(), uid,
                str(job.get("job_title") or "") or "",
                str(job.get("company") or "") or "",
                str(job.get("apply_url") or "") or "",
                str(job.get("source") or "") or "",
                description,
                desc_sha,
                _utc_now(),
            ))
        with self._connect() as db:
            db.executemany(
                '''INSERT INTO stage_events
                   (run_id, ts, job_fingerprint, job_uid, source, title, company,
                    stage, reason_code, score, breakdown)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', rows)
            db.executemany(
                '''INSERT OR REPLACE INTO job_texts
                   (run_id, job_uid, title, company, url, source, description,
                    description_sha256, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', text_rows)
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

        Identity is the per-INSTANCE job_uid (fingerprint alone is not
        unique across boards). A run is complete when every fetched
        instance has exactly one terminal row; instances with two terminal
        rows are reported, never hidden.
        """
        run_id = run_id or self.run_id
        with self._connect() as db:
            stages = dict(db.execute(
                '''SELECT stage, COUNT(*) FROM stage_events WHERE run_id=?
                   GROUP BY stage''', (run_id,)).fetchall())
            raw_rows, = db.execute(
                '''SELECT COUNT(*) FROM stage_events
                   WHERE run_id=? AND stage='raw_fetched' ''', (run_id,)).fetchone()
            raw_ids = {row[0] for row in db.execute(
                '''SELECT DISTINCT job_uid FROM stage_events
                   WHERE run_id=? AND stage='raw_fetched' AND job_uid IS NOT NULL''',
                (run_id,)).fetchall()}
            terminals = db.execute(
                '''SELECT job_uid, COUNT(*) c, MIN(stage) s
                   FROM stage_events WHERE run_id=? AND stage IN
                   ({marks}) GROUP BY job_uid'''.format(
                       marks=",".join("?" * len(TERMINAL_STAGES))),
                (run_id, *TERMINAL_STAGES)).fetchall()
        terminal_by_id = {row[0]: (row[2], row[1]) for row in terminals if row[0]}
        duplicated = sorted(k for k, v in terminal_by_id.items() if v[1] > 1)
        missing = sorted(raw_ids - set(terminal_by_id))
        terminal_sum = sum(stages.get(s, 0) for s in TERMINAL_STAGES)
        return {
            "run_id": self.run_id or run_id,
            "stages": stages,
            "raw_fetched": raw_rows,
            "raw_instances": len(raw_ids),
            "terminal_sum": terminal_sum,
            "complete": (not missing and not duplicated
                         and raw_rows == terminal_sum),
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


    def reload_run_jobs(self, run_id: str) -> list[dict]:
        """Reload all jobs for a run from job_texts, for offline re-evaluation.

        Returns a list of job dicts with title, company, url, source,
        description, and job_uid. Suitable for re-running the matching
        engine without re-scraping.
        """
        with self._connect() as db:
            rows = db.execute(
                '''SELECT job_uid, title, company, url, source, description
                   FROM job_texts WHERE run_id=? ORDER BY seq''', (run_id,)).fetchall()
        jobs = []
        for row in rows:
            jobs.append({
                "job_uid": row[0],
                "job_title": row[1],
                "company": row[2],
                "apply_url": row[3],
                "source": row[4],
                "description": row[5] or "",
                "job_fingerprint": "",  # not stored; recompute if needed
            })
        return jobs

    def run_job_text_count(self, run_id: str) -> int:
        """Count of job_text rows for a run."""
        with self._connect() as db:
            row = db.execute(
                'SELECT COUNT(*) FROM job_texts WHERE run_id=?', (run_id,)
            ).fetchone()
        return row[0] if row else 0


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
