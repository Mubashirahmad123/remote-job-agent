"""Regression tests for LLM markdown job extraction + string-field sanitization.

2026-10-17: a dashboard scrape died with ``AttributeError: 'list' object has
no attribute 'strip'`` after ``Crawl4AI-JustRemote`` — the model answered the
extraction prompt with ``"tech_stack": ["Python", "Docker"]``-style arrays and
``is_valid_dev_job()`` called ``.strip()`` on the list. Extraction now coerces
every field to text at the LLM boundary, and curator sanitization flattens
anything non-string as defense in depth.
"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agents.gemini_tools as gemini_tools
from agents.curator import sanitize_string_fields
from agents.gemini_tools import (
    _coerce_text,
    _normalize_extracted_job,
    extract_jobs_from_markdown,
)
from agents.scrapper import is_valid_dev_job
from tools.deduplicator import job_fingerprint


class TestCoerceText:
    def test_none_becomes_empty(self):
        assert _coerce_text(None) == ""

    def test_string_passthrough_and_trim(self):
        assert _coerce_text("  Backend Dev  ") == "Backend Dev"

    def test_list_joined_with_commas(self):
        assert _coerce_text(["Python", "Docker"]) == "Python, Docker"

    def test_nested_list_flattened(self):
        assert _coerce_text(["Python", ["AWS", None], "SQL"]) == "Python, AWS, SQL"

    def test_dict_values_flattened(self):
        assert _coerce_text({"min": 100, "max": 200}) == "100, 200"

    def test_scalar_stringified(self):
        assert _coerce_text(42) == "42"


class TestNormalizeExtractedJob:
    def test_non_dict_becomes_empty(self):
        assert _normalize_extracted_job("oops") == {}
        assert _normalize_extracted_job(None) == {}

    def test_fields_coerced_to_schema(self):
        job = _normalize_extracted_job({
            "job_title": "Backend Developer",
            "tech_stack": ["Python", "Docker"],
            "summary": ["Build APIs", "Own services"],
            "salary": None,
            "rogue_field": "dropped",
        })
        assert job["tech_stack"] == "Python, Docker"
        assert job["summary"] == "Build APIs, Own services"
        assert job["salary"] == ""
        assert "rogue_field" not in job
        assert set(job) == set(gemini_tools.JOB_EXTRACT_FIELDS)


class TestExtractJobsFromMarkdown:
    def _patch_llm(self, monkeypatch, raw):
        monkeypatch.setattr(
            gemini_tools, "generate_with_fallback", lambda prompt, task=None: raw
        )

    def test_list_typed_fields_survive_extraction(self, monkeypatch):
        raw = json.dumps([{
            "job_title": "Backend Developer",
            "company": "Acme",
            "tech_stack": ["Python", "Docker"],
            "summary": ["Build APIs", "Own services"],
            "salary": None,
            "apply_url": "https://example.com/jobs/1",
        }])
        self._patch_llm(monkeypatch, raw)
        jobs = extract_jobs_from_markdown("some page markdown")
        assert len(jobs) == 1
        assert all(isinstance(v, str) for v in jobs[0].values())

    def test_fenced_and_non_array_responses(self, monkeypatch):
        self._patch_llm(monkeypatch, '```json\n{"jobs": []}\n```')
        assert extract_jobs_from_markdown("md") == []
        self._patch_llm(monkeypatch, '"not an array"')
        assert extract_jobs_from_markdown("md") == []

    def test_empty_markdown_short_circuits(self, monkeypatch):
        def _boom(prompt, task=None):
            raise AssertionError("LLM must not be called for empty markdown")

        monkeypatch.setattr(gemini_tools, "generate_with_fallback", _boom)
        assert extract_jobs_from_markdown("") == []


class TestSanitizeStringFields:
    def test_none_becomes_empty_string(self):
        jobs = [{"job_title": None}]
        sanitize_string_fields(jobs)
        assert jobs[0]["job_title"] == ""

    def test_list_flattened_in_place(self):
        jobs = [{"tech_stack": ["Python", "Docker"], "summary": ["a", None, "b"]}]
        sanitize_string_fields(jobs)
        assert jobs[0]["tech_stack"] == "Python, Docker"
        assert jobs[0]["summary"] == "a, b"

    def test_scalar_stringified(self):
        jobs = [{"salary": 75000}]
        sanitize_string_fields(jobs)
        assert jobs[0]["salary"] == "75000"

    def test_non_dict_rows_ignored(self):
        sanitize_string_fields(["not-a-job", None])
        # No raise; nothing to assert beyond not crashing.


class TestPipelineSurvivesListTypedFields:
    """The exact crash path: extraction output fed to filter + dedup."""

    def test_filter_and_fingerprint_accept_sanitized_job(self):
        jobs = [{
            "job_title": "Backend Developer",
            "company": "Acme",
            "tech_stack": ["Python", "Docker"],
            "summary": ["Build APIs"],
            "apply_url": "https://example.com/jobs/1?utm=x",
        }]
        sanitize_string_fields(jobs)
        assert is_valid_dev_job(jobs[0]) is True
        assert job_fingerprint(jobs[0])
