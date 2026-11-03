"""Phase 4: compare the legacy curator with the shadow matcher on ONE run.

Read-only analysis. Emits a CSV plus a confusion matrix, and refuses to write
anything unless the ledger run reconciles: every fetched instance must have
exactly one terminal row.

Why this file was rewritten (2026-11-02, defect D10)
----------------------------------------------------
The previous version was not a comparison:
  * it picked the newest run by ``seq``, which included runs that never reached
    the curator (run ``16556b5baffc``: ``raw_fetched 312``, ``dev_filter_drop
    169``, ``country_drop 21``, 122 instances with no terminal row);
  * ``legacy_score`` was hard-coded to ``None`` while ``stage_events.score``
    held the real legacy score;
  * every pre-curation drop was mapped to ``legacy_decision='rejected'``, so a
    duplicate URL counted as a rejection and a dev-filter drop counted as a
    curation decision;
  * ``agreement`` was ``(legacy == 'eligible') == (new == 'eligible')``, a
    boolean identity that is ``True`` for every row when neither side emits
    ``eligible``. The CSV it produced reported **502/502 agreement** over 312
    real jobs while legacy emitted zero ``eligible`` and zero ``review``.

Honesty rules for this report
-----------------------------
1. The legacy matcher is NOT ground truth. It is the production controller,
   which is a different claim. Disagreement lists are therefore named
   ``legacy_rejected_new_open`` / ``legacy_eligible_new_closed``, never
   "false positives" or "errors".
2. Agreement is reported per class. A single scalar is undefined when a class
   has zero legacy support, and is printed as undefined rather than as 100%.
3. Rows are keyed by ``job_uid`` (one per fetched instance), so the ledger's
   duplicate ``job_texts`` rows (defect D6) cannot inflate the counts.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, fields as dc_fields
from pathlib import Path

from tools.matching_extract import extract_matching_evidence
from tools.matching_policy import JobEvidence
from tools.matching_score import (
    Requirement,
    RequirementsEvidence,
    score_match,
)
from tools.matching_shadow import _string_set, load_profile
from tools.pipeline_ledger import TERMINAL_STAGES, PipelineLedger

DEFAULT_DB = Path("data/pipeline_ledger.db")
DEFAULT_PROFILE = Path("data/matching_profile.json")
DEFAULT_OUT = Path("phase4_comparison_full.csv")

# Terminal stage -> the class the legacy pipeline actually produced.
# A duplicate and a pre-curation drop are NOT curation decisions, so they get
# their own classes instead of being folded into "rejected".
LEGACY_DECISION_BY_STAGE = {
    "legacy_passed": "eligible",
    "legacy_low_match": "review",
    "legacy_rejected": "rejected",
    # Same opening already seen / never entered curation.
    "dedup_missing_url": "duplicate",
    "dedup_url_dup": "duplicate",
    "dedup_cross_board": "duplicate",
    "dedup_fingerprint": "duplicate",
    # Dropped before the curator ever scored them: not a curation verdict.
    "dev_filter_drop": "prefiltered",
    "country_drop": "prefiltered",
    "date_drop": "prefiltered",
}
DECIDED_CLASSES = ("eligible", "review", "rejected")
NEW_CLASSES = ("eligible", "likely_fit", "review", "rejected")


class IncompleteRunError(RuntimeError):
    """The run cannot support a comparison. Nothing is written."""


@dataclass(frozen=True)
class ComparisonRow:
    job_uid: str
    job_title: str
    company: str
    source: str
    legacy_stage: str
    legacy_decision: str
    legacy_score: float | None
    legacy_reason: str
    new_decision: str
    new_reasons: str
    required_score: float | None
    location_gate: str
    role_gate: str
    seniority_gate: str


# ── Ledger reading ────────────────────────────────────────────────────────
def newest_run_id(conn: sqlite3.Connection) -> str | None:
    """Latest run by insertion order. Non-standard DISTINCT removed (D10 note)."""
    row = conn.execute(
        "SELECT run_id FROM stage_events ORDER BY seq DESC LIMIT 1").fetchone()
    return row[0] if row else None


def require_complete(db_path: Path, run_id: str | None = None) -> str:
    """Return a reconcilable run id, or raise. Never returns a partial run."""
    ledger = PipelineLedger(db_path, run_id=run_id)
    if run_id:
        target = run_id
    else:
        with closing(sqlite3.connect(db_path)) as conn:
            target = newest_run_id(conn)
    if not target:
        raise IncompleteRunError(f"no runs in ledger {db_path}")
    report = ledger.reconcile(target)
    if not report["complete"]:
        raise IncompleteRunError(
            "run {!r} is not reconcilable: raw_fetched={} terminal_sum={} "
            "missing_terminal={} duplicated_terminal={}. Refusing to write a "
            "comparison; a partial run cannot show agreement.".format(
                target, report["raw_fetched"], report["terminal_sum"],
                len(report["missing_terminal"]),
                len(report["duplicated_terminal"])))
    return target


def job_texts_by_uid(conn: sqlite3.Connection, run_id: str) -> dict[str, dict]:
    """One job text per instance, first row wins.

    ``job_texts`` has no UNIQUE(run_id, job_uid) yet (D6), so the same instance
    appears once per recorded stage. Collapsing here keeps this report at one
    row per job without touching stored data.
    """
    rows = conn.execute(
        """SELECT job_uid, title, company, url, source, description
             FROM job_texts WHERE run_id=? ORDER BY seq""",
        (run_id,)).fetchall()
    out: dict[str, dict] = {}
    for uid, title, company, url, source, description in rows:
        if uid in out:
            continue
        out[uid] = {
            "job_uid": uid,
            "job_title": title or "",
            "company": company or "",
            "url": url or "",
            "source": source or "",
            "description": description or "",
        }
    return out


def terminals_by_uid(conn: sqlite3.Connection, run_id: str) -> dict[str, dict]:
    """One terminal record per instance. Last recorded terminal row wins."""
    marks = ",".join("?" * len(TERMINAL_STAGES))
    rows = conn.execute(
        f"""SELECT job_uid, stage, reason_code, score
              FROM stage_events
             WHERE run_id=? AND stage IN ({marks})
             ORDER BY seq""",
        (run_id, *TERMINAL_STAGES)).fetchall()
    out: dict[str, dict] = {}
    for uid, stage, reason, score in rows:
        out[uid] = {"stage": stage, "reason_code": reason or "",
                    "score": score}
    return out


# ── New engine evaluation ─────────────────────────────────────────────────
def _job_evidence(job: dict, evidence: dict) -> JobEvidence:
    job_fields = {f.name for f in dc_fields(JobEvidence)} - {"title", "description"}
    kwargs = {k: v for k, v in evidence.items() if k in job_fields}
    for key in ("allowed_work_locations", "responsibilities", "role_hints"):
        if key in kwargs and kwargs[key] is not None:
            kwargs[key] = frozenset(kwargs[key])
    kwargs.setdefault("work_mode", "unknown")
    return JobEvidence(job.get("job_title") or "", job.get("description") or "",
                       **kwargs)


def _requirements(evidence: dict) -> RequirementsEvidence:
    extracted = evidence.get("requirements") or {}

    def groups(name):
        return tuple(
            Requirement(_string_set(r["alternatives"], "alternatives"),
                        r["evidence"], r.get("weight", 1),
                        r.get("essential", False), r.get("type", "technology"))
            for r in extracted.get(name, []))

    return RequirementsEvidence(
        groups("required") if "required" in extracted else None,
        groups("preferred"), extracted.get("complete", False),
        extracted.get("extractor_version", "unextracted-v1"))


def build_row(job: dict, terminal: dict | None, profile) -> ComparisonRow:
    stage = (terminal or {}).get("stage", "unknown")
    legacy_decision = LEGACY_DECISION_BY_STAGE.get(stage, "unknown")
    evidence = extract_matching_evidence(job)
    source_job = _job_evidence(job, evidence)
    result = score_match(source_job, profile, _requirements(evidence))
    gates = {gate.name: f"{gate.outcome}:{gate.reason}"
             for gate in result.eligibility.gates}
    return ComparisonRow(
        job_uid=job["job_uid"],
        job_title=job.get("job_title") or "",
        company=job.get("company") or "",
        source=job.get("source") or "",
        legacy_stage=stage,
        legacy_decision=legacy_decision,
        legacy_score=(terminal or {}).get("score"),
        legacy_reason=(terminal or {}).get("reason_code", ""),
        new_decision=result.decision,
        new_reasons="|".join(result.review_reasons),
        required_score=result.required.score,
        location_gate=gates.get("location", ""),
        role_gate=gates.get("role", ""),
        seniority_gate=gates.get("seniority", ""),
    )


def build_rows(db_path: Path, run_id: str, profile) -> list[ComparisonRow]:
    conn = sqlite3.connect(db_path)
    try:
        texts = job_texts_by_uid(conn, run_id)
        terminals = terminals_by_uid(conn, run_id)
    finally:
        conn.close()
    return [build_row(job, terminals.get(uid), profile)
            for uid, job in texts.items()]


# ── Reporting ─────────────────────────────────────────────────────────────
def confusion(rows: list[ComparisonRow]) -> dict:
    """3x3 matrix over decided classes, plus what was excluded and why.

    ``eligible``/``review``/``rejected`` are the only classes both engines
    produce. ``likely_fit`` is folded into the new engine's positive-ish column
    only for the matrix legend; it is reported separately so the fold is
    visible. ``duplicate``/``prefiltered``/``unknown`` never entered curation.
    """
    matrix = Counter()
    excluded = Counter()
    for row in rows:
        if row.legacy_decision in DECIDED_CLASSES:
            matrix[(row.legacy_decision, row.new_decision)] += 1
        else:
            excluded[row.legacy_decision] += 1
    return {"matrix": dict(matrix), "excluded": dict(excluded),
            "decided": sum(matrix.values())}


def agreement_by_legacy_class(report: dict) -> dict[str, float | None]:
    """Share of rows per legacy class where the new engine agrees exactly.

    ``None`` means undefined because that legacy class has zero rows. It is
    never rendered as 100%.
    """
    matrix = report["matrix"]
    support = Counter()
    for (legacy, _new), count in matrix.items():
        support[legacy] += count
    out: dict[str, float | None] = {}
    for legacy_class in DECIDED_CLASSES:
        total = support.get(legacy_class, 0)
        if total == 0:
            out[legacy_class] = None
            continue
        agree = matrix.get((legacy_class, legacy_class), 0)
        out[legacy_class] = round(100.0 * agree / total, 1)
    return out


def disagreements(rows: list[ComparisonRow]) -> dict[str, list[ComparisonRow]]:
    """Directional disagreement lists.

    Legacy is the production controller, not a label set, so neither list is
    called "false positive" or "false negative".
    """
    return {
        "legacy_rejected_new_open": [
            r for r in rows
            if r.legacy_decision == "rejected"
            and r.new_decision in ("eligible", "likely_fit", "review")],
        "legacy_eligible_new_closed": [
            r for r in rows
            if r.legacy_decision == "eligible"
            and r.new_decision in ("review", "rejected")],
    }


def render_report(rows: list[ComparisonRow], run_id: str) -> str:
    report = confusion(rows)
    rates = agreement_by_legacy_class(report)
    matrix = report["matrix"]
    lines = [
        f"=== Phase 4 comparison, run {run_id} ===",
        f"rows (one per job_uid): {len(rows)}",
        "",
        "Legacy class support:",
    ]
    for legacy_class in DECIDED_CLASSES:
        support = sum(c for (legacy, _new), c in matrix.items()
                      if legacy == legacy_class)
        lines.append(f"  {legacy_class:<9} {support}")
    lines.append("Excluded from the decided matrix: "
                 + (", ".join(f"{k}={v}" for k, v in sorted(
                     report["excluded"].items())) or "none"))
    lines.append("")
    header = "legacy \\ new".ljust(12) + "".join(
        f"{c:>12}" for c in NEW_CLASSES)
    lines.append(header)
    for legacy_class in DECIDED_CLASSES:
        cells = "".join(f"{matrix.get((legacy_class, n), 0):>12}"
                        for n in NEW_CLASSES)
        lines.append(f"{legacy_class:<12}{cells}")
    lines.append("")
    lines.append("Exact agreement within each legacy class "
                 "(None = undefined, zero support):")
    for legacy_class, rate in rates.items():
        lines.append(f"  {legacy_class:<9} "
                     + ("undefined (0 rows)" if rate is None else f"{rate}%"))
    lines.append("")
    lines.append("Legacy is the production controller, not ground truth. The "
                 "lists below are disagreements, not errors.")
    lists = disagreements(rows)
    for name, items in lists.items():
        lines.append(f"  {name}: {len(items)}")
    lines.append("")
    lines.append("Review reasons (new engine), most common:")
    counter = Counter(reason for row in rows
                      for reason in row.new_reasons.split("|") if reason)
    for reason, count in counter.most_common():
        lines.append(f"  {reason}: {count}")
    return "\n".join(lines)


def write_csv(rows: list[ComparisonRow], out_path: Path) -> None:
    fieldnames = [f.name for f in dc_fields(ComparisonRow)]
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--run", default=None,
                        help="ledger run id (default: newest, must reconcile)")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if not args.db.exists():
        sys.stderr.write(f"ledger not found: {args.db}\n")
        return 2
    try:
        run_id = require_complete(args.db, args.run)
    except IncompleteRunError as exc:
        sys.stderr.write(f"refusing to emit a comparison: {exc}\n")
        return 2
    if not args.profile.exists():
        sys.stderr.write(f"profile not found: {args.profile}\n")
        return 2

    rows = build_rows(args.db, run_id, load_profile(args.profile))
    write_csv(rows, args.out)
    print(render_report(rows, run_id))
    print(f"\nwrote {args.out} ({len(rows)} jobs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
