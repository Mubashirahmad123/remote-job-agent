"""Tests for tools/detail_cache.py: hash-keyed, rate-limited, size-capped
detail page cache. No network, no live APIs."""
import json
from pathlib import Path

import pytest

from tools.detail_cache import DetailCache


class TestDetailCache:
    def test_fetch_and_cache(self, tmp_path):
        """First fetch hits the network; second fetch is from cache."""
        db_path = tmp_path / "detail_cache.db"

        html = "<html><body>Full job description here</body></html>"
        headers = {"content-type": "text/html"}
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            return 200, html, headers

        cache = DetailCache(db_path=db_path, max_bytes=50000, rate_limit=0.0,
                            fetch_func=fake_fetch)

        result = cache.get("https://example.com/job/1")
        assert result["status"] == 200
        assert result["content"] == html
        assert result["content_length"] == len(html)
        assert result["cached"] is False
        assert len(calls) == 1

        # Second call: should use cache, no network
        result2 = cache.get("https://example.com/job/1")
        assert result2["cached"] is True
        assert result2["content"] == html
        assert len(calls) == 1  # no additional network call

    def test_size_cap(self, tmp_path):
        """Content larger than max_bytes is truncated DURING fetch (streaming)."""
        db_path = tmp_path / "detail_cache.db"

        html = "<html><body>" + "x" * 1000 + "</body></html>"
        headers = {"content-type": "text/html"}
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            # Simulate streaming: return only up to max_bytes
            truncated = html[:max_bytes]
            return 200, truncated, headers

        cache = DetailCache(db_path=db_path, max_bytes=100, rate_limit=0.0,
                            fetch_func=fake_fetch)

        result = cache.get("https://example.com/job/big")
        assert result["content_length"] == 100
        assert len(result["content"]) == 100

    def test_fetch_failure_not_cached(self, tmp_path):
        """A failed fetch (status 0) is NOT cached; subsequent calls retry."""
        db_path = tmp_path / "detail_cache.db"
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            raise Exception("connection refused")

        cache = DetailCache(db_path=db_path, max_bytes=50000, rate_limit=0.0,
                            fetch_func=fake_fetch)

        # First call fails
        result = cache.get("https://example.com/job/bad")
        assert result is not None
        assert result["status"] == 0
        assert result["content"] == ""
        assert result["cached"] is False
        assert len(calls) == 1

        # Second call should RETRY (not cached)
        result2 = cache.get("https://example.com/job/bad")
        assert result2["status"] == 0
        assert len(calls) == 2  # retried!

    def test_url_hash_deterministic(self):
        """Same URL always produces same hash key."""
        from tools.detail_cache import _url_hash
        h1 = _url_hash("https://example.com/job/1")
        h2 = _url_hash("https://example.com/job/1")
        h3 = _url_hash("https://example.com/job/2")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 32

    def test_stats(self, tmp_path):
        """stats() reports entry count, total bytes, domain count."""
        db_path = tmp_path / "detail_cache.db"

        html = "<html><body>content</body></html>"
        headers = {"content-type": "text/html"}
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            return 200, html, headers

        cache = DetailCache(db_path=db_path, max_bytes=50000, rate_limit=0.0,
                            fetch_func=fake_fetch)

        cache.get("https://example.com/job/1")
        cache.get("https://example.com/job/2")
        stats = cache.stats()
        assert stats["entries"] == 2
        assert stats["total_bytes"] > 0
        assert stats["domains"] == 1

    # ── D7: SSRF protection ──────────────────────────────────────────────
    def test_ssrf_blocks_private_ipv4(self, tmp_path):
        """Private IPv4 addresses (RFC 1918) are rejected."""
        db_path = tmp_path / "detail_cache.db"
        cache = DetailCache(db_path=db_path, rate_limit=0.0)
        for ip in ("10.0.0.1", "172.16.0.1", "172.31.255.255", "192.168.1.1",
                   "127.0.0.1", "169.254.169.254"):
            result = cache.get(f"http://{ip}/job")
            assert result["status"] == 0
            assert "SSRF" in result["headers"].get("error", "")

    def test_ssrf_blocks_private_ipv6(self, tmp_path):
        """Private IPv6 addresses (ULA, link-local, loopback) are rejected."""
        db_path = tmp_path / "detail_cache.db"
        cache = DetailCache(db_path=db_path, rate_limit=0.0)
        for ip in ("::1", "fc00::1", "fd00::1", "fe80::1"):
            result = cache.get(f"http://[{ip}]/job")
            assert result["status"] == 0
            assert "SSRF" in result["headers"].get("error", "")

    def test_ssrf_blocks_localhost(self, tmp_path):
        """Explicit localhost hostnames are rejected."""
        db_path = tmp_path / "detail_cache.db"
        cache = DetailCache(db_path=db_path, rate_limit=0.0)
        for host in ("localhost", "localhost.localdomain"):
            result = cache.get(f"http://{host}/job")
            assert result["status"] == 0
            assert "SSRF" in result["headers"].get("error", "")

    def test_ssrf_blocks_non_http_schemes(self, tmp_path):
        """Non-HTTP(S) schemes are rejected."""
        db_path = tmp_path / "detail_cache.db"
        cache = DetailCache(db_path=db_path, rate_limit=0.0)
        for scheme in ("ftp", "file", "gopher", "javascript", "data"):
            result = cache.get(f"{scheme}://example.com/job")
            assert result["status"] == 0
            assert "SSRF" in result["headers"].get("error", "")

    def test_ssrf_allows_public_hostnames(self, tmp_path):
        """Public hostnames are allowed (DNS resolution happens at fetch time)."""
        db_path = tmp_path / "detail_cache.db"
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            return 200, "ok", {}

        cache = DetailCache(db_path=db_path, rate_limit=0.0, fetch_func=fake_fetch)
        result = cache.get("https://api.example.com/job/1")
        assert result["status"] == 200
        assert len(calls) == 1

    # ── D7: TTL expiration ───────────────────────────────────────────────
    def test_ttl_expired_entry_refetched(self, tmp_path):
        """Expired cache entries are re-fetched (not served stale)."""
        db_path = tmp_path / "detail_cache.db"
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            return 200, f"content-{len(calls)}", {}

        # TTL = 0 days -> immediate expiry
        cache = DetailCache(db_path=db_path, rate_limit=0.0, ttl_days=0,
                            fetch_func=fake_fetch)

        # First fetch
        r1 = cache.get("https://example.com/job/1")
        assert r1["cached"] is False
        assert r1["content"] == "content-1"
        assert len(calls) == 1

        # Immediate second fetch should re-fetch because TTL=0
        r2 = cache.get("https://example.com/job/1")
        assert r2["cached"] is False  # not served from cache
        assert r2["content"] == "content-2"
        assert len(calls) == 2

    def test_ttl_valid_entry_served_from_cache(self, tmp_path):
        """Non-expired entries are served from cache."""
        db_path = tmp_path / "detail_cache.db"
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            return 200, "fresh-content", {}

        # TTL = 1 day -> not expired
        cache = DetailCache(db_path=db_path, rate_limit=0.0, ttl_days=1,
                            fetch_func=fake_fetch)

        r1 = cache.get("https://example.com/job/1")
        assert r1["cached"] is False
        assert len(calls) == 1

        r2 = cache.get("https://example.com/job/1")
        assert r2["cached"] is True
        assert r2["content"] == "fresh-content"
        assert len(calls) == 1  # no re-fetch

    def test_clear_expired_removes_old_entries(self, tmp_path):
        """clear_expired() removes only expired entries."""
        db_path = tmp_path / "detail_cache.db"
        calls = []

        def fake_fetch(url, max_bytes=50000):
            calls.append(url)
            return 200, "content", {}

        # Seed cache with TTL=0 (immediately expired)
        cache = DetailCache(db_path=db_path, rate_limit=0.0, ttl_days=0,
                            fetch_func=fake_fetch)
        cache.get("https://example.com/job/1")
        cache.get("https://example.com/job/2")
        assert cache.stats()["entries"] == 2

        # Create new cache instance with TTL=1 (entries now valid for it)
        cache2 = DetailCache(db_path=db_path, rate_limit=0.0, ttl_days=1)
        assert cache2.stats()["entries"] == 2
        # clear_expired with TTL=1 should remove nothing
        assert cache2.clear_expired() == 0
        assert cache2.stats()["entries"] == 2

        # Now use TTL=0 again and clear
        cache3 = DetailCache(db_path=db_path, rate_limit=0.0, ttl_days=0)
        deleted = cache3.clear_expired()
        assert deleted == 2
        assert cache3.stats()["entries"] == 0
