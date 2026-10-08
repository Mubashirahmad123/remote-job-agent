"""Proxy-header trust: who is allowed to tell us the client's IP address.

`api.ratelimit.client_ip()` deliberately returns `request.client.host` and only
consults `X-Forwarded-For` when `TRUST_PROXY_HEADERS=true`. That is correct —
but it rests on an assumption the deployment has to honour: that
`request.client.host` is the real client, not a value the client chose.

It was not. `docker-compose.yml` ran uvicorn with:

    --proxy-headers --forwarded-allow-ips "*"

and uvicorn's ProxyHeadersMiddleware, when every host is trusted, takes the
LEFT-MOST X-Forwarded-For entry:

    if self.always_trust:
        return _parse_host_port(x_forwarded_for_hosts[0])

Caddy APPENDS the real client IP to an incoming X-Forwarded-For rather than
replacing it, so an attacker sent `X-Forwarded-For: <chosen>`, Caddy forwarded
`<chosen>, <real>`, and uvicorn believed `<chosen>`. `client_ip()` then keyed the
per-IP login budget on a string the attacker picked.

Measured against a live server started with the compose flags as they were:

    40 login attempts / 40 usernames, fresh spoofed IP each -> 0 x 429
    the same 40 attempts with no X-Forwarded-For            -> 429 at attempt 13

The per-username budget still held, so this was not unlimited brute force
against one account; it was unlimited *spraying* across every account, and it
destroyed the audit trail — 64 login_events rows carried 46 distinct client_ips
from a single real source.

The compose comment argued `*` was safe because the port is only published to
127.0.0.1 and the docker network. That reasoning is wrong: the forged header
arrives *through* Caddy, from the public internet. Who can open a TCP connection
is not who controls the header value.

The fix is two independent ends, either of which closes it:
  * compose narrows --forwarded-allow-ips to the pinned internal subnet, so
    uvicorn walks the list from the RIGHT and stops at the real client;
  * deploy/Caddyfile overwrites X-Forwarded-For with {remote_host}, so the list
    only ever contains the real client in the first place.
"""

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware, _TrustedHosts

from api.app import create_app
from api.auth import create_user, db_path
from api.ratelimit import reset_login_limiter

# Must stay in sync with docker-compose.yml; test_compose_pins_the_subnet the
# test below fails if the two disagree.
SUBNET = "172.28.0.0/16"
CADDY_CONTAINER_IP = "172.28.0.5"   # the proxy, inside the trusted subnet
REAL_CLIENT_IP = "203.0.113.9"      # what Caddy appends after the attacker's value
PASSWORD = "s3cretPass1"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _client(trusted):
    """The app behind uvicorn's proxy-header middleware, as compose runs it.

    `client=` is the TCP peer, i.e. Caddy. TestClient does not add
    ProxyHeadersMiddleware itself — uvicorn does — so without wrapping it here
    the middleware under test would never run and the test would pass vacuously.
    """
    app = ProxyHeadersMiddleware(create_app(), trusted_hosts=[trusted])
    return TestClient(app, client=(CADDY_CONTAINER_IP, 40000))


def _attempt(client, username, spoofed_ip):
    """One login, forged exactly as Caddy would forward it: attacker first."""
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": "definitely-wrong"},
        headers={"X-Forwarded-For": f"{spoofed_ip}, {REAL_CLIENT_IP}"},
    )


# --- the mechanism -----------------------------------------------------------


def test_wildcard_trust_believes_the_leftmost_spoofed_entry():
    """Why "*" is banned. This is uvicorn's behaviour, pinned so that a future
    uvicorn upgrade which changes it is a visible event rather than a silent
    change in our security posture."""
    wildcard = _TrustedHosts(["*"])
    assert wildcard.get_trusted_client_address(f"8.8.8.8, {REAL_CLIENT_IP}")[0] == "8.8.8.8", (
        "uvicorn no longer takes the left-most entry when trusting '*'; "
        "re-read this module's docstring before relaxing the compose guard"
    )


def test_narrowed_trust_resolves_the_real_client_instead():
    """The same forged header, with the subnet compose now configures."""
    narrowed = _TrustedHosts([SUBNET])
    assert narrowed.get_trusted_client_address(f"8.8.8.8, {REAL_CLIENT_IP}")[0] == REAL_CLIENT_IP


def test_narrowed_trust_still_accepts_a_direct_connection_from_the_proxy():
    """No X-Forwarded-For at all must still yield the peer address, or narrowing
    the allow-list would break the ordinary single-proxy path."""
    create_user("alice", PASSWORD)   # before startup, so the app is in enforced mode
    app = ProxyHeadersMiddleware(create_app(), trusted_hosts=[SUBNET])
    with TestClient(app, client=(CADDY_CONTAINER_IP, 40000)) as client:
        assert client.post(
            "/api/auth/login", json={"username": "alice", "password": PASSWORD}
        ).status_code == 200


# --- the security property ---------------------------------------------------


def test_rotating_forwarded_for_cannot_mint_fresh_rate_limit_buckets(monkeypatch):
    """The end-to-end regression: the exact attack, with the fix in place.

    Ten attempts, each claiming a different source IP, all really from one
    client. The IP budget is 3, so this must 429 — and the negative control
    below proves the test would catch a return to "*".
    """
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "3")
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "999")  # isolate the IP budget
    monkeypatch.setenv("LOGIN_RATE_WINDOW", "600")
    reset_login_limiter()
    create_user("alice", PASSWORD)

    client = _client(SUBNET)
    codes = [
        _attempt(client, f"spray_{i}", f"10.0.{i // 250}.{i % 250 + 1}").status_code
        for i in range(10)
    ]
    assert 429 in codes, f"a forged X-Forwarded-For reset the IP budget: {codes}"
    assert codes.index(429) <= 3, f"429 arrived too late: {codes}"


def test_negative_control_wildcard_trust_reopens_the_bypass(monkeypatch):
    """Same loop, "*" instead of the subnet: no 429 ever.

    Without this the test above could pass for an unrelated reason (a limiter
    that never allows anything, a client fixture that drops the header) and
    nobody would notice it had stopped proving anything.
    """
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "3")
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "999")
    monkeypatch.setenv("LOGIN_RATE_WINDOW", "600")
    reset_login_limiter()
    create_user("alice", PASSWORD)

    client = _client("*")
    codes = [
        _attempt(client, f"spray_{i}", f"10.0.{i // 250}.{i % 250 + 1}").status_code
        for i in range(10)
    ]
    assert 429 not in codes, (
        f"the bypass no longer reproduces under '*': {codes}. If uvicorn changed "
        "its left-most behaviour, update this test and the docstring together."
    )


def test_audit_trail_records_the_real_client_not_the_forged_one(monkeypatch):
    """login_events.client_ip is the forensic record; it must not be a
    client-chosen string. 46 distinct IPs from one source is what this looked
    like before the fix."""
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "999")
    monkeypatch.setenv("LOGIN_USER_RATE_LIMIT", "999")
    reset_login_limiter()
    create_user("alice", PASSWORD)

    client = _client(SUBNET)
    for i in range(5):
        _attempt(client, "alice", f"198.18.{i}.1")

    rows = sqlite3.connect(db_path()).execute(
        "SELECT DISTINCT client_ip FROM login_events"
    ).fetchall()
    recorded = sorted(r[0] for r in rows)
    assert recorded == [REAL_CLIENT_IP], (
        f"audit trail recorded {recorded}, expected only {REAL_CLIENT_IP}"
    )


# --- the configuration itself ------------------------------------------------


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def test_compose_never_trusts_every_proxy():
    compose = _read("docker-compose.yml")
    m = re.search(r'"--forwarded-allow-ips",\s*"([^"]+)"', compose)
    assert m, "uvicorn is running --proxy-headers without an explicit allow-list"
    value = m.group(1)
    assert value.strip() != "*", (
        '--forwarded-allow-ips "*" lets any client forge its own rate-limit '
        "bucket and its own audit-trail IP; see this module's docstring"
    )


def test_compose_pins_the_subnet_the_allow_list_names():
    """The allow-list and the network must agree, or the allow-list names a
    subnet no container is ever in and every request looks untrusted."""
    compose = _read("docker-compose.yml")
    allow = re.search(r'"--forwarded-allow-ips",\s*"\$\{(\w+):?-?([^"}]*)\}"', compose)
    subnet = re.search(r"subnet:\s*\$\{(\w+):?-?([^}]*)\}", compose)
    assert allow, "--forwarded-allow-ips is not driven by a variable"
    assert subnet, "networks.default has no pinned subnet"
    assert allow.group(1) == subnet.group(1), (
        f"--forwarded-allow-ips uses ${{{allow.group(1)}}} but the network uses "
        f"${{{subnet.group(1)}}}; one variable must drive both so they cannot drift"
    )
    assert (allow.group(2) or "") == (subnet.group(2) or ""), "defaults differ"
    assert (allow.group(2) or SUBNET) == SUBNET, "update SUBNET in this file to match"


def test_caddy_overwrites_the_forwarded_headers():
    """The second, independent end of the fix."""
    caddy = _read("deploy/Caddyfile")
    assert re.search(r"header_up\s+X-Forwarded-For\s+\{remote_host\}", caddy), (
        "Caddy must SET X-Forwarded-For, not append to a client-supplied value"
    )
    assert re.search(r"header_up\s+X-Forwarded-Proto\s+\{scheme\}", caddy), (
        "X-Forwarded-Proto feeds api.auth.cookie_secure(); it must not be "
        "client-controlled either"
    )


def test_trust_proxy_headers_stays_off_by_default():
    """The app-level switch must not be flipped on to compensate: with it on,
    client_ip() reads the left-most header itself and reopens the same hole no
    matter what uvicorn is told."""
    for rel in ("docker-compose.yml", ".env.example", "deploy/Caddyfile"):
        text = _read(rel)
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            assert not re.search(r"^\s*TRUST_PROXY_HEADERS\s*[:=]\s*(1|true|yes|on)", line), (
                f"{rel} enables TRUST_PROXY_HEADERS; uvicorn --proxy-headers "
                "already rewrites the client IP, so reading the header again "
                "double-trusts a client-controlled value"
            )
