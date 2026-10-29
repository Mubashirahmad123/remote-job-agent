"""Deterministic eligibility policy; no network, storage, or implicit user defaults.

This is a shadow-evaluation foundation, not a replacement for the live curator.
Unknown evidence never becomes a confirmed rejection or a numeric zero-fit score.
"""
from dataclasses import dataclass
import re
from typing import Literal

Outcome = Literal["pass", "fail", "unknown"]
POLICY_VERSION = "eligibility-v2"


@dataclass(frozen=True)
class CandidatePolicy:
    """Work locations are confirmed residence/work permissions, NOT company preferences.

    Empty policy fields deliberately leave the corresponding gate unknown.
    Locations and seniority must use the same canonical identifiers as evidence.
    """
    role_families: frozenset[str] = frozenset()
    work_locations: frozenset[str] = frozenset()
    seniority_levels: frozenset[str] = frozenset()
    relocation_destinations: frozenset[str] = frozenset()
    sponsorship_required: bool = True

    def __post_init__(self):
        if type(self.sponsorship_required) is not bool:
            raise ValueError("sponsorship_required must be boolean")


@dataclass(frozen=True)
class JobEvidence:
    title: str
    description: str | None = None
    role_family: str | None = None
    # None means unverified; an empty set is not a worldwide permission.
    allowed_work_locations: frozenset[str] | None = None
    worldwide: bool = False
    seniority: str | None = None
    work_mode: Literal["remote", "onsite", "hybrid", "unknown"] = "remote"
    job_country: str | None = None
    visa_sponsorship: bool | None = None

    def __post_init__(self):
        if self.work_mode not in {"remote", "onsite", "hybrid", "unknown"}:
            raise ValueError("Invalid work mode")
        if type(self.worldwide) is not bool or (self.visa_sponsorship is not None and type(self.visa_sponsorship) is not bool):
            raise ValueError("Location permissions must be boolean or unknown")


@dataclass(frozen=True)
class GateResult:
    name: str
    outcome: Outcome
    reason: str
    evidence: str | None = None


@dataclass(frozen=True)
class EligibilityResult:
    decision: Literal["eligible", "review", "rejected"]
    gates: tuple[GateResult, ...]
    needs_description: bool
    policy_version: str = POLICY_VERSION


def _contains(text: str, pattern: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", text, re.I))


def infer_title_family(title: str) -> str | None:
    """Conservative title hints; generic engineering titles remain unresolved."""
    if _contains(title, r"hardware|robotics|embedded|sales engineer|solutions engineer|support engineer"):
        return "non_target"
    if _contains(title, r"full[ -]?stack"):
        return "fullstack"
    if _contains(title, r"back[ -]?end|node(?:\.js|js)?|python"):
        return "backend"
    if _contains(title, r"front[ -]?end|react(?:\.js|js)?|next(?:\.js|js)"):
        return "frontend"
    return None


def evaluate_eligibility(job: JobEvidence, policy: CandidatePolicy) -> EligibilityResult:
    """Evaluate explicit facts only. Extraction and fetching belong upstream.

    `worldwide` must represent verified worker eligibility, never an inference
    from the word 'remote'. No score is calculated until evidence is sufficient.
    """
    gates = []
    family = job.role_family or infer_title_family(job.title)
    if not policy.role_families or family is None:
        gates.append(GateResult("role", "unknown", "role_policy_or_evidence_missing", job.title))
    else:
        gates.append(GateResult("role", "pass" if family in policy.role_families else "fail",
                                "role_allowed" if family in policy.role_families else "role_not_allowed", family))

    if job.work_mode == "unknown":
        gates.append(GateResult("location", "unknown", "work_mode_unverified"))
    elif job.work_mode in {"onsite", "hybrid"}:
        if not job.job_country:
            gates.append(GateResult("location", "unknown", "job_country_missing"))
        elif job.job_country in policy.work_locations:
            gates.append(GateResult("location", "pass", "existing_work_rights" , job.job_country))
        elif job.job_country not in policy.relocation_destinations:
            gates.append(GateResult("location", "fail", "relocation_destination_not_allowed", job.job_country))
        elif policy.sponsorship_required and job.visa_sponsorship is None:
            gates.append(GateResult("location", "unknown", "sponsorship_unverified", job.job_country))
        elif policy.sponsorship_required and not job.visa_sponsorship:
            gates.append(GateResult("location", "fail", "sponsorship_unavailable", job.job_country))
        else:
            gates.append(GateResult("location", "pass", "relocation_conditions_met", job.job_country))
    elif not policy.work_locations:
        gates.append(GateResult("location", "unknown", "candidate_work_locations_missing"))
    elif job.worldwide and job.allowed_work_locations:
        gates.append(GateResult("location", "unknown", "location_evidence_conflict"))
    elif job.worldwide:
        gates.append(GateResult("location", "pass", "verified_worldwide"))
    elif not job.allowed_work_locations:
        gates.append(GateResult("location", "unknown", "worker_location_restriction_unverified"))
    else:
        permitted = bool(policy.work_locations & job.allowed_work_locations)
        gates.append(GateResult("location", "pass" if permitted else "fail",
                                "work_location_allowed" if permitted else "work_location_not_allowed",
                                ", ".join(sorted(job.allowed_work_locations))))

    if not policy.seniority_levels or not job.seniority:
        gates.append(GateResult("seniority", "unknown", "seniority_policy_or_evidence_missing"))
    else:
        permitted = job.seniority in policy.seniority_levels
        gates.append(GateResult("seniority", "pass" if permitted else "fail",
                                "seniority_allowed" if permitted else "seniority_not_allowed", job.seniority))

    missing = not (job.description and job.description.strip())
    gates.append(GateResult("description", "unknown" if missing else "pass",
                            "description_missing" if missing else "description_present"))
    outcomes = {gate.outcome for gate in gates}
    decision = "rejected" if "fail" in outcomes else "review" if "unknown" in outcomes else "eligible"
    return EligibilityResult(decision, tuple(gates), missing and decision != "rejected")
