"""Offline policy contracts; synthetic regressions, not a labeled evaluation set."""
import unittest
from dataclasses import replace

from tools.matching_policy import CandidatePolicy, JobEvidence, evaluate_eligibility, infer_title_family


class MatchingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CandidatePolicy(frozenset({"backend", "frontend", "fullstack"}),
                                      frozenset({"IN"}), frozenset({"mid"}))
        self.job = JobEvidence("Backend Developer", "Build APIs with Django",
                               allowed_work_locations=frozenset({"IN"}), seniority="mid")

    def test_confirmed_survivor_is_eligible(self):
        self.assertEqual(evaluate_eligibility(self.job, self.policy).decision, "eligible")

    def test_missing_description_requests_enrichment_not_rejection(self):
        for description in (None, "", "   "):
            result = evaluate_eligibility(replace(self.job, description=description), self.policy)
            self.assertEqual(result.decision, "review")
            self.assertTrue(result.needs_description)

    def test_us_only_rejected_for_india(self):
        result = evaluate_eligibility(replace(self.job, allowed_work_locations=frozenset({"US"})), self.policy)
        self.assertEqual(result.decision, "rejected")
        self.assertIn("work_location_not_allowed", [g.reason for g in result.gates])

    def test_remote_title_does_not_prove_worldwide(self):
        result = evaluate_eligibility(replace(self.job, title="Remote Backend Developer",
                                               allowed_work_locations=None), self.policy)
        self.assertEqual(result.decision, "review")

    def test_company_headquarters_cannot_grant_eligibility(self):
        job = replace(self.job, description="London headquarters; remote team", allowed_work_locations=None)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")

    def test_worldwide_explicit_permission(self):
        job = replace(self.job, worldwide=True, allowed_work_locations=None)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_emea_does_not_implicitly_include_india(self):
        job = replace(self.job, allowed_work_locations=frozenset({"EMEA"}))
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "rejected")

    def test_wrong_role_cannot_be_rescued_by_skill_overlap(self):
        for title in ("Robotics Engineer", "Hardware Engineer", "Solutions Engineer", "Support Engineer"):
            job = replace(self.job, title=title, description="Python React git")
            self.assertEqual(evaluate_eligibility(job, self.policy).decision, "rejected")

    def test_generic_title_waits_for_evidence(self):
        job = replace(self.job, title="Software Engineer II")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")
        self.assertEqual(evaluate_eligibility(replace(job, role_family="backend"), self.policy).decision, "eligible")

    def test_technology_mention_is_not_blanket_rejection(self):
        job = replace(self.job, description="React required. Other teams use Java and Go.")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_seniority_mismatch(self):
        self.assertEqual(evaluate_eligibility(replace(self.job, seniority="principal"), self.policy).decision,
                         "rejected")

    def test_unconfigured_policy_is_review_not_implicit_permission(self):
        self.assertEqual(evaluate_eligibility(self.job, CandidatePolicy()).decision, "review")

    def test_short_tokens_do_not_match_random_words(self):
        self.assertIsNone(infer_title_family("Regional Strategy Engineer"))
        self.assertIsNone(infer_title_family("JavaScript Developer"))
        self.assertEqual(infer_title_family("Node.js Developer"), "backend")

    def test_confirmed_rejection_does_not_request_expensive_enrichment(self):
        result = evaluate_eligibility(replace(self.job, title="Hardware Engineer", description=None), self.policy)
        self.assertEqual(result.decision, "rejected")
        self.assertFalse(result.needs_description)


class EvidenceConflictTests(unittest.TestCase):
    def test_worldwide_and_us_only_conflict_requires_review(self):
        policy = CandidatePolicy(frozenset({'backend'}), frozenset({'IN'}), frozenset({'mid'}))
        job = JobEvidence('Backend Engineer', 'Contradictory source fields',
                          allowed_work_locations=frozenset({'US'}), worldwide=True, seniority='mid')
        result = evaluate_eligibility(job, policy)
        self.assertEqual(result.decision, 'review')
        self.assertIn('location_evidence_conflict', [g.reason for g in result.gates])

    def test_support_word_alone_does_not_prove_support_role(self):
        self.assertIsNone(infer_title_family('Software Engineer, Developer Support Platform'))


class TitleFamilyTests(unittest.TestCase):
    def test_frontend_and_fullstack_aliases(self):
        self.assertEqual(infer_title_family("React Developer"), "frontend")
        self.assertEqual(infer_title_family("Full-Stack Developer"), "fullstack")


if __name__ == "__main__":
    unittest.main()
