# ADR-0001: Append-only SQLite per-job funnel ledger

**Date**: 2026-10-31
**Status**: accepted
**Deciders**: backend engineer (session), operator approved via live-scrape acceptance

## Context

The 2026-10-30 run (fbd2c54f337c) showed the funnel only as counts: 481
fetched → ~195 dev-filtered → 178 country-filtered → 133 scored → 20 saved.
The 110 low-match jobs were printed and never persisted, so false
rejections could not be audited; ~286 jobs dropped by the scraper-level
dev filter left no per-job record; dedup/rejection drops similarly left
only counts. Fixing the matcher later (Phase 2/3) requires knowing
exactly why each individual job was dropped and at which stage.

## Decision

Record one INSERT-only row per job per stage event in SQLite
(`data/pipeline_ledger.db`): `tools/pipeline_ledger.py`. Stages:
`raw_fetched`, `dev_filter_drop`, `country_drop`, `date_drop`,
`dedup_missing_url`, `dedup_url_dup`, `dedup_cross_board`,
`dedup_fingerprint`, `legacy_rejected`, `legacy_low_match`,
`legacy_passed`. Rows carry fingerprint (derived deterministically when
absent), source, title, company, reason code, score + breakdown, run_id,
timestamp. `reconcile()` reports incomplete funnels (`missing_terminal`,
`duplicated_terminal`) instead of claiming total counts are fine.

## Alternatives Considered

### Extend YieldTracker (per-board counts) to per-job rows
- **Pros**: one module, no new file.
- **Cons**: YieldTracker is an in-memory JSONL snapshot of counts;
  per-job history and cross-run health streaks need queries, not lists.

### Write drops to a Sheet tab
- **Pros**: visible in the existing dashboard.
- **Cons**: Sheets quota/rate pressure, PII in cloud cell, no SQL
  queries; the Sheet stays the *published output*, not the audit log.

### Postgres/event store
- **Pros**: richer querying.
- **Cons**: violates the task's no-new-heavy-dependency rule; SQLite is
  already the project's local store (apply_submit, matching_shadow).

## Consequences

### Positive
- False-rejection audit becomes a SELECT; Phase 4 comparison can diff
  both engines on identical, persisted records.
- Board health streaks are derivable from history (no mutable state).

### Negative
- One more SQLite file; job rows contain scraped text (gitignored, local).
- curate()/scrape_all gain writes on the hot path (~1ms per partition).

### Risks
- Tests writing the operator DB — mitigated by `PIPELINE_LEDGER_DB`
  env override used by tests.
