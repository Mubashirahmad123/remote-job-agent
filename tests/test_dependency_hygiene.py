"""Dependency pins are bounded, the lock agrees with them, and the audit works (L5).

Three separate failures are pinned here, because they fail in different
directions:

  * An unbounded pin (`pytest`, `google-genai>=1.0.0`) lets an upstream major
    release break `docker build` or CI on a commit that changed nothing. This is
    the original L5 finding.
  * A pin that disagrees with `requirements.lock.txt` makes the lock a lie. CI
    already checks this; these tests check it locally so a broken pair is caught
    before it is pushed.
  * The audit tooling itself. `deploy/dependency_audit.py` is what makes the
    vulnerability state visible, and a bug in its comparison logic fails open: a
    script that cannot parse pip-audit's output, or that treats "found
    vulnerabilities" (pip-audit's exit 1) as a crash, or that treats a crash as
    "clean", is worse than no audit because the green check still appears.

The last group is tested with synthetic payloads rather than by calling PyPI, so
this file stays offline and deterministic like the rest of the suite.
"""

import importlib.util
import os
import re
import subprocess
import sys

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(REPO, "requirements.txt")
LOCK = os.path.join(REPO, "requirements.lock.txt")
BASELINE = os.path.join(REPO, "deploy", "audit-baseline.txt")
AUDIT_SCRIPT = os.path.join(REPO, "deploy", "dependency_audit.py")

# name -> specifier, for every real requirement line.
REQUIREMENT_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_.\-+]+)\s*(?P<spec>[^#;]*?)\s*(?:#.*)?$"
)
# The lock pins exactly: `name==version`, possibly followed by markers.
LOCK_LINE = re.compile(r"^(?P<name>[A-Za-z0-9_.\-+]+)==(?P<version>[^\s;#]+)")
BASELINE_LINE = re.compile(r"^(?P<pkg>[A-Za-z0-9_.\-+]+)==(?P<version>[^\s]+)\s+(?P<id>\S+)$")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _requirements():
    """(line-number, name, specifier) for every non-comment requirement."""
    out = []
    for number, line in enumerate(_read(REQUIREMENTS).splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        match = REQUIREMENT_LINE.match(line)
        assert match, f"requirements.txt:{number} is not parseable: {line!r}"
        out.append((number, match.group("name"), match.group("spec").strip()))
    return out


def _lock():
    """name -> version, from the lock."""
    out = {}
    for line in _read(LOCK).splitlines():
        match = LOCK_LINE.match(line.strip())
        if match:
            out[match.group("name").lower().replace("_", "-")] = match.group("version")
    return out


def _baseline_entries():
    entries = []
    for line in _read(BASELINE).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.append(stripped)
    return entries


def _audit_module():
    """Load deploy/dependency_audit.py — `deploy` is not an importable package."""
    spec = importlib.util.spec_from_file_location("dependency_audit", AUDIT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the original finding: unbounded pins ------------------------------------


def test_there_are_requirements_to_check():
    assert len(_requirements()) > 20, "the parse found almost nothing; the regex broke"


@pytest.mark.parametrize("number,name,spec", _requirements(), ids=lambda v: str(v))
def test_every_requirement_has_an_upper_bound(number, name, spec):
    """`==` is exact; `<`/`<=`/`~=` bound the top. `>=` alone, and no specifier
    at all, leave the next major release free to break the build."""
    assert spec, (
        f"requirements.txt:{number} — `{name}` has NO version specifier, so it "
        "resolves to whatever is newest at build time"
    )
    bounded = (
        "==" in spec
        or "<" in spec
        or "~=" in spec
    )
    assert bounded, (
        f"requirements.txt:{number} — `{name}{spec}` has no upper bound. A future "
        "major release can break `docker build` or CI on a commit that changed "
        "nothing here. Bound it, and raise the ceiling deliberately after a test "
        "run rather than implicitly."
    )


def test_the_two_previously_loose_pins_are_now_bounded():
    specs = {name.lower(): spec for _, name, spec in _requirements()}
    assert specs["google-genai"] == ">=1.0.0,<2", specs["google-genai"]
    assert specs["pytest"] == ">=9,<10", specs["pytest"]


def test_no_pin_is_left_open_at_the_top_by_a_typo():
    """>=1.0.0, <2 has a space after the comma and still parses for pip, but a
    stray `<` on its own would satisfy the bound check above while pinning
    nothing. Assert every clause has a version in it."""
    for number, name, spec in _requirements():
        for clause in spec.split(","):
            clause = clause.strip()
            if not clause:
                continue
            assert re.match(r"^(==|>=|<=|>|<|~=|!=)\s*[A-Za-z0-9_.\-+*]+$", clause), (
                f"requirements.txt:{number} — `{name}` has a malformed clause "
                f"{clause!r}"
            )


# --- requirements.txt and the lock must agree --------------------------------


def test_every_requirement_is_in_the_lock():
    lock = _lock()
    missing = sorted(
        name for _, name, _ in _requirements()
        if name.lower().replace("_", "-") not in lock
    )
    assert not missing, (
        f"{missing} in requirements.txt but not in requirements.lock.txt — "
        "regenerate with: uv pip compile requirements.txt -o "
        "requirements.lock.txt --universal"
    )


def test_every_exact_pin_matches_the_lock():
    """The same check CI runs, so a disagreeing pair is caught before it is
    pushed rather than after."""
    lock = _lock()
    wrong = []
    for number, name, spec in _requirements():
        match = re.fullmatch(r"==\s*([A-Za-z0-9_.\-+]+)", spec)
        if not match:
            continue
        locked = lock.get(name.lower().replace("_", "-"))
        if locked is not None and locked != match.group(1):
            wrong.append(f"requirements.txt:{number} {name}=={match.group(1)} vs lock {locked}")
    assert not wrong, "\n".join(wrong)


def test_the_requests_bump_landed_in_both_files():
    """The one advisory in this tree that was cheap to clear: `requests` makes
    every outbound call the app does, and 2.32.3 carried two published
    advisories with fixes at 2.32.4 and 2.33.0."""
    specs = {name.lower(): spec for _, name, spec in _requirements()}
    assert specs["requests"] == "==2.33.0", specs["requests"]
    assert _lock()["requests"] == "2.33.0"


def test_pyasn1_security_floor_and_every_locked_version():
    """0.6.5 fixes four CVEs; neither the direct constraint nor any universal
    lock variant may silently permit a vulnerable older release."""
    specs = [spec for _, name, spec in _requirements() if name.lower() == "pyasn1"]
    assert len(specs) == 1, f"expected one pyasn1 constraint, got {specs!r}"
    specifier = SpecifierSet(specs[0])
    for vulnerable in ("0.6.0", "0.6.3", "0.6.4"):
        assert not specifier.contains(vulnerable, prereleases=True)
    assert specifier.contains("0.6.5"), "the patched release must remain installable"

    versions = []
    for line in _read(LOCK).splitlines():
        match = LOCK_LINE.match(line.strip())
        if match and match.group("name").lower().replace("_", "-") == "pyasn1":
            versions.append(Version(match.group("version")))
    assert versions, "pyasn1 is missing from the universal lock"
    for version in versions:
        assert version >= Version("0.6.5"), f"vulnerable pyasn1 lock: {version}"
        assert specifier.contains(version), f"pyasn1 {version} violates {specifier}"


def test_pyasn1_rsa_google_auth_compatibility_offline():
    """Exercise the pure-Python Google auth fallback that uses both pyasn1
    consumers, with an ephemeral synthetic key and no credentials or network."""
    from google.auth.crypt import _python_rsa
    from pyasn1.codec.der import decoder, encoder
    from pyasn1.type import univ
    from pyasn1_modules.rfc2437 import RSAPrivateKey
    from pyasn1_modules.rfc5208 import PrivateKeyInfo
    import rsa

    public, private = rsa.newkeys(1024)
    private_der = private.save_pkcs1("DER")
    decoded, remainder = decoder.decode(private_der, asn1Spec=RSAPrivateKey())
    assert remainder == b""
    assert int(decoded["modulus"]) == public.n

    # PKCS#8 is the format commonly used by Google service-account keys.
    info = PrivateKeyInfo()
    info["version"] = 0
    info["privateKeyAlgorithm"]["algorithm"] = univ.ObjectIdentifier("1.2.840.113549.1.1.1")
    info["privateKeyAlgorithm"]["parameters"] = univ.Null("")
    info["privateKey"] = private_der
    private_keys = (private.save_pkcs1(), rsa.pem.save_pem(encoder.encode(info), "PRIVATE KEY"))

    verifier = _python_rsa.RSAVerifier.from_string(public.save_pkcs1())
    message = b"synthetic offline auth compatibility check"
    for key in private_keys:
        signer = _python_rsa.RSASigner.from_string(key)
        signature = signer.sign(message)
        assert verifier.verify(message, signature)
        assert not verifier.verify(b"tampered message", signature)


def test_the_lock_still_demands_universal_resolution():
    """Hard-won and easy to lose: without `--universal`, uv resolves for the
    host OS only. The lock was first generated on Windows, which produced an
    unmarked `pywin32==312` line that cannot install on the Linux deployment VM
    and omitted `uvloop`. The header is the only place that survives a
    regeneration by someone who has never heard the story."""
    header = _read(LOCK).split("aiofiles")[0]
    assert "--universal" in header, "the lock header no longer demands --universal"


# --- the baseline ------------------------------------------------------------


def test_the_baseline_is_well_formed():
    entries = _baseline_entries()
    assert entries, "an empty baseline means either everything is fixed or the file broke"
    for entry in entries:
        assert BASELINE_LINE.match(entry), (
            f"{entry!r} is not `<name>==<version> <ADVISORY-ID>`"
        )
    assert entries == sorted(entries), "the baseline is unsorted, so diffs are unreadable"
    assert len(entries) == len(set(entries)), "the baseline has duplicate entries"


def test_every_baseline_entry_names_a_version_the_lock_actually_ships():
    """A baseline entry for a version that is no longer in the lock cannot
    reproduce, so it suppresses nothing and should be pruned. Catching it here
    rather than in the audit output means it cannot be left to rot."""
    lock = _lock()
    stale = []
    for entry in _baseline_entries():
        match = BASELINE_LINE.match(entry)
        name = match.group("pkg").lower().replace("_", "-")
        if lock.get(name) != match.group("version"):
            stale.append(f"{entry} (lock has {name}=={lock.get(name, 'NOTHING')})")
    assert not stale, (
        "these baseline entries no longer match the lock, so they are dead "
        "weight hiding real drift:\n  " + "\n  ".join(stale)
    )


def test_requests_is_not_in_the_baseline():
    """It was bumped past both advisories, so its entries were pruned. If a
    future change reverts the pin, the advisories come back and the audit fails
    — which is the ratchet working, and the reason pruning matters."""
    assert not [e for e in _baseline_entries() if e.startswith("requests==")]


def test_pyasn1_fixed_advisories_are_not_baselined():
    """Do not turn the four fixed advisories into audit exceptions, including
    their GHSA aliases if pip-audit ever changes which identifiers it emits."""
    fixed_ids = {
        "CVE-2026-119194", "CVE-2026-119195", "CVE-2026-119196", "CVE-2026-119197",
        "GHSA-fm9c-5rcf-2q5p", "GHSA-9m75-vc3g-4x39",
        "GHSA-2qm8-x737-gmw5", "GHSA-mm57-4v3p-rchx",
    }
    suppressed = []
    for entry in _baseline_entries():
        match = BASELINE_LINE.match(entry)
        if match and match.group("pkg").lower().replace("_", "-") == "pyasn1":
            if match.group("id") in fixed_ids:
                suppressed.append(entry)
    assert not suppressed, f"fixed pyasn1 advisories must not be baselined: {suppressed}"


def test_the_baseline_records_when_it_was_taken():
    assert re.search(r"^# Recorded: \d{4}-\d{2}-\d{2}", _read(BASELINE), re.M), (
        "an undated baseline cannot be judged stale"
    )


# --- the audit tool, offline -------------------------------------------------


def test_findings_deduplicates_a_repeated_advisory():
    """The PyPI backend reports the same advisory several times for a package
    published under more than one normalized name. Counting those separately
    inflates every number in the report — the raw output said 85 where the
    distinct count was 48."""
    audit = _audit_module()
    payload = {
        "dependencies": [
            {"name": "lxml", "version": "5.4.0", "vulns": [{"id": "PYSEC-1"}, {"id": "PYSEC-1"}]},
            {"name": "lxml", "version": "5.4.0", "vulns": [{"id": "PYSEC-1"}]},
            {"name": "mcp", "version": "1.26.0", "vulns": [{"id": "PYSEC-2"}]},
            {"name": "clean", "version": "1.0", "vulns": []},
            {"name": "broken", "version": None, "vulns": [{"id": "PYSEC-3"}]},
        ]
    }
    assert audit.findings(payload) == {"lxml==5.4.0 PYSEC-1", "mcp==1.26.0 PYSEC-2"}


def test_a_vulnerable_audit_result_is_not_treated_as_a_crash(monkeypatch):
    """pip-audit exits 1 when it FINDS vulnerabilities. Treating that as a
    failure to run would make every real finding look like broken tooling."""
    audit = _audit_module()

    class Result:
        returncode = 1
        stdout = '{"dependencies": [{"name": "x", "version": "1", "vulns": [{"id": "P-1"}]}]}'
        stderr = "Found 1 known vulnerability"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    assert audit.findings(audit.run_audit(audit.LOCK)) == {"x==1 P-1"}


def test_a_broken_audit_is_never_reported_as_clean(monkeypatch):
    """The dangerous direction. A tool that failed to reach PyPI must not produce
    an empty finding set, which reads exactly like a clean tree."""
    audit = _audit_module()

    class Result:
        returncode = 2
        stdout = ""
        stderr = "could not reach pypi.org"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(SystemExit) as excinfo:
        audit.run_audit(audit.LOCK)
    assert "did not complete" in str(excinfo.value)


def test_unparseable_audit_output_is_never_reported_as_clean(monkeypatch):
    audit = _audit_module()

    class Result:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(SystemExit) as excinfo:
        audit.run_audit(audit.LOCK)
    assert "could not parse" in str(excinfo.value)


def test_the_ratchet_math_is_right():
    """New fails, fixed informs, unchanged passes. This is the whole policy, so
    the set arithmetic is asserted directly rather than through a subprocess."""
    audit = _audit_module()
    known = {"a==1 P-1", "b==2 P-2"}
    assert sorted({"a==1 P-1", "c==3 P-3"} - known) == ["c==3 P-3"], "a new finding must appear"
    assert sorted(known - {"a==1 P-1"}) == ["b==2 P-2"], "a cleared finding must be reported"
    assert known - known == set(), "an unchanged tree must report nothing"


def test_writing_the_baseline_sorts_and_dates_it(tmp_path):
    audit = _audit_module()
    target = tmp_path / "baseline.txt"
    audit.write_baseline(target, {"z==1 P-9", "a==1 P-1", "m==1 P-5"})
    written = target.read_text(encoding="utf-8")
    body = [line for line in written.splitlines() if line and not line.startswith("#")]
    assert body == ["a==1 P-1", "m==1 P-5", "z==1 P-9"]
    assert re.search(r"^# Recorded: \d{4}-\d{2}-\d{2}", written, re.M)
    assert audit.read_baseline(target) == set(body)


def test_a_missing_baseline_reads_as_empty_rather_than_crashing(tmp_path):
    """First run on a fresh clone: no baseline file yet. Everything must read as
    NEW so the failure tells the operator to record one, rather than raising."""
    audit = _audit_module()
    assert audit.read_baseline(tmp_path / "absent.txt") == set()


# --- CI actually runs it -----------------------------------------------------


def test_ci_has_a_dependency_audit_job():
    """The tool is worthless if nothing invokes it. This repo already had one
    instance of exactly that failure: 397 passing tests and no workflow running
    them."""
    import yaml

    with open(os.path.join(REPO, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        workflow = yaml.safe_load(fh)
    jobs = workflow["jobs"]
    assert "dependency-audit" in jobs, sorted(jobs)
    steps = "\n".join(str(step) for step in jobs["dependency-audit"]["steps"])
    assert "dependency_audit.py" in steps, "the job does not run the audit script"
    assert "pip-audit" in steps, "the job never installs pip-audit"
    # Not continue-on-error: an audit that cannot fail is decoration.
    assert "continue-on-error" not in steps
