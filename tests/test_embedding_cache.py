"""The embedding cache is JSON, and nothing in the repo unpickles (L2).

`tools/embedding_matcher.py` read its cache with `pickle.load`, from a path taken
from `CV_EMBEDDINGS_PATH` in `.env` and defaulting to `cv_embeddings.pkl` in the
repo root — a writable location. `pickle.load` runs whatever `__reduce__` the
file names, with the privileges of whoever reads it, so anyone able to place a
file there (a shared volume, a restored backup, a different vulnerability, a
planted artifact in a PR) got code execution the next time curation scored a job.

The cache is `{section name: [float, ...]}` — pure data. The pickle bought
nothing but the execution. It is JSON now, and this was the ONLY
pickle/eval/exec sink in the repo; the scan at the bottom fails if one comes
back anywhere in `api/`, `agents/` or `tools/`.

Honest severity: `sentence-transformers` and `faiss` are commented out in
requirements.txt, so in the shipped image `SENTENCE_AVAILABLE` is False, nothing
ever writes the cache, and reaching this code needs the optional extra installed
first. That is why this was ranked Low rather than High — and why it was still
worth fixing, because the fix is free and the sink was real the moment anyone
followed the README's "pip install sentence-transformers faiss-cpu".

The tests below need `pickle` to BUILD an attack payload. That is the point: the
payload is written by the test and must not be executed by the code under test.
"""

import ast
import json
import os
import pickle
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.embedding_matcher import (
    CV_EMBEDDINGS_PATH,
    load_cv_embeddings,
    save_cv_embeddings,
)

REPO = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("api", "agents", "tools")

EMBEDDINGS = {
    "experience": [0.1, -0.25, 3.5, 0.0, 1e-17, 2.0 ** 0.5],
    "skills": [1.0, 2.0, 3.0],
    "education": [-0.0, 123456789.123456789],
}


# --- the payload -------------------------------------------------------------


def _write_marker(path):
    """Module-level so pickle can reference it by qualified name."""
    Path(path).write_text("arbitrary code ran")


class _Exploit:
    """Unpickling this runs `_write_marker`, which is how pickle achieves code
    execution: `__reduce__` names a callable and its arguments."""

    def __init__(self, marker):
        self.marker = str(marker)

    def __reduce__(self):
        return (_write_marker, (self.marker,))


def test_the_payload_really_would_execute(tmp_path):
    """Guard against a vacuous test.

    If this payload would not run under `pickle.loads`, then
    `test_a_hostile_pickle_at_the_cache_path_does_not_execute` proves nothing no
    matter what the code under test does — it would pass against the old,
    vulnerable implementation too. Asserting the attack works is what makes the
    next test meaningful, and it is why the negative control below is a permanent
    test rather than a one-off check.
    """
    marker = tmp_path / "control.txt"
    pickle.loads(pickle.dumps(_Exploit(marker)))
    assert marker.exists(), "the payload is inert; the exploit tests are vacuous"


def test_a_hostile_pickle_at_the_cache_path_does_not_execute(tmp_path):
    """Named `.json`, so this is about the CONTENT and not about a suffix check.
    A loader that only refused `.pkl` would still unpickle this."""
    marker = tmp_path / "pwned.txt"
    cache = tmp_path / "cv_embeddings.json"
    cache.write_bytes(pickle.dumps(_Exploit(marker)))

    assert load_cv_embeddings(cache) is None
    assert not marker.exists(), "the cache file executed code while being loaded"


def test_a_hostile_pickle_with_the_legacy_name_does_not_execute(tmp_path):
    marker = tmp_path / "pwned.txt"
    cache = tmp_path / "cv_embeddings.pkl"
    cache.write_bytes(pickle.dumps(_Exploit(marker)))

    assert load_cv_embeddings(cache) is None
    assert not marker.exists()


def test_no_module_in_the_app_unpickles_anything():
    """The generalized version of the finding: no pickle, marshal, shelve, eval,
    exec or unsafe yaml.load anywhere in the shipped code.

    An AST walk rather than a grep, because a grep for `eval(` also matches
    docstrings and comments — including the ones in this very file explaining
    what used to be wrong.
    """
    forbidden = {
        "pickle.load", "pickle.loads", "pickle.Unpickler",
        "marshal.load", "marshal.loads",
        "shelve.open",
        "dill.load", "dill.loads",
        "eval", "exec", "compile",
    }
    offenders = []
    for directory in SCANNED_DIRS:
        for path in sorted((REPO / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    owner = func.value
                    prefix = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
                    name = f"{prefix}.{func.attr}"
                else:
                    continue
                if name in forbidden:
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno} {name}()")
    assert not offenders, (
        "these calls can execute arbitrary code from data:\n  " + "\n  ".join(offenders)
    )


def test_yaml_is_never_loaded_unsafely():
    """`yaml.load` without SafeLoader is the same class of bug as pickle.load.
    Checked separately because the call is legal with a Loader argument."""
    for directory in SCANNED_DIRS:
        for path in sorted((REPO / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "load"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "yaml"
                ):
                    continue
                loaders = [
                    kw.value.id for kw in node.keywords if kw.arg in ("Loader", "loader")
                ]
                assert loaders and all(x.endswith("SafeLoader") for x in loaders), (
                    f"{path.relative_to(REPO)}:{node.lineno} calls yaml.load "
                    "without a SafeLoader"
                )


# --- the replacement format --------------------------------------------------


def test_round_trip_is_exact(tmp_path):
    target = tmp_path / "cv_embeddings.json"
    save_cv_embeddings(EMBEDDINGS, target)
    assert load_cv_embeddings(target) == EMBEDDINGS


def test_floats_survive_the_round_trip_bit_for_bit(tmp_path):
    """Python's json encoder writes floats with repr(), the shortest string that
    parses back to the same double, so cosine similarity does not drift between
    the run that built the cache and the one that reads it."""
    target = tmp_path / "cv_embeddings.json"
    save_cv_embeddings(EMBEDDINGS, target)
    reloaded = load_cv_embeddings(target)
    for section, vector in EMBEDDINGS.items():
        for original, restored in zip(vector, reloaded[section]):
            assert repr(original) == repr(restored), f"{section}: {original!r} != {restored!r}"


def test_the_cache_is_written_as_readable_json(tmp_path):
    target = tmp_path / "cv_embeddings.json"
    save_cv_embeddings(EMBEDDINGS, target)
    assert json.loads(target.read_text()) == EMBEDDINGS
    assert not target.read_bytes().startswith(b"\x80"), "that is a pickle, not JSON"


def test_saving_creates_a_missing_parent_directory(tmp_path):
    target = tmp_path / "nested" / "deeper" / "cv_embeddings.json"
    save_cv_embeddings(EMBEDDINGS, target)
    assert load_cv_embeddings(target) == EMBEDDINGS


def test_the_default_path_is_json_not_pickle():
    assert CV_EMBEDDINGS_PATH.suffix == ".json", CV_EMBEDDINGS_PATH
    assert CV_EMBEDDINGS_PATH.name == "cv_embeddings.json"


# --- degradation must be quiet but not silent --------------------------------


def test_a_missing_cache_returns_none(tmp_path):
    assert load_cv_embeddings(tmp_path / "absent.json") is None


def test_malformed_json_returns_none_instead_of_raising(tmp_path):
    """Callers treat None as "score by keyword". An exception here would take the
    curation run down over a corrupt cache file."""
    target = tmp_path / "cv_embeddings.json"
    target.write_text("{not json at all")
    assert load_cv_embeddings(target) is None


@pytest.mark.parametrize(
    "payload",
    [
        "[1, 2, 3]",                     # a list, not a dict
        '"a string"',                    # a scalar
        '{"skills": "not a vector"}',    # vector is a string
        '{"skills": {"a": 1}}',          # vector is a dict
        '{"skills": [1, "two", 3]}',     # vector mixes types
        '{"skills": [1, true, 3]}',      # bools are ints in Python but not vectors
        '{"skills": null}',
    ],
)
def test_a_wrongly_shaped_cache_is_rejected(tmp_path, payload):
    """score_semantic() iterates the values as vectors, so a wrong shape would
    fail deep inside the scorer with an error that never mentions this file."""
    target = tmp_path / "cv_embeddings.json"
    target.write_text(payload)
    assert load_cv_embeddings(target) is None


def test_an_empty_cache_is_accepted(tmp_path):
    """{} is well formed and means "no sections embedded"; score_semantic already
    treats a falsy mapping as unavailable, so it must not be rewritten to None."""
    target = tmp_path / "cv_embeddings.json"
    target.write_text("{}")
    assert load_cv_embeddings(target) == {}


def test_a_legacy_pickle_is_reported_rather_than_quietly_ignored(tmp_path, capsys):
    """The failure mode this has to avoid: an operator upgrades with a working
    cache, semantic matching silently becomes keyword-only, and nothing says why.
    That is the exact degradation README warns about, caused by our own change."""
    legacy = tmp_path / "cv_embeddings.pkl"
    legacy.write_bytes(pickle.dumps(EMBEDDINGS))
    assert load_cv_embeddings(legacy) is None
    output = capsys.readouterr().out
    assert "legacy pickle" in output.lower(), output
    assert "python -m tools.embedding_matcher" in output, (
        "the warning must say how to rebuild, not just that something is wrong"
    )


def test_a_benign_pickle_is_still_refused(tmp_path, capsys):
    """Not a question of whether the file is hostile — the loader must not be
    able to run code at all, so even our own old output is not read back."""
    legacy = tmp_path / "cv_embeddings.pkl"
    legacy.write_bytes(pickle.dumps(EMBEDDINGS))
    assert load_cv_embeddings(legacy) is None


# --- configuration -----------------------------------------------------------


def test_the_env_override_still_resolves(tmp_path, monkeypatch):
    """The path was always configurable and stays so; only the format changed."""
    import importlib

    import tools.embedding_matcher as matcher

    monkeypatch.setenv("CV_EMBEDDINGS_PATH", str(tmp_path / "custom.json"))
    importlib.reload(matcher)
    try:
        assert matcher.CV_EMBEDDINGS_PATH == tmp_path / "custom.json"
        matcher.save_cv_embeddings(EMBEDDINGS)
        assert matcher.load_cv_embeddings() == EMBEDDINGS
    finally:
        monkeypatch.delenv("CV_EMBEDDINGS_PATH", raising=False)
        importlib.reload(matcher)


def test_a_relative_override_resolves_against_the_repo_root(monkeypatch):
    import importlib

    import tools.embedding_matcher as matcher

    monkeypatch.setenv("CV_EMBEDDINGS_PATH", "cache/embeddings.json")
    importlib.reload(matcher)
    try:
        assert matcher.CV_EMBEDDINGS_PATH == matcher.BASE_DIR / "cache" / "embeddings.json"
    finally:
        monkeypatch.delenv("CV_EMBEDDINGS_PATH", raising=False)
        importlib.reload(matcher)
