# ADR-0005: Jobicy `jobGeo` is not worker permission — delete the dead branch

**Date**: 2026-11-02
**Status**: accepted
**Deciders**: operator (approved remediation Tier 4 housekeeping), architect (session)

## Context

Commit `bacc81db0` added a block to `tools/matching_extract.py` that reads
`job.get("jobGeo")`, splits it on commas, maps each part through
`_normalize_region()` and merges the result into `allowed_work_locations`. The
intent, per the commit message, was to treat Jobicy's structured geo field as a
worker-permission fact.

The branch cannot run. The Jobicy scraper stores the API's `jobGeo` value under
the key `"timezone"` (`agents/scrapper.py:1313`); no job dict in the pipeline has
a `jobGeo` key. `job.get("jobGeo")` therefore always returns `None`, and the
whole block is unreachable in production.

The operator's own profile note in `data/matching_profile.json` records the
opposite rule: Jobicy's geo field "is a region preference, **NOT** worker
permission — bare region names without eligibility phrasing do not set
`allowed_work_locations`".

So the dead branch is not merely dead; if it were wired up it would contradict
the recorded policy and would grant location `pass`/`fail` on a preference
field. It also verifies its quotes against the wrong string: the raw geo value
is not present in `combined`, so even with a `jobGeo` key the block emits an
empty `allowed_work_locations` and, in one configuration, `worldwide=True`.

## Decision

Delete the `jobGeo` block from `extract_matching_evidence()`. Jobicy posts keep
flowing through the normal path: `timezone` is read into
`location_field`, and a country is inferred only by the gazetteer, with
`allowed_work_locations` set only by explicit eligibility phrasing.

`data/matching_profile.json`'s `_meta.note` stays as written — the code now
matches it instead of contradicting it.

## Alternatives Considered

### Alternative 1: wire `jobGeo` as worker permission
- **Pros**: uses a structured field instead of prose; cheap to implement.
- **Cons**: contradicts the operator's recorded rule; a bare region name in a
  board API is a preference, not a statement of where an employer will hire;
  verification against `combined` fails anyway.
- **Why not**: it would convert a preference into an eligibility gate.

### Alternative 2: wire `jobGeo` as a preference input (no gate)
- **Pros**: keeps the information; could order results later.
- **Cons**: there is no preference input in the policy, no consumer for it, and
  no requirement for it in this mission. Adding one is a new feature, not a fix.
- **Why not**: out of scope; requires its own ADR and a consumer.

### Alternative 3: leave the dead code in place
- **Pros**: zero change.
- **Cons**: it reads as a shipped feature; the next audit has to re-derive that
  it is unreachable; and it would be a trap for anyone who later "fixes" the
  key name.
- **Why not**: dead code that contradicts documented policy is a defect.

## Consequences

### Positive
- The extractor and the operator profile now state the same rule.
- One fewer unreachable branch and one fewer unverified-quote path.
- No behaviour change: the branch never executed.

### Negative
- None. The deletion is provably behaviour-neutral (`jobGeo` is absent from every
  job dict the scraper produces), and the regression test asserts that a
  Jobicy-shaped job with `timezone=<geo>` stays REVIEW.

### Risks
- If the operator later wants geo as a ranking preference, it must be added
  deliberately as a preference input with its own ADR — not re-introduced by
  renaming a key.
