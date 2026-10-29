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
    """Personal-agent SQLite seam; explicit owner/profile/content version keys."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS extraction (
                    owner TEXT, digest TEXT, version TEXT, payload TEXT NOT NULL,
                    PRIMARY KEY(owner, digest, version));
                CREATE TABLE IF NOT EXISTS decisions (
                    owner TEXT, job_id TEXT, profile TEXT, digest TEXT, scorer TEXT,
                    extractor TEXT, decision TEXT NOT NULL, payload TEXT NOT NULL,
                    created TEXT NOT NULL,
                    PRIMARY KEY(owner, job_id, profile, digest, scorer, extractor));
            ''')

    @staticmethod
    def fingerprint(content: str) -> str:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def cache_extraction(self, owner: str, content: str, version: str, payload: dict):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR REPLACE INTO extraction VALUES (?, ?, ?, ?)',
                       (owner, self.fingerprint(content), version, json_payload(payload)))

    def get_extraction(self, owner: str, content: str, version: str):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT payload FROM extraction WHERE owner=? AND digest=? AND version=?',
                             (owner, self.fingerprint(content), version)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, owner: str, job_id: str, content: str, result: MatchResult):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR REPLACE INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (owner, job_id, result.profile_version, self.fingerprint(content),
                        result.scorer_version, result.extractor_version, result.decision,
                        json_payload(result), datetime.now(timezone.utc).isoformat()))

    def review_queue(self, owner: str, profile_version: str):
        """Latest decision per job for the requested profile, not stale review entries."""
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute('''SELECT job_id, payload FROM (
                SELECT job_id, payload, decision,
                       ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY created DESC, rowid DESC) AS n
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
