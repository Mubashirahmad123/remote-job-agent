"""D11 regression tests: required skill gaps must prevent eligible/likely_fit.

Before D11, a job with learnable required skill gaps could be scored as
"eligible" or "likely_fit" with a review_reasons list that didn't mention
the gaps. D11 requires that ANY required gap (learnable or not) produces a
"review" decision with either "required_skill_gaps" (non-learnable) or
"partial_required_coverage" (learnable-only) in review_reasons.
"""
import unittest
from dataclasses import replace

from tools.matching_policy import CandidatePolicy, JobEvidence
from tools.matching_score import (
    MatchProfile, Requirement, RequirementsEvidence, score_match,
)


def req(*skills, weight=1, essential=False):
    return Requirement(frozenset(skills), "Required: " + " or ".join(skills),
                       weight=weight, essential=essential)


class D11RequiredGapsTests(unittest.TestCase):
    def setUp(self):
        self.profile = MatchProfile(
            CandidatePolicy(frozenset({"backend"}), frozenset({"IN"}),
                           frozenset({"mid"})),
            frozenset({"python", "postgresql", "git"}),
            "profile-d11-v1",
            learnable_skills=frozenset({"kubernetes"}))

        self.job = JobEvidence(
            "Backend Engineer", "Build services",
            allowed_work_locations=frozenset({"IN"}),
            seniority="mid")

    def test_learnable_gap_is_partial_required_coverage_not_eligible(self):
        """A required gap that IS learnable -> partial_required_coverage -> review."""
        requirements = RequirementsEvidence(
            (req("python"), req("kubernetes"), req("postgresql")), complete=True)
        result = score_match(self.job, self.profile, requirements)
        # Has learnable gap (kubernetes) but no non-learnable gaps
        self.assertEqual(result.decision, "review")
        self.assertIn("partial_required_coverage", result.review_reasons)
        self.assertNotIn("required_skill_gaps", result.review_reasons)

    def test_non_learnable_gap_is_required_skill_gaps_not_eligible(self):
        """A required gap that is NOT learnable -> required_skill_gaps -> review."""
        requirements = RequirementsEvidence(
            (req("python"), req("rust"), req("postgresql")), complete=True)
        result = score_match(self.job, self.profile, requirements)
        # rust is not in learnable_skills
        self.assertEqual(result.decision, "review")
        self.assertIn("required_skill_gaps", result.review_reasons)
        self.assertNotIn("partial_required_coverage", result.review_reasons)

    def test_mixed_learnable_and_non_learnable_gaps(self):
        """One learnable, one non-learnable -> required_skill_gaps (the harder one wins)."""
        requirements = RequirementsEvidence(
            (req("python"), req("kubernetes"), req("rust")), complete=True)
        result = score_match(self.job, self.profile, requirements)
        self.assertEqual(result.decision, "review")
        self.assertIn("required_skill_gaps", result.review_reasons)
        # The non-learnable gap dominates the reason

    def test_no_gaps_still_eligible(self):
        """All required skills matched -> eligible."""
        requirements = RequirementsEvidence(
            (req("python"), req("postgresql")), complete=True)
        result = score_match(self.job, self.profile, requirements)
        self.assertEqual(result.decision, "eligible")
        self.assertEqual(result.required.score, 100)
        self.assertEqual(result.review_reasons, ())

    def test_likely_fit_requires_no_required_gaps(self):
        """likely_fit eligibility + requirements pass -> likely_fit.
        But if there are required gaps -> review."""
        # Use a profile that gets likely_fit eligibility (seniority_not_stated)
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"IN"}),
                                 frozenset({"senior"}))
        profile = MatchProfile(policy, frozenset({"python", "postgresql"}),
                               "profile-d11-v2", learnable_skills=frozenset({"kubernetes"}))
        # Job with seniority_not_stated=True -> likely_fit eligibility
        job = JobEvidence("Senior Backend Engineer", "Lead services",
                          allowed_work_locations=frozenset({"IN"}),
                          seniority=None,
                          seniority_not_stated=True)
        # No gaps -> likely_fit
        requirements = RequirementsEvidence((req("python"), req("postgresql")), complete=True)
        result = score_match(job, profile, requirements)
        self.assertEqual(result.decision, "likely_fit")

        # With learnable gap -> review, not likely_fit
        requirements_with_gap = RequirementsEvidence(
            (req("python"), req("kubernetes"), req("postgresql")), complete=True)
        result2 = score_match(job, profile, requirements_with_gap)
        self.assertEqual(result2.decision, "review")
        self.assertIn("partial_required_coverage", result2.review_reasons)

    def test_essential_gap_still_rejected_when_complete(self):
        """Essential gap with complete requirements -> rejected."""
        requirements = RequirementsEvidence(
            (req("python", essential=True), req("postgresql", essential=True)),
            complete=True)
        # Profile missing postgresql (essential)
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"IN"}),
                                 frozenset({"mid"}))
        profile = MatchProfile(policy, frozenset({"python"}), "profile-d11-v3")
        result = score_match(self.job, profile, requirements)
        self.assertEqual(result.decision, "rejected")
        self.assertIn("essential_skill_mismatch", result.review_reasons)


if __name__ == "__main__":
    unittest.main()