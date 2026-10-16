# PR #31 CI failure remediation — 2026-10-16

## Observed failures, not assumptions

At `72ff472`, push pytest passed while PR pytest failed. Both vulnerability
audits failed. Native x86-64/ARM64 Docker and dashboard checks passed in that
PR run. The raw Actions log download host is inaccessible from this sandbox;
the original pytest failure annotation contained only exit code 1, so its exact
assertion/traceback is **not known**.

The audit was independently reproduced against the unchanged lock:

```text
NEW — 1 vulnerability not in the baseline:
  + mcp==1.26.0 CVE-2026-59951
```

A diagnostic follow-up at `806f7d3` exposed failure output through escaped,
bounded GitHub Checks API annotations while preserving command exit status.
Both pytest jobs then passed; the PR dashboard job failed. That historical
frontend traceback is likewise unavailable. The wrapper now covers dashboard
failures too. These reruns do not retroactively diagnose the original failures.

## Actual dependency remediation (not an MCP exception)

`CVE-2026-59951` / `GHSA-84m7-p3x7-pcfv` concerns unbounded stateful MCP HTTP
session retention. PyPI reports **MCP 1.30.0** as the first fixed 1.x release.
The old CrewAI 1.14.7 requires `mcp~=1.26.0`; even CrewAI 1.15.28 caps MCP at
1.28.x. Simply forcing MCP 1.30.0 under either would create an inconsistent
installation, so no `--no-deps`, metadata override or disabled audit is used.

Instead, make a deliberate **CrewAI compatibility rollback to 1.6.1**, whose
published requirement is `mcp>=1.16.0`, and explicitly pin **MCP 1.30.0**.
The application uses Agent/Crew/Task/LLM/tool APIs available on this version.
This is a framework rollback, not an upgrade, and future CrewAI upgrades must
retain a dependency range that accepts a patched MCP.

The universal lock retains existing pins where compatible, changes these three
versions and drops dependencies no longer needed by CrewAI:

| Package | Previous | New | Reason |
| --- | --- | --- | --- |
| crewai | 1.14.7 | 1.6.1 | Permit patched MCP without breaking declared constraints |
| mcp | 1.26.0 | 1.30.0 | Fix the new advisory and the three older MCP baseline findings |
| json-repair | 0.25.3 | 0.25.2 | Exact requirement of CrewAI 1.6.1; known advisory remains |

**Existing risk retained:** `GHSA-xf7x-x43h-rpqh` in json-repair is not fixed.
Its previously accepted baseline entry moves from 0.25.3 to 0.25.2, the same
advisory on the now-required version. The three fixed MCP baseline entries
are removed; no exception for the new MCP advisory is added. This is a narrow,
reviewable baseline migration, not a wholesale baseline regeneration. Audit
now reports **43 known findings and no new findings**; it does not claim a
vulnerability-free dependency tree.

## Regression and CI reliability work

- API and dashboard CI install the **same universal lock** audited and installed
  in Docker, not independently floating transitive resolutions. Pip caches key
  on that lock. Existing direct-pin consistency checks remain active.
- Real SDK tests build the actual production factory extracted from main.py
  without loading its personal `.env`, run an offline agent/task kickoff and
  construct configured Gemini/Mistral/Groq adapters. Network attempts are denied;
  no provider inference, scraping or Sheets operation is performed. Installed
  CrewAI metadata must accept the patched MCP. These tests also run in both
  native container jobs, not just on the host interpreter.
- Review tests wait for fake browser entry before asserting its call count or
  assigning the first job's image index. A foreground timeout or heartbeat
  never guaranteed browser-thread scheduling; the old test assumptions could
  race on busy runners. This is an independently identified test defect, not a
  claimed reconstruction of the inaccessible historical traceback.
- Diagnostic-wrapper tests prove failed exit codes stay failed, stderr is
  included, annotation data is escaped/bounded and missing commands fail closed.
  No tests are skipped, retried automatically or marked allowed-to-fail.

Fresh local lock-only installation has **168 compatible packages**. Current
full Python/dashboard totals are recorded in TESTER.md. New hosted CI must be
checked on the remediation commit; older green image runs do not validate a
changed lock. No merge, deployment, live application, CAPTCHA bypass, intent or
submission is part of this remediation.
