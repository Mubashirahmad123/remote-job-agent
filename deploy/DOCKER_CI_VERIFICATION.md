# Locked Docker CI verification — 2026-10-15

## Evidence

- Tested code commit: `0971322d20cdc51ece030594a2f7a4764535eea2`.
- Branch: `arena/393bb940-remote-job-agent` (published; not merged/deployed).
- [CI run 38743655019](https://github.com/Mubashirahmad123/remote-job-agent/actions/runs/38743655019): **completed / success**.
- Reviewed using `gh run watch --exit-status`, `gh run view --json jobs`, and
  check-run annotation APIs. This is observed GitHub execution, not a local
  dry-run or a claim based only on workflow configuration.

| Job | GitHub result |
|---|---|
| [Locked image — native x86_64](https://github.com/Mubashirahmad123/remote-job-agent/actions/runs/38743655019/job/116451509548) | All steps passed |
| [Locked image — native aarch64](https://github.com/Mubashirahmad123/remote-job-agent/actions/runs/38743655019/job/116451508823) | All steps passed |
| API/auth/attribution + lock-drift checks | Passed |
| Dashboard E2E (smoke + tracker + environment) | Passed |
| Dependency audit against recorded baseline | Passed; not a zero-vulnerability claim |

## What the native image jobs verified

Both `ubuntu-latest` x86-64 and `ubuntu-24.04-arm` ARM64 runners executed:

1. `docker build` using `requirements.lock.txt`, including actual Chromium
   installation and its operating-system dependencies.
2. `uv pip check --system` in the built image.
3. Runtime architecture and non-root UID assertions, plus comparison of every
   active lock requirement against its installed package version.
4. FastAPI startup/lifespan and public liveness response via TestClient **inside
   the container**. This is not a deployed network-service or reverse-proxy test.
5. Real headless Chromium launch and local-page title assertion. No job board,
   CAPTCHA, LLM, personal Sheet, intent or submit endpoint is involved.
6. Selected API/auth/actor/country-filter/auto-applier regression suites inside
   the locked image. Full source-scanning tests run in the separate API job;
   `.git` and `.github` remain excluded from the runtime image.
7. Image filesystem inventory and the configured secret/database/cache/local
   venv leak-pattern checks.

No image was pushed to a registry; no application was deployed or submitted.
Requirements/lock pins and the vulnerability baseline were not changed.

## Review fix before execution

The old image inventory pipeline ended with `|| true`, permitting an export or
listing failure to look like a clean image. It now fails on export/listing
errors and empty inventory, and uses an EXIT trap to clean up its temporary
container. Three offline failure-injection cases execute the actual CI shell
with fake Docker/tar tools; they are not represented as image tests.

Local preflight: **63 Docker/hardening/leak tests passed**. Current full local
locked Linux suite: **1007 passed, 8 skipped, 32 warnings** (previous 1004 plus
these three guards). Skips are seven optional FAISS cases and deferred Lever
confirmation-copy coverage. Latest local frontend result remains **64 passed**;
GitHub also reports the frontend job passed, but no raw-log test counts are
claimed here.

## Review limits and remaining work

- **Raw logs:** `gh run view --log` could not download the archive because its
  signed redirect uses `results-receiver.actions.githubusercontent.com`, outside
  this sandbox's allowed hosts. Job/step conclusions and annotations were
  reviewed via the GitHub API; raw stdout was not reviewed or archived locally.
  The run/job links above remain the source for browser inspection. No exact
  CI pytest counts, installed-pin counts or image digests are inferred from logs.
- **Runner notice:** GitHub reports that `ubuntu-latest` begins migrating to
  Ubuntu 26 on 2026-10-19. This is a notice, not a failed check. Retest after that
  transition or deliberately pin the runner in a follow-up; a passing run is
  evidence for its tested runner environment, not every future mutable label.
- **Oracle VM:** deployment, Compose/Caddy/TLS, scheduler, host-volume UID/GID
  ownership and live mounted configuration still need operational verification.
  Native ARM CI does not establish that the user's actual VM is deployed.
- **Reproducibility/security:** base-image and uv-bootstrap tags are mutable;
  artifact hashes are not locked, optional packages outside the lock are not
  covered, and baseline vulnerabilities are not eliminated by a green audit.
- **Application:** native browser launch does not close dashboard responsive/
  input/login/CSP coverage or the reported Democorp fill-timeout/screenshot-404
  issue. Submit stays disabled; CV upload remains deferred.
