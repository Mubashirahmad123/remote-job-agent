# AUDIT.md — Pipeline Run Audit

Full-stack review of one live pipeline run, done from three seats: senior architect,
senior software developer, and product manager. Findings are grounded in code with
`file:line` references. **No code was changed as part of this audit.**

- **Run audited:** `a274ecf93247`
- **Date:** 2026-10-18
- **Trigger:** `POST /api/scrape` from dashboard
- **Scope:** scrape → dedup → rejection → CV scoring → ranking → Google Sheets

---

## 1. Executive summary

The scraping fleet works. The matching engine does not — or more precisely, it is
running in a half-blind mode nobody recalibrated for, and it is scoring a large
share of jobs against placeholder text instead of real descriptions.

**End-to-end yield this run: 7 jobs saved from 155 scraped (4.5%).**
110 surviving jobs (88%) were rejected as LOW MATCH, and a meaningful portion of
those were never really scored at all — they were scored against empty or stub
text, which deterministically produces a score of 0.

Top three findings:

1. **Semantic scoring is disabled** (`sentence-transformers` / `faiss-cpu` are
   commented out of `requirements.txt`), so every run is keyword-only — but
   `MIN_SCORE=70` was never recalibrated for that mode.
2. **The coverage-based score formula structurally punishes detailed job
   postings** — the more core skills a job lists, the lower the score.
3. **Several board parsers feed the scorer stub summaries** ("Himalayas remote
   listing", "Full-Time listing from WeWorkRemotely."), which guarantees a 0
   regardless of CV quality.

Everything else in the run — TLS handling, bot-protection retries, LLM fallback
chain, sheet dedup, auth — behaved correctly or has minor, fixable defects
(listed in §5).

---

## 2. The funnel: where 155 jobs became 7

| Stage | Count | Lost | Verdict |
|---|---|---|---|
| Raw scraped | 163 | — | healthy |
| Country filter (scrapper pass) | 155 | −8 | OK |
| URL dedup | 136 | −15 dupes, **−4 silent** | ⚠️ 4 jobs dropped uncounted (Bug 1) |
| Fingerprint dedup | 125 | −11 | ⚠️ cross-board dupes leak through (Bug 2) |
| Rejection engine | 117 | −8 (5 title, 3 body) | patterns working as designed |
| CV scoring (min 70, keyword-only) | **7** | **−110 (88%)** | 🔴 the real problem lives here |
| Saved to Google Sheet | 7 | — | 4.5% end-to-end yield |

Sheet outcome: 7 rows → ALL JOBS, 7 rows → GOOD MATCHES, **0 rows → TOP MATCHES**
(needs ≥85; best score this run was 82 — see PM-1).

---

## 3. Critical findings — matching engine

### C1. Semantic scoring is disabled; the 70 threshold was never recalibrated

- `requirements.txt:48-50` — `sentence-transformers` and `faiss-cpu` are commented out.
- `agents/curator.py:426-428` — every run takes the `SEMANTIC_AVAILABLE=False`
  path (the log line `Semantic matching unavailable (optional dependencies
  missing); using keyword-only scoring`).
- `agents/curator.py:499-504` — with semantic off, `base_score = keyword_score`
  alone; the 0.6/0.4 `KEYWORD_WEIGHT`/`SEMANTIC_WEIGHT` blend never happens.
- `agents/curator.py:39` — `MIN_SCORE = 70` (env `MIN_MATCH_SCORE`).

Consequence: the gate that produced 110 LOW MATCH out of 117 scored jobs is a
threshold that was (at best) tuned for blended keyword+semantic scoring, applied
to keyword-only scores. **Either re-enable the semantic deps or recalibrate the
threshold for keyword-only mode — one or the other, deliberately.**

### C2. Coverage formula structurally punishes detailed postings

`tools/cv_matcher.py:342`:

```python
core_coverage = len(core_matches) / len(core_job_skills)
```

A posting listing 5 core skills where the CV has 3 → coverage 0.6 → ≈42 + bonuses
≈ 55 → LOW MATCH. A posting listing exactly the CV's 3 skills → coverage 1.0 →
passes. **The richer and more realistic the posting, the lower the score.**
This is a design flaw, not a tuning issue.

Evidence from this run:

| Job title | Score | Why |
|---|---|---|
| Full Stack Developer - Python/Django/ReactJS | ✅ 79 | few core skills, all matched |
| Software Engineer, Backend | ⚠️ 0 | no skill signal (see C3) |
| Full Stack Developer (Remote) | ⚠️ 0 | no skill signal |
| Golang Kubernetes Engineer | ⚠️ 0 | CV lacks go/k8s → `has_core_signal` gate zeroes *everything* (`cv_matcher.py:354`) |

Related: the `has_core_signal` gate (`cv_matcher.py:354-362`) zeroes all bonuses
when there is zero core-stack overlap, so one unfamiliar core skill in an
otherwise perfect posting can flatten the score to 0.

### C3. Multiple parsers feed the scorer placeholder text → guaranteed 0

The scorer only sees `title + summary + tech_stack` (`tools/cv_matcher.py:294-298`).
These parsers write stub summaries instead of real descriptions:

| Location | Board | Stub summary |
|---|---|---|
| `agents/scrapper.py:1379` | WeWorkRemotely (HTML) | `"Full-Time listing from WeWorkRemotely."` |
| `agents/scrapper.py:1450` | Wellfound | `"Wellfound listing - {location}"` |
| `agents/scrapper.py:1529` | NoDesk | `"NoDesk remote listing"` |
| `agents/scrapper.py:1608` | Himalayas (HTML) | `"Himalayas remote listing"` |
| `agents/scrapper.py:1799` | JustRemote | `"{job_type} position via JustRemote"` |
| `agents/scrapper.py:1847` | Arc | `"Arc.dev remote listing"` |
| `agents/scrapper.py:1958` | JustJoinIt | `"JustJoin.it listing"` |
| `agents/scrapper.py:1697` | generic HTML fallback | `"Listing from {board_name}"` |
| `agents/scrapper.py:2056` | stealth/other fallback | `"Listing from {board}"` |

Additionally, RSS/API parsers derive `tech_stack` from the **title only**
(`agents/scrapper.py:45, 85`), so those boards carry even less skill signal.

So a generic title ("Software Engineer") from any of these boards has zero skill
signal → `"No recognizable tech skills in job"` → score 0, regardless of the CV.
**The PlaywrightStealth pass (130 jobs — the largest single source this run)
funnels through the generic parser with stub summaries.** A large share of the
110 LOW MATCH results were never scored against real text at all.

Note: the WWR *RSS* path is fine (`agents/scrapper.py:88` uses the real feed
summary); the HTML path is the stub.

### C4. LOW MATCH log lines hide the computed reason

`agents/curator.py:521` prints only the two numbers:

```
⚠️ LOW MATCH (0+0): Software Engineer
```

…but `match_reason` is already computed and stored on the job
(`agents/curator.py:513`): `"No recognizable tech skills in job"` vs
`"No core stack overlap"` vs `"Matched: python, react"`. Printing it would have
exposed C3 immediately. Cheapest fix on this list, highest diagnostic value.

### C5. Minor: every job is scored twice; single-CV log noise

- `agents/curator.py:461` → `CVLibrary.pick_best()` runs `matcher.score(job)` to
  select a CV; `agents/curator.py:468-469` then scores the same job again with
  the same CV. Pure redundant compute (`tools/cv_library.py:206-265`).
- With one CV registered, the `Best CV for 'X': my_cv.pdf (score 0)` lines look
  like errors in the log but are just the pick-best score echoed. Misleading
  noise (`tools/cv_library.py:259`).

---

## 4. What was verified as working correctly

Worth recording so future audits don't re-litigate these:

- **TLS fail-closed policy.** `agents/scrapper.py:821-833` retries SSLErrors with
  verification ON and permanently skips boards whose chain does not validate
  (TimesJobs this run). The old `verify=False` downgrade is fully removed — the
  comment block documents the MITM rationale (scraped `apply_url` feeds the
  auto-applier and LLM prompts). Correct and secure.
- **Bot-protection retries.** EU Remote Jobs: 403 → retry → success (6 jobs).
  `fetch_with_retry` rotates headers and backs off (`agents/scrapper.py:774-837`).
- **LLM fallback chain.** Crawl4AI markdown extraction: Gemini 503 → Groq
  recovered. The chain works under provider outage.
- **Cross-board URL dedup.** RemoteOK skipped as same-URL duplicate of
  RemoteOKAPI; FounditIN skipped as duplicate of Naukri.
- **JobSpy opt-in gate.** Disabled by default with clear log message.
- **Per-scraper time budget.** Subprocess-based, `SCRAPER_TIMEOUT` default 300s
  (`agents/scrapper.py:2191-2241`).
- **Freshness never gates the threshold** — it only affects ranking
  (`agents/curator.py:492`, comment at 492-506). Correct design.
- **Empty-shell CV cache guard.** `tools/cv_parser.py:237-277` refuses to serve
  or persist an empty cached profile (a past incident where every job scored 0
  against a shell profile — see the docstring at 242-245). This run is *not*
  that failure mode: scores >0 exist.
- **Sheet duplicate detection.** Existing URLs and fingerprints loaded from ALL
  JOBS before appending (`agents/curator.py:333-379`); 7/7 new jobs correctly
  detected as new.

---

## 5. Bugs (smaller, but real)

### Bug 1 — Silent data loss on missing `apply_url`

`agents/curator.py:371-372`:

```python
url = (job.get("apply_url") or "").split("?")[0].strip()
if not url:
    continue          # dropped, NOT counted in `duplicates`
```

The run's own math proves it: 155 − 15 duplicates = 140 expected, but
`Unique: 136` was printed. **4 jobs vanished without a trace or counter.**
Fix: count them as a `missing_url` category and print it.

### Bug 2 — Cross-board duplicates survive fingerprint dedup

Fingerprint = `title | company | normalized-URL` (`tools/deduplicator.py:14-22`).
The same job posted on two boards has different URLs → not caught. This run:

- `Software Engineer I, Fullstack (Search)` ×2
- `Software Engineer, AI Coding Tasks` ×4+
- `Senior Software Engineer, Backend` at Dave ×2 (same board, different URLs)

Fix: add a second pass keyed on `(title.lower(), company.lower())` alone.

### Bug 3 — Freshness off-by-one (day 7)

`agents/curator.py:45-48` defines day 7 → `0`, but the branch at
`agents/curator.py:170-171` awards `FRESHNESS_BOOST[4] = 2` to days 4–7
*inclusive*. Day-7 jobs get +2 instead of 0.

### Bug 4 — Future-dated postings get the maximum boost

`agents/curator.py:162-163`: `days_old < 0 → return 20`. A board emitting garbage
future dates is *rewarded* with the highest freshness score. Should clamp to 0
or flag the board.

### Bug 5 — Google Sheets 429 is structural; no backoff anywhere

One run performs, in `tools/sheet_writer.py`:

1. ALL JOBS append (batched, line 425-433)
2. TOP MATCHES / GOOD MATCHES appends (446-452)
3. STATS row append (454-461)
4. Cleanup reads + deletes on up to 4 worksheets (469-478)
5. Full formatting of 5 worksheets — dozens of write calls (480-484)

Total easily exceeds the 60 write-requests/min/user quota — exactly the 429 this
run hit: `⚠️ Formatting failed (non-fatal): APIError: [429] Quota exceeded …`.
There is **no backoff/retry on any Sheets call**. Additional risks:

- Formatting silently skipped → dashboard cosmetics drift (observed).
- An exception mid-`append_rows` (e.g. 429 on the batch append) jumps to the
  outer handler at line 493 and **skips STATS + cleanup silently** → partial
  write state.

Fixes: exponential backoff on 429; skip formatting when nothing structural
changed (or format on a slower cadence); wrap each phase so a failure in one
doesn't skip the others.

### Bug 6 — Country filter defeated by placeholder summaries (and runs twice)

`is_allowed_location` (`agents/scrapper.py:637+`) scans summary/title text.
Boards writing `"Himalayas remote listing"` (see C3) cannot be country-checked,
so any location passes. Also runs **twice** per run — once in the scrapper
(`agents/scrapper.py:2451`, `Country filter: blocked 8 jobs`) and once in the
curator (`agents/curator.py:401-407`, `Filtered by country: 0`). Harmless but
redundant; the double pass should collapse into one.

---

## 6. Scraper fleet review (architect view)

**15 of 42 boards failed this run (36%)**, and chronic failures burn real
wall-clock time: 3 retries each with 3–6s base delays, extra 403 backoff, and
30–40s timeouts (`fetch_with_retry`, `agents/scrapper.py:774-837`).

| Failure class | Boards (this run) | Recommendation |
|---|---|---|
| Chronic timeouts (3× every run) | FlexJobs, CWJobs, Remotees, NaukriGulf | Circuit breaker: after N consecutive failed runs, auto-skip + surface a warning |
| TLS cert (fail-closed ✅ correct) | TimesJobs | Drop the board — chain is genuinely broken and the board is out of region |
| Selector precision (many elements, ~no jobs) | Jobspresso (248 el → 3), Dice (26 → 1), GoRemote (3 → 0), RemoteJobsCom (4 → 0) | Tighten selectors or accept low value; track elements→jobs precision ratio |
| Broken endpoint / behavior | WorkInStartups (405), TheMuse (0 jobs), Naukri (bot wall, 35KB shell) | Fix or drop |
| Transient (recovered ✅) | EU Remote Jobs (403 → ok), Remote.co (Playwright HTTP2 err, requests path covered elsewhere) | Working as designed |
| Opt-in, intentionally off | JobSpy (`ENABLE_JOBSPY`) | Keep as-is |

**Cost/benefit flag:** Crawl4AI-JustRemote burned one Gemini call (503) plus one
Groq fallback call to produce **1 job**. Track yield-per-LLM-call per board and
drop boards below a floor.

Also observed: many `✅ Connected to spreadsheet` lines per run — modules
re-create gspread clients repeatedly; a cached client would cut latency and
token refreshes.

---

## 7. Product review (PM view)

### PM-1 — TOP MATCHES tab got 0 rows and will keep getting 0

`tools/sheet_writer.py:435-439` routes jobs to TOP MATCHES only at score ≥85.
Best score this run: 82. If the scorer's realistic ceiling sits under 85, the
dashboard's TOP MATCHES tab is permanently empty and looks broken. Either move
the bar or fix the scorer (C1–C3) — but make the two numbers agree.

### PM-2 — 110 low-match jobs are invisible; no review queue

Rejected LOW MATCH jobs leave no trace in the dashboard. A "maybe" bucket
(e.g. 45–69) with the match reason attached (C4) would turn dead output into a
one-click triage list. The data is already computed; only the write and the UI
are missing.

### PM-3 — Multi-CV machinery is idle

`CVLibrary.pick_best()` with tag-based selection is built and tested
(`tools/cv_library.py`), but the library holds one CV tagged `general`. Two
tagged variants (e.g. `backend`, `fullstack`) would let the existing selection
code actually differentiate — currently every job scores against the same CV and
the log prints misleading `Best CV … (score 0)` noise (C5).

### PM-4 — Rejection policy question: body-pattern collateral

`\bcybersecurity\b` in `BODY_REJECTION_PATTERNS` (`tools/cv_matcher.py:154`)
rejected BeyondTrust's *Cloud Engineer* and *eLearning Developer* because the
company blurb mentions security. Product decision needed: is "works at a
security company" a rejection reason, or should body patterns require a role
noun (e.g. `\bcybersecurity (engineer|analyst|specialist)\b`)?

### PM-5 — Likely false positive worth eyeballing

`Research Engineer (m/f/d)` passed at 73 — probably matched summary keywords
rather than being a genuine fullstack fit. One manual review in the sheet will
tell whether the title-bonus/summary path needs a guard.

### PM-6 — Housekeeping

- `API_TOKEN` is unset (`[api] auth enforced (users=2, api_token=unset)`). Fine
  locally; must be set on the deployed VM per `deploy/DEPLOY_ORACLE.md`.
- `GET /favicon.ico` 404 — cosmetic.
- `INFO:google_genai.models:AFC is enabled…` — library log noise; could be
  silenced via logging config.

---

## 8. Priority table

| # | Item | Ref | Impact | Effort |
|---|---|---|---|---|
| 1 | Print `match_reason` on LOW MATCH lines | C4 | Instant diagnosis, zero risk | ~5 min |
| 2 | Re-enable semantic deps **or** recalibrate `MIN_SCORE` for keyword-only | C1 | Kills the 88% false-rejection rate | Medium |
| 3 | Fix coverage-formula inversion / soften `has_core_signal` zeroing | C2 | High — scoring correctness | Medium |
| 4 | Replace stub summaries with real extracted descriptions | C3 | High — scoring input quality | Medium |
| 5 | Count + log missing-URL drops; add title+company dedup pass | Bugs 1–2 | Data integrity | Small |
| 6 | Sheets: 429 backoff + skip-format-if-unchanged + per-phase error isolation | Bug 5 | Reliability | Small |
| 7 | Scraper circuit breaker + drop TimesJobs | §6 | Runtime hygiene | Medium |
| 8 | Freshness day-7 fix + future-date clamp | Bugs 3–4 | Correctness | Small |
| 9 | TOP MATCHES bar vs scorer ceiling alignment | PM-1 | Dashboard credibility | Small |
| 10 | Maybe-bucket (45–69) with reasons in dashboard | PM-2 | Product value | Medium |
| 11 | Register tagged CV variants | PM-3 | Uses existing machinery | Small |
| 12 | Body-pattern rejection policy decision | PM-4 | Product policy | Decision |

Quick wins: **1, 5, 6, 8, 9, 11.** The items that change the pipeline from
"7 jobs per run" to a real funnel: **2, 3, 4.**

---

## 9. Method notes

Findings were verified against the code, not inferred from the log alone:

- Scoring path: `agents/curator.py:422-528`, `tools/cv_matcher.py:293-401`
- Threshold/weights: `agents/curator.py:39-48`, `requirements.txt:48-50`
- Dedup: `agents/curator.py:363-398`, `tools/deduplicator.py:14-22`
- Rejection patterns: `tools/cv_matcher.py:106-162`
- Parser stubs: `agents/scrapper.py` lines listed in §3 C3 table
- Retry/TLS: `agents/scrapper.py:750-840`
- Sheets write path: `tools/sheet_writer.py:291-495`, 218-262, 651+
- CV selection: `tools/cv_library.py:206-265`
- CV cache guard: `tools/cv_parser.py:229-278`

## 10. Not done (2026-10-21)

- PM‑3 – tagged CV variants: needs your real CV files in `CV_DIR` (e.g. `backend`, `fullstack‑front‑end`).
- PM‑5 – manual sheet review: one‑time human check of a few rows in the Google Sheet.
- PM‑6 – API_TOKEN on the VM: a 2‑minute deployment‑step you perform on the target VM.
- Q5 – frontend dead‑code sweep: front‑end session (pairs with B1‑B5).
- B3 / B4 – demo‑leak e2e suite: front‑end test work (not part of this backend‑only pass).
- §6 extras – selector‑precision per board, deep‑dive yield‑per‑LLM‑call: optional follow‑ups; the basic breaker + yield counters are in.
- Phase‑gate items (A1‑A6, C1‑C5, D1‑D4): live‑browser / VM tasks; the documented A1/A2 platform debt remains open.
