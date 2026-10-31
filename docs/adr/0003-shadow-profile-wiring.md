# ADR-0003: Shadow matcher profile wiring and health logging

**Date**: 2026-10-31
**Status**: accepted
**Deciders**: operator (USER INPUT 1 answers), backend engineer (session)

## Context

`agents/curator.py`'s shadow hook (`run_optional_shadow`) only executes
when `MATCHING_SHADOW_PROFILE` is set and points to a loadable JSON. On
2026-10-30 the variable existed in `.env` but was **empty**, so the hook
silently did nothing and `data/matching_shadow.db` was never created —
and nothing in the run log distinguished "shadow disabled" from
"shadow enabled and succeeded". Separately, profile loading lacked
tests for string-valued lists, and one malformed job aborting
`shadow_batch` remained a known Phase 3 design gap.

## Decision

1. Ship a real profile `data/matching_profile.json` (gitignored) in
   `load_profile()`'s exact shape, with USER INPUT 1 answers:
   `role_families` fullstack/backend/frontend, `work_locations` ["india"]
   (the candidate's verified work right), `seniority_levels`
   junior/mid, `relocation_destinations` ["india"],
   `sponsorship_required` false (no visa needed for India work).
   Documented in the profile `_meta`: remote-anywhere semantics are NOT
   yet representable in the current single location gate; remote jobs
   without extracted `allowed_work_locations` stay UNKNOWN → review.
   This is deliberately conservative (no wrong passes) until Phase 3
   separates remote permission from onsite country.
2. Wire `.env` (local): `MATCHING_SHADOW_PROFILE=data/matching_profile.json`,
   `MATCHING_SHADOW_DB=data/matching_shadow.db`.
3. `tools/matching_shadow.log_shadow_config()` prints one line at the
   start of every `curate()` run — `DISABLED | BROKEN(path|error) |
   ENABLED profile=path version=v` — so a run can never again be
   mistaken for shadow-enabled.

## Alternatives Considered

### Env-only boolean (MATCHING_SHADOW_ENABLED=true)
- **Pros**: simpler.
- **Cons**: with no separate DB env, db path drift; "enabled" without a
  valid file would still print enabled and then fail per-run.

### Store the profile in the dashboard DB
- **Pros**: editable from UI.
- **Cons**: matches a later phase; operator-owned JSON is auditable in
  git-ignored local storage and matches tests/MATCHING_QA.md already.

## Consequences

### Positive
- Every run self-reports its shadow state and profile version.
- Loader strictness is now regression-tested (string-in-list, non-bool
  sponsorship, empty-string members all raise).

### Negative
- None material; the offline smoke confirms decision rows land per job
  with no evidence (all gates → review).

### Risks
- Live acceptance of "one decision row per hooked job" is only proven by
  an actual scrape (running at ADR time); the offline tests do not
  exercise the curator wiring.
