# ADR-0004: "senior" is a REVIEW, not a hard rejection

**Date**: 2026-11-02
**Status**: accepted
**Deciders**: operator (approved remediation Tier 1 / D9), architect (session)

## Context

`tools/matching_policy.py` documented the product intent in a comment directly
above `HARD_SENIORITY_MISMATCH`:

> "senior" is deliberately NOT here: a senior posting without a stated year
> range is a REVIEW, not a rejection.

The very next statement put `"senior"` inside that frozen set, so every posting
with a `senior` label was rejected outright (`seniority_not_allowed`) even when
the role family and worker location both passed. A live check reproduced it:
`Senior Software Engineer`, fully remote, "open to candidates in India",
Python/React requirements → `rejected`, with the role and location gates `pass`.

Two facts made this a decision rather than a typo fix. First, the ambiguity was
real: `senior` can mean a level the candidate cannot reach, or a posting that
simply has more scope. Second, the engine had no way to express the middle
outcome the comment described. The mission rule is that a hard rejection must
rest on defensible evidence, and a bare `senior` label in a title is not
defensible evidence that a specific candidate is out of range.

A second, independent defect (D8) made the question urgent: the seniority
regexes had no trailing word boundary, so `internal`/`international` produced an
`intern` label on 89 of 312 live jobs, and verbs such as "you will lead code
reviews" produced a `lead` label. Any answer that kept `senior` in the hard set
would keep rejecting on prose.

## Decision

`senior` is removed from `HARD_SENIORITY_MISMATCH`. A `senior` label yields
`unknown` / `seniority_label_requires_review` → **REVIEW**.

The only path from a seniority signal to FAIL is a *stated year range* whose gap
beyond the candidate's experience exceeds `seniority_gap_threshold`
(default 2). `job.years_min`/`years_max` are extracted from explicit overall
experience statements only ("5+ years of experience", "0 to 4 yrs"); per-skill
years are not seniority evidence.

`lead`, `principal`, `staff`, `director` and `executive` stay hard failures.
They name a structural level that is out of reach for a junior/mid profile in a
way `senior` alone does not. `intern` and the other members of
`SENIORITY_NOT_A_LEVEL` stay `unknown`.

The code comment, the frozen set, `POLICY_VERSION` and `tests/MATCHING_QA.md`
are updated together so they cannot drift apart again.

## Alternatives Considered

### Alternative 1: keep `senior` hard-rejected (make the comment match the code)
- **Pros**: maximum precision, lowest volume, simplest to explain.
- **Cons**: rejects on a title word with no stated requirement, which the mission
  forbids; discards postings where "senior" is a company's internal band.
- **Why not**: a hard rejection would rest on evidence the posting never gave.

### Alternative 2: make every seniority label REVIEW (delete the hard set)
- **Pros**: uniform, no judgement calls per label.
- **Cons**: loses the ability to reject `principal`/`staff` postings whose year
  requirements are frequently unstated; floods the queue.
- **Why not**: `principal`/`staff`/`director` are not ambiguous band names.

### Alternative 3: infer level from the description
- **Pros**: more evidence.
- **Cons**: D8 proved description prose is noise ("you will lead code reviews");
  inferring a level from prose is exactly the defect being fixed.
- **Why not**: it reintroduces the failure mode being removed.

## Consequences

### Positive
- The shipped behaviour matches the documented product decision, so the comment
  is no longer a lie.
- Hard rejections now require a number the posting actually stated.
- The same change gives the engine a legitimate middle outcome, which is what
  makes `review` meaningful for senior roles.

### Negative
- `review` volume rises and `rejected` volume falls. That is the intended
  direction, but it means the next comparison must be read per class, not as a
  single "rejections down" number.

### Risks
- Keeping `lead` in the hard set is defensible only while D8 guarantees the
  label comes from the title or an explicit level phrase. If that extraction is
  ever loosened, `lead` becomes the same trap `senior` was.
- `seniority_gap_threshold` is operator policy in `data/matching_profile.json`;
  this ADR does not change its value.
