"""Pure three-layer matching contract for shadow evaluation.

Consumes structured requirements, never guesses that every skill mentioned in a
posting is required. Extraction, fetching and persistence are separate concerns.
Scores are provisional requirement coverage, not calibrated application odds.
"""
from dataclasses import dataclass, field
import math
import re
from typing import Literal

from tools.matching_policy import (CandidatePolicy, Decision, EligibilityResult,
                                   JobEvidence, evaluate_eligibility)

SCORER_VERSION = "requirements-v3"
ALIASES = {
    "nodejs": "node", "node.js": "node", "reactjs": "react", "react.js": "react",
    "nextjs": "next", "next.js": "next", "postgres": "postgresql",
    "ts": "typescript", "js": "javascript", "rest api": "rest",
    ".net": "dotnet", "golang": "go",
}


def normalize_skill(skill: str) -> str:
    """Normalize an extracted skill token, not arbitrary description substrings."""
    key = re.sub(r"\s+", " ", skill.strip().lower())
    return ALIASES.get(key, key)


@dataclass(frozen=True)
class Requirement:
    """One requirement; alternatives mean OR, separate requirements mean AND.

    Phase 3 adds `type`: only "technology" requirements count towards
    coverage. Practices ("agile", "scrum") and soft skills are recorded as
    evidence but never create a coverage gap and never trigger the
    essential-gap rejection — a missing "git" is not a reason to reject a
    suitable job.
    """
    alternatives: frozenset[str]
    evidence: str
    weight: float = 1.0
    essential: bool = False
    type: Literal["technology", "practice", "soft"] = "technology"

    def __post_init__(self):
        if type(self.essential) is not bool:
            raise ValueError("essential must be boolean")
        if self.type not in {"technology", "practice", "soft"}:
            raise ValueError("type must be technology, practice or soft")
        normalized = frozenset(normalize_skill(s) for s in self.alternatives)
        if not normalized or "" in normalized or not self.evidence.strip():
            raise ValueError("Requirements need nonempty alternatives and supporting evidence")
        if not math.isfinite(self.weight) or not 0 < self.weight <= 1_000_000:
            raise ValueError("Requirement weight must be finite and in (0, 1000000]")
        object.__setattr__(self, "alternatives", normalized)


@dataclass(frozen=True)
class MatchProfile:
    policy: CandidatePolicy
    skills: frozenset[str]
    version: str
    learnable_skills: frozenset[str] = frozenset()

    def __post_init__(self):
        if not self.version.strip():
            raise ValueError("A profile version is required")
        object.__setattr__(self, "learnable_skills", frozenset(normalize_skill(s) for s in self.learnable_skills))
        object.__setattr__(self, "skills", frozenset(normalize_skill(s) for s in self.skills if s.strip()))


@dataclass(frozen=True)
class RequirementsEvidence:
    # None: not extracted. Empty: extraction found no explicit requirements.
    required: tuple[Requirement, ...] | None = None
    preferred: tuple[Requirement, ...] = ()
    complete: bool = False
    extractor_version: str = "manual-v1"

    def __post_init__(self):
        if type(self.complete) is not bool or not self.extractor_version.strip():
            raise ValueError("Extraction needs boolean completeness and a version")


@dataclass(frozen=True)
class Coverage:
    score: float | None
    matched_weight: float
    total_weight: float
    hits: tuple[Requirement, ...]
    gaps: tuple[Requirement, ...]


def requirement_coverage(requirements: tuple[Requirement, ...] | None,
                         skills: frozenset[str]) -> Coverage:
    """Technology coverage only.

    Practices and soft skills are evidence, not fit: they are excluded from
    the totals, so they can neither inflate the score nor create a gap that
    would push a job into review/rejection.
    """
    normalized_skills = frozenset(normalize_skill(s) for s in skills)
    if not requirements:
        return Coverage(None, 0, 0, (), ())
    technology = tuple(r for r in requirements if r.type == "technology")
    if not technology:
        return Coverage(None, 0, 0, (), ())
    # Duplicate extracted groups cannot inflate coverage; retain the first
    # evidence/weight deterministically. Extractors must resolve disagreements.
    unique = {}
    for r in technology:
        previous = unique.get(r.alternatives)
        if previous is None or (r.essential and not previous.essential):
            unique[r.alternatives] = r
    hits, gaps = [], []
    for requirement in unique.values():
        (hits if requirement.alternatives & normalized_skills else gaps).append(requirement)
    total = sum(r.weight for r in unique.values())
    matched = sum(r.weight for r in hits)
    return Coverage(round(100 * (matched / total), 2), matched, total, tuple(hits), tuple(gaps))


@dataclass(frozen=True)
class MatchResult:
    decision: Decision
    eligibility: EligibilityResult
    required: Coverage
    preferred: Coverage
    evidence_completeness: dict[str, bool]
    profile_version: str
    extractor_version: str
    scorer_version: str = SCORER_VERSION
    review_reasons: tuple[str, ...] = field(default_factory=tuple)


def score_match(job: JobEvidence, profile: MatchProfile,
                requirements: RequirementsEvidence) -> MatchResult:
    eligibility = evaluate_eligibility(job, profile.policy)
    # Rejected jobs do not receive a misleading fit number.
    rejected = eligibility.decision == "rejected"
    required = requirement_coverage(None if rejected else requirements.required, profile.skills)
    preferred = requirement_coverage(None if rejected else requirements.preferred, profile.skills)
    completeness = {g.name: g.outcome != "unknown" for g in eligibility.gates}
    completeness["requirements"] = bool(requirements.required) and requirements.complete
    reasons = [g.reason for g in eligibility.gates if g.outcome == "unknown"]
    if not completeness["requirements"]:
        reasons.append("requirements_unverified")
    essential_gaps = tuple(r for r in required.gaps if r.essential)
    if essential_gaps and requirements.complete:
        rejected = True
    elif not rejected and required.gaps:
        # Any required gap (learnable or not) prevents eligible/likely_fit.
        # Learnable gaps are a separate signal; non-learnable are harder.
        learnable_gap_count = sum(1 for r in required.gaps
                                  if r.alternatives & profile.learnable_skills)
        non_learnable_gap_count = len(required.gaps) - learnable_gap_count
        if non_learnable_gap_count:
            reasons.append("required_skill_gaps")
        else:
            reasons.append("partial_required_coverage")
    if essential_gaps:
        reasons.append("essential_skill_mismatch" if requirements.complete else "essential_requirements_unverified")
    if not rejected and required.score == 0:
        reasons.append("no_required_skill_overlap")

    # LIKELY_FIT: eligibility says likely_fit AND requirements pass
    # (all essential met, coverage > 0, no required gaps). Never eligible/auto-eligible.
    if eligibility.decision == "likely_fit":
        reqs_pass = (requirements.required is not None
                     and required.score is not None
                     and required.score > 0
                     and not essential_gaps
                     and not required.gaps)
        if reqs_pass:
            decision: Decision = "likely_fit"
        else:
            decision = "review"
    else:
        decision = ("rejected" if rejected else "review" if reasons else "eligible")

    return MatchResult(decision, eligibility, required, preferred, completeness,
                       profile.version, requirements.extractor_version,
                       review_reasons=tuple(reasons))


def shortlist(results: list[MatchResult], limit: int) -> list[MatchResult]:
    """Up to N eligible results; never fill a quota from review/rejected jobs.

    Return original objects so callers can associate results with their jobs.
    Stable ordering preserves upstream order on ties. Preferred skills only
    break ties and never compensate for missing required skills.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")
    eligible = [r for r in results if r.decision == "eligible" and r.required.score is not None]
    return sorted(eligible, key=lambda r: (r.required.score, r.preferred.score or 0), reverse=True)[:limit]
