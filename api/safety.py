"""Safety constants for the apply path (Phase 2a fill-only).

SUBMIT_ENABLED is the single kill-switch for any future submit code path.
Phase 2a MUST NOT submit: the apply router rejects every mode other than
"review" and never reads AUTO_APPLY_CONFIRM, so no HTTP request can cause
a real-world application no matter what the env holds.
"""

SUBMIT_ENABLED = False
