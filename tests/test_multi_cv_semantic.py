"""Per-CV semantic routing and cache invalidation, with no models/network/Sheets.

CV files are text fixtures at the extract_cv_text boundary; the real cache,
CVLibrary selection and curate pipeline run. Numerical FAISS integration is
covered separately when that optional dependency is installed.
"""

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import embedding_matcher as em


@pytest.fixture
def semantic(tmp_path, monkeypatch):
    """Deterministic encoder/extractor: never download a model or parse with LLM."""
    from tools import cv_parser

    calls = []
    extracted = []

    def extract(path):
        extracted.append(path)
        return Path(path).read_text(encoding="utf-8")

    def compute(text):
        calls.append((text, em.EMBEDDING_MODEL))
        return {"skills": [float(len(text)), 1.0]}

    monkeypatch.setattr(em, "SENTENCE_AVAILABLE", True)
    monkeypatch.setattr(em, "FAISS_AVAILABLE", True)
    monkeypatch.setattr(em, "EMBEDDING_MODEL", "test-model")
    monkeypatch.setattr(em, "EMBEDDING_CACHE_DIR", tmp_path / "embeddings")
    monkeypatch.setattr(em, "compute_cv_embeddings", compute)
    monkeypatch.setattr(cv_parser, "extract_cv_text", extract)
    cv = tmp_path / "cv_backend.pdf"
    cv.write_text("Python FastAPI", encoding="utf-8")
    return SimpleNamespace(cv=cv, calls=calls, extracted=extracted)


def test_same_cv_reuses_memory_and_persisted_cache(semantic):
    cache = em.CVEmbeddingCache()
    expected = cache.get(semantic.cv)
    assert cache.get(semantic.cv) == expected
    assert em.CVEmbeddingCache().get(semantic.cv) == expected
    assert len(semantic.calls) == len(semantic.extracted) == 1
    payload = json.loads(cache.cache_path(semantic.cv).read_text(encoding="utf-8"))
    assert payload["identity"]["model"] == "test-model"
    assert payload["embeddings"] == expected
    assert semantic.cv.read_text(encoding="utf-8") not in json.dumps(payload)


def test_same_filename_in_different_folders_has_separate_slots(semantic, tmp_path):
    second = tmp_path / "other" / semantic.cv.name
    second.parent.mkdir()
    second.write_text("React", encoding="utf-8")
    cache = em.CVEmbeddingCache()
    assert cache.get(semantic.cv) != cache.get(second)
    assert cache.cache_path(semantic.cv) != cache.cache_path(second)
    assert len(semantic.calls) == 2


@pytest.mark.parametrize("new_instance", [False, True])
def test_content_edit_invalidates_even_if_size_and_mtime_unchanged(semantic, new_instance):
    cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    stat = semantic.cv.stat()
    semantic.cv.write_text("React frontend", encoding="utf-8")  # same byte count
    assert semantic.cv.stat().st_size == stat.st_size
    os.utime(semantic.cv, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    if new_instance:
        cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    assert len(semantic.calls) == 2
    assert semantic.calls[-1][0] == "React frontend"
    assert len(list(cache.cache_dir.glob("*.json"))) == 1  # replace old slot


@pytest.mark.parametrize("new_instance", [False, True])
def test_model_change_invalidates_memory_and_disk(semantic, monkeypatch, new_instance):
    cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    monkeypatch.setattr(em, "EMBEDDING_MODEL", "different-model")
    if new_instance:
        cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    assert [model for _, model in semantic.calls] == ["test-model", "different-model"]


def test_schema_change_invalidates_cache(semantic, monkeypatch):
    cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    monkeypatch.setattr(em, "EMBEDDING_CACHE_VERSION", 2)
    cache.get(semantic.cv)
    assert len(semantic.calls) == 2


@pytest.mark.parametrize("payload", ["{invalid", "[]", '{"skills": [1, 2]}', '\u0080pickle'])
def test_corrupt_or_unattributed_legacy_cache_is_rebuilt(semantic, payload):
    cache = em.CVEmbeddingCache()
    target = cache.cache_path(semantic.cv)
    target.parent.mkdir()
    target.write_text(payload, encoding="utf-8")
    assert cache.get(semantic.cv)
    assert len(semantic.calls) == 1
    assert json.loads(target.read_text(encoding="utf-8"))["identity"]


@pytest.mark.parametrize("vectors", [
    {}, [], {"skills": []}, {"skills": [True]}, {"skills": ["bad"]},
    {"skills": [float("nan")]}, {"skills": [float("inf")]},
    {"skills": [1, 2], "experience": [1]},
])
def test_invalid_disk_vectors_are_rebuilt(semantic, vectors):
    cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    target = cache.cache_path(semantic.cv)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["embeddings"] = vectors
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert em.CVEmbeddingCache().get(semantic.cv)
    assert len(semantic.calls) == 2


def test_wrong_cv_identity_is_not_reused(semantic):
    cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    target = cache.cache_path(semantic.cv)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["identity"]["cv_sha256"] = "different-file"
    target.write_text(json.dumps(payload), encoding="utf-8")
    em.CVEmbeddingCache().get(semantic.cv)
    assert len(semantic.calls) == 2


def test_failed_rebuild_never_returns_old_vectors_and_retries_next_run(semantic, monkeypatch, capsys):
    cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    semantic.cv.write_text("Changed CV", encoding="utf-8")
    compute = em.compute_cv_embeddings

    def fail(text):
        raise RuntimeError("secret CV content must not appear in logs")

    monkeypatch.setattr(em, "compute_cv_embeddings", fail)
    assert cache.get(semantic.cv) is None
    assert cache.get(semantic.cv) is None
    output = capsys.readouterr().out
    assert output.count("embedding failed") == 1
    assert "keyword-only" in output
    assert "secret CV content" not in output
    monkeypatch.setattr(em, "compute_cv_embeddings", compute)
    assert em.CVEmbeddingCache().get(semantic.cv)
    assert len(semantic.calls) == 2


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_extraction_does_not_embed(semantic, monkeypatch, empty):
    from tools import cv_parser

    monkeypatch.setattr(cv_parser, "extract_cv_text", lambda path: empty)
    assert em.CVEmbeddingCache().get(semantic.cv) is None
    assert not semantic.calls


def test_missing_file_does_not_reuse_cached_vectors(semantic):
    cache = em.CVEmbeddingCache()
    cache.get(semantic.cv)
    semantic.cv.unlink()
    assert cache.get(semantic.cv) is None
    assert em.CVEmbeddingCache().get(semantic.cv) is None


@pytest.mark.parametrize("dependency", ["SENTENCE_AVAILABLE", "FAISS_AVAILABLE"])
def test_missing_optional_dependency_is_keyword_only(semantic, monkeypatch, dependency, capsys):
    monkeypatch.setattr(em, dependency, False)
    cache = em.CVEmbeddingCache()
    assert cache.get(semantic.cv) is None
    assert cache.get(semantic.cv) is None
    assert not semantic.calls
    assert capsys.readouterr().out.count("keyword-only") == 1


def test_read_only_cache_still_uses_in_memory_vectors(semantic, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise PermissionError("read only")

    monkeypatch.setattr(em.tempfile, "NamedTemporaryFile", fail)
    cache = em.CVEmbeddingCache()
    assert cache.get(semantic.cv)
    assert cache.get(semantic.cv)
    assert len(semantic.calls) == 1
    assert "in-memory" in capsys.readouterr().out


def test_atomic_replace_failure_cleans_temp_file(semantic, monkeypatch):
    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(em.os, "replace", fail)
    cache = em.CVEmbeddingCache()
    assert cache.get(semantic.cv)
    assert not list(cache.cache_dir.iterdir())


def test_file_changing_during_encoding_is_not_cached(semantic, monkeypatch):
    original = em.compute_cv_embeddings

    def mutate(text):
        semantic.cv.write_text("Edited while encoding", encoding="utf-8")
        return original(text)

    monkeypatch.setattr(em, "compute_cv_embeddings", mutate)
    cache = em.CVEmbeddingCache()
    assert cache.get(semantic.cv) is None
    assert not cache.cache_path(semantic.cv).exists()


def test_relative_paths_resolve_against_project_root(semantic, monkeypatch):
    monkeypatch.setattr(em, "BASE_DIR", semantic.cv.parent)
    cache = em.CVEmbeddingCache()
    assert cache.get(semantic.cv.name)
    assert cache.cache_path(semantic.cv.name) == cache.cache_path(semantic.cv)


def test_model_object_is_reloaded_when_model_name_changes(monkeypatch):
    models = []

    def constructor(name):
        models.append(name)
        return object()

    monkeypatch.setattr(em, "SENTENCE_AVAILABLE", True)
    monkeypatch.setattr(em, "SentenceTransformer", constructor, raising=False)
    monkeypatch.setattr(em, "_model", None)
    monkeypatch.setattr(em, "_model_name", None)
    monkeypatch.setattr(em, "EMBEDDING_MODEL", "first")
    first = em._get_model()
    assert em._get_model() is first
    monkeypatch.setattr(em, "EMBEDDING_MODEL", "second")
    assert em._get_model() is not first
    assert models == ["first", "second"]


def test_file_builder_seeds_managed_cache_and_preserves_legacy_export(semantic, monkeypatch, tmp_path):
    target = tmp_path / "legacy.json"
    monkeypatch.setattr(em, "CV_EMBEDDINGS_PATH", target)
    assert em.build_cv_index_from_file(str(semantic.cv)) == target
    assert em.load_cv_embeddings(target) == em.CVEmbeddingCache().get(semantic.cv)
    assert len(semantic.calls) == 1


@pytest.fixture
def curator(monkeypatch):
    """Load curator privately with no on-disk CV/LLM setup or module-state leaks."""
    import dotenv
    from tools import cv_library

    monkeypatch.setenv("CV_PATH", "")
    monkeypatch.setenv("CV_DIR", "")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(cv_library, "_library", None)
    path = Path(__file__).resolve().parents[1] / "agents" / "curator.py"
    spec = importlib.util.spec_from_file_location("_curator_semantic_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "cleanup_sheet", lambda *a: None)
    monkeypatch.setattr(module, "get_all_rows", lambda: [])
    monkeypatch.setattr(module, "load_seen_hashes", set)
    monkeypatch.setattr(module, "save_seen_hashes", lambda *a: None)
    monkeypatch.setattr(module, "append_rows", lambda *a: None)
    monkeypatch.setattr(module, "is_allowed_location", lambda job: True)
    monkeypatch.setattr(module, "_should_reject", lambda job: (False, ""))
    monkeypatch.setattr(module, "CV_MATCHING_ENABLED", True)
    monkeypatch.setattr(module, "MIN_SCORE", 0)
    monkeypatch.setattr(module, "KEYWORD_WEIGHT", 0.6)
    monkeypatch.setattr(module, "SEMANTIC_WEIGHT", 0.4)
    return module


def jobs():
    return [
        {"job_title": "Python Backend Developer", "summary": "Python FastAPI PostgreSQL",
         "apply_url": "https://example.com/backend", "job_fingerprint": "backend"},
        {"job_title": "React Frontend Developer", "summary": "React JavaScript CSS",
         "apply_url": "https://example.com/frontend", "job_fingerprint": "frontend"},
    ]


def run_curator(curator, job_list=None):
    # Passing a tracker avoids writing yield logs from the test.
    tracker = SimpleNamespace(stage=lambda *a: None)
    return curator.curate(job_list or jobs(), tracker=tracker)


def test_real_cv_selection_routes_each_jobs_own_vectors(curator, semantic, monkeypatch, tmp_path):
    from tools.cv_library import CVLibrary

    front = tmp_path / "cv_frontend.pdf"
    front.write_text("React JavaScript CSS", encoding="utf-8")
    library = CVLibrary(cv_dir=str(tmp_path))
    profiles = {
        str(semantic.cv): {"skills": ["Python", "FastAPI", "PostgreSQL"]},
        str(front): {"skills": ["React", "JavaScript", "CSS"]},
    }
    for entry in library.cvs:
        entry["profile"] = profiles[entry["path"]]
    monkeypatch.setattr(curator, "_CV_LIBRARY", library)
    monkeypatch.setattr(curator, "CV_PROFILE", profiles[str(front)])
    monkeypatch.setattr(curator, "cv_path", str(front))
    monkeypatch.setattr(curator, "SEMANTIC_AVAILABLE", True)
    seen = {}

    def score(job, embeddings):
        seen[job["job_fingerprint"]] = embeddings
        return 90 if job["job_fingerprint"] == "backend" else 70

    monkeypatch.setattr(curator, "score_semantic", score)
    result = run_curator(curator)
    assert result["status"] == "success"
    by_id = {job["job_fingerprint"]: job for job in result["top_jobs"]}
    assert by_id["backend"]["selected_cv_path"] == str(semantic.cv)
    assert by_id["frontend"]["selected_cv_path"] == str(front)
    assert seen["backend"] == {"skills": [float(len("Python FastAPI")), 1.0]}
    assert seen["frontend"] == {"skills": [float(len("React JavaScript CSS")), 1.0]}
    for fp, job in by_id.items():
        assert job["semantic_computed"] is True
        expected = 0.6 * job["keyword_score"] + 0.4 * job["semantic_score"]
        assert job["match_score"] == round(expected, 1)
    assert len(semantic.calls) == 2


@pytest.mark.parametrize("outcome", ["missing", "error", "unavailable", "disabled", "zero", "normal"])
def test_single_cv_fallback_and_score_renormalization(curator, semantic, monkeypatch, outcome):
    monkeypatch.setattr(curator, "cv_path", str(semantic.cv))
    monkeypatch.setattr(curator, "CV_PROFILE", {"skills": ["Python"]})
    monkeypatch.setattr(curator, "SEMANTIC_AVAILABLE", outcome != "disabled")
    monkeypatch.setattr(curator, "_get_matcher_for_profile", lambda *a: SimpleNamespace(
        score=lambda job: {"score": 80, "match_reason": "test"}))
    requested = []

    def get(path):
        requested.append(path)
        return None if outcome == "missing" else {"skills": [1, 0]}

    def score(job, embeddings):
        if outcome == "error":
            raise RuntimeError("scorer failed")
        return None if outcome == "unavailable" else (0 if outcome == "zero" else 50)

    monkeypatch.setattr(em.CVEmbeddingCache, "get", lambda self, path: get(path))
    monkeypatch.setattr(curator, "score_semantic", score)
    result = run_curator(curator, jobs()[:1])
    job = result["top_jobs"][0]
    if outcome in {"zero", "normal"}:
        assert job["semantic_computed"] is True
        assert job["semantic_score"] == (0 if outcome == "zero" else 50)
        assert job["match_score"] == (48 if outcome == "zero" else 68)
    else:
        assert job["semantic_computed"] is False
        assert job["semantic_score"] == ""
        assert job["match_score"] == 80
    assert requested == ([] if outcome == "disabled" else [str(semantic.cv)])


def test_selected_cv_failure_does_not_fall_back_to_primary(curator, semantic, monkeypatch, tmp_path):
    other = tmp_path / "primary.pdf"
    other.write_text("React", encoding="utf-8")
    monkeypatch.setattr(curator, "cv_path", str(other))
    monkeypatch.setattr(curator, "CV_PROFILE", {"skills": ["React"]})
    profile = {"skills": ["Python"]}
    monkeypatch.setattr(curator, "_CV_LIBRARY", SimpleNamespace(
        is_empty=False, pick_best=lambda job: (str(semantic.cv), profile, 80)))
    monkeypatch.setattr(curator, "SEMANTIC_AVAILABLE", True)
    requested = []

    def get(self, path):
        requested.append(path)
        return None

    monkeypatch.setattr(em.CVEmbeddingCache, "get", get)
    monkeypatch.setattr(curator, "score_semantic", lambda *a: pytest.fail("must not score"))
    job = run_curator(curator, jobs()[:1])["top_jobs"][0]
    assert requested == [str(semantic.cv)]
    assert job["selected_cv_path"] == str(semantic.cv)
    assert job["semantic_computed"] is False
    assert job["match_score"] == job["keyword_score"]


def test_no_cv_path_does_not_consult_unattributed_primary_cache(curator, monkeypatch):
    monkeypatch.setattr(curator, "CV_PROFILE", {"skills": ["Python"]})
    monkeypatch.setattr(curator, "SEMANTIC_AVAILABLE", True)
    monkeypatch.setattr(em.CVEmbeddingCache, "get", lambda *a: pytest.fail("no source CV"))
    job = run_curator(curator, jobs()[:1])["top_jobs"][0]
    assert job["semantic_computed"] is False


def test_managed_cache_directory_is_ignored_and_excluded_from_images():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "check-ignore", "cache/cv_embeddings/example.json"],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 0
    assert "cache/" in (root / ".dockerignore").read_text(encoding="utf-8").splitlines()


@pytest.fixture
def numeric_encoder(monkeypatch):
    """Real FAISS/cosine math, deterministic local encoder (no model download)."""
    faiss = pytest.importorskip("faiss")
    np = pytest.importorskip("numpy")
    monkeypatch.setattr(em, "faiss", faiss, raising=False)
    monkeypatch.setattr(em, "np", np, raising=False)
    monkeypatch.setattr(em, "SENTENCE_AVAILABLE", True)
    monkeypatch.setattr(em, "FAISS_AVAILABLE", True)
    model = SimpleNamespace(encode=lambda text: np.array([1.0, 0.0], dtype=np.float32))
    monkeypatch.setattr(em, "_get_model", lambda: model)
    return model


@pytest.mark.parametrize("vector,expected", [([1, 0], 100), ([0, 1], 50), ([-1, 0], 0)])
def test_actual_cosine_scoring_including_genuine_zero(numeric_encoder, vector, expected):
    result = em.score_semantic({"job_title": "Python developer"}, {"skills": vector})
    assert result == pytest.approx(expected)


def test_incompatible_dimensions_are_missing_not_a_computed_zero(numeric_encoder):
    assert em.score_semantic({"job_title": "Python"}, {"skills": [1, 0, 0]}) is None


def test_only_compared_sections_contribute_to_weight_denominator(numeric_encoder):
    result = em.score_semantic({"job_title": "Python"}, {
        "skills": [1, 0], "experience": [1, 0, 0],
    })
    assert result == pytest.approx(100)


def test_encoder_failure_is_missing_not_a_computed_zero(numeric_encoder):
    def fail(text):
        raise RuntimeError("encoding failed")

    numeric_encoder.encode = fail
    assert em.score_semantic({"job_title": "Python"}, {"skills": [1, 0]}) is None


def test_real_docx_extraction_builds_sections_without_parsing_llm(tmp_path, monkeypatch, numeric_encoder):
    docx = pytest.importorskip("docx")
    from tools import cv_parser

    monkeypatch.setattr(cv_parser, "parse_cv", lambda *a: pytest.fail("must not invoke LLM parsing"))
    path = tmp_path / "cv.docx"
    document = docx.Document()
    document.add_paragraph("Skills")
    document.add_paragraph("Python FastAPI")
    document.add_paragraph("Experience")
    document.add_paragraph("Built backend APIs")
    document.save(path)
    cache = em.CVEmbeddingCache(cache_dir=tmp_path / "cache")
    assert cache.get(path) == {"skills": [1.0, 0.0], "experience": [1.0, 0.0]}
    assert cache.cache_path(path).exists()


def test_cv_edit_invalidates_keyword_pick_and_profile_caches(semantic, monkeypatch, tmp_path):
    from tools import cv_parser
    from tools.cv_library import CVLibrary

    front = tmp_path / "cv_frontend.pdf"
    front.write_text("React CSS", encoding="utf-8")
    parsed = []

    def parse(path):
        parsed.append(path)
        return {"skills": Path(path).read_text(encoding="utf-8").split()}

    monkeypatch.setattr(cv_parser, "parse_cv", parse)
    library = CVLibrary(cv_dir=str(tmp_path))
    backend_job = jobs()[0]
    assert library.pick_best(backend_job)[0] == str(semantic.cv)
    assert len(parsed) == 2
    library.pick_best(backend_job)
    assert len(parsed) == 2
    semantic.cv.write_text("No relevant skills", encoding="utf-8")
    path, profile, _ = library.pick_best(backend_job)
    assert str(semantic.cv) in parsed[2:]
    backend_entry = next(e for e in library.cvs if e["path"] == str(semantic.cv))
    assert backend_entry["profile"]["skills"] == ["No", "relevant", "skills"]
    assert profile != {"skills": ["Python", "FastAPI"]}


def test_curator_keyword_matcher_is_replaced_when_profile_changes(curator):
    first = curator._get_matcher_for_profile({"skills": ["Python"]}, "same/path.pdf")
    assert curator._get_matcher_for_profile({"skills": ["Python"]}, "same/path.pdf") is first
    second = curator._get_matcher_for_profile({"skills": ["React"]}, "same/path.pdf")
    assert second is not first
    assert second.cv_profile == {"skills": ["React"]}
