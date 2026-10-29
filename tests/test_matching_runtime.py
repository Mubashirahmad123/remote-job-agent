"""Offline runtime regressions, using temporary databases and synthetic labels."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest

from tools.matching_policy import CandidatePolicy, JobEvidence, evaluate_eligibility
from tools.matching_score import MatchProfile, Requirement, RequirementsEvidence, score_match
from tools.matching_runtime import MatchStore, PriorityEvidence, rank_matches, evaluate_labels


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.policy = CandidatePolicy(frozenset({'backend'}), frozenset({'IN'}), frozenset({'mid'}),
                                      frozenset({'SA', 'AE'}), True)
        self.profile = MatchProfile(self.policy, frozenset({'python'}), 'p1', frozenset({'django'}))
        self.job = JobEvidence('Backend Engineer', 'Build APIs', allowed_work_locations=frozenset({'IN'}),
                               seniority='mid')
        self.requirements = RequirementsEvidence((Requirement(frozenset({'python'}), 'Python required'),),
                                                 complete=True)
        self.result = score_match(self.job, self.profile, self.requirements)

    def test_sponsored_relocation(self):
        job = replace(self.job, work_mode='onsite', job_country='SA', visa_sponsorship=True)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, 'eligible')
        self.assertEqual(evaluate_eligibility(replace(job, visa_sponsorship=False), self.policy).decision, 'rejected')
        self.assertEqual(evaluate_eligibility(replace(job, visa_sponsorship=None), self.policy).decision, 'review')

    def test_onsite_requires_country_and_allowed_destination(self):
        job = replace(self.job, work_mode='hybrid', job_country=None)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, 'review')
        self.assertEqual(evaluate_eligibility(replace(job, job_country='US', visa_sponsorship=True), self.policy).decision,
                         'rejected')
        self.assertEqual(evaluate_eligibility(replace(job, job_country='IN'), self.policy).decision, 'eligible')

    def test_unknown_work_mode(self):
        self.assertEqual(evaluate_eligibility(replace(self.job, work_mode='unknown'), self.policy).decision, 'review')

    def test_remote_us_only_not_rescued_by_sponsorship(self):
        job = replace(self.job, allowed_work_locations=frozenset({'US'}), visa_sponsorship=True)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, 'rejected')

    def test_relocation_without_sponsorship_requirement(self):
        job = replace(self.job, work_mode='onsite', job_country='AE')
        self.assertEqual(evaluate_eligibility(job, replace(self.policy, sponsorship_required=False)).decision, 'eligible')

    def test_learnable_gap_lowers_fit_but_not_eligibility(self):
        requirements = replace(self.requirements, required=self.requirements.required +
                                (Requirement(frozenset({'django'}), 'Django required'),))
        result = score_match(self.job, self.profile, requirements)
        self.assertEqual(result.decision, 'eligible')
        self.assertEqual(result.required.score, 50)
        self.assertEqual(len(result.required.gaps), 1)

    def test_essential_gap_blocks_even_if_learnable(self):
        requirements = replace(self.requirements, required=(Requirement(frozenset({'django'}), 'Django essential',
                                                                         essential=True),))
        result = score_match(self.job, self.profile, requirements)
        self.assertEqual(result.decision, 'rejected')
        self.assertIn('essential_skill_mismatch', result.review_reasons)

    def test_preferences_and_freshness_do_not_change_fit(self):
        now = datetime(2026, 10, 29, tzinfo=timezone.utc)
        entries = [('old', self.result, PriorityEvidence(posted_at=now-timedelta(days=20))),
                   ('fresh', self.result, PriorityEvidence(posted_at=now))]
        self.assertEqual(rank_matches(entries, now, 10)[0][0], 'fresh')
        self.assertEqual(self.result.required.score, 100)
        preferred = ('preferred', self.result, PriorityEvidence(startup_preferred=True))
        self.assertEqual(rank_matches(entries + [preferred], now, 10)[0][0], 'preferred')

    def test_rank_validation_and_no_quota_fill(self):
        now = datetime.now(timezone.utc)
        for limit in (-1, True, .5):
            with self.assertRaises(ValueError):
                rank_matches([], now, limit)
        with self.assertRaises(ValueError):
            rank_matches([], datetime.now(), 2)
        review = score_match(self.job, self.profile, RequirementsEvidence())
        self.assertEqual(rank_matches([('review', review, PriorityEvidence())], now, 5), [])

    def test_cache_version_content_and_owner_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'matches.db'
            store = MatchStore(path)
            store.cache_extraction('alice', 'description', 'v1', {'stack': ['python']})
            self.assertEqual(MatchStore(path).get_extraction('alice', 'description', 'v1'), {'stack': ['python']})
            for owner, text, version in [('bob', 'description', 'v1'), ('alice', 'new text', 'v1'),
                                         ('alice', 'description', 'v2')]:
                self.assertIsNone(store.get_extraction(owner, text, version))

    def test_review_queue_survives_restart_and_clears_on_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'matches.db'
            store = MatchStore(path)
            review = score_match(self.job, self.profile, RequirementsEvidence())
            store.record('alice', 'j1', 'old content', review)
            self.assertEqual(len(MatchStore(path).review_queue('alice', 'p1')), 1)
            self.assertEqual(store.review_queue('bob', 'p1'), [])
            self.assertEqual(store.review_queue('alice', 'p2'), [])
            store.record('alice', 'j1', 'new content', self.result)
            self.assertEqual(store.review_queue('alice', 'p1'), [])

    def test_evaluation_excludes_unknown_labels(self):
        report = evaluate_labels({'a': 'apply', 'b': 'skip', 'c': 'uncertain'}, {'b'}, {'a', 'c', 'd'})
        self.assertEqual(report['new']['precision'], 1)
        self.assertEqual(report['new']['recall'], 1)
        self.assertEqual(report['new']['unlabeled_or_uncertain_selected'], 2)
        self.assertEqual(report['old']['precision'], 0)
        self.assertIsNone(evaluate_labels({}, set(), set())['new']['precision'])
        with self.assertRaises(ValueError):
            evaluate_labels({'a': 'invented'}, set(), set())


class ShadowTests(unittest.TestCase):
    setUp = RuntimeTests.setUp
    def test_shadow_records_unknown_extraction_without_mutating_jobs(self):
        from tools.matching_shadow import shadow_batch
        import copy
        with tempfile.TemporaryDirectory() as tmp:
            store = MatchStore(Path(tmp) / 'shadow.db')
            jobs = [{'job_fingerprint': 'j1', 'job_title': 'Backend Engineer', 'summary': 'Python APIs'}]
            before = copy.deepcopy(jobs)
            results = shadow_batch(jobs, self.profile, store, 'alice')
            self.assertEqual(results['j1'].decision, 'review')
            self.assertEqual(jobs, before)
            self.assertEqual(len(store.review_queue('alice', 'p1')), 1)

    def test_verified_evidence_is_scored_and_cached(self):
        from tools.matching_shadow import shadow_batch
        with tempfile.TemporaryDirectory() as tmp:
            store = MatchStore(Path(tmp) / 'shadow.db')
            jobs = [{'job_fingerprint': 'j1', 'job_title': 'Backend Engineer', 'summary': 'Python APIs',
                     'matching_evidence': {'work_mode': 'remote', 'allowed_work_locations': ['IN'],
                         'seniority': 'mid', 'requirements': {'required': [
                             {'alternatives': ['python'], 'evidence': 'Python required'}],
                             'complete': True, 'extractor_version': 'test-v1'}}}]
            self.assertEqual(shadow_batch(jobs, self.profile, store, 'alice')['j1'].decision, 'eligible')

    def test_disabled_hook_does_not_open_database(self):
        from tools.matching_shadow import run_optional_shadow
        from unittest.mock import patch
        with patch.dict('os.environ', {'MATCHING_SHADOW_PROFILE': ''}):
            self.assertIsNone(run_optional_shadow([]))

    def test_operator_profile_loading(self):
        from tools.matching_shadow import load_profile
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profile.json'
            path.write_text(json.dumps({'version': 'p1', 'skills': ['python'], 'policy': {
                'work_locations': ['IN'], 'relocation_destinations': ['SA', 'AE'],
                'sponsorship_required': True}}), encoding='utf-8')
            profile = load_profile(path)
            self.assertEqual(profile.policy.relocation_destinations, frozenset({'SA', 'AE'}))

    def test_duplicate_cannot_remove_essential_status(self):
        requirements = replace(self.requirements, required=(
            Requirement(frozenset({'django'}), 'Django requested'),
            Requirement(frozenset({'django'}), 'Django essential', essential=True)))
        self.assertEqual(score_match(self.job, self.profile, requirements).decision, 'rejected')

    def test_string_booleans_cannot_grant_permission(self):
        with self.assertRaises(ValueError):
            replace(self.job, visa_sponsorship='false')
        with self.assertRaises(ValueError):
            replace(self.policy, sponsorship_required='false')
        with self.assertRaises(ValueError):
            replace(self.job, work_mode='anywhere')


if __name__ == '__main__':
    unittest.main()
