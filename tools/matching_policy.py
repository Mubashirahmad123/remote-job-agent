"""Deterministic eligibility policy; no network, storage, or implicit user defaults.

This is a shadow-evaluation foundation, not a replacement for the live curator.
Unknown evidence never becomes a confirmed rejection or a numeric zero-fit score.

Phase 3 (2026-10-31) keeps FOUR location facts apart. They are not
interchangeable and one never implies another:
1. employer/company HQ — not an eligibility fact at all (never read here),
2. the job's physical location (job_country + job_city) — matters for
   onsite/hybrid work and for relocation,
3. the worker locations the employer permits (allowed_work_locations) — the
   only thing that decides whether a REMOTE job can be taken from India,
4. the work mode ("remote") — says nothing about where the worker may sit.

Policy inputs are operator-owned (data/matching_profile.json); the gates
below never invent an answer the operator did not give.
"""
from dataclasses import dataclass
import re
from typing import Literal

Outcome = Literal["pass", "fail", "unknown"]
POLICY_VERSION = "eligibility-v3"

# Labels that are structurally out of reach for a junior/mid profile.
# "senior" is deliberately NOT here: a senior posting without a stated
# year range is a REVIEW, not a rejection (the candidate may still be
# considered; a wrong rejection is the worst outcome).
HARD_SENIORITY_MISMATCH = frozenset({
    "intern", "principal", "staff", "lead", "director", "executive",
})

# Responsibility hints that make a role REVIEW even when the title family
# matches the policy: the actual job may not be the one the family implies.
ROLE_REVIEW_HINTS = frozenset({
    "architect", "forward_deployed", "devrel", "support", "research",
    "hardware_eda", "consultant",
})


@dataclass(frozen=True)
class CandidatePolicy:
    """Work locations are confirmed residence/work permissions, NOT company preferences.

    Empty policy fields deliberately leave the corresponding gate unknown.
    Locations and seniority must use the same canonical identifiers as evidence.

    Phase 3 separates the candidate's own facts:
    - work_locations: where the candidate may work onsite/hybrid today
      (a confirmed work right, e.g. the country they live in).
    - remote_work_locations: where the candidate accepts to sit while a
      job is remote (their remote base, e.g. the country they live in).
    - work_cities: the candidate's own city — an onsite/hybrid job in
      another city is a RELOCATION, not "existing work rights".
    - relocation_destinations: where the candidate would relocate to.
    - years_experience: the candidate's years of experience, compared with
      year ranges stated in postings ("0 to 4 yrs", "5+ years").
    - accept_unrestricted_remote: operator-approved handling of a remote
      posting that names NO worker restriction (verified remote wording,
      complete text, no region token). Off by default: an absent fact is
      normally UNKNOWN, never a pass.
    """

    role_families: frozenset[str] = frozenset()
    work_locations: frozenset[str] = frozenset()
    seniority_levels: frozenset[str] = frozenset()
    relocation_destinations: frozenset[str] = frozenset()
    sponsorship_required: bool = True
    remote_work_locations: frozenset[str] = frozenset()
    work_cities: frozenset[str] = frozenset()
    years_experience: float | None = None
    accept_unrestricted_remote: bool = False

    def __post_init__(self):
        if type(self.sponsorship_required) is not bool:
            raise ValueError("sponsorship_required must be boolean")
        if type(self.accept_unrestricted_remote) is not bool:
            raise ValueError("accept_unrestricted_remote must be boolean")
        for name in ("role_families", "work_locations", "seniority_levels",
                     "relocation_destinations", "remote_work_locations",
                     "work_cities"):
            value = getattr(self, name)
            if not isinstance(value, frozenset) or any(
                    not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f"{name} must be a frozenset of nonempty strings")
        if self.years_experience is not None:
            if isinstance(self.years_experience, bool) or not isinstance(
                    self.years_experience, (int, float)):
                raise ValueError("years_experience must be a number or None")
            if self.years_experience < 0:
                raise ValueError("years_experience must not be negative")

    @property
    def remote_bases(self) -> frozenset[str]:
        """Where the candidate accepts remote work; falls back to the
        confirmed work locations when the profile does not say."""
        return self.remote_work_locations or self.work_locations


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
    # Phase 3 additions — optional, evidence-backed when set.
    job_city: str | None = None
    years_min: int | None = None
    years_max: int | None = None
    responsibilities: frozenset[str] = frozenset()
    # Responsibility hints found in the TITLE (e.g. architect, devrel).
    role_hints: frozenset[str] = frozenset()
    # True when the searched text was complete, so "no worker restriction
    # was mentioned" is a fact about the posting rather than a truncation.
    location_text_complete: bool = False

    def __post_init__(self):
        if self.work_mode not in {"remote", "onsite", "hybrid", "unknown"}:
            raise ValueError("Invalid work mode")
        if type(self.worldwide) is not bool or (self.visa_sponsorship is not None and type(self.visa_sponsorship) is not bool):
            raise ValueError("Location permissions must be boolean or unknown")
        for name in ("responsibilities", "role_hints"):
            value = getattr(self, name)
            if not isinstance(value, frozenset) or any(
                    not isinstance(item, str) or not item.strip()
                    for item in value):
                raise ValueError(f"{name} must be a frozenset of strings")
        for name in ("years_min", "years_max"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool)
                                      or not isinstance(value, (int, float))):
                raise ValueError(f"{name} must be a number or None")
        if (self.years_min is not None and self.years_max is not None
                and self.years_min > self.years_max):
            raise ValueError("years_min must not exceed years_max")
        if type(self.location_text_complete) is not bool:
            raise ValueError("location_text_complete must be boolean")


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


def _role_gate(job: JobEvidence, policy: CandidatePolicy) -> GateResult:
    """Role gate with a hint-aware middle step.

    Explicit non-target titles (hardware, robotics, support, sales) FAIL.
    A title that matches a wanted family but carries a conflicting
    responsibility hint (architect, devrel, forward-deployed, ...) is
    REVIEW, not a silent pass: the family alone does not prove the job.
    """
    family = job.role_family or infer_title_family(job.title)
    if not policy.role_families or family is None:
        return GateResult("role", "unknown", "role_policy_or_evidence_missing", job.title)
    if family == "non_target":
        return GateResult("role", "fail", "role_not_allowed", job.title)
    if family not in policy.role_families:
        return GateResult("role", "fail", "role_not_allowed", family)
    hints = job.role_hints & ROLE_REVIEW_HINTS
    if hints:
        return GateResult("role", "unknown", "role_hint_requires_review",
                          ", ".join(sorted(hints)))
    return GateResult("role", "pass", "role_allowed", family)


def _location_gate(job: JobEvidence, policy: CandidatePolicy) -> GateResult:
    """Location gate: country, city, worker permission and work mode are
    four separate facts and are checked separately."""
    if job.work_mode == "unknown":
        return GateResult("location", "unknown", "work_mode_unverified")

    if job.work_mode in {"onsite", "hybrid"}:
        if not job.job_country:
            return GateResult("location", "unknown", "job_country_missing")
        known_here = job.job_country in policy.work_locations
        if known_here and policy.work_cities and job.job_city:
            # Same country, different city: that is a relocation, not an
            # existing work right.
            if job.job_city in policy.work_cities:
                return GateResult("location", "pass", "existing_work_rights",
                                  job.job_country)
            if job.job_country not in policy.relocation_destinations:
                return GateResult("location", "fail",
                                  "relocation_destination_not_allowed", job.job_country)
        elif known_here:
            return GateResult("location", "pass", "existing_work_rights",
                              job.job_country)
        elif job.job_country not in policy.relocation_destinations:
            return GateResult("location", "fail",
                              "relocation_destination_not_allowed", job.job_country)
        if policy.sponsorship_required and job.visa_sponsorship is None:
            return GateResult("location", "unknown", "sponsorship_unverified",
                              job.job_country)
        if policy.sponsorship_required and not job.visa_sponsorship:
            return GateResult("location", "fail", "sponsorship_unavailable",
                              job.job_country)
        return GateResult("location", "pass", "relocation_conditions_met",
                          job.job_country)

    # Remote work: the employer's worker-permission list is the only
    # deciding fact. Company HQ and the job's own city are irrelevant here.
    if not policy.remote_bases:
        # An unconfigured profile never grants permission (it is not an
        # implicit "yes").
        return GateResult("location", "unknown", "candidate_work_locations_missing")
    if job.worldwide and job.allowed_work_locations:
        return GateResult("location", "unknown", "location_evidence_conflict")
    if job.worldwide:
        return GateResult("location", "pass", "verified_worldwide")
    if job.allowed_work_locations:
        permitted = bool(policy.remote_bases & job.allowed_work_locations)
        return GateResult(
            "location", "pass" if permitted else "fail",
            "work_location_allowed" if permitted else "work_location_not_allowed",
            ", ".join(sorted(job.allowed_work_locations)))
    if (policy.accept_unrestricted_remote and job.location_text_complete
            and job.description and job.description.strip()):
        # Operator-approved: a complete remote posting that names no
        # worker restriction is treated as hiring from anywhere.
        return GateResult("location", "pass", "verified_unrestricted_remote")
    return GateResult("location", "unknown", "worker_location_restriction_unverified")


def _seniority_gate(job: JobEvidence, policy: CandidatePolicy) -> GateResult:
    """Seniority gate, years-aware.

    An explicit year range is compared with the candidate's years first:
    too few years FAILs, too many years is REVIEW (over-qualified is not a
    rejection). A label is used only when no year range is stated.
    """
    if not policy.seniority_levels:
        return GateResult("seniority", "unknown", "seniority_policy_or_evidence_missing")
    if job.years_min is not None and policy.years_experience is not None:
        if policy.years_experience < job.years_min:
            return GateResult("seniority", "fail", "candidate_experience_below_requirement",
                              f"requires {job.years_min}+ years")
        if job.years_max is not None and policy.years_experience > job.years_max:
            return GateResult("seniority", "unknown", "candidate_experience_above_range",
                              f"up to {job.years_max} years")
        return GateResult("seniority", "pass", "years_experience_within_range",
                          f"{job.years_min}-{job.years_max if job.years_max is not None else '+'} years")
    if not job.seniority:
        return GateResult("seniority", "unknown", "seniority_policy_or_evidence_missing")
    if job.seniority in policy.seniority_levels:
        return GateResult("seniority", "pass", "seniority_allowed", job.seniority)
    if job.seniority in HARD_SENIORITY_MISMATCH:
        return GateResult("seniority", "fail", "seniority_not_allowed", job.seniority)
    return GateResult("seniority", "unknown", "seniority_label_requires_review",
                      job.seniority)


def evaluate_eligibility(job: JobEvidence, policy: CandidatePolicy) -> EligibilityResult:
    """Evaluate explicit facts only. Extraction and fetching belong upstream.

    `worldwide` must represent verified worker eligibility, never an inference
    from the word 'remote'. No score is calculated until evidence is sufficient.
    """
    gates = [_role_gate(job, policy),
             _location_gate(job, policy),
             _seniority_gate(job, policy)]

    missing = not (job.description and job.description.strip())
    gates.append(GateResult("description", "unknown" if missing else "pass",
                            "description_missing" if missing else "description_present"))
    outcomes = {gate.outcome for gate in gates}
    decision = "rejected" if "fail" in outcomes else "review" if "unknown" in outcomes else "eligible"
    return EligibilityResult(decision, tuple(gates), missing and decision != "rejected")
