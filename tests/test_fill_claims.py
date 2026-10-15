"""Unit tests for api.fill_claims — the atomic fill-generation lock.

These pin the primitive the double-fire fix rests on: of two racers on one
fingerprint exactly one wins; a crashed claim self-expires; and a release
only ever drops the caller's own row. The DB is isolated per test by
tests/conftest.py (`_isolate_apply_state_db`).
"""

import os
import sys
import threading
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from api import apply_state
from api.fill_claims import (
    STALE_FILL_CLAIM_MINUTES,
    FillInProgress,
    claim_fill,
    list_active_fill_fingerprints,
    refresh_fill_claim,
    release_fill_claim,
)


@pytest.fixture()
def connection():
    conn = apply_state.connect()
    yield conn
    conn.close()


class TestClaimFill:
    def test_first_claim_wins_and_second_raises(self, connection):
        claim = claim_fill(connection, "fp-a", actor="dashboard")
        assert claim["job_fingerprint"] == "fp-a"
        assert claim["claimed_at"]

        with pytest.raises(FillInProgress) as excinfo:
            claim_fill(connection, "fp-a", actor="second-tab")

        assert excinfo.value.job_fingerprint == "fp-a"
        assert excinfo.value.claimed_at == claim["claimed_at"]
        assert excinfo.value.retry_after >= 1

    def test_different_fingerprints_never_conflict(self, connection):
        claim_fill(connection, "fp-a")
        claim_fill(connection, "fp-b")
        assert list_active_fill_fingerprints(connection) == {"fp-a", "fp-b"}

    def test_stale_claim_is_reclaimable(self, connection):
        t0 = datetime.now(timezone.utc)
        first = claim_fill(connection, "fp-a", now=t0)
        later = t0 + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=1)

        reclaimed = claim_fill(connection, "fp-a", now=later)

        assert reclaimed["claimed_at"] != first["claimed_at"]
        # The stale row was replaced, not duplicated.
        assert list_active_fill_fingerprints(connection, now=later) == {"fp-a"}

    def test_claim_soon_expiring_still_conflicts(self, connection):
        t0 = datetime.now(timezone.utc)
        claim_fill(connection, "fp-a", now=t0)
        inside_window = t0 + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=-1)

        with pytest.raises(FillInProgress):
            claim_fill(connection, "fp-a", now=inside_window)


class TestReleaseFillClaim:
    def test_release_allows_immediate_reclaim(self, connection):
        claim = claim_fill(connection, "fp-a")
        assert release_fill_claim(connection, "fp-a", claim["claimed_at"]) is True
        assert list_active_fill_fingerprints(connection) == set()
        # A retry after a failed fill is not blocked by the dead claim.
        claim_fill(connection, "fp-a")

    def test_release_never_drops_a_fresher_claim(self, connection):
        # A fill that outlived its stale window finishes AFTER another
        # request reclaimed the job: its late release must leave the live
        # claim alone or double-generation reopens.
        t0 = datetime(2026, 10, 13, 9, 30, 0, tzinfo=timezone.utc)
        stale_claim = claim_fill(connection, "fp-a", now=t0)
        t1 = t0 + timedelta(minutes=STALE_FILL_CLAIM_MINUTES + 5)
        fresh_claim = claim_fill(connection, "fp-a", now=t1)

        assert release_fill_claim(connection, "fp-a", stale_claim["claimed_at"]) is False
        assert list_active_fill_fingerprints(connection, now=t1) == {"fp-a"}

        assert release_fill_claim(connection, "fp-a", fresh_claim["claimed_at"]) is True
        assert list_active_fill_fingerprints(connection, now=t1) == set()


class TestListActiveFillFingerprints:
    def test_stale_rows_are_ignored_not_deleted(self, connection):
        now = datetime.now(timezone.utc)
        claim_fill(connection, "fp-dead", now=now - timedelta(hours=1))
        claim_fill(connection, "fp-live", now=now)

        active = list_active_fill_fingerprints(connection, now=now)

        assert active == {"fp-live"}
        # The stale row is still there for claim_fill to reclaim lazily.
        rows = connection.execute(
            "SELECT job_fingerprint FROM apply_fill_claims"
        ).fetchall()
        assert {row[0] for row in rows} == {"fp-dead", "fp-live"}


class TestConcurrentClaims:
    """The atomicity itself — the part the sequential tests above cannot see.

    Every other test in this file calls claim_fill twice in a row on ONE
    connection. That proves the SELECT-then-INSERT branch logic, but it
    proves nothing about BEGIN IMMEDIATE, which is a SQLite behavior rather
    than a behavior of this module. The live bug it exists to prevent was
    never sequential: two dashboard requests raced, each on its own
    threadpool worker with its own connection.

    If someone downgrades BEGIN IMMEDIATE to a bare INSERT, the sequential
    tests still pass and the duplicates come back. These do not.
    """

    RACERS = 8
    ROUNDS = 5

    def _race_one_fingerprint(self, fingerprint: str):
        """Hammer claim_fill with RACERS threads on RACERS separate
        connections; return (winners, FillInProgress losers)."""
        start = threading.Barrier(self.RACERS)
        winners: list[str] = []
        losers: list[str] = []
        lock = threading.Lock()
        unexpected: list[BaseException] = []

        def racer(index: int) -> None:
            # A fresh connection PER THREAD, as production does — uvicorn runs
            # sync routes in a threadpool and api.apply_state.connect() opens
            # one connection per call. sqlite3 forbids sharing one across
            # threads, which is exactly why the race needed its own DB file
            # in the first place.
            conn = apply_state.connect()
            try:
                start.wait(timeout=30)
                claim_fill(conn, fingerprint, actor=f"racer-{index}")
                with lock:
                    winners.append(fingerprint)
            except FillInProgress:
                with lock:
                    losers.append(fingerprint)
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                # "database is locked" / DDL races are real failure modes of
                # this code path and must fail the test, not be swallowed.
                with lock:
                    unexpected.append(exc)
            finally:
                conn.close()

        threads = [
            threading.Thread(target=racer, args=(i,), daemon=True)
            for i in range(self.RACERS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(t.is_alive() for t in threads), "racer thread hung"
        assert not unexpected, f"unexpected exception in racer: {unexpected!r}"
        return winners, losers

    def test_exactly_one_thread_wins_a_contested_fingerprint(self):
        for attempt in range(self.ROUNDS):
            fingerprint = f"fp-race-{attempt}"
            winners, losers = self._race_one_fingerprint(fingerprint)
            assert len(winners) == 1, (
                f"round {attempt}: {len(winners)} threads generated the same "
                f"job (this is the duplicate-package bug)"
            )
            assert len(losers) == self.RACERS - 1

    def test_only_one_claim_row_survives_the_race(self):
        """Losers must not leave rows behind — no stale rows, no duplicates."""
        for attempt in range(self.ROUNDS):
            fingerprint = f"fp-rows-{attempt}"
            self._race_one_fingerprint(fingerprint)

            conn = apply_state.connect()
            try:
                rows = conn.execute(
                    "SELECT COUNT(*) FROM apply_fill_claims WHERE job_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()[0]
            finally:
                conn.close()
            assert rows == 1, f"round {attempt}: {rows} claim rows for one fingerprint"

    def test_the_winner_releases_and_the_job_becomes_claimable_again(self):
        """A completed fill must free the job, not wedge it forever."""
        for attempt in range(3):
            fingerprint = f"fp-release-{attempt}"
            winners, _ = self._race_one_fingerprint(fingerprint)

            conn = apply_state.connect()
            try:
                claimed_at = conn.execute(
                    "SELECT claimed_at FROM apply_fill_claims WHERE job_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()[0]
                assert release_fill_claim(conn, fingerprint, claimed_at) is True
                assert fingerprint not in list_active_fill_fingerprints(conn)
                # Reclaimable straight away — this is what lets the next
                # dashboard click reach the same job again.
                claim_fill(conn, fingerprint, actor="next-click")
            finally:
                conn.close()


class TestHeartbeat:
    """A slow-but-healthy fill must keep its claim; a dead one must not.

    The stale window has to mean "no heartbeat for this long", not "running
    for this long". A fill legitimately takes minutes (LLM resume, LLM cover
    letter, then an ATS fill that alone waits up to 90s), so a TTL measured
    from claimed_at expires DURING a normal fill — the next request reclaims
    the job and both generate. That is the duplicate-package bug returning
    through a different door, so it gets pinned here.
    """

    def test_a_beating_fill_keeps_its_claim_past_the_stale_window(self, connection):
        t0 = datetime(2026, 10, 13, 9, 30, 0, tzinfo=timezone.utc)
        claim = claim_fill(connection, "fp-slow", now=t0)

        # Work that outlives the TTL but beats along the way.
        for minute in (1, 4, 7, 10, 13, 16, 19):
            at = t0 + timedelta(minutes=minute)
            assert refresh_fill_claim(
                connection, "fp-slow", claim["claimed_at"], now=at
            ) is True
            assert list_active_fill_fingerprints(connection, now=at) == {"fp-slow"}

        # Still held a second before the window after the LAST beat closes.
        last_beat = t0 + timedelta(minutes=19)
        just_alive = last_beat + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=-1)
        assert list_active_fill_fingerprints(connection, now=just_alive) == {"fp-slow"}

        # Three times the stale window in, a fresh beat still holds it — this
        # is the case a start-time TTL gets wrong, and the reason the bug
        # would otherwise come back through the door the heartbeat removed.
        late_beat = t0 + timedelta(minutes=40)
        assert refresh_fill_claim(
            connection, "fp-slow", claim["claimed_at"], now=late_beat
        ) is True
        far = late_beat + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=-1)
        assert list_active_fill_fingerprints(connection, now=far) == {"fp-slow"}
        with pytest.raises(FillInProgress):
            claim_fill(connection, "fp-slow", now=far)

    def test_a_silent_fill_still_expires_after_the_window(self, connection):
        """The crash case must keep working, or a dead worker wedges a job."""
        t0 = datetime(2026, 10, 13, 9, 30, 0, tzinfo=timezone.utc)
        original = claim_fill(connection, "fp-dead", now=t0)

        inside = t0 + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=-1)
        assert list_active_fill_fingerprints(connection, now=inside) == {"fp-dead"}

        # No heartbeat after t0: past the window it is reclaimable again.
        after = t0 + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=1)
        assert list_active_fill_fingerprints(connection, now=after) == set()
        reclaimed = claim_fill(connection, "fp-dead", now=after)
        # A genuinely new claim, not the stale row re-reported as live.
        assert reclaimed["claimed_at"] != original["claimed_at"]
        assert reclaimed["heartbeat_at"] == reclaimed["claimed_at"]

    def test_the_window_runs_from_the_last_heartbeat_not_the_start(self, connection):
        t0 = datetime(2026, 10, 13, 9, 30, 0, tzinfo=timezone.utc)
        claim = claim_fill(connection, "fp-gap", now=t0)

        # A single late beat 10 minutes in.
        beat_at = t0 + timedelta(minutes=10)
        refresh_fill_claim(connection, "fp-gap", claim["claimed_at"], now=beat_at)

        # Measured from the beat, not from t0: still alive at +10min+TTL-1s
        # even though that is nearly 2x the window since the claim started.
        alive = beat_at + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=-1)
        assert list_active_fill_fingerprints(connection, now=alive) == {"fp-gap"}

        # ...and dead 1s after the beat's own window closes.
        dead = beat_at + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=1)
        assert list_active_fill_fingerprints(connection, now=dead) == set()

    def test_a_beat_cannot_revive_a_claim_taken_over(self, connection):
        """A worker that lost its claim must NOT resurrect it.

        If it could, two workers would generate the same job and both would
        believe they own it — the duplicate bug, with extra steps.
        """
        t0 = datetime(2026, 10, 13, 9, 30, 0, tzinfo=timezone.utc)
        original = claim_fill(connection, "fp-stolen", now=t0)

        # Silent past the window, so a second request reclaims it.
        stolen_at = t0 + timedelta(minutes=STALE_FILL_CLAIM_MINUTES + 5)
        claim_fill(connection, "fp-stolen", now=stolen_at)

        # The original owner finally beats. It must be refused, not revived.
        assert refresh_fill_claim(
            connection, "fp-stolen", original["claimed_at"], now=stolen_at
        ) is False

        # And the live owner's claim is intact and still live.
        assert "fp-stolen" in list_active_fill_fingerprints(
            connection, now=stolen_at
        )
        # The original owner cannot release the new owner's claim either.
        assert release_fill_claim(
            connection, "fp-stolen", original["claimed_at"]
        ) is False

    def test_a_legacy_table_is_migrated_and_its_rows_stay_live(self):
        """Real migration path, built as a real pre-heartbeat database.

        Deployed databases already have apply_fill_claims WITHOUT a
        heartbeat_at column, holding claims from fills that were genuinely
        in flight at upgrade time. If those read as dead the moment the code
        ships, every one of them gets reclaimed and double-generated — the
        exact bug, triggered by the deploy rather than by user behaviour.

        So this builds the old schema, inserts a live claim into it, runs the
        migration, and asserts the row is still honoured.
        """
        from api.fill_claims import initialize_fill_claim_store

        conn = apply_state.connect()
        try:
            # Recreate the table exactly as the previous version wrote it.
            conn.execute("DROP TABLE IF EXISTS apply_fill_claims")
            conn.execute(
                """CREATE TABLE apply_fill_claims (
                    job_fingerprint TEXT PRIMARY KEY,
                    claimed_at TEXT NOT NULL,
                    actor TEXT
                )"""
            )
            t0 = datetime.now(timezone.utc)
            conn.execute(
                "INSERT INTO apply_fill_claims (job_fingerprint, claimed_at, actor) "
                "VALUES (?, ?, ?)",
                ("fp-legacy", t0.isoformat(), "dashboard"),
            )
            conn.commit()

            before = {
                row[1] for row in conn.execute("PRAGMA table_info(apply_fill_claims)")
            }
            assert "heartbeat_at" not in before

            # The migration every connect() performs.
            initialize_fill_claim_store(conn)

            after = {
                row[1] for row in conn.execute("PRAGMA table_info(apply_fill_claims)")
            }
            assert "heartbeat_at" in after
            # Existing data survived the ALTER.
            rows = conn.execute(
                "SELECT job_fingerprint, heartbeat_at FROM apply_fill_claims"
            ).fetchall()
            assert [row[0] for row in rows] == ["fp-legacy"]
            assert rows[0][1] is None, "migration must not backdate a heartbeat"

            # A NULL heartbeat falls back to claimed_at, so the in-flight
            # fill from before the upgrade still holds its claim.
            assert list_active_fill_fingerprints(conn, now=t0) == {"fp-legacy"}
            inside = t0 + timedelta(minutes=STALE_FILL_CLAIM_MINUTES, seconds=-1)
            assert list_active_fill_fingerprints(conn, now=inside) == {"fp-legacy"}
            with pytest.raises(FillInProgress):
                claim_fill(conn, "fp-legacy", now=inside)

            # And it still expires on claimed_at like any other claim.
            after_window = t0 + timedelta(
                minutes=STALE_FILL_CLAIM_MINUTES, seconds=1
            )
            assert list_active_fill_fingerprints(
                conn, now=after_window
            ) == set()
        finally:
            conn.close()
