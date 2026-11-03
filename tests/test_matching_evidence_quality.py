"""Evidence-quality regression tests for D1, D2, D4 and D5.

PROVENANCE: every description/location string below was WRITTEN BY THE TEST
AUTHOR to exercise one rule. None of it is quoted from a live posting, and nothing
here talks to a board, a sheet or an LLM. The point of these tests is not "does
the regex fire" but "does the engine distinguish an ask from a mention, a
sentence about the work location from a sentence about the HQ, and a fact from
its source field".

D1 - a technology named in a stack list or a responsibilities block is bindung
     evidence, not a requirement.
D2 - "we extracted nothing" must be distinguishable from "the posting asked for
     nothing" before completeness can unlock a rejection.
D4 - a city name is not a work location: HQ, offices, travel and meetings are
     not where the job sits.
D5 - every location fact must verify against the string its `field` names, or it
     is dropped; location_tags and URL slugs are real evidence, not noise.
"""
import pytest

from tools.matching_extract import (
    extract_matching_evidence,
    requirements_evidence,
)
from tools.matching_locations import (
    job_country_from_text,
    verify,
)


def _classes(items):
    return sorted((tuple(i["alternatives"]), i["class"]) for i in items)


# ── D1: requirement classes ────────────────────────────────────────────────


class TestRequirementClasses:
    def test_requirements_heading_makes_bullets_required(self):
        required, preferred, facts = requirements_evidence(
            "Requirements:\n- Python\n- Docker")
        assert _classes(required) == [(("docker",), "required"),
                                      (("python",), "required")]
        assert preferred == []
        assert facts["requirements"]["count"]["required"] == 2

    def test_inline_nice_to_have_does_not_reclassify_following_text(self):
        """One "Nice to have:" sentence is a preference for that sentence only.

        Before D1 the marker leaked: every later paragraph became a preference,
        so a must-have read as optional. The reverse leak (a preference turning
        the rest of the page into requirements) is just as expensive.
        """
        required, preferred, _ = requirements_evidence(
            "Nice to have: Docker.\nKubernetes runs our cluster.")
        assert required == []
        assert _classes(preferred) == [(("docker",), "preferred"),
                                       (("kubernetes",), "mention")]

    def test_bare_preferred_heading_persists_for_its_block(self):
        _, preferred, _ = requirements_evidence(
            "Nice to have:\nDocker\nRust")
        assert _classes(preferred) == [(("docker",), "preferred"),
                                       (("rust",), "preferred")]

    def test_stack_heading_is_a_mention(self):
        required, preferred, facts = requirements_evidence(
            "Our stack:\nPython\nPostgreSQL")
        assert required == []
        assert _classes(preferred) == [(("postgresql",), "mention"),
                                       (("python",), "mention")]
        assert facts["requirements"]["count"]["mention"] == 2

    def test_responsibilities_heading_is_not_a_requirement(self):
        required, preferred, facts = requirements_evidence(
            "Responsibilities:\nBuild APIs with Python")
        assert required == []
        assert _classes(preferred) == [(("python",), "responsibility")]
        assert facts["requirements"]["count"]["responsibility"] == 1

    def test_modality_without_section_is_still_required(self):
        required, _, facts = requirements_evidence("You must know Python.")
        assert _classes(required) == [(("python",), "required")]
        assert facts["requirements"]["section_found"] is False

    def test_bare_technology_without_modality_is_only_a_mention(self):
        required, preferred, _ = requirements_evidence("Python")
        assert required == []
        assert _classes(preferred) == [(("python",), "mention")]

    def test_new_heading_resets_the_previous_block(self):
        """"Benefits:" ends the requirements block; Python there is a perk."""
        required, preferred, _ = requirements_evidence(
            "Requirements:\nPython\nBenefits:\nPython and Docker")
        assert _classes(required) == [(("python",), "required")]
        assert _classes(preferred) == [(("docker",), "mention"),
                                       (("python",), "mention")]

    def test_optional_marker_demotes_inside_a_required_block(self):
        required, preferred, _ = requirements_evidence(
            "Requirements:\n- Python\n- Optional: Docker")
        assert _classes(required) == [(("python",), "required")]
        assert _classes(preferred) == [(("docker",), "optional")]

    def test_required_bucket_never_holds_a_mention(self):
        """Only class == "required" may create a coverage gap."""
        required, _, _ = requirements_evidence(
            "Requirements:\nPython\nOur stack: Go, Rust")
        assert [i["class"] for i in required] == ["required"]

    def test_negated_requirement_is_recorded_not_counted(self):
        required, _, facts = requirements_evidence(
            "Requirements:\n- Python\n- No Kubernetes experience required")
        assert [i["alternatives"] for i in required] == [["python"]]
        assert facts.get("negations")


# ── D2: description completeness ───────────────────────────────────────────


def _completeness(description: str) -> dict:
    return extract_matching_evidence(
        {"job_title": "Backend Engineer", "description": description})


class TestDescriptionCompleteness:
    def test_empty_description_is_reported_as_absent(self):
        e = _completeness("")
        c = e["description_completeness"]
        assert c["description_present"] is False
        assert c["description_length"] == 0
        assert c["requirements_section_found"] is False
        assert c["extraction_confidence"] == "none"
        assert e["requirements"]["complete"] is False

    def test_prose_only_posting_is_not_complete(self):
        e = _completeness("We are a fast-growing startup with free lunch.")
        c = e["description_completeness"]
        assert c["description_present"] is True
        assert c["requirements_section_found"] is False
        assert c["requirements_count"]["required"] == 0
        assert c["extraction_confidence"] == "none"
        assert e["requirements"]["complete"] is False

    def test_terse_posting_with_a_heading_is_complete(self):
        e = _completeness("Requirements:\nPython")
        c = e["description_completeness"]
        assert c["requirements_section_found"] is True
        assert c["requirements_count"]["required"] == 1
        assert c["extraction_confidence"] == "requirements_section"
        assert e["requirements"]["complete"] is True

    def test_full_posting_reports_every_class(self):
        description = (
            "About us: we build things.\n\n"
            "Requirements:\n- 5+ years Python\n- Experience with PostgreSQL\n\n"
            "Nice to have:\n- Docker\n\n"
            "Benefits: remote work")
        e = _completeness(description)
        c = e["description_completeness"]
        assert c["requirements_section_found"] is True
        assert c["requirements_count"]["required"] == 2
        assert c["requirements_count"]["preferred"] == 1
        assert c["requirements_count"]["mention"] == 0
        # "Benefits: remote work" is a perk, not a requirement.
        assert all("remote" not in i["alternatives"]
                   for i in e["requirements"]["required"])
        assert e["requirements"]["complete"] is True

    def test_modality_only_posting_is_not_complete(self):
        """Requirement wording without a heading is weaker evidence."""
        e = _completeness("Experience with Kubernetes and Docker.")
        c = e["description_completeness"]
        assert c["requirements_section_found"] is False
        assert c["requirements_count"]["required"] == 2
        assert c["extraction_confidence"] == "modality_only"
        assert e["requirements"]["complete"] is False


# ── D4: a city is not a work location ──────────────────────────────────────


class TestJobCountryIsNotAHQ:
    def test_hq_sentence_does_not_win_over_the_role_location(self):
        out = job_country_from_text(
            "Our HQ is in Austin, Texas. The role is based in Berlin, Germany.")
        assert list(out) == ["germany"]
        assert out["germany"]["city"] == "berlin"

    def test_hq_only_posting_has_no_job_country(self):
        assert job_country_from_text("Our HQ is in Austin, Texas.") == {}

    def test_travel_sentence_is_not_a_work_location(self):
        assert job_country_from_text(
            "Our team meets twice a year in Berlin, and our HQ is in Austin."
        ) == {}

    def test_office_visits_are_not_a_work_location(self):
        assert job_country_from_text(
            "We have offices in London. You will visit the Munich office "
            "quarterly.") == {}

    def test_structured_location_tag_beats_travel_prose(self):
        out = job_country_from_text(
            "We meet twice a year in Austin.", location_tags="Berlin")
        assert list(out) == ["germany"]
        assert out["germany"]["field"] == "location_tags"

    def test_location_label_is_accepted(self):
        out = job_country_from_text("Location: Berlin\nWe build developer tools.")
        assert list(out) == ["germany"]
        assert out["germany"]["city"] == "berlin"

    def test_earliest_city_wins_not_the_first_gazetteer_entry(self):
        out = job_country_from_text(
            "We are hiring in San Francisco. We also hire in Berlin.")
        assert list(out) == ["united_states"]
        assert out["united_states"]["city"] == "san francisco"

    def test_title_city_is_accepted(self):
        out = job_country_from_text("", title="Backend Engineer - Berlin")
        assert list(out) == ["germany"]
        assert out["germany"]["field"] == "title"

    def test_worker_permission_is_never_a_job_country(self):
        assert job_country_from_text(
            "Open to candidates in the EEA. Work from anywhere.") == {}


# ── D5: every location fact carries its own source ─────────────────────────


class TestLocationProvenance:
    def test_location_tags_only_posting_keeps_its_country(self):
        job = {"job_title": "Backend Engineer", "location_tags": ["Bangalore"],
               "description": "We build developer tools."}
        e = extract_matching_evidence(job)
        assert e["job_country"] == "india"
        one_fact = e["facts"]["job_country"]["india"]
        assert one_fact["field"] == "location_tags"
        assert one_fact["source_field"] == "location_tags"
        assert one_fact["source_value"] == "india"
        assert one_fact["extraction_method"] == "gazetteer"
        assert verify(one_fact, "Bangalore")
        # The tag is not in the combined title/location/description blob, which
        # is exactly why verifying against that blob silently dropped it.
        assert verify(one_fact, "Backend Engineer\n\nWe build developer tools.") is False

    def test_url_slug_only_posting_keeps_its_country(self):
        job = {"job_title": "Backend Engineer",
               "apply_url": "https://jobs.example.com/berlin/eng-1",
               "description": "We build developer tools."}
        e = extract_matching_evidence(job)
        assert e["job_country"] == "germany"
        one_fact = e["facts"]["job_country"]["germany"]
        assert one_fact["field"] == "url_slug"
        assert verify(one_fact, job["apply_url"])
        assert e["job_city"] == "berlin"

    def test_timezone_field_names_the_city(self):
        job = {"job_title": "Backend Engineer", "timezone": "Asia/Kolkata",
               "description": "We build developer tools."}
        e = extract_matching_evidence(job)
        assert e["job_country"] == "india"
        one_fact = e["facts"]["job_country"]["india"]
        assert one_fact["field"] == "tz_field"
        assert verify(one_fact, job["timezone"])

    def test_no_location_evidence_stays_unknown(self):
        e = extract_matching_evidence(
            {"job_title": "Backend Engineer",
             "description": "We build developer tools."})
        assert "job_country" not in e
