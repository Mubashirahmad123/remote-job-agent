"""A missing username must cost the same as a wrong password (M4).

`verify_login` used to short-circuit on `row is None` and return without
touching Argon2. An existing username therefore cost one Argon2id verify
(~107 ms at m=65536,t=3,p=4) and a non-existent one cost none. Measured over
the real HTTP endpoint during the audit:

    username that exists      601, 663, 712, 745, 780, 799 ms
    username that does not    507, 508 ms

The distributions did not overlap, so a handful of requests sorted any candidate
list into "real account" and "not a real account". That is the prerequisite for
everything else aimed at this endpoint: a password spray pointed only at
usernames known to exist, and a phishing list of confirmed employees.

The response body was already identical (401, same JSON) and the audit trail
already records the attempt either way — wall-clock time was the only remaining
channel.

This file asserts the fix two ways, because one of them can lie:

  * structurally, by counting Argon2id verifications with a spy. This is exact
    and cannot flake.
  * empirically, by timing both paths over the real endpoint. This is the thing
    an attacker actually measures, so it is worth measuring here too — but it is
    noisy, so it interleaves the two paths and compares medians with a generous
    tolerance rather than asserting an absolute bound.

Also pinned: what is deliberately NOT equalised. Requests rejected on their own
shape (empty or oversized password) skip the verification entirely. That branch
is decided by what the caller sent, not by whether the account exists, so it
leaks nothing about usernames — and paying for a decoy verify there would
re-open the unbounded-Argon2 hole that `PASSWORD_MAX_LENGTH` exists to close.
"""

import os
import statistics
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api import auth
from api.app import create_app
from api.auth import (
    _DECOY_PASSWORD_HASH,
    create_user,
    hash_password,
    verify_login,
    verify_password,
)
from api.ratelimit import reset_login_limiter

PASSWORD = "s3cretPass1"
MISSING = "no-such-user-anywhere"


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _fresh_buckets():
    reset_login_limiter()
    yield
    reset_login_limiter()


@pytest.fixture()
def verify_spy(monkeypatch):
    """Every (hash, password) pair handed to a real Argon2id verification."""
    calls = []
    real = auth.verify_password

    def spy(password_hash, password):
        calls.append((password_hash, password))
        return real(password_hash, password)

    monkeypatch.setattr(auth, "verify_password", spy)
    return calls


# --- structural: the count is exact ------------------------------------------


def test_a_missing_username_still_runs_one_verification(verify_spy):
    assert verify_login(MISSING, "whatever-123") is None
    assert len(verify_spy) == 1, (
        f"expected exactly one Argon2id verify on the no-such-user path, got "
        f"{len(verify_spy)} — zero is the timing oracle this fixes"
    )
    assert verify_spy[0][0] == _DECOY_PASSWORD_HASH, (
        "the verification must be against the decoy hash, so it costs what a "
        "real verification costs"
    )


def test_an_existing_username_verifies_against_its_own_hash(verify_spy):
    """Not against the decoy — the decoy is for usernames that do not exist. If
    both paths verified the same hash, a real user's password would never match."""
    create_user("alice", PASSWORD)
    assert verify_login("alice", "wrong-one-123") is None
    assert len(verify_spy) == 1
    used_hash = verify_spy[0][0]
    assert used_hash != _DECOY_PASSWORD_HASH
    assert used_hash.startswith("$argon2id$"), used_hash
    # ...and it really is alice's: the same hash accepts her real password.
    assert verify_password(used_hash, PASSWORD) is True


def test_both_paths_perform_the_same_number_of_verifications(verify_spy):
    create_user("alice", PASSWORD)

    verify_login(MISSING, "same-password")
    missing_count = len(verify_spy)
    verify_spy.clear()

    verify_login("alice", "same-password")
    existing_count = len(verify_spy)

    assert missing_count == existing_count == 1, (
        f"no-such-user ran {missing_count} verifications, existing-user ran "
        f"{existing_count}. Any difference is directly measurable by an attacker."
    )


def test_a_correct_password_is_unaffected(verify_spy):
    create_user("alice", PASSWORD)
    result = verify_login("alice", PASSWORD)
    assert result is not None and result["username"] == "alice"
    assert len(verify_spy) == 1, "a successful login must not verify twice"


def test_the_decoy_never_authenticates_anyone(verify_spy):
    """The decoy's plaintext was generated with token_urlsafe(32) and discarded.
    Even so, pin that reaching it cannot produce a login: the result is thrown
    away unconditionally."""
    for guess in ("", "password", "Password1", PASSWORD, "admin", "secret"):
        assert verify_login(MISSING, guess) is None
    assert not verify_password(_DECOY_PASSWORD_HASH, PASSWORD)


# --- the decoy must be comparable to a real hash ------------------------------


def test_the_decoy_uses_the_production_parameters():
    """The whole fix rests on the decoy verify costing the same as a real one.
    Different m/t/p means a different duration, which is a fresh oracle."""
    assert _DECOY_PASSWORD_HASH.startswith("$argon2id$v=19$")
    decoy_params = _DECOY_PASSWORD_HASH.split("$")[3]
    real_params = hash_password("anything").split("$")[3]
    assert decoy_params == real_params == "m=65536,t=3,p=4", (
        f"decoy {decoy_params} vs live {real_params}"
    )


def test_a_single_verify_costs_what_a_single_verify_costs():
    """Guard against the decoy being, say, a deliberately cheap hash. Two
    verifications — one against the decoy, one against a freshly hashed password
    — must land in the same ballpark."""
    real = hash_password("a-real-password")
    timings = {}
    for label, target in (("decoy", _DECOY_PASSWORD_HASH), ("real", real)):
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            verify_password(target, "some-guess")
            samples.append(time.perf_counter() - start)
        timings[label] = statistics.median(samples)
    ratio = timings["decoy"] / timings["real"] if timings["real"] else 0
    assert 0.5 < ratio < 2.0, (
        f"decoy verify {timings['decoy']*1000:.0f} ms vs real "
        f"{timings['real']*1000:.0f} ms — a ratio of {ratio:.2f} is itself an "
        "oracle"
    )


# --- what is deliberately NOT equalised --------------------------------------


@pytest.mark.parametrize("password", ["", None])
def test_a_rejected_shape_does_not_pay_for_argon2(verify_spy, password):
    """Decided by the caller's own input, not by whether the account exists, so
    it leaks nothing about usernames — and a decoy verify here would re-open the
    unbounded-Argon2 hole the password ceiling closes."""
    create_user("alice", PASSWORD)
    assert verify_login("alice", password) is None
    assert verify_login(MISSING, password) is None
    assert verify_spy == [], "empty/None passwords must be rejected before hashing"


def test_an_oversized_password_does_not_pay_for_argon2(verify_spy, monkeypatch):
    monkeypatch.setenv("PASSWORD_MAX_LENGTH", "32")
    create_user("alice", PASSWORD)
    oversized = "x" * 64
    assert verify_login("alice", oversized) is None
    assert verify_login(MISSING, oversized) is None
    assert verify_spy == []


# --- empirical: over the real HTTP endpoint ----------------------------------


def _login(client, username, password):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def _trimmed(values):
    """Drop the single fastest and slowest sample so one GC pause or one noisy
    neighbour on a shared CI runner cannot decide an assertion about overlap."""
    ordered = sorted(values)
    return ordered[1:-1] if len(ordered) > 4 else ordered


def _ranges_overlap(first, second):
    """True when the two intervals share at least one point.

    Worth spelling out: the first version of this test computed
    `min(max(a), max(b)) > min(min(a), min(b))`, which is true for almost any
    two positive ranges and so passed on the VULNERABLE code. Two intervals
    [a1,a2] and [b1,b2] overlap when the later start is at or before the earlier
    end.
    """
    return max(min(first), min(second)) <= min(max(first), max(second))


def _one_verification_costs():
    """Median wall-clock cost of a single Argon2id verify on THIS machine.

    Everything below is expressed relative to this, which is what makes the
    assertion portable: the fix removes exactly one verification from the
    missing-username path, so the gap between the two paths should be a small
    fraction of one verification's cost. An absolute millisecond bound would be
    wrong on a machine three times faster and a flake generator on a loaded one.
    """
    samples = []
    for _ in range(3):
        start = time.perf_counter()
        verify_password(_DECOY_PASSWORD_HASH, "some-guess")
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def test_the_endpoint_hides_which_usernames_exist(client):
    """The measurement an attacker would actually make.

    Interleaved (missing, existing, missing, existing, ...) so machine drift
    cancels out instead of landing on one side. Two assertions, both scale-free:

      1. the median gap between the paths is a small fraction of the cost of ONE
         Argon2id verify, measured here rather than hardcoded — removing the decoy
         makes the gap equal to that cost, so this is the assertion that fails;
      2. the two sample ranges overlap, which is the attacker's own criterion for
         "cannot tell these apart from timing".

    Before this change the same measurement produced 601-799 ms for an existing
    username and 507-508 ms for a missing one: disjoint, with a gap of roughly
    one Argon2 verify.
    """
    create_user("alice", PASSWORD)
    verify_cost = _one_verification_costs()
    samples = {"missing": [], "existing": []}

    # Warm both paths first: the initial request pays for schema creation,
    # connection setup and import-time work that has nothing to do with Argon2.
    _login(client, MISSING, "wrong-password-1")
    _login(client, "alice", "wrong-password-1")

    for index in range(9):
        for label, username in (("missing", MISSING), ("existing", "alice")):
            reset_login_limiter()
            start = time.perf_counter()
            response = _login(client, username, f"wrong-password-{index}")
            elapsed = time.perf_counter() - start
            assert response.status_code == 401, response.text
            assert response.json() == EXPECTED_401_BODY, (
                "the two failures must also be identical in body, not just in "
                f"status and timing: {response.json()}"
            )
            samples[label].append(elapsed)

    medians = {label: statistics.median(values) for label, values in samples.items()}
    gap = abs(medians["missing"] - medians["existing"])
    budget = 0.4 * verify_cost
    missing_range = _trimmed(samples["missing"])
    existing_range = _trimmed(samples["existing"])

    assert gap <= budget, (
        f"median {medians['missing']*1000:.0f} ms for a missing username vs "
        f"{medians['existing']*1000:.0f} ms for an existing one: a "
        f"{gap*1000:.0f} ms gap against a budget of {budget*1000:.0f} ms "
        f"(one Argon2id verify costs {verify_cost*1000:.0f} ms here). A gap of "
        "about one verify means the missing-username path is skipping it, which "
        "is exactly the oracle."
    )
    assert _ranges_overlap(missing_range, existing_range), (
        "the two timing ranges do not overlap, so one request each is enough to "
        f"tell a real username from a fake one: missing "
        f"{missing_range[0]*1000:.0f}-{missing_range[-1]*1000:.0f} ms, existing "
        f"{existing_range[0]*1000:.0f}-{existing_range[-1]*1000:.0f} ms"
    )


# Both failure paths are asserted against this one literal, so neither can drift
# into a more specific message ("no such user") without failing the test.
EXPECTED_401_BODY = {"detail": "Invalid username or password"}
