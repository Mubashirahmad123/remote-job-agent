#!/usr/bin/env python3
"""Dependency vulnerability audit against a RATCHETING baseline.

    python deploy/dependency_audit.py                  # CI: fail on NEW findings
    python deploy/dependency_audit.py --update-baseline  # record the current state

Why a baseline at all. The first run of this audit against
`requirements.lock.txt` reported 48 distinct published advisories across 8
packages. Almost none of them are cheap to clear:

    crawl4ai==0.3.74     18 advisories, fixes start at 0.8.0 — five minors on,
                         and crawl4ai drives the JS-rendered board scraper, so
                         the upgrade is a porting project, not a bump
    pillow==10.4.0       17 advisories, fixes start at 12.1.1 — two majors on
    chromadb==1.1.1       4 advisories and NO fixed version published at all
    mcp==1.26.0           3 advisories (transitive, via crewai)
    pdfminer-six          2 advisories (transitive, via pdfplumber)
    lxml==5.4.0           1 advisory, fix is a major (6.1.0)
    json-repair==0.25.3   1 advisory (transitive)

A CI job that fails on all 48 from day one is a job that gets disabled by the
end of the week, and a disabled audit is worse than no audit because it looks
like coverage. So this one fails only on what is NEW.

That makes it a ratchet, and the ratchet only turns one way in practice:

  * A newly published advisory in a package this project ships fails the build,
    which is the moment the information is actionable and cheap.
  * Clearing one — as `requests` 2.32.3 → 2.33.0 cleared two — is reported as
    FIXED so the baseline entry can be pruned. Once pruned it can never come
    back silently: a regression to the vulnerable version fails the build.
  * Adding an entry to the baseline is a commit to a reviewed file, so accepting
    a risk is a visible decision rather than something that happens by itself.

The baseline records `name==version ADVISORY-ID`. The version is part of the key
on purpose: bumping a package changes its findings, so a stale entry for an old
version shows up as FIXED and prompts a look, rather than quietly suppressing
whatever the new version reports.

Scans the LOCK, not requirements.txt, because the lock is the full transitive
resolution — and every one of the 48 findings above is in a package
requirements.txt does not mention. Caveat worth knowing: nothing currently
INSTALLS from the lock (the Dockerfile installs requirements.txt), so this
audits the best available record of what ships rather than a byte-exact
manifest. Making the image install from the lock is the real fix and is a
separate, riskier change — it has to be verified on the ARM deployment VM,
which CI does not run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Set

REPO = Path(__file__).resolve().parent.parent
LOCK = REPO / "requirements.lock.txt"
BASELINE = REPO / "deploy" / "audit-baseline.txt"

HEADER = """# Known-vulnerability baseline for `deploy/dependency_audit.py`.
#
# Format: one `<name>==<version> <ADVISORY-ID>` per line. Blank lines and `#`
# comments are ignored. Keep it sorted; the writer does, and an unsorted file
# makes a diff unreadable.
#
# This is NOT a list of advisories judged harmless. It is the state of the
# dependency tree on the date below, recorded so that CI fails on NEW findings
# instead of on all of them at once — a job red from day one is a job that gets
# switched off. Read the reasoning and the per-package remediation cost in the
# docstring of deploy/dependency_audit.py.
#
# Remove an entry once the package is upgraded past it. The audit reports
# entries that no longer reproduce as FIXED precisely so they get pruned, and a
# pruned entry can never come back silently.
#
# Regenerate wholesale with:
#     python deploy/dependency_audit.py --update-baseline
#
# Recorded: {date}
"""


def run_audit(lock: Path) -> dict:
    """Invoke pip-audit and return its JSON payload."""
    command = [
        sys.executable, "-m", "pip_audit",
        "-r", str(lock),
        "-s", "pypi",       # the PyPI JSON API; the OSV backend needs api.osv.dev
        "--no-deps",        # the lock is already fully resolved
        "-f", "json",
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    except FileNotFoundError:
        raise SystemExit(
            "pip-audit is not installed. In CI it is installed by the audit job; "
            "locally: python -m pip install pip-audit"
        )
    # pip-audit exits 1 when it FINDS vulnerabilities, which is a result here,
    # not a failure to run. Anything else means the audit did not happen, and
    # that must not be allowed to look like "clean".
    if proc.returncode not in (0, 1):
        raise SystemExit(
            f"pip-audit exited {proc.returncode} — the audit did not complete, so "
            f"nothing can be concluded.\n{proc.stderr.strip()[:2000]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise SystemExit(
            "could not parse pip-audit's JSON output; the audit did not complete.\n"
            f"stdout: {proc.stdout.strip()[:800]}\nstderr: {proc.stderr.strip()[:800]}"
        )


def findings(payload: dict) -> Set[str]:
    """Distinct `<name>==<version> <advisory>` strings from an audit payload.

    A set, because the PyPI backend reports the same advisory several times for
    a package published under more than one normalized name, and counting those
    separately inflates every number in the report.
    """
    out: Set[str] = set()
    for dep in payload.get("dependencies", []):
        name = dep.get("name")
        version = dep.get("version")
        if not name or not version:
            continue
        for vuln in dep.get("vulns") or []:
            advisory = vuln.get("id")
            if advisory:
                out.add(f"{name}=={version} {advisory}")
    return out


def read_baseline(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    entries: Set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line)
    return entries


def write_baseline(path: Path, entries: Iterable[str]) -> None:
    from datetime import date

    body = "\n".join(sorted(entries))
    header = HEADER.replace("{date}", date.today().isoformat())
    path.write_text(header + "\n" + body + ("\n" if body else ""), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record the current findings as the accepted baseline and exit 0",
    )
    parser.add_argument("--lock", default=str(LOCK), help="lock file to audit")
    parser.add_argument(
        "--baseline", default=str(BASELINE), help="baseline file to compare against"
    )
    args = parser.parse_args(argv)

    lock, baseline_path = Path(args.lock), Path(args.baseline)
    if not lock.exists():
        raise SystemExit(f"no such lock file: {lock}")

    current = findings(run_audit(lock))

    if args.update_baseline:
        write_baseline(baseline_path, current)
        print(f"baseline written: {len(current)} findings -> {baseline_path}")
        return 0

    known = read_baseline(baseline_path)
    new = sorted(current - known)
    fixed = sorted(known - current)

    if fixed:
        print(f"FIXED — {len(fixed)} baseline entr{'y' if len(fixed) == 1 else 'ies'} no longer reproduce:")
        for entry in fixed:
            print(f"  - {entry}")
        print(f"  Prune them from {baseline_path.name} so they cannot come back silently.")
        print()

    if new:
        print(f"NEW — {len(new)} vulnerabilit{'y' if len(new) == 1 else 'ies'} not in the baseline:")
        for entry in new:
            print(f"  + {entry}")
        print()
        print("Either upgrade past it, or accept it deliberately by adding the")
        print(f"line to {baseline_path} in the same commit:")
        print("    python deploy/dependency_audit.py --update-baseline")
        return 1

    print(f"OK — {len(current)} known findings, all in the baseline; nothing new.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
