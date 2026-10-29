# Future user product — deferred architecture and scope

Decision recorded: **2026-10-15**. Status: **deferred, no target date; planning only**.

## 1. Product boundary

`main` remains the owner's personal software-development job agent. Keep its
intentional dev-role filters, personal CV configuration, Sheets workflow, and
operator-supplied environment configuration. Do not merge CV upload or the
profession-agnostic/user-isolation redesign into `main` as part of this plan.

The intended future product branch is **`user`**. It is a future destination,
not a branch created or switched to by this documentation change. Implementation
requires a separately scoped and approved effort in a session that supports that
branch. No automatic merge back to `main` is planned; any reusable fixes would
need separate review.

CV upload is deferred together with this product, rather than delivered as an
isolated Phase 2.1a feature in the personal agent. An upload endpoint alone could
be built, but it would not deliver the intended outcome: another person's CV
must not be evaluated with the owner's dev-only rules or use the owner's data
and credentials. Existing on-disk CV/profile editing and multi-CV functionality
on `main` stay unchanged.

## 2. Scope that must be designed together

### Backend and matching

- Remove the assumption that every candidate is a software developer. Audit
  `TECH_FILTER`/`DEV_TITLE_FILTER` in `agents/scrapper.py`, rejection logic in
  `tools/cv_matcher.py`, `CORE_CATEGORIES`, role detection in
  `agents/gemini_tools.py`, and resume/cover-letter prompts.
- Define profession-aware requirements, relevance scoring, and gap analysis;
  a tech-stack-only skill diff is insufficient for arbitrary professions.
- Reuse the existing CV parser where appropriate, but validate it against
  representative non-software CVs before promising broad support.
- Pass an authenticated user/workspace context through API requests, matching,
  background runs, caches, generated materials, tracker writes and apply state.
  Attribution alone is not data isolation.

### Dashboard Profile — future user-product scope

Decision recorded: **2026-10-29**. Add a dedicated **Profile** section to the
future user product; do not build this dashboard feature on personal `main` as
part of the current matching-foundation work. This is planning, not a shipped
feature or authorization to create/switch branches.

The profile must capture each user's own matching policy rather than hardcode
the owner's preferences:

- Current residence/work country and explicitly declared work rights.
- Remote-work arrangements and the countries from which the user will work.
- Relocation destinations, willingness to relocate, and sponsorship needs.
- Seniority bands, relevant experience, acceptable role families and professions.
- Confirmed skills, essential constraints, learnable gaps and avoided stacks.
- Employer-region, industry/startup, timezone and daily-shortlist preferences,
  kept distinct from eligibility requirements.

Keep user-confirmed policy separate from CV-extracted facts. Do not infer work
rights from residence, employer headquarters, a CV, or the word “remote”. A US
employer hiring remotely from India is different from a US-residents-only job;
relocation with unknown sponsorship goes to review. Missing required profile
answers remain unknown, never silently filled with the owner's defaults.

Use the profile as versioned input to the three-layer matcher: eligibility gates
(pass/fail/unknown), requirement-based fit, and per-field evidence completeness.
Every match must retain its profile/scorer/extractor versions. Saving changed
preferences must clearly distinguish saved configuration from pending/completed
rematching; historical results must not appear freshly evaluated automatically.

Persistence and API access must be bound to the authenticated user/workspace,
with ownership enforced server-side. Include validation, honest load/save/error
states, profile completeness, export/reset/delete behavior and appropriate
retention rules; never expose secrets as ordinary profile fields.

Acceptance criteria for the future implementation:

- Two users can save different policies and cannot read or modify each other's
  profiles, matches or derived caches, including through background jobs.
- Remote eligibility, relocation sponsorship, ambiguous seniority and missing
  answers have explicit pass/fail/unknown regression coverage.
- Saved changes survive reload; failed saves never display success.
- CV import cannot silently overwrite user-confirmed work rights/preferences.
- Profile-version changes invalidate relevant match caches and permit deliberate
  rematching without rewriting the provenance of historical decisions.
- API and real-browser tests cover validation, keyboard access and error recovery.

The owner's example (India work, sponsored Saudi/UAE relocation, international
remote work explicitly permitting India) is a test scenario only, not a default
for new accounts. Profession-aware policy remains required; web-development
role families must not become universal product rules.

### Persistence and isolation

- Design database-backed per-user persistence for profiles, jobs/matches,
  tracker history, configuration metadata, runs and artifact ownership. The app
  already uses SQLite for auth/apply state; that does **not** make the existing
  shared pipeline multi-tenant.
- Decide whether the first release is independently self-hosted per user or a
  shared hosted service. Even self-hosted mode must use that user's own setup;
  shared hosting additionally requires enforced tenant isolation everywhere.
- Choose the database, ownership keys, migration strategy and file/object storage
  model before implementing upload. Uploaded files need explicit ownership,
  access checks, retention, deletion and backup policies.
- Isolate caches, deduplication, queues, screenshots, generated resumes, activity
  visibility and daily budgets. Never rely on a client-supplied user ID alone.
- Decide whether Sheets is an optional per-user export/integration or retained
  as a per-user storage adapter. The owner's Sheet must never be a fallback.

### Bring-your-own credentials and configuration

- Each user supplies their own supported LLM provider keys and, if using Sheets,
  their own Sheet destination and authorized Google credentials. Do not reuse
  the owner's keys, Sheet ID or service-account file when setup is incomplete.
- Inventory current `.env` settings and classify them as deployment-only,
  user preferences, user integrations, or secrets. Do not expose the full server
  environment as editable user settings.
- Choose secret custody explicitly: private environment/secret mounts for
  isolated self-hosted instances, or encrypted server-side secret storage with
  deployment-managed encryption keys and per-user authorization for hosted mode.
  Never return secret values to the frontend, put them in browser localStorage,
  commit them, or include them in logs/artifacts.
- Specify credential validation, masked configured/not-configured status,
  replacement/revocation and actionable provider errors. Missing configuration
  blocks affected operations with a setup message; no personal fallback.
- Define provider routing and cost/quota controls per user. One user's fallback
  chain or background run must not spend another user's API quota.

### Frontend and onboarding

- Provide onboarding for account/workspace, profession/job preferences, CV,
  provider credentials and optional Sheets configuration, in an order determined
  by the chosen deployment model.
- Replace dev-only filters, labels, skill panels and assumptions with
  profession-appropriate UI. Keep language grounded in actual CV/job evidence.
- Show active CV, profile completeness, configuration readiness and explicit
  reset/delete controls. Never silently substitute the owner's profile.
- Make loading, parsing failures, unsupported professions, invalid credentials,
  missing setup and provider outages explicit. Never render secret values back.
- Support resume/cover-letter review, relevant gap feedback, accessible forms
  and responsive layouts without implying that generation means submission.

## 3. Proposed delivery order — not a schedule

1. Agree deployment model, supported initial professions, data ownership and
   provider/Sheets configuration policy. Write the architecture decisions and
   threat model; do not promise every profession on day one.
2. Build/test ownership-aware persistence and credential/configuration boundaries.
3. Generalize matching, filtering and materials generation with representative
   profession fixtures, including regression coverage for software development.
4. Implement onboarding, protected PDF/DOCX upload, active-profile selection and
   profession-aware gap feedback end to end.
5. Validate isolation, secret handling, quotas, deletion/retention and deployment
   before opening the product to other users.

These are dependency-ordered workstreams, not a commitment to a database vendor,
endpoint contract, hosting service or release date.

## 4. Release gates

- [ ] Product/deployment model and first supported professions approved.
- [ ] Every user uses their own configured resources; absent/invalid credentials
      fail clearly, with no owner-resource fallback.
- [ ] User A cannot read, change or infer user B's CV, jobs, artifacts, keys,
      runs, activity or budget through APIs, downloads or background tasks.
- [ ] PDF/DOCX content and size validation, parse failures, profile switching,
      active-CV display and gap feedback tested end to end.
- [ ] Non-software matching/materials tests pass without dev-only rejection or
      invented experience; original software workflow regression-tested.
- [ ] Credential lifecycle, retention/deletion, backup/restore and migrations
      documented and tested for the chosen deployment model.
- [ ] Main's existing submit kill-switch and human-review requirements remain
      intact; this redesign does not authorize auto-submit or captcha evasion.

## 5. What happens now

Documentation only. No upload endpoint, DB migration, credential collection,
branch creation or generalized matching implementation is authorized by this
plan. Continue personal-agent maintenance on `main`; keep the cache seam as an
independent low-priority item, not a dependency for starting this future product.

Related: `PM.md` §2.1 and §5 (Scenario A vs Scenario B), `ARCHITECTURE.md` §4b,
`BACKEND.md`, `FRONTEND.md`, and `PRODUCTION.md` §9.
