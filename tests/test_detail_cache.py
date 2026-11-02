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
        cache = DetailCache(db_path=db_path, max_bytes=50000, rate_limit=0.0)

        html = "<html><body>Full job description here</body></html>"
        headers = {"content-type": "text/html"}
        calls = []

        def fake_fetch(url):
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
        """Content larger than max_bytes is truncated."""
        db_path = tmp_path / "detail_cache.db"
        cache = DetailCache(db_path=db_path, max_bytes=100, rate_limit=0.0)

        html = "<html><body>" + "x" * 1000 + "</body></html>"
        headers = {"content-type": "text/html"}
        calls = []

        def fake_fetch(url):
            calls.append(url)
            return 200, html, headers

        cache = DetailCache(db_path=db_path, max_bytes=100, rate_limit=0.0,
                            fetch_func=fake_fetch)

        result = cache.get("https://example.com/job/big")
        assert result["content_length"] == 100
        assert len(result["content"]) == 100

    def test_fetch_failure_returns_none(self, tmp_path):
        """A failed fetch returns status=0 (no crash)."""
        db_path = tmp_path / "detail_cache.db"
        cache = DetailCache(db_path=db_path, max_bytes=50000, rate_limit=0.0)

        def fake_fetch(url):
            raise Exception("connection refused")

        cache = DetailCache(db_path=db_path, max_bytes=50000, rate_limit=0.0,
                            fetch_func=fake_fetch)

        result = cache.get("https://example.com/job/bad")
        assert result is not None
        assert result["status"] == 0
        assert result["content"] == ""
        assert result["cached"] is False

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
        cache = DetailCache(db_path=db_path, max_bytes=50000, rate_limit=0.0)

        html = "<html><body>content</body></html>"
        headers = {"content-type": "text/html"}
        calls = []

        def fake_fetch(url):
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
