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

from tools.matching_extract import FAMILY_PATTERNS, FAMILY_RES

Outcome = Literal["pass", "fail", "unknown", "not_stated"]
Decision = Literal["eligible", "likely_fit", "review", "rejected"]
POLICY_VERSION = "eligibility-v5"

# Labels that are structurally out of reach for a junior/mid profile.
# "senior" is deliberately NOT here (ADR-0004): a senior posting without a
# stated year range is a REVIEW, not a rejection. Only an explicit year
# range whose gap exceeds seniority_gap_threshold can fail a senior role.
HARD_SENIORITY_MISMATCH = frozenset({
    "principal", "staff", "lead", "director", "executive",
})

# Labels that are NOT seniority levels and should never cause a seniority
# fail — they stay UNKNOWN/review.
SENIORITY_NOT_A_LEVEL = frozenset({
    "intern", "assistant", "coordinator", "founding",
})

# Responsibility hints that make a role REVIEW even when the title family
# matches the policy: the actual job may not be the one the family implies.
ROLE_REVIEW_HINTS = frozenset({
    "architect", "forward_deployed", "devrel", "support", "research",
    "data_infra", "hardware_eda", "consultant",
})

# Generic software titles that map to the "software" family (defaults to
# backend-compatible). These pass the role gate unless a review hint exists.
GENERIC_SOFTWARE_TITLES = frozenset({
    "software developer", "software engineer", "programmer",
    "web developer", "software developer engineer",
})


@dataclass(frozen=True)
class CandidatePolicy:
    """Work locations are confirmed residence/work permissions, NOT company preferences.

    Empty policy fields deliberately leave the corresponding gate unknown.
    Locations and seniority must use the same canonical identifiers as evidence.

    Phase 4 separates the candidate's own facts:
    - work_locations: where the candidate may work onsite/hybrid today
      (a confirmed work right, e.g. the country they live in).
    - remote_work_locations: where the candidate accepts to sit while a
      job is remote (their remote base, e.g. the country they live in).
    - work_cities: the candidate's own city — an onsite/hybrid job in
      another city is a RELOCATION, not "existing work rights".
    - relocation_destinations: where the candidate would relocate to.
    - years_experience: the candidate's years of experience, compared with
      year ranges stated in postings ("0 to 4 yrs", "5+ years").
    - seniority_gap_threshold: years gap between candidate and requirement
      that still yields REVIEW (<= threshold) vs FAIL (> threshold).
    - accept_unrestricted_remote: operator-approved handling of a remote
      posting that names NO worker restriction. Off by default: an absent
      fact is UNKNOWN, never a pass.
    """

    role_families: frozenset[str] = frozenset()
    work_locations: frozenset[str] = frozenset()
    seniority_levels: frozenset[str] = frozenset()
    relocation_destinations: frozenset[str] = frozenset()
    sponsorship_required: bool = True
    remote_work_locations: frozenset[str] = frozenset()
    work_cities: frozenset[str] = frozenset()
    years_experience: float | None = None
    seniority_gap_threshold: int = 2
    accept_unrestricted_remote: bool = False

    def __post_init__(self):
        if type(self.sponsorship_required) is not bool:
            raise ValueError("sponsorship_required must be boolean")
        if type(self.accept_unrestricted_remote) is not bool:
            raise ValueError("accept_unrestricted_remote must be boolean")
        if type(self.seniority_gap_threshold) is not int or self.seniority_gap_threshold < 0:
            raise ValueError("seniority_gap_threshold must be a nonnegative int")
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
    work_mode: Literal["remote", "onsite", "hybrid", "flexible", "unknown"] = "remote"
    job_country: str | None = None
    job_city: str | None = None
    visa_sponsorship: bool | None = None
    # Phase 3/4 additions — optional, evidence-backed when set.
    years_min: int | None = None
    years_max: int | None = None
    responsibilities: frozenset[str] = frozenset()
    # Responsibility hints found in the TITLE (e.g. architect, devrel).
    role_hints: frozenset[str] = frozenset()
    # True when the searched text was complete, so "no worker restriction
    # was mentioned" is a fact about the posting rather than a truncation.
    location_text_complete: bool = False
    # True when no seniority evidence exists at all (distinct from unknown
    # which means evidence exists but is unverifiable/conflicting).
    seniority_not_stated: bool = False
    # Quote and span for seniority evidence, used for fail messages.
    seniority_quote: str = ""
    seniority_span: tuple[int, int] | None = None

    def __post_init__(self):
        if self.work_mode not in {"remote", "onsite", "hybrid", "flexible", "unknown"}:
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
        if type(self.seniority_not_stated) is not bool:
            raise ValueError("seniority_not_stated must be boolean")
        if self.seniority_quote is not None and not isinstance(self.seniority_quote, str):
            raise ValueError("seniority_quote must be a string or None")
        if self.seniority_span is not None and not isinstance(self.seniority_span, (tuple, list)):
            raise ValueError("seniority_span must be a tuple/list or None")


@dataclass(frozen=True)
class GateResult:
    name: str
    outcome: Outcome
    reason: str
    evidence: str | None = None


@dataclass(frozen=True)
class EligibilityResult:
    decision: Decision
    gates: tuple[GateResult, ...]
    needs_description: bool
    policy_version: str = POLICY_VERSION


def _contains(text: str, pattern: str) -> bool:
    return bool(re.search(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", text, re.I))


def infer_title_family(title: str) -> str | None:
    """Conservative title hints using shared FAMILY_PATTERNS (one source of truth).

    Families from FAMILY_PATTERNS (fullstack, backend, frontend, software) are
    matched first — this includes tech-stack aliases (React → frontend, Node →
    backend, Go/DevOps → software). GENERIC_SOFTWARE_TITLES are NOT used here;
    they apply only when the extractor has already determined a family from
    the description. Explicit non-target titles (assistant, coordinator, hardware,
    robotics, sales, support engineer, etc.) map to "non_target" which fails
    the role gate.
    """
    if not title:
        return None

    # 1. FAMILY_PATTERNS (shared with extractor): fullstack, backend, frontend, software
    for name, pattern in FAMILY_RES:
        if pattern.search(title):
            return name

    # 2. Explicit non-target titles
    if _contains(title, r"assistant|coordinator|account executive|sales|marketing|recruiter|customer success|office|operations specialist"):
        return "non_target"
    if _contains(title, r"hardware|robotics|embedded|sales engineer|solutions engineer|support engineer"):
        return "non_target"

    return None


def _role_gate(job: JobEvidence, policy: CandidatePolicy) -> GateResult:
    """Role gate with a hint-aware middle step.

    Explicit non-target titles (hardware, robotics, support, sales) FAIL.
    A title that matches a wanted family but carries a conflicting
    responsibility hint (architect, devrel, forward-deployed, ...) is
    REVIEW, not a silent pass: the family alone does not prove the job.
    Generic software titles pass unless a review hint exists.
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
    """Location gate with Phase 4 ordering:

    0. Unconfigured profile (empty remote_bases) -> REVIEW.
    1. Conflict: worldwide AND explicit permission list -> REVIEW.
    2. For NON-flexible modes: explicit worker-permission list present,
       not worldwide, no overlap with remote bases -> FAIL.
    3. Verified worldwide -> PASS for remote/flexible.
    4. Work-mode logic:
       - onsite/hybrid abroad -> FAIL; in India -> PASS.
       - "flexible": remote part by (2)/(3), hybrid part by location.
         PASS if EITHER option works.
    5. Bare "Remote" with no permission wording -> REVIEW.
    """
    # 0. Unconfigured profile never grants permission.
    if not policy.remote_bases:
        return GateResult("location", "unknown", "candidate_work_locations_missing")

    # 1. Conflict: worldwide AND explicit permission list -> REVIEW
    if job.worldwide and job.allowed_work_locations:
        return GateResult("location", "unknown", "location_evidence_conflict")

    # 3. Verified worldwide -> PASS for remote/flexible
    if job.worldwide and job.work_mode in {"remote", "flexible"}:
        return GateResult("location", "pass", "verified_worldwide")

    # 4. Work-mode logic
    if job.work_mode == "unknown":
        return GateResult("location", "unknown", "work_mode_unverified")

    if job.work_mode in {"onsite", "hybrid"}:
        if not job.job_country:
            return GateResult("location", "unknown", "job_country_missing")
        known_here = job.job_country in policy.work_locations
        if known_here:
            if policy.work_cities and job.job_city:
                if job.job_city in policy.work_cities:
                    return GateResult("location", "pass", "existing_work_rights",
                                      job.job_country)
                if job.job_country not in policy.relocation_destinations:
                    return GateResult("location", "fail",
                                      "relocation_destination_not_allowed",
                                      job.job_country)
            return GateResult("location", "pass", "existing_work_rights",
                              job.job_country)
        elif job.job_country not in policy.relocation_destinations:
            return GateResult("location", "fail",
                              "relocation_destination_not_allowed",
                              job.job_country)
        if policy.sponsorship_required and job.visa_sponsorship is None:
            return GateResult("location", "unknown", "sponsorship_unverified",
                              job.job_country)
        if policy.sponsorship_required and not job.visa_sponsorship:
            return GateResult("location", "fail", "sponsorship_unavailable",
                              job.job_country)
        return GateResult("location", "pass", "relocation_conditions_met",
                          job.job_country)

    if job.work_mode == "flexible":
        # Flexible: try remote part first, then hybrid part. PASS if either works.
        remote_ok = False
        hybrid_ok = False

        # Remote part: check worker-permission list
        if job.allowed_work_locations and not job.worldwide:
            if bool(policy.remote_bases & job.allowed_work_locations):
                remote_ok = True
        # If no explicit permission list and worldwide is False, remote part fails
        # (no permission to work remotely from candidate's bases)

        # Hybrid part: check physical location
        if job.job_country:
            if job.job_country in policy.work_locations:
                hybrid_ok = True
            elif job.job_country in policy.relocation_destinations:
                # Relocation allowed (sponsorship checked below)
                if not policy.sponsorship_required or job.visa_sponsorship:
                    hybrid_ok = True
                elif job.visa_sponsorship is None:
                    # Sponsorship unknown -> hybrid part is UNKNOWN, not FAIL
                    pass
                else:
                    # Sponsorship explicitly unavailable
                    pass

        if remote_ok or hybrid_ok:
            if remote_ok and hybrid_ok:
                return GateResult("location", "pass", "work_location_allowed",
                                  ", ".join(sorted(job.allowed_work_locations or set())))
            if remote_ok:
                return GateResult("location", "pass", "work_location_allowed",
                                  ", ".join(sorted(job.allowed_work_locations or set())))
            if hybrid_ok:
                if job.job_city and job.job_city in policy.work_cities:
                    return GateResult("location", "pass", "existing_work_rights",
                                      job.job_country)
                return GateResult("location", "pass", "existing_work_rights",
                                  job.job_country)

        # Both remote and hybrid failed
        if job.job_country and job.job_country not in policy.relocation_destinations:
            return GateResult("location", "fail",
                              "relocation_destination_not_allowed",
                              job.job_country)
        if job.allowed_work_locations and not job.worldwide:
            return GateResult(
                "location", "fail", "work_location_not_allowed",
                ", ".join(sorted(job.allowed_work_locations)))
        return GateResult("location", "unknown",
                          "flexible_location_undetermined")

    # work_mode == "remote" at this point
    # Explicit worker-permission list present (not worldwide)
    if job.allowed_work_locations and not job.worldwide:
        permitted = bool(policy.remote_bases & job.allowed_work_locations)
        if not permitted:
            return GateResult(
                "location", "fail", "work_location_not_allowed",
                ", ".join(sorted(job.allowed_work_locations)))
        return GateResult("location", "pass", "work_location_allowed",
                          ", ".join(sorted(job.allowed_work_locations)))

    # 5. Bare "Remote" with no permission wording -> REVIEW
    if (policy.accept_unrestricted_remote and job.location_text_complete
            and job.description and job.description.strip()):
        return GateResult("location", "pass", "verified_unrestricted_remote")
    return GateResult("location", "unknown", "worker_location_restriction_unverified")





def _seniority_gate(job: JobEvidence, policy: CandidatePolicy) -> GateResult:
    """Seniority gate, years-aware with configurable gap threshold.

    An explicit year range is compared with the candidate's years first:
    gap <= threshold -> REVIEW, gap > threshold -> FAIL.
    A label is used only when no year range is stated.

    A stated year range is the ONLY seniority fact that can fail a role
    outright. Labels split three ways (ADR-0004):
    - `principal`/`staff`/`lead`/`director`/`executive`: FAIL, they name a
      structural level a junior/mid profile does not reach;
    - `senior`: REVIEW, because the posting gave no requirement to measure;
    - `intern`/`assistant`/`coordinator`/`founding`: not levels at all.

    No seniority evidence at all -> "not_stated" (distinct from "unknown").
    """
    if not policy.seniority_levels:
        return GateResult("seniority", "unknown", "seniority_policy_or_evidence_missing")

    # Explicit year range comparison
    if job.years_min is not None and policy.years_experience is not None:
        gap = policy.years_experience - job.years_min
        if gap < 0:
            # Candidate has fewer years than minimum
            abs_gap = abs(gap)
            if abs_gap <= policy.seniority_gap_threshold:
                return GateResult("seniority", "unknown",
                                  "candidate_experience_below_range",
                                  f"requires {job.years_min}+ years, gap {abs_gap}")
            return GateResult("seniority", "fail",
                              "candidate_experience_below_requirement",
                              f"requires {job.years_min}+ years, gap {abs_gap}")
        if job.years_max is not None and policy.years_experience > job.years_max:
            return GateResult("seniority", "unknown",
                              "candidate_experience_above_range",
                              f"up to {job.years_max} years")
        return GateResult("seniority", "pass", "years_experience_within_range",
                          f"{job.years_min}-{job.years_max if job.years_max is not None else '+'} years")

    # No year range — check for explicit label
    if job.seniority:
        # Labels that are NOT seniority levels — stay unknown, not fail
        if job.seniority in SENIORITY_NOT_A_LEVEL:
            return GateResult("seniority", "unknown",
                              "seniority_not_a_level", job.seniority_quote)
        # Explicit seniority labels that are structurally out of reach
        if job.seniority in HARD_SENIORITY_MISMATCH:
            return GateResult("seniority", "fail", "seniority_not_allowed",
                              job.seniority_quote)
        if job.seniority in policy.seniority_levels:
            return GateResult("seniority", "pass", "seniority_allowed",
                              job.seniority_quote)
        return GateResult("seniority", "unknown",
                          "seniority_label_requires_review",
                          job.seniority_quote)

    # No seniority evidence at all -> not_stated (not unknown)
    if job.seniority_not_stated:
        return GateResult("seniority", "not_stated",
                          "seniority_not_stated")

    return GateResult("seniority", "unknown", "seniority_policy_or_evidence_missing")


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

    # LIKELY_FIT: location, role, description all PASS, seniority is not_stated.
    # Never eligible (auto-eligible), never TOP MATCHES.
    if ("pass" in outcomes and "fail" not in outcomes
            and "not_stated" in outcomes
            and "unknown" not in outcomes):
        return EligibilityResult("likely_fit", tuple(gates),
                                 missing and False,  # needs_description=False since description passed
                                 POLICY_VERSION)

    decision: Decision = ("rejected" if "fail" in outcomes
                          else "review" if "unknown" in outcomes
                          else "eligible")
    return EligibilityResult(decision, tuple(gates), missing and decision != "rejected",
                             POLICY_VERSION)
