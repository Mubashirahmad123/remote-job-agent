"""Offline matching persistence, priority and evaluation helpers.

Not a tenant-isolation boundary: callers must supply authenticated owner IDs.
No scraper/network calls and no automatic replacement of the production curator.
"""
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from tools.matching_score import MatchResult


def json_payload(value):
    return json.dumps(value, default=lambda v: sorted(v) if isinstance(v, (set, frozenset)) else asdict(v),
                      sort_keys=True, allow_nan=False)


class MatchStore:
    """Personal-agent SQLite seam; explicit owner/profile/content version keys.

    Phase 3: `decisions` is APPEND-ONLY. Every evaluation becomes a new row
    with its own sequence number, so the history of what the engine decided
    (and when) survives profile changes. A pre-Phase-3 table (no `seq`
    column) is renamed to `decisions_legacy_v1` and kept — never dropped.
    """
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            # Migration first: the legacy table must be renamed before the
            # new schema is created, otherwise IF NOT EXISTS keeps the old
            # shape and the append-only contract is lost.
            legacy_columns = {row[1] for row in db.execute("PRAGMA table_info(decisions)")}
            if legacy_columns and "seq" not in legacy_columns:
                db.execute("ALTER TABLE decisions RENAME TO decisions_legacy_v1")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS extraction (
                    owner TEXT, digest TEXT, version TEXT, payload TEXT NOT NULL,
                    PRIMARY KEY(owner, digest, version));
                CREATE TABLE IF NOT EXISTS decisions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL, job_id TEXT NOT NULL, profile TEXT NOT NULL,
                    digest TEXT NOT NULL, scorer TEXT NOT NULL, extractor TEXT NOT NULL,
                    decision TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL,
                    evidence TEXT);
                CREATE INDEX IF NOT EXISTS idx_decisions_owner_profile
                    ON decisions(owner, profile, job_id, seq);
                CREATE TABLE IF NOT EXISTS run_status (
                    owner TEXT NOT NULL, run_id TEXT NOT NULL, profile TEXT NOT NULL,
                    started TEXT NOT NULL, finished TEXT,
                    processed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    reasons TEXT,
                    PRIMARY KEY(owner, run_id, profile));
            ''')

    @staticmethod
    def fingerprint(content: str) -> str:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def cache_extraction(self, owner: str, content: str, version: str, payload: dict):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR REPLACE INTO extraction VALUES (?, ?, ?, ?)',
                       (owner, self.fingerprint(content), version, json_payload(payload)))

    def get_extraction(self, owner: str, content: str, version: str):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute('SELECT payload FROM extraction WHERE owner=? AND digest=? AND version=?',
                             (owner, self.fingerprint(content), version)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, owner: str, job_id: str, content: str, result: MatchResult,
               evidence: dict = None):
        """Append one decision. History is never overwritten.

        `evidence` keeps the quote-verified facts next to the decision, so a
        reviewer can check WHY without re-running the extractor.
        """
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''INSERT INTO decisions
                (owner, job_id, profile, digest, scorer, extractor, decision, payload, created, evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (owner, job_id, result.profile_version, self.fingerprint(content),
                        result.scorer_version, result.extractor_version, result.decision,
                        json_payload(result), datetime.now(timezone.utc).isoformat(),
                        json_payload(evidence) if evidence else None))

    def latest_decisions(self, owner: str, profile_version: str):
        """Latest decision per job for one profile (append-only history)."""
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute('''SELECT job_id, decision, payload, seq FROM (
                SELECT job_id, decision, payload, seq,
                       ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY seq DESC) AS n
                FROM decisions WHERE owner=? AND profile=?) WHERE n=1
                ORDER BY job_id''', (owner, profile_version)).fetchall()
        return [{"job_id": row[0], "decision": row[1], "result": json.loads(row[2]),
                 "seq": row[3]} for row in rows]

    def decision_count(self, owner: str = None) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            if owner is None:
                return db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]
            return db.execute('SELECT COUNT(*) FROM decisions WHERE owner=?',
                              (owner,)).fetchone()[0]

    def start_run(self, owner: str, run_id: str, profile: str):
        """Open a run-status row so an interrupted batch stays visible."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''INSERT OR REPLACE INTO run_status
                (owner, run_id, profile, started, finished, processed, failed, reasons)
                VALUES (?, ?, ?, ?, NULL, 0, 0, NULL)''',
                       (owner, run_id, profile, datetime.now(timezone.utc).isoformat()))

    def finish_run(self, owner: str, run_id: str, profile: str,
                   processed: int, failed: int, reasons=None):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''UPDATE run_status
                SET finished=?, processed=?, failed=?, reasons=?
                WHERE owner=? AND run_id=? AND profile=?''',
                       (datetime.now(timezone.utc).isoformat(), processed, failed,
                        json_payload(reasons) if reasons else None,
                        owner, run_id, profile))

    def run_status(self, owner: str, run_id: str):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute('''SELECT processed, failed, reasons, started, finished
                FROM run_status WHERE owner=? AND run_id=? ORDER BY started DESC LIMIT 1''',
                             (owner, run_id)).fetchone()
        if not row:
            return None
        return {"processed": row[0], "failed": row[1],
                "reasons": json.loads(row[2]) if row[2] else [],
                "started": row[3], "finished": row[4]}

    def review_queue(self, owner: str, profile_version: str):
        """Latest decision per job for the requested profile, not stale review entries."""
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute('''SELECT job_id, payload FROM (
                SELECT job_id, payload, decision,
                       ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY seq DESC) AS n
                FROM decisions WHERE owner=? AND profile=?) WHERE n=1 AND decision='review'
                ORDER BY job_id''', (owner, profile_version)).fetchall()
        return [{"job_id": row[0], "result": json.loads(row[1])} for row in rows]


@dataclass(frozen=True)
class PriorityEvidence:
    employer_region_preferred: bool | None = None
    startup_preferred: bool | None = None
    timezone_preferred: bool | None = None
    posted_at: datetime | None = None


def rank_matches(items: list[tuple[str, MatchResult, PriorityEvidence]], now: datetime, limit: int):
    """Fit first; preferences then freshness break ties. No confidence multiplication.

    Unknown/false preferences provide no boost, never a fit penalty. Caller supplies
    UTC-aware clock for reproducibility. No calibrated score bands implied.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError('limit must be a nonnegative integer')
    if now.tzinfo is None:
        raise ValueError('now must be timezone aware')

    def key(item):
        _, result, evidence = item
        preferences = sum(v is True for v in (evidence.employer_region_preferred,
                                               evidence.startup_preferred, evidence.timezone_preferred))
        freshness = 0.0
        if evidence.posted_at is not None:
            if evidence.posted_at.tzinfo is None:
                raise ValueError('posted_at must be timezone aware')
            days = (now - evidence.posted_at).total_seconds() / 86400
            # Future timestamps are unverified rather than awarded maximum credit.
            freshness = max(0, 1 - days / 14) if days >= 0 else 0
        return (result.required.score, result.preferred.score or 0, preferences, freshness)

    eligible = [item for item in items if item[1].decision == 'eligible' and item[1].required.score is not None]
    return sorted(eligible, key=key, reverse=True)[:limit]


def evaluate_labels(labels: dict[str, str], old_selected: set[str], new_selected: set[str]):
    """Held-out label metrics; no inference that not-applied means skip.

    Uncertain/unlabeled jobs are excluded from precision/recall, and selection of
    unlabeled jobs is reported separately. Human labeling remains external.
    """
    if any(label not in {'apply', 'skip', 'uncertain'} for label in labels.values()):
        raise ValueError('labels must be apply, skip or uncertain')
    positives = {key for key, value in labels.items() if value == 'apply'}
    known = {key for key, value in labels.items() if value != 'uncertain'}

    def metrics(selected):
        tp = len(selected & positives)
        evaluated = selected & known
        return {'precision': tp / len(evaluated) if evaluated else None,
                'recall': tp / len(positives) if positives else None,
                'true_positives': tp, 'false_positives': len(evaluated - positives),
                'unlabeled_or_uncertain_selected': len(selected - known)}
    return {'old': metrics(old_selected), 'new': metrics(new_selected),
            'added': sorted(new_selected - old_selected), 'removed': sorted(old_selected - new_selected)}
