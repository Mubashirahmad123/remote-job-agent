"""QA boundary cases for malformed or incomplete matching evidence."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from tools.matching_policy import CandidatePolicy, JobEvidence
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_shadow import load_profile, shadow_batch
from tools.matching_runtime import MatchStore


class MatchingAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.profile = MatchProfile(CandidatePolicy(frozenset({'backend'}), frozenset({'IN'}),
                                                   frozenset({'mid'})), frozenset({'python'}), 'qa-v1',
                                    frozenset({'django'}))
        self.job = JobEvidence('Backend Developer', 'Django APIs',
                               allowed_work_locations=frozenset({'IN'}), seniority='mid')

    def test_incomplete_essential_extraction_cannot_confirm_rejection(self):
        requirements = RequirementsEvidence((Requirement(frozenset({'django'}), 'Django essential',
                                                            essential=True),), complete=False)
        self.assertEqual(score_match(self.job, self.profile, requirements).decision, 'review')

    def test_zero_required_overlap_cannot_enter_shortlist_as_learnable(self):
        requirements = RequirementsEvidence((Requirement(frozenset({'django'}), 'Django required'),), complete=True)
        result = score_match(self.job, self.profile, requirements)
        self.assertEqual(result.required.score, 0)
        self.assertEqual(result.decision, 'review')

    def test_profile_string_collection_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profile.json'
            path.write_text(json.dumps({'version': 'v1', 'skills': 'python',
                                        'policy': {'work_locations': 'IN'}}), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_profile(path)

    def test_shadow_location_string_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MatchStore(Path(tmp) / 'qa.db')
            job = {'job_fingerprint': 'j1', 'job_title': 'Backend Developer',
                   'matching_evidence': {'allowed_work_locations': 'IN'}}
            with self.assertRaises(ValueError):
                shadow_batch([job], self.profile, store, 'qa')

    def test_missing_description_still_goes_to_review(self):
        requirements = RequirementsEvidence((Requirement(frozenset({'python'}), 'Python required'),), complete=True)
        self.assertEqual(score_match(replace(self.job, description=None), self.profile, requirements).decision,
                         'review')
