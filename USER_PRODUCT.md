# Future user product — deferred architecture and scope

Decision recorded: **2026-10-15**. Status: **deferred, no target date; planning only**.

## 1. Product boundary

`main` remains the owner's personal software-development job agent. Keep its
intentional dev-role filters, personal CV configuration, Sheets workflow, and
operator-supplied environment configuration. Do not merge CV upload or the
profession-agnostic/user-isolation redesign into `main` as part of this plan.

The intended future product branch is **`user`**, created from
**`feat/matching-evidence`** when implementation is separately approved. That
branch is the product baseline because it contains both the production legacy
matcher and the shadow matcher, their comparison/evidence facilities, and the
accepted shadow-profile wiring decision. It is not a branch created or switched
to by this documentation change. No automatic merge back to `main` is planned;
any reusable fixes would need separate review.

CV upload is deferred together with this product, rather than delivered as an
isolated Phase 2.1a feature in the personal agent. An upload endpoint alone could
be built, but it would not deliver the intended outcome: another person's CV
must not be evaluated with the owner's dev-only rules or use the owner's data
and credentials. Existing on-disk CV/profile editing and multi-CV functionality
on `main` stay unchanged.

## 2. Confirmed architecture decisions

These decisions make the future product implementation-ready while preserving
the current documentation-only status.

### Product, tenancy, and persistence

- **Deployment:** v1 is a shared OCI-hosted SaaS for individual users. Each
  user owns one private workspace; organizations, memberships, invitations,
  native clients, and public API clients are deferred.
- **Canonical storage:** PostgreSQL is the source of truth for users, sessions,
  profile/CV versions, scraper configuration, runs, jobs, matches/evidence,
  dashboard aggregates, tracker state, materials, quotas, and audit events.
  Google Sheets is an optional user-owned export, never a storage fallback.
- **Tenant boundary:** every user-owned row has immutable `workspace_id`. The
  server derives it exclusively from the authenticated session; a request body,
  route parameter, header, worker message, or browser state can never select
  the effective workspace.
- **Enforcement:** repositories scope every query by `workspace_id`; PostgreSQL
  Row-Level Security is deny-by-default on every tenant table; the runtime DB
  role cannot bypass RLS; migrations use a separate privileged role. Pooled
  connections must set workspace context transaction-locally and clear it on
  release.
- **Files and caches:** private OCI Object Storage keeps CVs and generated
  artifacts under workspace-prefixed keys. Database metadata owns authorization;
  downloads are authenticated application streams, never durable public URLs.
  Caches, deduplication, queues, screenshots, activity, and quotas are all
  workspace-scoped.
- **No personal fallback:** SQLite state, local files, owner Sheets, owner CVs,
  personal caches, owner credentials, and `main` artifacts are unavailable to
  the user product.

### Authentication and browser security

- **Web authentication:** retain opaque, random server-side sessions rather
  than browser JWT access/refresh tokens. The browser receives only an
  `HttpOnly`, `Secure`, `SameSite=Lax` session cookie; PostgreSQL retains only
  its hash.
- **Session lifecycle:** rotate the session at login; enforce absolute and idle
  expiry; revoke it on logout, password reset, credential-compromise response,
  and account deletion; let users review/revoke their active sessions.
- **Account lifecycle:** email/password signup requires verification before
  expensive or provider-using actions. Password-reset and verification tokens
  are single-use, hashed, expiring server-side records. OCI Email Delivery is
  the email transport.
- **Request defenses:** cookie-authenticated mutations require CSRF validation.
  CORS uses an explicit allowlist and never permits arbitrary credentialed
  origins. Rate limits cover signup, login, verification resend, reset, upload,
  scraping, matching, and generation, with independent IP, account, and
  workspace budgets. API errors never enumerate accounts or disclose secrets.
- **Deferred JWT use:** JWT/OAuth access and refresh tokens are reserved for a
  future native/mobile or third-party API client; they are not stored in browser
  local/session storage for v1.

### User settings and secret custody

- User API keys for supported LLM providers and optional Sheets credentials are
  write-only OCI Vault secrets. PostgreSQL stores only a workspace-scoped Vault
  reference, provider/integration type, masked configured state, validation
  time, and audit metadata.
- A secret is never returned by an API, rendered in HTML, placed in browser
  storage, included in logs/traces/exports/error details, or copied into a job
  payload. Replacement creates a new Vault version; revocation prevents queued
  and retried work from using it.
- The Settings UI separates safe preferences from integrations and secrets. It
  provides configured/not-configured state, validate, replace, revoke, and
  provider-specific actionable errors without exposing values.
- Per-workspace provider routing, concurrency, daily scrape limits, and
  LLM/material-generation budgets prevent one user from spending another
  user's resources.

### Matching-evidence product contract

- Preserve the legacy matcher and the shadow matcher from
  `feat/matching-evidence`; user-facing evaluations label each result and never
  silently replace one with the other. Comparison evidence remains available
  for product evaluation, but the legacy matcher is not treated as ground truth.
- Replace global developer/country/seniority filters with a versioned,
  profession-aware profile. V1 supports software/IT, marketing, and sales;
  other professions are explicitly unsupported until fixture-backed validation
  is approved.
- A match records immutable profile version, CV version, extractor version,
  scorer/matcher version, job observation version, eligibility result, fit
  result, evidence completeness, explanations, and explicitly labelled
  legacy/shadow decisions.
- Eligibility is always `pass`, `fail`, or `unknown`. Work rights, remote
  country permission, relocation/sponsorship, seniority, and missing evidence
  that cannot be established become `unknown` and a visible review outcome,
  never a hidden rejection or assumed pass.
- Updating a profile creates a new version. Historical evaluations are never
  rewritten; affected results become visibly stale and rematch only after an
  explicit user action.

### Product experience and mobile boundary

- Onboarding proceeds: verified account, Profile policy, CV upload/parse,
  provider setup, optional Sheets export, then first scrape. Each stage exposes
  loading, validation, partial failure, retry, and completion truthfully.
- The web dashboard adds Profile and Settings beside jobs, tracker, materials,
  and runs. It uses evidence-led language rather than developer-only labels;
  users can see active CV, profile completeness, configuration readiness,
  match reasons, unknown/review states, and deletion/export controls.
- The app is responsive and keyboard-accessible. Forms expose labels, errors,
  focus, and recovery; inputs remain usable at mobile text sizes; touch feedback
  is capability-based; safe areas and dynamic viewport behavior are tested on
  real hardware. A native app is out of scope, but API contracts remain
  extensible for it.
- The visual system extends the existing dashboard tokens/components rather
  than adding a UI framework. It prioritizes compact work surfaces, clear
  hierarchy, visible state changes, accessible contrast, and honest empty/error
  states over decorative dashboard patterns.

## 3. Scope that must be designed together

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

## 4. Proposed delivery order — not a schedule

1. Record the confirmed decisions as ADRs and write the OCI threat model,
   migration/restore procedure, retention policy, and deletion workflow.
2. Build/test PostgreSQL ownership, RLS, session/CSRF, Vault, and Object Storage
   boundaries before any user-facing matching flow.
3. Generalize matching, filtering and materials generation with representative
   profession fixtures, including regression coverage for software development.
4. Implement onboarding, protected PDF/DOCX upload, active-profile selection and
   profession-aware gap feedback end to end.
5. Validate isolation, secret handling, quotas, deletion/retention and deployment
   before opening the product to other users.

These are dependency-ordered workstreams, not a release date. OCI PostgreSQL,
Object Storage, Vault, and Email Delivery are the v1 infrastructure target.

## 5. Release gates

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
- [ ] Two-workspace API, RLS, worker, cache, queue, and Object Storage tests
      prove no cross-workspace resource can be read, changed, searched,
      downloaded, deduplicated, claimed, or charged.
- [ ] Missing workspace context fails closed; pooled PostgreSQL connections
      cannot retain a prior request's RLS context; the application role cannot
      bypass RLS.
- [ ] Auth tests prove verification/reset expiry and single use, hashed session
      storage, cookie flags, rotation/revocation, CSRF rejection, CORS denial,
      and rate-limit recovery.
- [ ] Vault, API, browser, export, queue, audit, and log checks prove user
      secrets never leave write-only custody; revocation blocks queued retries.
- [ ] Every matching result retains profile/CV/extractor/scorer provenance and
      explicit legacy/shadow labels; unknown eligibility remains reviewable.
- [ ] End-to-end tests cover signup through verified onboarding, provider setup,
      scoped scrape, matching evidence, dashboard, and material review for two
      concurrent users, including mobile and keyboard recovery states.

## 6. What happens now

Documentation only. No upload endpoint, DB migration, credential collection,
branch creation or generalized matching implementation is authorized by this
plan. Continue personal-agent maintenance on `main`; keep the cache seam as an
independent low-priority item, not a dependency for starting this future product.

Related: `PM.md` §2.1 and §5 (Scenario A vs Scenario B), `ARCHITECTURE.md` §4b,
`BACKEND.md`, `FRONTEND.md`, and `PRODUCTION.md` §9.
