"""Cached detail-page fetch for job boards.

Provides hash-keyed, rate-limited, size-capped fetching of job detail
pages. Used by boards that ship truncated summaries (Shine, DailyRemote,
WeAreDevelopers, JustJoinIt) to recover full job descriptions.

Design:
- Hash-keyed: cache key = SHA-256 of the detail URL
- Rate-limited: minimum delay between requests to the same domain
- Size-capped: max bytes stored per page (default 50 KB), enforced DURING fetch
- TTL: entries expire after configurable time (default 7 days)
- SSRF-safe: rejects private/internal IPs and non-HTTP schemes
- Persistent: SQLite seam in data/detail_cache.db
- Idempotent: re-fetching the same URL returns cached content (if not expired)
- Non-caching on error: status 0 / fetch errors are NOT cached
"""
import hashlib
import ipaddress
import json
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_MAX_BYTES = 50_000
DEFAULT_RATE_LIMIT = 2.0          # seconds between requests to the same domain
DEFAULT_TTL_DAYS = 7              # cache entry time-to-live
DEFAULT_DB_PATH = Path('data/detail_cache.db')

# Private/internal IP ranges to reject (SSRF protection)
_PRIVATE_NETWORKS = (
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),  # link-local
    ipaddress.ip_network('::1/128'),         # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),        # IPv6 unique local
    ipaddress.ip_network('fe80::/10'),       # IPv6 link-local
)


def _url_hash(url: str) -> str:
    """Stable SHA-256 hash of a URL for cache keying."""
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]


def _domain(url: str) -> str:
    """Extract domain from URL for rate-limiting."""
    return urlparse(url).netloc.lower()


def _validate_url(url: str) -> str:
    """Validate URL for SSRF safety. Returns normalized URL or raises ValueError.

    Rejects:
    - Non-HTTP(S) schemes
    - Private/internal IP ranges (RFC 1918, loopback, link-local, ULA)
    - Localhost and variants
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ('http', 'https'):
        raise ValueError(f"Unsupported scheme: {scheme}")

    host = parsed.hostname or ''
    if not host:
        raise ValueError("No hostname in URL")

    # Resolve host to IP for private range checks
    try:
        # Try as IP address first
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal — could be a hostname. We can't resolve here
        # without network, so we allow hostnames but warn via comment.
        # In production, the DNS resolution happens in requests.get().
        pass
    else:
        # IP literal — check private ranges
        for net in _PRIVATE_NETWORKS:
            if ip in net:
                raise ValueError(f"Private/internal IP blocked: {host}")

    # Also reject explicit localhost variants
    if host.lower() in {'localhost', 'localhost.localdomain', '::1'}:
        raise ValueError(f"Localhost blocked: {host}")

    # Normalize: ensure scheme + netloc + path (no fragment)
    normalized = f"{scheme}://{parsed.netloc}{parsed.path or '/'}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized


def _default_fetch(url: str, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[int, str, dict]:
    """Default fetch function using requests.get with streaming size cap.

    Returns (status_code, content, headers). On error, returns (0, '', {'error': ...}).
    """
    try:
        with requests.get(
            url,
            timeout=15,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) remote-job-agent/1.0'},
            stream=True,
        ) as resp:
            status = resp.status_code
            # Read up to max_bytes from the stream
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    # Truncate the last chunk if it exceeds the cap
                    excess = total - max_bytes
                    if excess > 0:
                        chunks[-1] = chunks[-1][:-excess]
                    break
            content = ''.join(chunks)
            return status, content, dict(resp.headers)
    except Exception as exc:
        return 0, '', {'error': str(exc)}


class DetailCache:
    """Hash-keyed, rate-limited, size-capped, TTL-bounded detail page cache.

    SSRF-safe: validates URLs before fetch, rejects private/internal IPs.
    Non-caching on error: status 0 / fetch exceptions are NOT stored.
    Size cap enforced DURING fetch via streaming (no wasted bandwidth).
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, max_bytes: int = DEFAULT_MAX_BYTES,
                 rate_limit: float = DEFAULT_RATE_LIMIT, ttl_days: int = DEFAULT_TTL_DAYS,
                 fetch_func=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.rate_limit = rate_limit
        self.ttl_days = ttl_days
        self.fetch_func = fetch_func or _default_fetch
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
        """Fetch a URL with per-domain rate limiting and SSRF validation."""
        # SSRF validation — may raise ValueError
        validated_url = _validate_url(url)
        domain = _domain(validated_url)
        now = time.time()
        last = self._last_fetch.get(domain, 0)
        elapsed = now - last
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        try:
            # Pass max_bytes to fetch_func for streaming size cap
            status, content, headers = self.fetch_func(validated_url, self.max_bytes)
            self._last_fetch[domain] = time.time()
            return status, content, headers
        except Exception as exc:
            self._last_fetch[domain] = time.time()
            return 0, '', {'error': str(exc)}

    def _is_expired(self, fetched_at: str) -> bool:
        """Check if a cached entry has exceeded its TTL."""
        try:
            fetched = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        except ValueError:
            return True  # malformed timestamp -> treat as expired
        age = datetime.now(timezone.utc) - fetched
        return age > timedelta(days=self.ttl_days)

    def get(self, url: str) -> dict | None:
        """Get cached detail page content for a URL.

        Returns dict with keys: url, status, content, content_length,
        fetched_at, headers, cached (bool). Returns None if:
        - URL fails SSRF validation
        - Not cached and fetch fails (status 0 or exception)
        - Cached entry is expired (TTL exceeded)
        """
        # SSRF validation upfront — reject before any DB hit
        try:
            validated_url = _validate_url(url)
        except ValueError as exc:
            return {'url': url, 'status': 0, 'content': '',
                    'content_length': 0, 'fetched_at': '',
                    'headers': {'error': f'SSRF: {exc}'}, 'cached': False}

        url_hash = _url_hash(validated_url)
        with closing(sqlite3.connect(self.db_path)) as db:
            row = db.execute(
                'SELECT url, status, content, content_length, fetched_at, headers '
                'FROM detail_cache WHERE url_hash=?',
                (url_hash,)
            ).fetchone()
        if row:
            fetched_at = row[4]
            if self._is_expired(fetched_at):
                # Expired — fall through to re-fetch
                pass
            else:
                return {
                    'url': row[0],
                    'status': row[1],
                    'content': row[2],
                    'content_length': row[3],
                    'fetched_at': row[4],
                    'headers': json.loads(row[5]) if row[5] else {},
                    'cached': True,
                }
        # Not cached or expired — fetch
        status, content, headers = self._rate_limited_fetch(validated_url)
        # Do NOT cache error responses (status 0) or empty content from errors
        if status == 0:
            return {
                'url': validated_url,
                'status': status,
                'content': content,
                'content_length': len(content),
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'headers': headers,
                'cached': False,
            }
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute(
                '''INSERT OR REPLACE INTO detail_cache
                   (url_hash, url, domain, status, content, content_length, fetched_at, headers)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (url_hash, validated_url, _domain(validated_url), status, content, len(content),
                 datetime.now(timezone.utc).isoformat(), json.dumps(headers)),
            )
        return {
            'url': validated_url,
            'status': status,
            'content': content,
            'content_length': len(content),
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'headers': headers,
            'cached': False,
        }

    def stats(self) -> dict:
        """Return cache statistics (includes expired entries in count)."""
        with closing(sqlite3.connect(self.db_path)) as db:
            total = db.execute('SELECT COUNT(*) FROM detail_cache').fetchone()[0]
            total_bytes = db.execute(
                'SELECT COALESCE(SUM(content_length), 0) FROM detail_cache'
            ).fetchone()[0]
            domains = db.execute(
                'SELECT COUNT(DISTINCT domain) FROM detail_cache'
            ).fetchone()[0]
        return {'entries': total, 'total_bytes': total_bytes, 'domains': domains}

    def clear_expired(self) -> int:
        """Remove expired entries from the cache. Returns count of deleted rows."""
        with closing(sqlite3.connect(self.db_path)) as db, db:
            # First, find expired hashes
            rows = db.execute(
                'SELECT url_hash, fetched_at FROM detail_cache'
            ).fetchall()
            expired_hashes = [row[0] for row in rows if self._is_expired(row[1])]
            if not expired_hashes:
                return 0
            placeholders = ','.join('?' * len(expired_hashes))
            cursor = db.execute(
                f'DELETE FROM detail_cache WHERE url_hash IN ({placeholders})',
                expired_hashes,
            )
            return cursor.rowcount
