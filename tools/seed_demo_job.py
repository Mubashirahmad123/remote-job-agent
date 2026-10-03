"""Seed Greenhouse's own demo posting into the local snapshot.

The submit path only operates on jobs the pipeline knows about
(`cache.get_job(fingerprint)`), so a supervised live-submit rehearsal needs
the target posting present as a row. Scraping it is not an option — it is
not on any board feed — so this writes it into the local snapshot the API
falls back to.

Target: Greenhouse's public example board, "Full Stack Engineer" at
Democorp (job 83446). Not a real employer and not a real vacancy, which is
the entire point: it exercises the real Greenhouse DOM, the real embedded
confirmation metadata, and the real submit control without consuming a
human being's attention.

    python -m tools.seed_demo_job                 # write + print fingerprint
    python -m tools.seed_demo_job --print-only    # just show the fingerprint

The row is marked `source="GreenhouseDemo"` and `tab="ALL JOBS"` so it is
trivially identifiable and removable. Never write this row to the Google
Sheet — it is local test scaffolding, not a job.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from tools.deduplicator import job_fingerprint

DEMO_URL = "https://job-boards.greenhouse.io/example/jobs/83446"
SNAPSHOT = Path("scraped_jobs.json")

DEMO_JOB: Dict[str, Any] = {
    "job_title": "Full Stack Engineer",
    "company": "Democorp",
    "location": "New York",
    "apply_url": DEMO_URL,
    "url": DEMO_URL,
    "source": "GreenhouseDemo",
    "tab": "ALL JOBS",
    # Score must clear the submit gate but stay out of "dream" tier, which
    # is forbidden from automated submit by design.
    "match_score": 85,
    "score": 85,
    "tier": "good_fit",
    "status": "new",
    "scraped_at": "2026-10-03T00:00:00+00:00",
    "tech_stack": "Python, JavaScript, React",
    "description": (
        "Greenhouse public demo posting used for supervised submit-path "
        "rehearsal. Not a real vacancy."
    ),
}


def build_row() -> Dict[str, Any]:
    row = dict(DEMO_JOB)
    row["job_fingerprint"] = job_fingerprint(row)
    return row


def seed(path: Path = SNAPSHOT) -> Dict[str, Any]:
    row = build_row()
    rows = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            rows = loaded if isinstance(loaded, list) else loaded.get("rows", [])
        except (json.JSONDecodeError, AttributeError):
            rows = []
    rows = [r for r in rows if r.get("job_fingerprint") != row["job_fingerprint"]]
    rows.append(row)
    path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return row


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--print-only", action="store_true", help="Do not write the snapshot")
    parser.add_argument("--snapshot", default=str(SNAPSHOT))
    args = parser.parse_args(argv)

    if args.print_only:
        row = build_row()
    else:
        row = seed(Path(args.snapshot))
        print(f"Wrote demo posting to {args.snapshot}")

    print(f"  title:       {row['job_title']} @ {row['company']}")
    print(f"  apply_url:   {row['apply_url']}")
    print(f"  fingerprint: {row['job_fingerprint']}")
    print("\nTyped-title confirmation for /submit must be exactly:")
    print(f"  {row['job_title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
