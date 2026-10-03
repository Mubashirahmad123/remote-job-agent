"""Safety constants and arming logic for the apply path.

The submit path has THREE states, not two:

  1. disarmed (default)  — `/intent` + `/submit` fail closed with 403 and no
     browser is ever launched for submit.
  2. dry run             — the entire real submit path executes against the
     real posting (real browser, real fill, real field/attachment readback,
     every gate, real submit-button lookup) and stops one statement before
     `.click()`. Nothing is claimed, no intent is consumed, no application
     is sent. This exists so the submit code can be exercised against
     reality without consequences.
  3. armed                — the click happens.

Why three states: with a binary switch the only way to learn whether the
submit path works against a real Greenhouse DOM is to send a real
application. That makes every rehearsal expensive, so no rehearsal happens,
so the first execution is also the first test. Dry run removes that.

Resolution order (both flags):
  - the module constant is the hard default and stays False in git;
  - an environment variable can arm it for one process. It must be exactly
    one of {"1", "true", "yes", "on"} (case-insensitive). Anything else,
    including unset, resolves False.

Call `submit_enabled()` / `submit_dry_run()` rather than reading the
constants, so env arming and test monkeypatching both work. Tests
monkeypatch the constants; `tests/conftest.py` scrubs both env vars from
every test process so a developer's armed `.env` can never make the suite
pass a gate it should fail.

Phase 2a fill-only review (`POST /api/apply/{fp}`) is unaffected by all of
this — it never submits.
"""

import os

SUBMIT_ENABLED = False
SUBMIT_DRY_RUN = False

_TRUE = {"1", "true", "yes", "on"}


def _env_true(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in _TRUE


def submit_enabled() -> bool:
    """True when the submit path may run at all (dry run included)."""
    return bool(SUBMIT_ENABLED) or _env_true("SUBMIT_ENABLED")


def submit_dry_run() -> bool:
    """True when the submit path must stop before the click.

    Only meaningful once `submit_enabled()` is True. Dry run is checked
    *after* the kill-switch, so `SUBMIT_DRY_RUN=true` alone never opens the
    path — it cannot be used to bypass the kill-switch.
    """
    return bool(SUBMIT_DRY_RUN) or _env_true("SUBMIT_DRY_RUN")


def submit_mode() -> str:
    """Human-readable state for logs, runbooks and the health endpoint."""
    if not submit_enabled():
        return "disarmed"
    return "dry_run" if submit_dry_run() else "armed"
