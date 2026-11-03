"""D8 / D9 regressions: seniority evidence must be a fact about the role.

D8: every label used to be compiled as ``\\b(?:intern)`` with no trailing
boundary, so "internal" produced an ``intern`` label on 89 of 312 live jobs and
"you will lead code reviews" produced a ``lead`` label — enough to hard-reject a
plain "Software Engineer". D9: ``senior`` sat in ``HARD_SENIORITY_MISMATCH``
directly under a comment saying it was deliberately not there.
"""
import pytest

from tools.matching_extract import extract_matching_evidence, seniority_evidence
from tools.matching_policy import (
    HARD_SENIORITY_MISMATCH,
    CandidatePolicy,
    JobEvidence,
    evaluate_eligibility,
)


# ── D8: substring contamination ───────────────────────────────────────────
class TestSeniorityWordBoundaries:
    @pytest.mark.parametrize("title", [
        "Internal Tools Developer",
        "International Sales Manager",
        "Platform Engineer, Internal Systems",
        "Internal Audit Analyst",
    ])
    def test_internal_is_not_intern(self, title):
        label, _lo, _hi, _facts, not_stated = seniority_evidence(
            title, "Build internal services for our international teams.")
        assert label != "intern"
        assert label is None
        assert not_stated is True

    @pytest.mark.parametrize("prose", [
        "You will lead code reviews.",
        "Leading a small team of engineers.",
        "Leadership experience is a plus.",
        "You lead the project from discovery to launch.",
        "We are leaders in developer tooling.",
    ])
    def test_prose_verbs_are_not_seniority(self, prose):
        label, _lo, _hi, _facts, not_stated = seniority_evidence(
            "Software Engineer", prose)
        assert label is None, f"{prose!r} produced label {label!r}"
        assert not_stated is True

    def test_seniority_mention_in_prose_is_not_a_label(self):
        label, *_ = seniority_evidence(
            "Front End Developer",
            "You will work with senior engineers and mentor juniors.")
        assert label is None

    def test_description_is_no_longer_a_seniority_source(self):
        """The exact end-to-end D8 reproduction: plain title, prose 'lead'."""
        evidence = extract_matching_evidence({
            "job_title": "Software Engineer",
            "timezone": "",
            "description": (
                "Fully remote. Open to candidates in India. "
                "Requirements: Python, JavaScript, React, PostgreSQL. "
                "You will lead code reviews."),
            "apply_url": "https://example.test/job/1",
            "source": "ExampleBoard",
        })
        assert "seniority" not in evidence
        assert evidence["seniority_not_stated"] is True


class TestSeniorityLabelsThatStillExist:
    @pytest.mark.parametrize("title,expected", [
        ("Senior Backend Engineer", "senior"),
        ("Staff Software Engineer", "staff"),
        ("Principal Engineer", "principal"),
        ("Tech Lead", "lead"),
        ("Junior Developer", "junior"),
        ("Software Engineer Intern", "intern"),
        ("Softwarearchitekt (m/w/d)", "senior"),
    ])
    def test_title_labels_are_kept(self, title, expected):
        label, _lo, _hi, facts, not_stated = seniority_evidence(title, "x")
        assert label == expected
        assert not_stated is False
        assert facts["seniority"]["field"] == "title"

    @pytest.mark.parametrize("prose,expected", [
        ("We are looking for a Senior Backend Engineer.", "senior"),
        ("We're hiring a Junior Developer for this role.", "junior"),
        ("Seniority: staff", "staff"),
        ("This is a lead role on the platform team.", "lead"),
        ("The position is a mid level role.", "mid"),
    ])
    def test_explicit_level_statements_are_kept(self, prose, expected):
        label, _lo, _hi, facts, not_stated = seniority_evidence(
            "Backend Engineer", prose)
        assert label == expected
        assert not_stated is False
        assert facts["seniority"]["quote"]

    def test_explicit_statement_fact_verifies_in_combined_text(self):
        from tools.matching_locations import verify

        title = "Backend Engineer"
        description = "We are looking for a Senior Backend Engineer."
        combined = f"{title}\n\n{description}"
        _label, _lo, _hi, facts, _ = seniority_evidence(
            title, description, combined)
        assert verify(facts["seniority"], combined)

    def test_engineering_manager_is_review_not_rejected(self):
        """No label word is a level here; the role gate decides, never a guess."""
        label, *_ = seniority_evidence("Engineering Manager", "Manage the team.")
        assert label is None
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}))
        job = JobEvidence("Engineering Manager", "Manage the team.",
                          work_mode="remote",
                          allowed_work_locations=frozenset({"india"}))
        assert evaluate_eligibility(job, policy).decision != "rejected"


# ── D9: senior is review, not rejection ───────────────────────────────────
class TestSeniorPolicy:
    POLICY = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                             frozenset({"junior", "mid"}), years_experience=3,
                             seniority_gap_threshold=2)

    def _job(self, **over):
        base = dict(title="Senior Backend Developer", description="Build APIs.",
                    role_family="backend", work_mode="remote",
                    allowed_work_locations=frozenset({"india"}),
                    seniority="senior")
        base.update(over)
        return JobEvidence(**base)

    def test_senior_is_not_in_the_hard_set(self):
        assert "senior" not in HARD_SENIORITY_MISMATCH

    def test_senior_label_is_review(self):
        result = evaluate_eligibility(self._job(), self.POLICY)
        assert result.decision == "review"
        seniority = [g for g in result.gates if g.name == "seniority"][0]
        assert seniority.outcome == "unknown"
        assert seniority.reason == "seniority_label_requires_review"

    def test_senior_with_unreachable_years_still_fails(self):
        job = self._job(years_min=9, years_max=None)
        result = evaluate_eligibility(job, self.POLICY)
        assert result.decision == "rejected"
        seniority = [g for g in result.gates if g.name == "seniority"][0]
        assert seniority.reason == "candidate_experience_below_requirement"

    def test_senior_with_reachable_years_is_review(self):
        job = self._job(years_min=5, years_max=None)  # gap 2 == threshold
        assert evaluate_eligibility(job, self.POLICY).decision == "review"

    @pytest.mark.parametrize("label", ["lead", "principal", "staff"])
    def test_structural_levels_still_fail(self, label):
        job = self._job(title=f"{label.title()} Engineer", seniority=label)
        assert evaluate_eligibility(job, self.POLICY).decision == "rejected"
