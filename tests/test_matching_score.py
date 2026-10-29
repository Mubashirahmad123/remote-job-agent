"""Synthetic contracts for the shadow matcher, not an accuracy benchmark."""
import unittest
from dataclasses import asdict, replace
import json

from tools.matching_policy import CandidatePolicy, JobEvidence
from tools.matching_score import (MatchProfile, Requirement, RequirementsEvidence,
                                  normalize_skill, requirement_coverage, score_match, shortlist)


def req(*skills, weight=1):
    return Requirement(frozenset(skills), "Required: " + " or ".join(skills), weight)


class MatchingScoreTests(unittest.TestCase):
    def setUp(self):
        self.profile = MatchProfile(CandidatePolicy(frozenset({"backend"}), frozenset({"IN"}),
                                                   frozenset({"mid"})),
                                    frozenset({"node.js", "React", "git"}), "profile-test-v1")
        self.job = JobEvidence("Backend Engineer", "Build services", allowed_work_locations=frozenset({"IN"}),
                               seniority="mid")
        self.requirements = RequirementsEvidence((req("nodejs"),), complete=True)

    def test_aliases_normalized(self):
        self.assertEqual(normalize_skill(" Node.js "), "node")
        self.assertEqual(normalize_skill("Postgres"), "postgresql")

    def test_no_substring_matching(self):
        self.assertIsNone(requirement_coverage(None, self.profile.skills).score)
        self.assertEqual(requirement_coverage((req("java"),), frozenset({"javascript"})).score, 0)
        self.assertEqual(requirement_coverage((req("go"),), frozenset({"django"})).score, 0)

    def test_coverage_uses_job_requirements(self):
        coverage = requirement_coverage((req("node", weight=3), req("django", weight=3), req("git", weight=.2)),
                                        self.profile.skills)
        self.assertAlmostEqual(coverage.score, 51.61)
        self.assertEqual(len(coverage.gaps), 1)

    def test_alternative_requires_only_one_match(self):
        self.assertEqual(requirement_coverage((req("react", "vue"),), self.profile.skills).score, 100)

    def test_duplicate_alias_groups_not_double_counted(self):
        coverage = requirement_coverage((req("node.js"), req("nodejs"), req("django")), self.profile.skills)
        self.assertEqual(coverage.score, 50)
        self.assertEqual(coverage.total_weight, 2)

    def test_missing_requirements_stay_unknown(self):
        for required in (None, ()):
            result = score_match(self.job, self.profile, RequirementsEvidence(required, complete=True))
            self.assertEqual(result.decision, "review")
            self.assertIsNone(result.required.score)

    def test_preferred_cannot_rescue_required_gap(self):
        result = score_match(self.job, self.profile,
                             RequirementsEvidence((req("java"),), (req("react"), req("git")), True))
        self.assertEqual(result.required.score, 0)
        self.assertEqual(result.preferred.score, 100)
        self.assertEqual(result.decision, "review")
        self.assertEqual(shortlist([result], 10), [])

    def test_full_match_is_eligible(self):
        result = score_match(self.job, self.profile, self.requirements)
        self.assertEqual(result.decision, "eligible")
        self.assertEqual(result.required.score, 100)

    def test_description_is_not_extraction_confidence(self):
        result = score_match(self.job, self.profile, replace(self.requirements, complete=False))
        self.assertEqual(result.decision, "review")
        self.assertTrue(result.evidence_completeness["description"])
        self.assertFalse(result.evidence_completeness["requirements"])

    def test_location_unknown_not_buried_in_numeric_score(self):
        result = score_match(replace(self.job, allowed_work_locations=None), self.profile, self.requirements)
        self.assertEqual(result.required.score, 100)
        self.assertEqual(result.decision, "review")
        self.assertFalse(result.evidence_completeness["location"])

    def test_rejected_job_has_no_fit_score(self):
        result = score_match(replace(self.job, title="Hardware Engineer"), self.profile, self.requirements)
        self.assertEqual(result.decision, "rejected")
        self.assertIsNone(result.required.score)

    def test_shortlist_does_not_fill_quota(self):
        good = score_match(self.job, self.profile, self.requirements)
        review = score_match(self.job, self.profile, RequirementsEvidence())
        self.assertEqual(shortlist([review, good], 20), [good])
        self.assertEqual(shortlist([good], 0), [])
        for invalid in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                shortlist([good], invalid)

    def test_invalid_requirement_evidence_or_weight_rejected(self):
        for weight in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                req("react", weight=weight)
        with self.assertRaises(ValueError):
            Requirement(frozenset({"react"}), "")
        with self.assertRaises(ValueError):
            Requirement(frozenset(), "Required")

    def test_version_and_evidence_survive_serialization(self):
        result = score_match(self.job, self.profile, self.requirements)
        payload = json.loads(json.dumps(asdict(result), default=lambda value: sorted(value)))
        self.assertEqual(payload["profile_version"], "profile-test-v1")
        self.assertEqual(payload["extractor_version"], "manual-v1")
        self.assertEqual(payload["scorer_version"], "requirements-v2")
        self.assertTrue(payload["required"]["hits"][0]["evidence"])


class NumericBoundaryTests(unittest.TestCase):
    def test_large_finite_weights_do_not_produce_nan(self):
        with self.assertRaises(ValueError):
            req('react', weight=1e308)

    def test_tiny_finite_weights_remain_valid(self):
        coverage = requirement_coverage((req('react', weight=1e-310),), frozenset({'react'}))
        self.assertEqual(coverage.score, 100)


class ProfileValidationTests(unittest.TestCase):
    def test_missing_profile_version_rejected(self):
        with self.assertRaises(ValueError):
            MatchProfile(CandidatePolicy(), frozenset(), " ")


if __name__ == "__main__":
    unittest.main()
