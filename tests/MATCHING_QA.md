# Matching foundation QA — 2026-10-29

## 2026-10-29 — adversarial QA audit (latest)

**Verdict: offline/shadow prototype checks pass; NO-GO for live cutover.**

Fresh Linux Python 3.11 environment installed from requirements.lock.txt;
coverage is a QA-only extra. No dependency pin changes or PR. Existing unrelated
workspace edits were preserved.

| Check | Actual result |
| --- | --- |
| Full pytest suite, `-q -rs --tb=short` | 1205 passed, 8 skipped, 32 warnings; 69.43s |
| Frontend canonical npm suite | 88 passed, 0 failed/skipped; 36.14s |
| Four matching modules, targeted unittest | 57 passed |
| Branch-aware coverage, all four matching modules | 97% (311 statements, 92 branches) |
| Dependency consistency | pip check passed |

Skip reasons: seven optional FAISS cases and one deliberately deferred Lever
confirmation-copy case. Warnings are Starlette/httpx and cookie deprecations plus
the intentional CORS fallback warning. jsdom is not real-Chrome verification.
The former 100% figure applied only to the earlier two-module foundation.

### Four additional defects found RED, then fixed

- Incomplete essential-skill extraction could reject a job; it now stays review.
- Zero required overlap could enter eligibility if every gap was learnable;
  now explicit no_required_skill_overlap routes to review without inventing a
  numeric acceptance threshold.
- Profile collections supplied as strings could silently split into characters;
  the JSON boundary now validates collections of nonempty strings.
- Shadow location/requirement collections had the same issue; corrected at input.

Five new adversarial tests cover these four failures plus missing-description
behavior. These are synthetic regressions, not human-labeled accuracy evidence.

### Senior-engineering / architecture / product findings

- Keep the optional sidecar disabled by default. The legacy matcher still makes
  live decisions, so production recommendation quality has not yet improved.
- Extraction and enrichment are absent. Consequently, ordinary scraped jobs
  cannot provide all the structured evidence required by this prototype.
- Relocation handling expresses sponsor availability, not actual visa approval,
  job-specific permit feasibility or full legal eligibility.
- Structured evidence still relies on a trusted upstream extractor/operator; a
  supporting string is not verified against the source text by the scorer.
- Priority rules are deterministic but uncalibrated. There is no held-out labeled
  precision/recall comparison. Do not claim improved recommendation quality.
- The SQLite seam is personal-only, has no authenticated queue API, retention
  policy or backup drill. Namespacing is not an authorization boundary.
- A malformed shadow job currently aborts the remaining batch; curator catches
  this and preserves live selection, but a partial sidecar run needs explicit
  run status/per-job error isolation before operational reliance.
- Same-key decision writes replace prior payloads. Current provenance is stored,
  but this is not an append-only decision audit log.
- Global `git diff --check` flags a pre-existing PM.md trailing blank line; left
  untouched because it is outside this QA change. No claim of globally clean diff.

Next release gates: safe extraction/enrichment, profile confirmation, per-job
shadow failure reporting, human labels, observed old/new comparison, then explicit
rollout approval. Future multi-user Profile remains planning-only.


## Continuation — runtime implementation (supersedes relevant gaps below)

Latest full suite: **1200 passed, 8 skipped, 32 warnings in 73.00s**. Matching
cases: **52**. Frontend unchanged; previous frontend run remains historical.

Implemented relocation/sponsorship rules, explicit learnable/essential gaps,
preference/freshness ranking, SQLite review/cache helpers, evaluation metrics and
an opt-in curator shadow hook. Historical audit below describes the prior stage.
Live adoption still NO-GO: automatic text extraction/enrichment, calibrated
preferences, held-out human labels and observed shadow comparison remain absent.

### Optional personal shadow configuration

Set MATCHING_SHADOW_PROFILE to an operator-owned JSON path. Omit/leave empty to
disable. MATCHING_SHADOW_DB defaults to data/matching_shadow.db (private runtime
state; no shared-user API). Example profile schema, not an imposed seniority:

```json
{
  "version": "owner-policy-1",
  "skills": ["python", "node.js", "react"],
  "learnable_skills": ["django"],
  "policy": {
    "role_families": ["backend", "frontend", "fullstack"],
    "work_locations": ["IN"],
    "seniority_levels": [],
    "relocation_destinations": ["SA", "AE"],
    "sponsorship_required": true
  }
}
```

An empty seniority band deliberately produces review until configured. No Profile
UI is added. This personal sidecar is NOT multi-tenant isolation. Authentication
and owner binding for the future user product require separate implementation.

Shadow job inputs may carry `matching_evidence` with canonical JobEvidence fields
and a `requirements` object: required/preferred groups (alternatives, evidence,
weight, essential), boolean complete and extractor_version. Without this, raw
scraped text is NOT promoted to confirmed restrictions or requirements. Evidence
is operator/upstream supplied, not automatically trustworthy because structured.

The hook records decisions before legacy filters but does not yet automatically
join old/new outcomes. `evaluate_labels` accepts real labels and selected job IDs;
its synthetic tests prove metric arithmetic only. No production quality gain or
historical labeled dataset is claimed. Cache storage exists; an extractor still
needs a read-through adapter. No public queue UI/API or retention/backup policy
is shipped. Review entries retain latest state per profile and preserve history.

Priority is lexicographic: fit, preferred coverage, confirmed preference count,
then 14-day freshness. Unknown/future posting dates receive no freshness credit.
This is a deterministic provisional policy, not calibrated ranking weights.

## Scope and verdict

Base: integrated main 5709e685 plus uncommitted session changes on
arena/51545db4-remote-job-agent. No PR, push, live scraper run or submission.

**Foundation checks pass; NO-GO for replacing the live matcher.**
These modules are pure structured-input prototypes, not an end-to-end matching
system. Test coverage is not evidence of recommendation accuracy.

## Design acceptance audit

| Agreed behavior | Status |
| --- | --- |
| Pass/fail/unknown gates and reason codes | Implemented |
| Missing description produces review/enrichment request, not zero fit | Implemented request signal only; fetching absent |
| Remote is not worldwide; headquarters do not confer work rights | Structured-input gate implemented; text extraction absent |
| India remote vs sponsored UAE/Saudi relocation | Not implemented; remote/location intersection alone is insufficient |
| Broad software titles remain unresolved until evidence | Implemented; title inference still heuristic |
| Exclusions based on responsibilities/primary stack | Partial: title hints only; no responsibility extraction |
| Requirement coverage and OR alternatives | Implemented for validated structured input |
| No double penalties / preferred cannot erase required gaps | Implemented |
| Negation such as 'No Java required' | Not implemented: must be handled by future extractor, not scorer |
| Essential vs learnable requirements | Not implemented: all required gaps conservatively route to review |
| Separate fit from priority | Required/preferred scores separate; employer/freshness priority absent |
| Confidence does not multiply fit | Implemented field completeness; not calibrated confidence |
| Up-to-N eligible results, no forced quota | Implemented as standalone helper |
| Profile/scorer/extractor versions | Implemented in result |
| Content + extractor version cache | Not implemented |
| Review queue persistence / live pipeline integration | Not implemented |
| Historical labels, held-out metrics and shadow comparison | Not implemented |
| Future user dashboard Profile | Planning only in USER_PRODUCT.md, deliberately deferred |

## QA findings reproduced RED, then fixed

1. Contradictory `worldwide=True` plus a specific allowed-country set could
   bypass geographic restrictions. It now produces UNKNOWN and review.
2. Any occurrence of `support` in a title could reject a software-platform
   engineering job. Narrowed exclusions to role phrases; generic titles remain
   unresolved. This still requires labeled false-positive/false-negative testing.
3. Extremely large individually finite weights could yield NaN coverage through
   floating-point overflow. Bounded validated weights and divided before scaling.
   Very small positive weights also have a regression case.

## Tests and environment

Python 3.11.2, Linux x86-64, Node 22.22.3. Fresh .venv installed from
requirements.lock.txt; coverage is a separate QA-only tool, not a runtime pin.
`pip check`: no broken requirements. No dependency files changed.

- `coverage run --branch --source=tools.matching_policy,tools.matching_score -m
  unittest tests.test_matching_policy tests.test_matching_score -q`: **34 passed**.
- `coverage report -m`: **100% statements and branches** for these two modules
  (152 statements, 36 branches). This does not cover absent extraction or pipeline.
- First full `pytest tests/ -q --tb=short`: **1176 passed, 8 skipped, 32 warnings**
  in 82.15s, collected before the six additional boundary/coverage cases.
- `npm test --prefix tests/e2e`: **88 passed, 0 failed, 0 skipped** in 43.74s.
  This is real-API jsdom coverage, NOT a real Chrome/browser or new matcher UI test.
- Final `.venv/bin/python -m pytest tests/ -q -rs --tb=short`:
  **1182 passed, 8 skipped, 32 warnings in 71.67s**. Skips: seven optional
  FAISS cases (not installed in lock) and one deliberately deferred Lever
  confirmation-copy case. Warnings: Starlette/httpx deprecations, per-request
  cookie deprecations and the intentional CORS fallback test warning.

## Architectural risks before rollout

- Eligible jobs currently must satisfy every required group, so their required
  coverage is 100%; shortlist ranking is effectively preferred-skill tie-breaking.
  Do not claim calibrated fit discrimination until essential/learnable gaps and
  labeled evaluation are implemented.
- Geographic identifiers must be canonical and regional sets expanded upstream.
  Country intersection does not check visas, residency or authorization.
- Evidence strings are supplied by callers; the scorer does not verify extraction
  fidelity or resolve all contradictory claims. Duplicate groups retain first
  evidence/weight; extraction conflicts need an explicit contract before rollout.
- Description presence is only presence, not quality/completeness. Structured
  fields are not extracted automatically from descriptions.
- Persisted provenance needs content fingerprints and stable job/profile IDs.
- No existing curator, Sheets writing or ranking threshold has been replaced.

Next: confirm personal policy inputs without building the deferred Profile UI;
implement evidence extraction and essential-gap semantics; safe enrichment;
shadow integration, review storage and real evaluation before live cutover.
