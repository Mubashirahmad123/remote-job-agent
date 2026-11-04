# ADR-0002: Board status taxonomy

**Date**: 2026-10-31
**Status**: accepted
**Deciders**: backend engineer (session)

## Context

On 2026-10-30 the run log said "20 empty boards". The truth: 12 boards
genuinely attempted-and-zero — of which 4 were repeated timeouts
(FlexJobs, CWJobs, Remotees, NaukriGulf), 7 fetched HTML but parsed 0
jobs (e.g. Jobspresso, with ~292 candidate elements), 1 was a confirmed
empty API list (Himalayas) — plus 8 boards that were *skipped*
(skipped-js/duplicate/disabled) and never attempted. Health decisions
(skip a board? fix a parser?) are impossible when timeout, parser
breakage and skip reasons all collapse into "empty".

## Decision

Fixed status vocabulary everywhere (scrapper → tracker → API rollup):

```
ok | empty_confirmed | parse_zero | timeout | blocked | fetch_failed |
skipped_js | skipped_duplicate | skipped_disabled | skipped_breaker |
error
```

- `empty_confirmed`: body fetched and parsed; the source genuinely lists
  zero jobs (API/RSS).
- `parse_zero`: body fetched but the parser found nothing (HTML boards
  incl. Playwright/Crawl4AI passes).
- `timeout` / `blocked` / `fetch_failed`: fetch never produced a usable
  body; cause distinguished via `fetch_with_retry(outcome_out=...)`.
- `skipped_*`: the board did not run this pass; keeps its skip cause.

The "board is bad on 3 consecutive runs" health flag streaks ONLY over
attempted outcomes (`empty_confirmed, parse_zero, timeout, blocked,
fetch_failed, error`); skipped boards break the streak — a skip is
neither a failure nor evidence of zero.

## Alternatives Considered

### Keep "empty" but add an error field
- **Pros**: smaller diff, nothing renames.
- **Cons**: every consumer must remember to check the error field;
  the 30-Oct-day mistake (health/parallel triage) recurs on every new
  consumer; skipped-vs-empty still conflated in the rollup.

### Only statuses, no fetch_outcome side-channel
- **Pros**: no `fetch_with_retry` signature change.
- **Cons**: timeout/403/etc. cannot be distinguished from inside
  `fetch_jobs_from_board` because `fetch_with_retry` returns `None` for
  every exhaustion cause.

## Consequences

### Positive
- "12 empties split by cause" (Phase 1 acceptance) falls out directly.
- api/runs rollup gains a `boards_skipped` bucket; skips are never
  counted as empty.
- Health flag is honest: JobSpy disabled-by-default no longer looks like
  a three-streak failure.

### Negative
- String statuses flow into logs/board_yield.jsonl and the tracker; old
  consumers of `"empty"`/`"skipped-js"` strings needed updates (done:
  source-naming guard, API rollup, scraper-timeout guard).

### Risks
- Any future tracking point that re-introduces a status string outside
  `PipelineLedger.record_board`'s guard raises immediately (ValueError).
