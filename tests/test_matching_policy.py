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


class Phase3PolicyConstructionTests(unittest.TestCase):
    def test_new_fields_default_to_empty_unknown(self):
        p = CandidatePolicy()
        self.assertEqual(p.role_families, frozenset())
        self.assertEqual(p.remote_work_locations, frozenset())
        self.assertEqual(p.work_cities, frozenset())
        self.assertIsNone(p.years_experience)
        self.assertFalse(p.accept_unrestricted_remote)

    def test_remote_bases_falls_back_to_work_locations(self):
        p = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                            frozenset({"mid"}),
                            remote_work_locations=frozenset({"eea", "uk"}))
        self.assertEqual(p.remote_bases, frozenset({"eea", "uk"}))
        p2 = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                             frozenset({"mid"}))
        self.assertEqual(p2.remote_bases, frozenset({"india"}))

    def test_rejects_bad_sponsorship_and_unrestricted_types(self):
        with self.assertRaises(ValueError):
            CandidatePolicy(sponsorship_required="yes")
        with self.assertRaises(ValueError):
            CandidatePolicy(accept_unrestricted_remote="yes")
        with self.assertRaises(ValueError):
            CandidatePolicy(years_experience=-1)
        with self.assertRaises(ValueError):
            CandidatePolicy(work_locations={"india"})  # not a frozenset


class Phase3LocationTests(unittest.TestCase):
    def setUp(self):
        self.policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                      frozenset({"junior", "mid"}),
                                      relocation_destinations=frozenset({"india"}),
                                      sponsorship_required=False,
                                      remote_work_locations=frozenset({"india"}),
                                      work_cities=frozenset({"srinagar"}),
                                      years_experience=3,
                                      accept_unrestricted_remote=True)

    def test_remote_job_permitting_india_passes_location(self):
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="remote", allowed_work_locations=frozenset({"india"}),
                          seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_remote_job_permitting_only_eu_fails_for_india_worker(self):
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="remote", allowed_work_locations=frozenset({"eu"}),
                          seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "rejected")

    def test_worldwide_remote_passes_without_region_list(self):
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="remote", worldwide=True,
                          allowed_work_locations=None, seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_unrestricted_remote_with_complete_text_passes(self):
        job = JobEvidence("Backend Developer", "Fully remote position, work from anywhere.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=None, worldwide=False,
                          seniority="mid", location_text_complete=True)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_unrestricted_remote_incomplete_text_stays_review(self):
        job = JobEvidence("Backend Developer", "Remote.", role_family="backend",
                          work_mode="remote", allowed_work_locations=None,
                          worldwide=False, seniority="mid",
                          location_text_complete=False)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")

    def test_onsite_in_own_city_is_existing_work_right(self):
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="onsite", job_country="india", job_city="srinagar",
                          seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_onsite_in_other_indian_city_is_relocation_allowed(self):
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="onsite", job_country="india", job_city="bangalore",
                          seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_onsite_outside_relocation_destination_fails(self):
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="onsite", job_country="germany", job_city="berlin",
                          seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "rejected")

    def test_company_headquarters_does_not_grant_worker_permission(self):
        # HQ mention must not be read as allowed_work_locations; only the
        # explicit worker-permission list decides a remote job.
        job = JobEvidence("Backend Developer", "HQ in London; fully remote.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=None, worldwide=False,
                          seniority="mid", location_text_complete=True)
        # No worker region quoted -> unrestricted remote path applies (profile allows it).
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_unconfigured_remote_profile_is_unknown_not_permission(self):
        empty_policy = CandidatePolicy(frozenset({"backend"}),
                                       frozenset(), frozenset({"mid"}),
                                       remote_work_locations=frozenset())
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="remote", allowed_work_locations=frozenset({"india"}),
                          seniority="mid")
        result = evaluate_eligibility(job, empty_policy)
        self.assertEqual(result.decision, "review")
        self.assertIn("candidate_work_locations_missing",
                      [g.reason for g in result.gates])


class Phase3SeniorityTests(unittest.TestCase):
    def setUp(self):
        self.policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                      frozenset({"junior", "mid"}),
                                      years_experience=3)

    def test_years_range_within_candidate_experience_passes(self):
        job = JobEvidence("Backend Developer", "0 to 4 yrs of experience.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          years_min=0, years_max=4, seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_candidate_below_min_years_fails(self):
        job = JobEvidence("Backend Developer", "5+ years experience required.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          years_min=5, years_max=None, seniority="mid")
        # Gap = 2, threshold = 2 -> REVIEW (not FAIL per gap<=threshold rule)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")

    def test_candidate_above_max_years_is_review_not_reject(self):
        job = JobEvidence("Backend Developer", "0 to 2 yrs of experience.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          years_min=0, years_max=2, seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")

    def test_explicit_senior_label_requires_fail_not_review(self):
        job = JobEvidence("Senior Backend Developer", "Lead the team.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          seniority="senior")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "rejected")

    def test_hard_mismatch_labels_fail(self):
        for label in ("principal", "staff", "lead", "director", "executive"):
            job = JobEvidence(f"{label.title()} Engineer", "x", role_family="backend",
                              work_mode="remote",
                              allowed_work_locations=frozenset({"india"}),
                              seniority=label)
            self.assertEqual(evaluate_eligibility(job, self.policy).decision, "rejected")

    def test_no_seniority_evidence_is_unknown(self):
        job = JobEvidence("Backend Developer", "Build APIs", role_family="backend",
                          work_mode="remote", allowed_work_locations=frozenset({"india"}),
                          seniority=None)
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")


class Phase3RoleHintTests(unittest.TestCase):
    def setUp(self):
        self.policy = CandidatePolicy(frozenset({"backend", "fullstack"}), frozenset({"india"}),
                                      frozenset({"junior", "mid"}))

    def test_explicit_non_target_title_still_fails(self):
        for title in ("Hardware Engineer", "Support Engineer", "Robotics Engineer"):
            job = JobEvidence(title, "x", role_family="non_target",
                              work_mode="remote", allowed_work_locations=frozenset({"india"}),
                              seniority="mid")
            self.assertEqual(evaluate_eligibility(job, self.policy).decision, "rejected")

    def test_wanted_family_with_architect_hint_is_review(self):
        job = JobEvidence("Softwarearchitekt", "You own the overall architecture.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          seniority="mid", role_hints=frozenset({"architect"}))
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")
        self.assertIn("role_hint_requires_review",
                      [g.reason for g in evaluate_eligibility(job, self.policy).gates])

    def test_wanted_family_without_hint_passes(self):
        job = JobEvidence("Backend Developer", "Build APIs.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          seniority="mid")
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "eligible")

    def test_devrel_hint_is_review(self):
        job = JobEvidence("Developer Relations Engineer", "Advocate for our tooling.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          seniority="mid", role_hints=frozenset({"devrel"}))
        self.assertEqual(evaluate_eligibility(job, self.policy).decision, "review")

    def test_bare_remote_is_review(self):
        """Bare 'Remote' with no permission wording -> REVIEW."""
        job = JobEvidence("Backend Developer", "Remote position.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=None, worldwide=False,
                          seniority="mid", location_text_complete=True)
        result = evaluate_eligibility(job, self.policy)
        self.assertEqual(result.decision, "review")
        self.assertIn("worker_location_restriction_unverified",
                      [g.reason for g in result.gates])

    def test_remote_eu_only_is_rejected_via_worker_permission(self):
        """'Remote, EU only' -> REJECTED via work_location_not_allowed."""
        job = JobEvidence("Backend Developer", "Remote, open to candidates in EU.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"eu"}), worldwide=False,
                          seniority="mid")
        result = evaluate_eligibility(job, self.policy)
        self.assertEqual(result.decision, "rejected")
        self.assertIn("work_location_not_allowed",
                      [g.reason for g in result.gates])

    def test_work_from_anywhere_location_passes(self):
        """'work from anywhere' -> location PASS (verified_worldwide)."""
        job = JobEvidence("Backend Developer", "Remote, work from anywhere.",
                          role_family="backend", work_mode="remote",
                          worldwide=True, allowed_work_locations=None,
                          seniority="mid")
        result = evaluate_eligibility(job, self.policy)
        location_gate = [g for g in result.gates if g.name == "location"][0]
        self.assertEqual(location_gate.outcome, "pass")
        self.assertEqual(location_gate.reason, "verified_worldwide")

    def test_hybrid_outside_india_is_rejected(self):
        """Hybrid in Berlin -> REJECTED (relocation destination not allowed)."""
        job = JobEvidence("Backend Developer", "Hybrid in Berlin.",
                          role_family="backend", work_mode="hybrid",
                          job_country="germany", job_city="berlin",
                          seniority="mid")
        result = evaluate_eligibility(job, self.policy)
        self.assertEqual(result.decision, "rejected")
        self.assertIn("relocation_destination_not_allowed",
                      [g.reason for g in result.gates])

    def test_four_plus_years_vs_three_is_review(self):
        """'4+ years' for 3-year candidate -> REVIEW (gap <= threshold)."""
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}),
                                 years_experience=3, seniority_gap_threshold=2)
        job = JobEvidence("Backend Developer", "4+ years of experience.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          years_min=4, years_max=None, seniority="mid")
        result = evaluate_eligibility(job, policy)
        self.assertEqual(result.decision, "review")
        self.assertIn("candidate_experience_below_range",
                      [g.reason for g in result.gates])

    def test_eight_plus_years_vs_three_is_rejected(self):
        """'8+ years' for 3-year candidate -> REJECTED (gap > threshold)."""
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}),
                                 years_experience=3, seniority_gap_threshold=2)
        job = JobEvidence("Backend Developer", "8+ years of experience.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          years_min=8, years_max=None, seniority="mid")
        result = evaluate_eligibility(job, policy)
        self.assertEqual(result.decision, "rejected")
        self.assertIn("candidate_experience_below_requirement",
                      [g.reason for g in result.gates])

    def test_five_plus_years_of_react_no_seniority_effect(self):
        """'5+ years of React' is requirement context, not seniority."""
        job = JobEvidence("Backend Developer", "Requires 5+ years of React. "
                          "Requirements: Python.",
                          role_family="backend", work_mode="remote",
                          allowed_work_locations=frozenset({"india"}),
                          seniority="mid")
        result = evaluate_eligibility(job, self.policy)
        # seniority gate should pass (explicit mid label), not fail on React years
        seniority_gate = [g for g in result.gates if g.name == "seniority"][0]
        self.assertEqual(seniority_gate.outcome, "pass")

    def test_likely_fit_path(self):
        """Location + role + description PASS + seniority not_stated -> LIKELY_FIT."""
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}),
                                 years_experience=3, seniority_gap_threshold=2,
                                 remote_work_locations=frozenset({"india"}),
                                 accept_unrestricted_remote=False)
        job = JobEvidence("Backend Developer", "Remote position, work from anywhere.",
                          role_family="backend", work_mode="remote",
                          worldwide=True, allowed_work_locations=None,
                          seniority=None, seniority_not_stated=True,
                          location_text_complete=True)
        result = evaluate_eligibility(job, policy)
        self.assertEqual(result.decision, "likely_fit")

    def test_generic_software_title_passes_without_hint(self):
        """Generic software titles resolve to 'software' family and PASS."""
        policy = CandidatePolicy(frozenset({"backend", "frontend", "fullstack", "software"}),
                                 frozenset({"india"}), frozenset({"junior", "mid"}),
                                 remote_work_locations=frozenset({"india"}),
                                 years_experience=3, seniority_gap_threshold=2)
        for title in ("Software Developer", "Software Engineer", "Programmer", "Web Developer"):
            job = JobEvidence(title, "Build APIs.", role_family="software",
                              work_mode="remote", allowed_work_locations=frozenset({"india"}),
                              seniority="mid")
            result = evaluate_eligibility(job, policy)
            self.assertEqual(result.decision, "eligible",
                             f"{title} should be eligible")

    def test_role_gate_review_hints(self):
        """Review hints printed for support, forward-deployed, research, data/infra,
        hardware/EDA, devrel, architect titles."""
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}),
                                 remote_work_locations=frozenset({"india"}),
                                 years_experience=3, seniority_gap_threshold=2)
        hint_titles = {
            "Support Engineer": "support",
            "Forward Deployed Engineer": "forward_deployed",
            "Research Engineer": "research",
            "Data Infrastructure Engineer": "data_infra",
            "Hardware EDA Engineer": "hardware_eda",
            "Developer Relations Engineer": "devrel",
            "Softwarearchitekt": "architect",
        }
        for title, expected_hint in hint_titles.items():
            job = JobEvidence(title, "Build systems.",
                              role_family="backend", work_mode="remote",
                              allowed_work_locations=frozenset({"india"}),
                              seniority="mid", role_hints=frozenset({expected_hint}))
            result = evaluate_eligibility(job, policy)
            self.assertEqual(result.decision, "review",
                             f"{title} should be review due to {expected_hint} hint")
            self.assertIn("role_hint_requires_review",
                          [g.reason for g in result.gates])

    def test_flexible_worldwide_or_hybrid_berlin_passes(self):
        """'Remote (worldwide) or hybrid in Berlin' -> location PASS."""
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}),
                                 remote_work_locations=frozenset({"india"}),
                                 years_experience=3, seniority_gap_threshold=2)
        job = JobEvidence("Backend Developer", "Remote (worldwide) or hybrid in Berlin.",
                          role_family="backend", work_mode="flexible",
                          worldwide=True, allowed_work_locations=None,
                          job_country="germany", job_city="berlin",
                          seniority="mid")
        result = evaluate_eligibility(job, policy)
        location_gate = [g for g in result.gates if g.name == "location"][0]
        self.assertEqual(location_gate.outcome, "pass")
        self.assertEqual(location_gate.reason, "verified_worldwide")

    def test_flexible_eea_only_or_hybrid_bangalore_passes(self):
        """'Remote (EEA only) or hybrid in Bangalore' -> PASS via hybrid (India)."""
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}),
                                 remote_work_locations=frozenset({"india"}),
                                 relocation_destinations=frozenset({"india"}),
                                 years_experience=3, seniority_gap_threshold=2)
        job = JobEvidence("Backend Developer", "Remote (EEA only) or hybrid in Bangalore.",
                          role_family="backend", work_mode="flexible",
                          allowed_work_locations=frozenset({"eea"}),
                          job_country="india", job_city="bangalore",
                          seniority="mid")
        result = evaluate_eligibility(job, policy)
        location_gate = [g for g in result.gates if g.name == "location"][0]
        self.assertEqual(location_gate.outcome, "pass")
        self.assertEqual(location_gate.reason, "existing_work_rights")

    def test_flexible_eea_only_or_hybrid_london_fails(self):
        """'Remote (EEA only) or hybrid in London' -> FAIL (hybrid abroad)."""
        policy = CandidatePolicy(frozenset({"backend"}), frozenset({"india"}),
                                 frozenset({"junior", "mid"}),
                                 remote_work_locations=frozenset({"india"}),
                                 relocation_destinations=frozenset({"india"}),
                                 years_experience=3, seniority_gap_threshold=2)
        job = JobEvidence("Backend Developer", "Remote (EEA only) or hybrid in London.",
                          role_family="backend", work_mode="flexible",
                          allowed_work_locations=frozenset({"eea"}),
                          job_country="united_kingdom", job_city="london",
                          seniority="mid")
        result = evaluate_eligibility(job, policy)
        location_gate = [g for g in result.gates if g.name == "location"][0]
        self.assertEqual(location_gate.outcome, "fail")
        self.assertEqual(location_gate.reason, "relocation_destination_not_allowed")


if __name__ == "__main__":
    unittest.main()
