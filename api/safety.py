"""Safety constants for the apply path.

SUBMIT_ENABLED is the single kill-switch for the Greenhouse intent/submit
code path (`POST /api/apply/{fp}/intent`, `POST /api/apply/{fp}/submit`).
It defaults to False and is read at call time (not import time) so tests
can flip it via monkeypatch. When False, both routes fail closed with 403
and no browser is ever launched for submit.
Phase 2a fill-only review (`POST /api/apply/{fp}`) is unaffected.
"""

SUBMIT_ENABLED = False
