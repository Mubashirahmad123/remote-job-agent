"""API_CORS_ORIGINS is filtered, not trusted (M1).

`allow_credentials=True` is required because auth is an HttpOnly cookie, so a
cross-origin dashboard cannot send the session cookie without it. Three separate
places asserted that this was safe because a wildcard "is never accepted":

    api/deps.py       (the old cors_origins() had no such logic at all)
    api/app.py:246    "Starlette rejects '*' combined with credentials anyway"
    PRODUCTION.md:129 "so a wildcard is never accepted"
    .env.example:142  "a wildcard is never accepted"

None of it was true. Starlette 1.7.0 computes:

    preflight_explicit_allow_origin = not allow_all_origins or allow_credentials

so `allow_origins=["*"]` *with* credentials makes it REFLECT the caller's Origin
and answer `Access-Control-Allow-Credentials: true`. Confirmed live against a
server started with API_CORS_ORIGINS=*:

    Origin: https://evil.example
      -> Access-Control-Allow-Origin: https://evil.example
         Access-Control-Allow-Credentials: true
    GET /api/jobs with the operator's session cookie
      -> 200, and a browser would let evil.example read the body

i.e. any website could read the jobs, tracker, CV profile and audit feed of a
signed-in operator. The default configuration was never affected — this only
bites an operator who sets `*`, and the docs actively reassured them it was
harmless.

The existing test in test_api_auth_hardening.py asserted `"*" not in origins`,
which is a true statement about the DEFAULT and says nothing about the override
path that was broken. That is why it passed while the hole was open.
"""

import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import DEFAULT_CORS_ORIGINS, cors_origins

EVIL = "https://evil.example"
GOOD = "https://dash.example.com"


@pytest.fixture()
def set_origins(monkeypatch):
    def _set(value):
        if value is None:
            monkeypatch.delenv("API_CORS_ORIGINS", raising=False)
        else:
            monkeypatch.setenv("API_CORS_ORIGINS", value)

    return _set


def _cors_middleware(app):
    for middleware in app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            return middleware.kwargs
    pytest.fail("CORSMiddleware not found on the app")


# --- the filter --------------------------------------------------------------


def test_default_is_the_localhost_list(set_origins):
    set_origins(None)
    assert cors_origins() == list(DEFAULT_CORS_ORIGINS)


def test_a_valid_named_origin_passes_through(set_origins):
    set_origins(f"{GOOD}, http://other.example.com:8443")
    assert cors_origins() == [GOOD, "http://other.example.com:8443"]


def test_wildcard_alone_falls_back_to_the_defaults(set_origins):
    set_origins("*")
    with pytest.warns(RuntimeWarning, match="wildcard"):
        result = cors_origins()
    assert "*" not in result
    assert result == list(DEFAULT_CORS_ORIGINS), (
        "with nothing usable left, fall back to the stricter default rather than "
        "an empty list — an empty allow_origins silently disables cross-origin "
        "access, which is safe but would read as a mystery bug"
    )


def test_wildcard_mixed_with_a_real_origin_keeps_only_the_real_one(set_origins):
    set_origins(f"*, {GOOD}")
    with pytest.warns(RuntimeWarning):
        result = cors_origins()
    assert result == [GOOD]


@pytest.mark.parametrize(
    "entry",
    [
        "https://*.example.com",       # Starlette has no wildcard matching here
        "*://dash.example.com",
        "null",                        # the file:// / sandboxed-frame origin
        "ftp://dash.example.com",
        "dash.example.com",            # no scheme
        "//dash.example.com",
        f"{GOOD}/dashboard",           # a path never appears in an Origin header
        f"{GOOD}/",                    # trailing slash never matches
        f"{GOOD}/?x=1",
        f"{GOOD}#frag",
        "",
    ],
)
def test_unusable_entries_are_rejected(set_origins, entry):
    """Anything Starlette could never match is dropped loudly. Dead config that
    looks like it grants access is how this class of mistake survives review."""
    set_origins(entry)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = cors_origins()
    assert entry not in result, f"{entry!r} was accepted"
    if entry.strip():
        assert any("ignored" in str(w.message) for w in caught), (
            f"{entry!r} was dropped without telling anyone"
        )


def test_duplicates_and_padding_are_normalised(set_origins):
    set_origins(f"  {GOOD} ,,{GOOD},  ")
    assert cors_origins() == [GOOD]


# --- end to end, through the real middleware ---------------------------------


def test_wildcard_env_does_not_produce_a_reflecting_middleware(set_origins):
    """The property the docs claimed and the code did not enforce."""
    set_origins("*")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        kwargs = _cors_middleware(create_app())
    assert kwargs.get("allow_credentials") is True, "cookie auth needs this"
    assert "*" not in (kwargs.get("allow_origins") or [])


def test_an_evil_origin_gets_no_cors_grant_under_wildcard_env(set_origins):
    """The actual exploit, re-run against the fixed code.

    Before: ACAO echoed https://evil.example with Allow-Credentials: true and
    /api/jobs returned 200 readable by the attacker's page. After: no ACAO
    header at all, so a browser blocks the read.
    """
    set_origins("*")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        client = TestClient(create_app())

    simple = client.get("/api/health/live", headers={"Origin": EVIL})
    assert simple.status_code == 200, "the liveness probe is public by design"
    assert simple.headers.get("access-control-allow-origin") != EVIL, (
        "the attacker's origin was reflected — any website can read authenticated "
        "responses with the operator's cookie"
    )
    assert simple.headers.get("access-control-allow-origin") in (None, ""), (
        f"unexpected ACAO {simple.headers.get('access-control-allow-origin')!r}"
    )

    preflight = client.options(
        "/api/jobs",
        headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 400, (
        f"preflight from an unlisted origin must be refused, got {preflight.status_code}"
    )
    assert preflight.headers.get("access-control-allow-origin") != EVIL


def test_a_configured_origin_still_works(set_origins):
    """The fix must not break the feature: a named cross-origin dashboard is the
    whole reason allow_credentials is on."""
    set_origins(GOOD)
    client = TestClient(create_app())

    preflight = client.options(
        "/api/jobs",
        headers={
            "Origin": GOOD,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200, preflight.text
    assert preflight.headers["access-control-allow-origin"] == GOOD
    assert preflight.headers["access-control-allow-credentials"] == "true"

    simple = client.get("/api/health/live", headers={"Origin": GOOD})
    assert simple.headers.get("access-control-allow-origin") == GOOD


def test_an_unlisted_origin_is_refused_even_with_a_real_allow_list(set_origins):
    set_origins(GOOD)
    client = TestClient(create_app())
    response = client.get("/api/health/live", headers={"Origin": EVIL})
    assert response.headers.get("access-control-allow-origin") != EVIL
