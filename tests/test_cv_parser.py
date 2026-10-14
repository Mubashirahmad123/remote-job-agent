"""
tests/test_cv_parser.py

Regression tests for the 2026-10-03 incident: every LLM provider failed during
a CV parse, the exception was swallowed into `parsed = {}`, and the resulting
empty profile shell was cached as if it were a successful parse. That shell was
then trusted for days — every job scored 0 against an empty skill set, and
nothing distinguished "parsed successfully with empty data" from "parsing
failed".

The contract pinned here:

  * an empty shell (no name + no skills + no experience) is a FAILED parse,
  * it is never returned, never cached, and never trusted from an existing
    cache file (read-side guard),
  * `_save_cached_profile` refuses to persist one at all (write-side guard),
  * `parse_cv` raises `CVParseError` loudly instead, carrying the underlying
    provider-chain failure in the message,
  * sparse-but-real profiles (a name, say, but no skills/experience) are NOT
    rejected — the gate only fires when all three fields are empty,
  * curator re-raises `CVParseError` at startup so a configured-but-unparseable
    CV hard-stops the pipeline instead of running a doomed all-zero scrape.

Fully offline: LLM providers, text extraction and cache paths are all
monkeypatched. No network, no real PDF parsing, no writes outside tmp_path.
"""

import json
import pathlib

import pytest

import tools.cv_parser as parser
from tools.cv_parser import (
    CVParseError,
    _is_empty_shell,
    _load_cached_profile,
    _save_cached_profile,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

FAKE_CV_TEXT = "Mubashir Nazir — Full Stack Developer. Python, FastAPI, React."

VALID_PROFILE_JSON = json.dumps({
    "name": "Mubashir Nazir",
    "email": "mubashir@example.com",
    "location": "Lahore, Pakistan",
    "years_experience": 3,
    "skills": ["Python", "FastAPI", "React", "PostgreSQL"],
    "experience": [
        {
            "title": "Full Stack Developer",
            "company": "FastBeetle",
            "duration": "2023-2026",
            "description": "Built and shipped web platforms.",
        }
    ],
})


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point the cv_parser cache into tmp_path and stub text extraction.

    Returns (cv_path, cache_file) with every external touchpoint removed:
    no repo cache/ pollution, no pdfplumber, no real file reads.
    """
    cache_file = tmp_path / "cv_profile_test.json"
    monkeypatch.setattr(parser, "_get_cache_path", lambda cv_path: cache_file)
    monkeypatch.setattr(parser, "extract_cv_text", lambda cv_path: FAKE_CV_TEXT)
    return str(tmp_path / "my_cv.pdf"), cache_file


class TestEmptyShellNeverCached:
    """The exact Oct-3 failure shape: providers fail -> shell -> must raise."""

    def test_all_providers_failing_raises_and_never_caches(self, isolated, monkeypatch, capsys):
        cv_path, cache_file = isolated

        def _all_providers_down(prompt, task="cv_parsing"):
            raise Exception(
                "All LLMs failed: Gemini: 503; Groq: 429; Mistral: 500; "
                "GLM: timeout; Ollama: connection refused"
            )

        monkeypatch.setattr(parser, "_parse_with_llm", _all_providers_down)

        with pytest.raises(CVParseError) as exc:
            parser.parse_cv(cv_path)

        # The provider-chain failure rides along in the error — not swallowed.
        assert "All LLMs failed" in str(exc.value)
        # Nothing was cached: the failed parse left no poisoned file behind.
        assert not cache_file.exists()
        # The failure is loud on the console, not a "✅ parsed" success line.
        out = capsys.readouterr().out
        assert "refusing to cache" in out
        assert "Check LLM provider availability" in out

    def test_invalid_llm_json_raises_and_never_caches(self, isolated, monkeypatch):
        cv_path, cache_file = isolated
        monkeypatch.setattr(
            parser, "_parse_with_llm",
            lambda prompt, task="cv_parsing": "sorry, I cannot parse that",
        )

        with pytest.raises(CVParseError) as exc:
            parser.parse_cv(cv_path)

        assert "invalid JSON" in str(exc.value)
        assert not cache_file.exists()

    def test_unextractable_cv_raises_and_never_caches(self, isolated, monkeypatch):
        cv_path, cache_file = isolated
        monkeypatch.setattr(parser, "extract_cv_text", lambda cv_path: "")

        with pytest.raises(CVParseError) as exc:
            parser.parse_cv(cv_path)

        assert "Could not extract any text" in str(exc.value)
        assert not cache_file.exists()

    def test_save_cached_profile_refuses_empty_shell(self, isolated):
        cv_path, cache_file = isolated
        shell = parser._validate_profile({})  # the exact Oct-3 shape: all defaults

        with pytest.raises(CVParseError):
            _save_cached_profile(cv_path, shell)

        assert not cache_file.exists()

    def test_save_cached_profile_refuses_raw_empty_dict(self, isolated):
        cv_path, cache_file = isolated

        with pytest.raises(CVParseError):
            _save_cached_profile(cv_path, {})

        assert not cache_file.exists()


class TestPoisonedCacheNeverTrusted:
    """A shell that already sits on disk (e.g. written by older code) is a
    cache miss, never a valid profile — this is the read-side guard that
    would have killed the Oct-3 incident immediately."""

    def test_load_returns_none_for_shell_cache_file(self, isolated):
        cv_path, cache_file = isolated
        # Mimic the actual poisoned file: full key set, every field blank,
        # fresh timestamp so the <7-day age check does not save us.
        shell = parser._validate_profile({})
        shell["_parsed_at"] = "2026-10-03T17:21:09"
        cache_file.write_text(json.dumps(shell), encoding="utf-8")

        assert _load_cached_profile(cv_path) is None

    def test_parse_cv_re_parses_over_a_shell_cache(self, isolated, monkeypatch):
        cv_path, cache_file = isolated
        cache_file.write_text(json.dumps(parser._validate_profile({})), encoding="utf-8")
        monkeypatch.setattr(
            parser, "_parse_with_llm",
            lambda prompt, task="cv_parsing": VALID_PROFILE_JSON,
        )

        profile = parser.parse_cv(cv_path)  # use_cache=True is the default

        # The shell was NOT served; a real re-parse happened...
        assert profile["name"] == "Mubashir Nazir"
        # ...and the re-parse replaced the shell on disk.
        on_disk = json.loads(cache_file.read_text(encoding="utf-8"))
        assert on_disk["name"] == "Mubashir Nazir"


class TestValidProfilesStillWork:
    """The gate must not over-reject: real parses cache and load as before."""

    def test_valid_parse_caches_then_second_call_serves_from_cache(self, isolated, monkeypatch, capsys):
        cv_path, cache_file = isolated
        monkeypatch.setattr(
            parser, "_parse_with_llm",
            lambda prompt, task="cv_parsing": VALID_PROFILE_JSON,
        )

        first = parser.parse_cv(cv_path)
        assert first["name"] == "Mubashir Nazir"
        assert cache_file.exists()

        # Second call must come from cache: swap in a provider that would
        # fail the test if invoked.
        def _must_not_run(prompt, task="cv_parsing"):
            raise AssertionError("LLM must not be re-invoked on a cache hit")

        monkeypatch.setattr(parser, "_parse_with_llm", _must_not_run)
        second = parser.parse_cv(cv_path)
        assert second["name"] == "Mubashir Nazir"
        assert "Using cached CV profile" in capsys.readouterr().out

    def test_sparse_but_real_profile_is_not_rejected(self, isolated, monkeypatch):
        """A CV that yields a name but no skills/experience is sparse, not
        failed. `_is_empty_shell` requires ALL THREE fields empty."""
        cv_path, cache_file = isolated
        monkeypatch.setattr(
            parser, "_parse_with_llm",
            lambda prompt, task="cv_parsing": json.dumps({"name": "Mubashir Nazir"}),
        )

        profile = parser.parse_cv(cv_path)

        assert profile["name"] == "Mubashir Nazir"
        assert profile["skills"] == []
        assert cache_file.exists()  # sparse != failed, so it caches normally

    def test_is_empty_shell_requires_all_three_fields(self):
        assert _is_empty_shell(None) is True
        assert _is_empty_shell({}) is True
        assert _is_empty_shell(parser._validate_profile({})) is True
        assert _is_empty_shell({"name": "X"}) is False
        assert _is_empty_shell({"skills": ["Python"]}) is False
        assert _is_empty_shell({"experience": [{"company": "FastBeetle"}]}) is False


class TestCuratorHardStopsOnFailedParse:
    """curator must re-raise CVParseError at startup when a configured CV
    fails to parse. Degrading to 'matching disabled' would run a full scrape
    and drop every job with score 0 — the wasted-run pattern from the
    incident. Source-scan pin (same style as tests/test_glm_client.py):
    behavioural import-time tests here would drag in the whole pipeline."""

    def test_curator_re_raises_cv_parse_error(self):
        src = (REPO_ROOT / "agents" / "curator.py").read_text(encoding="utf-8")
        assert "except CVParseError:" in src, (
            "agents/curator.py must re-raise CVParseError at startup: a "
            "configured CV that fails to parse is a hard stop, not a "
            "degraded all-zero run (2026-10-03 incident)"
        )
