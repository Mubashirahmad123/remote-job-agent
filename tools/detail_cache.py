"""Cached detail-page fetch for job boards.

Provides hash-keyed, rate-limited, size-capped fetching of job detail
pages. Used by boards that ship truncated summaries (Shine, DailyRemote,
WeAreDevelopers, JustJoinIt) to recover full job descriptions.

Design:
- Hash-keyed: cache key = SHA-256 of the detail URL
- Rate-limited: minimum delay between requests to the same domain
- Size-capped: max bytes stored per page (default 50 KB)
- Persistent: SQLite seam in data/detail_cache.db
- Idempotent: re-fetching the same URL returns cached content
"""
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_MAX_BYTES = 50_000
DEFAULT_RATE_LIMIT = 2.0  # seconds between requests to same domain
DEFAULT_DB_PATH = Path('data/detail_cache.db')


def _url_hash(url: str) -> str:
    """Stable SHA-256 hash of a URL for cache keying."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]


def _domain(url: str) -> str:
    """Extract domain from URL for rate-limiting."""
    return urlparse(url).netloc.lower()


class DetailCache:
    """Hash-keyed, rate-limited, size-capped detail page cache."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, max_bytes: int = DEFAULT_MAX_BYTES,
                 rate_limit: float = DEFAULT_RATE_LIMIT):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.rate_limit = rate_limit
        self._last_fetch: dict[str, float] = {}  # domain -> last fetch time
        self._init_db()

    def _init_db(self):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS detail_cache (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_length INTEGER NOT NULL,
                    fetched_at TEXT NOT NULL,
                    headers TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_detail_cache_domain
                    ON detail_cache(domain);
            ''')

    def _rate_limited_fetch(self, url: str) -> tuple[int, str, dict]:
        """Fetch a URL with per-domain rate limiting."""
        domain = _domain(url)
        now = time.time()
        last = self._last_fetch.get(domain, 0)
        elapsed = now - last
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        try:
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) remote-job-agent/1.0'
            })
            self._last_fetch[domain] = time.time()
            return resp.status_code, resp.text, dict(resp.headers)
        except Exception as exc:
            self._last_fetch[domain] = time.time()
            return 0, '', {'error': str(exc)}

    def get(self, url: str) -> dict | None:
        """Get cached detail page content for a URL.

        Returns dict with keys: url, status, content, content_length,
        fetched_at, headers, cached (bool). Returns None if not cached
        and fetch fails.
        """
        url_hash = _url_hash(url)
        with closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                'SELECT url, status, content, content_length, fetched_at, headers '
                'FROM detail_cache WHERE url_hash=?',
                (url_hash,)
            ).fetchone()
        if row:
            return {
                'url': row[0],
                'status': row[1],
                'content': row[2],
                'content_length': row[3],
                'fetched_at': row[4],
                'headers': json.loads(row[5]) if row[5] else {},
                'cached': True,
            }
        # Not cached — fetch and store
        status, content, headers = self._rate_limited_fetch(url)
        content = content[: self.max_bytes]  # size cap
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                '''INSERT OR REPLACE INTO detail_cache
                   (url_hash, url, domain, status, content, content_length, fetched_at, headers)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (url_hash, url, _domain(url), status, content, len(content),
                 datetime.now(timezone.utc).isoformat(), json.dumps(headers)),
            )
        return {
            'url': url,
            'status': status,
            'content': content,
            'content_length': len(content),
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'headers': headers,
            'cached': False,
        }

    def stats(self) -> dict:
        """Return cache statistics."""
        with closing(sqlite3.connect(self.db_path)) as db:
            total = db.execute('SELECT COUNT(*) FROM detail_cache').fetchone()[0]
            total_bytes = db.execute(
                'SELECT COALESCE(SUM(content_length), 0) FROM detail_cache'
            ).fetchone()[0]
            domains = db.execute(
                'SELECT COUNT(DISTINCT domain) FROM detail_cache'
            ).fetchone()[0]
        return {'entries': total, 'total_bytes': total_bytes, 'domains': domains}
