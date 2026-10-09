"""Refuse to aim a server-side browser at anything that is not a public web page.

Why this exists
---------------
`apply_url` reaches `page.goto()` in a real headless browser, in a container
that runs as root, with `./.env` and `./keys.json` mounted. Before this module
the only validation on the way in was `api/schemas.py`'s
`apply_url: str = Field(min_length=1)`, and the navigation sites did none at
all. Both were confirmed by probe: `POST /api/tracker` accepted
`apply_url = "javascript:alert(1)"` and `"file:///etc/passwd"` (they failed
later, on an unrelated Sheets error — i.e. after validation).

So a job row could point the browser at:

    file:///etc/passwd                  local file read
    file:///app/.env                    every API key in the deployment
    file:///app/keys.json               the Google service-account private key
    http://169.254.169.254/...          cloud instance metadata
    http://127.0.0.1:8000/api/...       the API itself, from inside
    http://<other-container>:6379/      anything else on the docker network

and `api/apply.py` stores a screenshot of whatever rendered, which
`GET /api/apply/{fingerprint}/screenshot` then hands back to any authenticated
caller. That is a complete read primitive: aim, navigate, read the picture.

The URLs do not have to come from an authenticated user either. They arrive in
scraped job postings, so a hostile listing on any board the scraper reads can
supply one — and while TLS verification was being disabled on retry (H2, fixed
separately) an on-path attacker could inject one into any board.

Two layers, deliberately
------------------------
The frontend already had this guard: `escape.js`'s `safeHttpUrl()` restricts
rendered hrefs to http/https. That protects the operator's browser. Nothing
protected the server's. This module is the server-side equivalent, applied at
both the point where a URL enters the system and the point where it is
navigated, because the two are not the same set — scraped URLs never pass
through the API schema at all.

`resolve=False` (the default) is pure syntax and literal-IP checking. It is
what the API boundary uses: doing DNS on every request would add latency and
hand an unauthenticated-ish caller a DNS amplification primitive.

`resolve=True` additionally resolves the hostname and rejects the navigation if
ANY address it resolves to is non-public. That is what the `page.goto()` sites
use, and it is what stops `http://attacker.example/` from being a perfectly
valid-looking public hostname that resolves to 169.254.169.254. A name that does
not resolve at all is allowed through — the browser cannot reach it either, and
rejecting it would make the guard untestable against the RFC 2606 reserved names
every hermetic test in this repo uses. `check_navigable_url` documents that
trade-off, and the residual rebinding risk, at the call site.

Known limit, stated rather than hidden: resolve-then-navigate has a TOCTOU gap.
A hostname with a short TTL can resolve to a public address for the check and
to an internal one for the browser (DNS rebinding). Closing that properly means
resolving once and connecting to that pinned address with the Host header set,
which Playwright does not expose. The window is small and the attacker already
needs to control a job posting, but it is real, and `resolve=True` narrows it
rather than eliminating it.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

__all__ = [
    "UrlRejected",
    "check_navigable_url",
    "is_navigable_url",
    "assert_navigable_url",
]

# http/https only. This is what rejects file:, javascript:, data:, vbscript:,
# gopher:, dict:, ftp: and the rest — every non-web scheme a browser will
# happily honour from page.goto().
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Ports a public job board has no reason to serve on. Restricting these stops
# `http://internal-host:6379/` (Redis), `:5432` (Postgres), `:22`, and the
# docker-network service ports, even when the hostname itself looks public.
ALLOWED_PORTS = frozenset({80, 443, None})

# Hostname suffixes that are never internet-routable. Checked as strings so
# they are rejected even when DNS would fail anyway — a name that resolves is
# not evidence that it is public, and some of these resolve via mDNS/search
# domains inside a container.
BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".lan",
    ".corp",
    ".intranet",
    ".home",
    ".localdomain",
)
BLOCKED_HOST_NAMES = frozenset({"localhost", "metadata", "instance-data"})

# Ranges the ipaddress predicates miss on current Python, listed explicitly so
# the block does not silently depend on a standard-library detail. Both are
# reachable from inside a VM and neither is a public job board.
_EXTRA_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "100.64.0.0/10",   # CGNAT / RFC 6598 shared address space
        "192.88.99.0/24",  # 6to4 relay anycast, deprecated by RFC 7526
    )
)


class UrlRejected(ValueError):
    """A URL that must not be navigated to. Carries a human-readable reason.

    A ValueError subclass so existing `except Exception` handlers around the
    browser paths keep working unchanged, while callers that care can catch the
    specific type.
    """

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"refusing to navigate to {url!r}: {reason}")


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Why this address is not a public internet destination, or '' if it is."""
    # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) is the IPv4 address; check
    # that, or the mapping becomes a way to smuggle a blocked IPv4 past the
    # IPv6 predicates.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    sixtofour = getattr(ip, "sixtofour", None)
    if sixtofour is not None:
        ip = sixtofour

    # link-local is checked before private because is_private also returns True
    # for it, and "link-local" is the accurate thing to tell an operator who
    # just tried to point the scraper at 169.254.169.254.
    checks = (
        ("loopback", ip.is_loopback),
        ("link-local", ip.is_link_local),          # 169.254.169.254 metadata
        ("private", ip.is_private),
        ("multicast", ip.is_multicast),
        ("reserved", ip.is_reserved),
        ("unspecified", ip.is_unspecified),
    )
    for name, hit in checks:
        if hit:
            return f"resolves to a {name} address ({ip})"

    # The named predicates above are not exhaustive, and the gaps are exactly
    # the interesting ones. On Python 3.11:
    #
    #   100.64.0.0/10   is_private=False is_global=False  CGNAT / RFC 6598
    #   192.88.99.0/24  is_private=False is_global=True   6to4 relay anycast
    #
    # 100.64.0.0/10 is the one that matters operationally: cloud providers use
    # shared address space for their own internal fabric, so it is a real
    # destination from inside a VM and `is_private` does not flag it. Rather
    # than enumerate ranges and drift as the ipaddress module changes, ask the
    # question that was actually meant — "is this reachable on the public
    # internet?" — and reject anything that is not.
    if not ip.is_global:
        return f"resolves to a non-globally-routable address ({ip})"
    for extra in _EXTRA_BLOCKED_NETWORKS:
        # Membership across address families raises TypeError, so compare only
        # within a version.
        if ip.version == extra.version and ip in extra:
            return f"resolves to a blocked address ({ip} in {extra})"
    return ""


def _check_host_literal(host: str) -> str:
    """Check a hostname that may itself be an IP literal. Returns a reason."""
    lowered = host.lower().rstrip(".")
    if not lowered:
        return "has no host"
    if lowered in BLOCKED_HOST_NAMES:
        return f"host {lowered!r} is never a public destination"
    for suffix in BLOCKED_HOST_SUFFIXES:
        if lowered.endswith(suffix):
            return f"host {lowered!r} is in the non-routable {suffix} namespace"
    # Strip IPv6 brackets before parsing.
    candidate = lowered[1:-1] if lowered.startswith("[") and lowered.endswith("]") else lowered
    try:
        return _blocked_ip(ipaddress.ip_address(candidate))
    except ValueError:
        return ""  # a hostname, not a literal — the resolver decides


def check_navigable_url(url: object, *, resolve: bool = False) -> str:
    """Return the reason this URL must not be navigated to, or '' if it may be.

    Returns a string rather than raising so callers can log-and-skip a single
    job without unwinding a whole scrape run.
    """
    if not isinstance(url, str):
        return f"is not a string ({type(url).__name__})"
    # urlparse tolerates leading/trailing whitespace and embedded tabs/newlines
    # on modern Python, but do it explicitly: "  file:///etc/passwd" and
    # "java\tscript:..." are exactly the shapes used to slip past a prefix check.
    cleaned = url.strip().replace("\t", "").replace("\n", "").replace("\r", "")
    if not cleaned:
        return "is empty"

    try:
        parsed = urlparse(cleaned)
    except ValueError as exc:
        return f"could not be parsed ({exc})"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return f"scheme {scheme or '(none)'!r} is not allowed; only http and https are"

    host = parsed.hostname or ""
    if not host:
        return "has no host"

    # `http://trusted.example@evil.example/` parses with hostname=evil.example.
    # Reject rather than reason about which half a browser would believe.
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        return "contains embedded credentials (a user:pass@ prefix)"

    if parsed.port is not None and parsed.port not in ALLOWED_PORTS:
        return f"port {parsed.port} is not 80 or 443"

    reason = _check_host_literal(host)
    if reason:
        return reason

    if resolve:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80))
        except (socket.gaierror, UnicodeError, OSError):
            # A name that does not resolve is NOT rejected, which is a deliberate
            # reversal of the usual fail-closed instinct. Two reasons:
            #
            #   * It buys nothing. A host the resolver cannot answer is a host
            #     the browser cannot reach either, so the navigation fails on its
            #     own a moment later. Rejecting early only changes the error text.
            #   * It would break hermetic testing. Every reserved name this repo's
            #     tests use — .test, .example, .invalid — correctly never
            #     resolves, so a fail-closed resolver check makes the guard
            #     untestable without monkeypatching DNS at every call site.
            #
            # What IS rejected is the case that matters: a name that resolves
            # successfully to a non-public address, which is how a
            # public-looking hostname reaches 169.254.169.254.
            #
            # Residual risk, stated rather than hidden: intermittent resolution —
            # NXDOMAIN for this check, an internal address for the browser's —
            # gets through. That is the DNS-rebinding TOCTOU described in the
            # module docstring; closing it means resolving once and connecting to
            # that pinned address, which Playwright does not expose.
            return ""
        for info in infos:
            address = info[4][0]
            try:
                ip = ipaddress.ip_address(address.split("%")[0])
            except ValueError:
                return f"host {host!r} resolved to an unparsable address {address!r}"
            blocked = _blocked_ip(ip)
            if blocked:
                return f"host {host!r} {blocked}"
    return ""


def is_navigable_url(url: object, *, resolve: bool = False) -> bool:
    """True when `url` may be handed to a browser or an HTTP client."""
    return check_navigable_url(url, resolve=resolve) == ""


def assert_navigable_url(url: object, *, resolve: bool = False) -> str:
    """Raise UrlRejected unless `url` may be navigated to. Returns the URL.

    Use at the `page.goto()` boundary: the raise is caught by the surrounding
    per-job error handling, so one poisoned row skips instead of aborting a run.
    """
    reason = check_navigable_url(url, resolve=resolve)
    if reason:
        raise UrlRejected(str(url), reason)
    return str(url)
