"""In-process sliding-window rate limiter for the public auth endpoints.

Why this exists
  `POST /api/auth/login` is the only unauthenticated write on the API. A
  `time.sleep()` penalty inside a *sync* endpoint is not a defence — it holds
  a Starlette threadpool worker (default pool = 40) for the whole penalty, so
  ~40 concurrent bad-password requests stall every other sync route. Measured
  before this module: 40 concurrent bad logins => 5.6s wall, ~4.8s each.

  The fix is to reject *before* doing any expensive work (Argon2 verify,
  session insert) and to make the penalty non-blocking. This module is that
  "reject before" half; api/routers/auth.py is the other half.

Design
  Sliding window (not fixed buckets): each key keeps its recent hit
  timestamps, so a limiter can never be dodged by straddling a bucket
  boundary. Memory is bounded two ways — per-key history is trimmed to the
  window, and `_prune()` drops keys that have gone quiet.

Scope
  Deliberately **per-process**, not shared. docker-compose runs the API with
  `--workers 1`, so this is exact. If you ever scale out, move the same
  interface onto Redis/SQLite — the call sites do not change. A limiter that
  is per-process is still strictly better than no limiter: with N workers an
  attacker gets N x the budget, not an unbounded one.

Env
  LOGIN_RATE_LIMIT        attempts per window per client IP  (default 12)
  LOGIN_RATE_WINDOW       window in seconds                  (default 600)
  LOGIN_USER_RATE_LIMIT   attempts per window per username   (default 6)
  TRUST_PROXY_HEADERS     honour X-Forwarded-For for the client IP
                          (default false — set true ONLY behind your own proxy,
                          otherwise a client can spoof the header and get a
                          fresh bucket per request)

All functions are thread-safe; the login handler may run in a worker thread.
"""

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

__all__ = [
    "Decision",
    "RateLimiter",
    "client_ip",
    "login_limiter",
    "reset_login_limiter",
]


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(float(os.getenv(name, "") or default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class Decision:
    """Outcome of one `allow()` call.

    `allowed` is False when the budget is spent; `retry_after` is then the
    number of seconds until the oldest recorded hit leaves the window (always
    >= 1, so it is usable directly as a `Retry-After` header).
    """

    __slots__ = ("allowed", "remaining", "retry_after")

    def __init__(self, allowed: bool, remaining: int, retry_after: int = 0) -> None:
        self.allowed = allowed
        self.remaining = max(0, remaining)
        self.retry_after = retry_after

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Decision(allowed={self.allowed}, remaining={self.remaining}, "
            f"retry_after={self.retry_after})"
        )


class RateLimiter:
    """Sliding-window counter keyed by an arbitrary hashable identity."""

    def __init__(self, limit: int, window_seconds: float, max_keys: int = 4096) -> None:
        self.limit = max(1, int(limit))
        self.window = max(1.0, float(window_seconds))
        # Hard cap on tracked keys so a flood of distinct identities (rotating
        # IPs, random usernames) cannot grow the dict without bound.
        self.max_keys = max(64, int(max_keys))
        self._hits: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        """Drop keys whose history has fully expired (caller holds the lock)."""
        cutoff = now - self.window
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
        for key in stale:
            del self._hits[key]
        # Still over cap (many *active* keys): evict the least recently hit.
        # Target `max_keys - 1` so the entry `allow()` is about to add cannot
        # push the dict past the cap — the bound holds at all times, not just
        # between calls.
        budget = self.max_keys - 1
        if len(self._hits) > budget:
            for key, _ in sorted(
                self._hits.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0
            )[: len(self._hits) - budget]:
                del self._hits[key]

    def allow(self, key: str) -> Decision:
        """Record one attempt for `key`; report whether it is within budget.

        A rejected attempt is NOT recorded — otherwise a client that keeps
        hammering after the limit would push its own oldest hit out of the
        window and never see the counter fall.
        """
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            self._prune(now)
            history = [t for t in self._hits.get(key, ()) if t > cutoff]
            if len(history) >= self.limit:
                retry_after = int(history[0] + self.window - now) + 1
                self._hits[key] = history
                return Decision(False, 0, max(1, retry_after))
            history.append(now)
            self._hits[key] = history
            return Decision(True, self.limit - len(history), 0)

    def reset(self, key: Optional[str] = None) -> None:
        """Clear one key, or every key when `key` is None (used by tests)."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)

    def snapshot(self, key: str) -> int:
        """Attempts currently recorded against `key` (test/inspection aid)."""
        cutoff = time.monotonic() - self.window
        with self._lock:
            return len([t for t in self._hits.get(key, ()) if t > cutoff])


class _LoginLimiter:
    """Two independent budgets per login attempt: per-IP and per-username.

    Both must allow the attempt. Per-IP alone lets one attacker lock out a
    whole NAT'd office; per-username alone lets an attacker spray one password
    across every account from rotating IPs. Neither alone is sufficient, so
    the pair is checked together and the strictest `retry_after` is returned.
    """

    def __init__(self) -> None:
        self._by_ip: Optional[RateLimiter] = None
        self._by_user: Optional[RateLimiter] = None
        self._lock = threading.Lock()

    def _build(self) -> Tuple[RateLimiter, RateLimiter]:
        """Lazily (re)build from env so tests can monkeypatch between calls."""
        with self._lock:
            by_ip = RateLimiter(
                _positive_int("LOGIN_RATE_LIMIT", 12),
                _positive_int("LOGIN_RATE_WINDOW", 600),
            )
            by_user = RateLimiter(
                _positive_int("LOGIN_USER_RATE_LIMIT", 6),
                _positive_int("LOGIN_RATE_WINDOW", 600),
            )
            self._by_ip, self._by_user = by_ip, by_user
            return by_ip, by_user

    @property
    def by_ip(self) -> RateLimiter:
        return self._by_ip if self._by_ip is not None else self._build()[0]

    @property
    def by_user(self) -> RateLimiter:
        return self._by_user if self._by_user is not None else self._build()[1]

    def allow(self, ip: str, username: str) -> Decision:
        """Check both budgets.

        The username bucket is consumed even when the IP bucket already
        rejected, so an attacker rotating IPs still exhausts the per-account
        budget (and vice versa).
        """
        ip_decision = self.by_ip.allow(f"ip:{ip or 'unknown'}")
        user_decision = self.by_user.allow(f"user:{(username or '').strip().lower()}")
        if ip_decision.allowed and user_decision.allowed:
            return Decision(True, min(ip_decision.remaining, user_decision.remaining), 0)
        return Decision(
            False, 0, max(ip_decision.retry_after, user_decision.retry_after, 1)
        )

    def clear_success(self, ip: str, username: str) -> None:
        """Forget the per-account budget after a *successful* login.

        A legitimate operator who mistyped twice should not carry those
        failures into their next session. The per-IP budget is deliberately
        kept: it is the anti-spray control and a success does not prove the IP
        is benign.
        """
        self.by_user.reset(f"user:{(username or '').strip().lower()}")

    def reset(self) -> None:
        """Drop every bucket (tests, and the `reset_login_limiter` helper)."""
        with self._lock:
            self._by_ip = None
            self._by_user = None


login_limiter = _LoginLimiter()


def reset_login_limiter() -> None:
    """Clear all login budgets — call between tests so state never leaks."""
    login_limiter.reset()


def client_ip(request) -> str:
    """Best-effort client IP for rate-limit keying.

    `request.client.host` is authoritative when uvicorn runs with
    `--proxy-headers` (docker-compose does), because uvicorn has already
    rewritten it from X-Forwarded-For. Reading the header *again* here would
    double-trust it.

    TRUST_PROXY_HEADERS=true is the escape hatch for deployments where the
    proxy is trusted but uvicorn was not told about it. It is OFF by default:
    honouring a client-supplied X-Forwarded-For would let an attacker mint a
    fresh bucket per request by randomising the header, which is worse than no
    limiter at all.
    """
    try:
        direct = request.client.host if request.client else ""
    except Exception:
        direct = ""
    raw = (os.getenv("TRUST_PROXY_HEADERS") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        try:
            forwarded = (request.headers.get("x-forwarded-for") or "").strip()
        except Exception:
            forwarded = ""
        if forwarded:
            # Left-most entry is the original client; the rest are proxies.
            return forwarded.split(",")[0].strip() or direct or "unknown"
    return direct or "unknown"
