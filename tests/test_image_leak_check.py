"""The CI image-leak check must catch real leaks and nothing else (L2 follow-up).

Adding the pickle check to `.github/workflows/ci.yml` broke the build on the very
commit that added it. The pattern was `(^|/)[^/]+\\.pkl$` and the file list comes
from `docker export | tar -t`, which streams the ENTIRE container filesystem — so
it matched `.pkl` data files that pip installed inside `site-packages`, which are
not a leak from the developer's working tree at all.

The bug was not visible locally for a specific and embarrassing reason: the
virtualenv here does not install the heavy half of `requirements.txt` (no
chromadb, no crewai, no crawl4ai), so `find .venv -name '*.pkl'` returned zero
and looked like confirmation. It was a measurement of the wrong filesystem.

So the patterns are now pinned in BOTH directions, offline, against a synthetic
file list: each must match the leak it exists to catch, and none may match
anything legitimately present in the image. A pattern that is merely "probably
fine" is what shipped last time.

Two failure directions, and the second is worse:

  * false positive — red build on an innocent commit, which trains everyone to
    ignore or disable the check
  * false negative — a real credential baked into a published image layer, which
    survives every later `docker rm`

Both are asserted, and `test_a_pattern_that_matches_nothing_is_a_bug` exists
because the easy "fix" for a false positive is to loosen a pattern until it
matches nothing, which is indistinguishable from deleting the check.
"""

import os
import re
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO, ".github", "workflows", "ci.yml")
DOCKERIGNORE = os.path.join(REPO, ".dockerignore")

# `check "<label>" '<pattern>'` as written in the workflow.
CHECK_LINE = re.compile(r"""check\s+"(?P<label>[^"]+)"\s+'(?P<pattern>[^']+)'""")


def _leak_step():
    """The shell script of the docker job's leak-verification step."""
    with open(WORKFLOW, encoding="utf-8") as fh:
        workflow = yaml.safe_load(fh)
    steps = workflow["jobs"]["docker"]["steps"]
    for step in steps:
        if "leak" in str(step.get("name", "")).lower() or "baked into" in str(step.get("name", "")):
            return step["run"]
    raise AssertionError(f"no leak-verification step in the docker job: {[s.get('name') for s in steps]}")


def _patterns():
    """[(label, compiled-regex)] for every check in the step."""
    script = _leak_step()
    found = CHECK_LINE.findall(script)
    assert found, "no `check \"...\" '...'` lines found; the step's shape changed"
    return [(label, re.compile(pattern)) for label, pattern in found]


def _pattern_for(keyword):
    matches = [(label, rx) for label, rx in _patterns() if keyword.lower() in label.lower()]
    assert len(matches) == 1, (
        f"expected exactly one check matching {keyword!r}, got {[m[0] for m in matches]}"
    )
    return matches[0]


# Paths that legitimately exist in the exported image and must NEVER be reported.
# `docker export | tar -t` lists the whole filesystem with no leading slash, so
# these are the real shapes: the build context under app/, the interpreter and
# every installed package under usr/, and the OS underneath.
BENIGN = [
    # the application itself
    "app/main.py",
    "app/api/app.py",
    "app/api/errors.py",
    "app/frontend/js/login.js",
    "app/frontend/login.html",
    "app/tools/embedding_matcher.py",
    "app/tests/test_embedding_cache.py",
    "app/requirements.txt",
    "app/requirements.lock.txt",
    "app/deploy/audit-baseline.txt",
    "app/deploy/dependency_audit.py",
    "app/.env.example",
    "app/.dockerignore",
    "app/data/schema.sql",
    # pickles that belong to installed packages, not to the build context.
    # These three shapes are the regression: the unscoped `*.pkl` pattern
    # matched files like these and failed an innocent commit.
    "usr/lib/python3.11/site-packages/chromadb/data/example.pkl",
    "usr/lib/python3.11/site-packages/joblib/test/data/joblib_0.9.2_pickle_py27_np16.pkl",
    "usr/local/lib/python3.11/site-packages/sklearn/datasets/covertype.pkl",
    "usr/lib/python3.11/site-packages/somepkg/fixtures/cache.pickle",
    # ordinary OS and interpreter files
    "usr/local/bin/python3.11",
    "usr/local/lib/python3.11/site-packages/fastapi/applications.py",
    "usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "etc/ssl/certs/ca-certificates.crt",
    "var/lib/dpkg/status",
    "ms-playwright/chromium-1091/chrome-linux/chrome",
    # near-misses that must not be caught by an over-eager pattern
    "app/env.example",
    "app/keys.json.example",
    "app/data/README.md",
    "app/my_cv.pdf",
]

# label keyword -> paths the check MUST match.
MUST_MATCH = {
    ".env (API keys": ["app/.env", ".env"],
    "keys.json": ["app/keys.json", "keys.json"],
    "SQLite database under data/": ["app/data/apply_submit.db", "app/data/other.db"],
    "apply_submit.db": ["app/data/apply_submit.db"],
    "cv_embeddings.json": ["app/cv_embeddings.json", "app/cache/cv_embeddings.json"],
    "pickle": ["app/cv_embeddings.pkl", "app/cache/embeddings.pkl"],
    ".venv/": ["app/.venv/bin/python", ".venv/lib/x.py"],
    "node_modules/": ["app/node_modules/jsdom/package.json"],
}


def test_the_leak_check_exists_and_is_a_real_gate():
    script = _leak_step()
    assert "docker export" in script
    assert "tar -t" in script
    assert re.search(r"exit \$\(\(leaks > 0\)\)", script), (
        "the step counts leaks but never fails on them"
    )
    assert "continue-on-error" not in script


def test_every_pattern_matches_the_leak_it_exists_to_catch():
    for label, rx in _patterns():
        key = next((k for k in MUST_MATCH if k.lower() in label.lower()), None)
        assert key is not None, (
            f"no MUST_MATCH case for the check labelled {label!r} — add one, so a "
            "new check arrives with proof it can actually fire"
        )
        for path in MUST_MATCH[key]:
            assert rx.search(path), f"check {label!r} does not match {path!r}"


@pytest.mark.parametrize("path", BENIGN)
def test_no_pattern_matches_anything_legitimately_in_the_image(path):
    """The regression. Every pattern is tried against every benign path, so a
    new check cannot reintroduce an unscoped extension match."""
    hits = [label for label, rx in _patterns() if rx.search(path)]
    assert not hits, (
        f"{path!r} is a legitimate image file but would be reported as a leak by "
        f"{hits}. Scope the pattern to app/ — the build context — rather than to "
        "the whole exported filesystem."
    )


def test_the_pickle_check_is_scoped_to_the_build_context():
    """Named explicitly because this is the one that broke, and because the
    generalisation is easy to get wrong: `.pkl` is a common extension in
    installed ML packages, so an unscoped match is a false-positive generator."""
    label, rx = _pattern_for("pickle")
    assert "app/" in rx.pattern, (
        f"the pickle pattern {rx.pattern!r} is not scoped to app/; site-packages "
        "ships .pkl data files and would fail the build"
    )
    assert rx.search("app/cv_embeddings.pkl")
    assert not rx.search("usr/lib/python3.11/site-packages/chromadb/data/example.pkl")


def test_the_cv_cache_check_is_scoped_too():
    label, rx = _pattern_for("cv_embeddings.json")
    assert "app/" in rx.pattern, f"{rx.pattern!r} is not scoped to app/"
    assert rx.search("app/cv_embeddings.json")


def test_a_pattern_that_matches_nothing_is_a_bug():
    """The easy "fix" for a false positive is to loosen a pattern until it stops
    matching — which is indistinguishable from deleting the check. Every pattern
    must match at least one realistic leak path AND reject at least one benign
    path, so it is doing something."""
    for label, rx in _patterns():
        assert any(rx.search(path) for paths in MUST_MATCH.values() for path in paths), (
            f"check {label!r} ({rx.pattern}) matches no leak path at all"
        )
        assert not any(rx.search(path) for path in BENIGN), (
            f"check {label!r} ({rx.pattern}) is unscoped"
        )


# --- .dockerignore is what makes the check meaningful -------------------------


def test_dockerignore_excludes_everything_the_check_looks_for():
    """The check verifies that .dockerignore worked. If an exclusion is dropped,
    the check is the only thing that notices — so the two lists must stay in
    step, and this is the assertion that keeps them there."""
    with open(DOCKERIGNORE, encoding="utf-8") as fh:
        entries = {
            line.strip()
            for line in fh
            if line.strip() and not line.strip().startswith("#")
        }
    for required in (".env", "keys.json", "cv_embeddings.json", "*.pkl", ".venv/", "node_modules/", "data/*.db"):
        assert required in entries, (
            f"{required!r} is checked in CI but not excluded by .dockerignore, so "
            "the image would contain it and the build would fail"
        )


def test_the_pickle_exclusion_survives_the_format_change():
    """The cache moved from .pkl to .json. Both patterns have to stay: the new
    one because the cache is JSON now, the old one because an operator upgrading
    from before the switch still has a .pkl in their build context."""
    with open(DOCKERIGNORE, encoding="utf-8") as fh:
        text = fh.read()
    assert "cv_embeddings.json" in text
    assert "*.pkl" in text


def test_the_workflow_explains_why_the_patterns_are_scoped():
    """So the next person does not "simplify" `app/.*\\.pkl` back to `[^/]+\\.pkl`.
    The reason is a broken build, and the comment is where that is recorded."""
    script = _leak_step()
    assert "site-packages" in script, (
        "the docker job no longer explains that the file list covers the whole "
        "filesystem, which is the reason the patterns are scoped to app/"
    )
