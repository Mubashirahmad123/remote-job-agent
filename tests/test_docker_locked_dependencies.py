"""Static guards for locked Docker installs and native runtime verification.

These do NOT build an image or prove ARM compatibility. The CI docker matrix
builds/runs the image, including Chromium, on each architecture.
"""

import ast
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

from tests.test_container_hardening import _dockerfile_instructions

ROOT = Path(__file__).resolve().parents[1]


def docker_instructions():
    return _dockerfile_instructions((ROOT / "Dockerfile").read_text(encoding="utf-8"))


def docker_job():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["docker"]


def test_docker_installs_the_lock_not_fresh_direct_requirements():
    installs = [shlex.split(args) for name, args, _ in docker_instructions()
                if name == "RUN" and "uv pip install" in args]
    assert len(installs) == 1
    tokens = installs[0]
    assert tokens[tokens.index("-r") + 1] == "requirements.lock.txt"
    assert "--system" in tokens
    assert "requirements.txt" not in tokens
    assert "--no-deps" not in tokens, "do not suppress dependency compatibility checks"


def test_lock_is_copied_before_install_for_docker_layer_invalidation():
    instructions = docker_instructions()
    copies = [line for name, args, line in instructions
              if name == "COPY" and shlex.split(args) == ["requirements.lock.txt", "."]]
    installs = [line for name, args, line in instructions
                if name == "RUN" and "uv pip install" in args]
    assert copies and installs
    assert copies[0] < installs[0]


def test_build_checks_installed_dependency_consistency():
    runs = [args for name, args, _ in docker_instructions() if name == "RUN"]
    assert any("&& uv pip check --system" in command for command in runs)


def test_every_lock_entry_is_an_exact_pin():
    requirements = []
    for line in (ROOT / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            req = Requirement(line)
            specs = list(req.specifier)
            assert len(specs) == 1 and specs[0].operator == "==", line
            assert "*" not in specs[0].version, line
            requirements.append(req)
    assert requirements


def test_lock_keeps_windows_only_packages_out_of_linux_install():
    lock = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    windows = next(Requirement(line) for line in lock.splitlines() if line.startswith("pywin32=="))
    assert windows.marker is not None
    assert not windows.marker.evaluate({"sys_platform": "linux"})
    assert windows.marker.evaluate({"sys_platform": "win32"})


def test_docker_ci_uses_native_x86_and_arm_runners():
    job = docker_job()
    assert job["runs-on"] == "${{ matrix.runner }}"
    assert job["strategy"]["fail-fast"] is False
    configurations = job["strategy"]["matrix"]["include"]
    assert {c["arch"] for c in configurations} == {"x86_64", "aarch64"}
    arm = next(c for c in configurations if c["arch"] == "aarch64")
    assert arm["runner"] == "ubuntu-24.04-arm"
    assert not job.get("continue-on-error", False)


def test_each_native_image_must_pass_runtime_tests_and_leak_checks():
    steps = docker_job()["steps"]
    scripts = "\n".join(step.get("run", "") for step in steps)
    assert "docker build -t remote-job-agent:ci ." in scripts
    assert "docker run --rm remote-job-agent:ci uv pip check --system" in scripts
    assert "docker run --rm remote-job-agent:ci python -m pytest -q" in scripts
    assert "tests/test_api_auth_hardening.py" in scripts
    assert "docker export" in scripts  # existing secret/image checks retained
    assert not any(step.get("continue-on-error", False) for step in steps)
    smoke = next(step for step in steps if "Smoke-test runtime" in step.get("name", ""))
    assert smoke["env"]["EXPECTED_ARCH"] == "${{ matrix.arch }}"
    script = smoke["run"]
    for check in ["platform.machine()", 'os.environ["EXPECTED_ARCH"]', "os.geteuid() != 0",
                  "/api/health/live", "response.status_code == 200", "playwright.chromium.launch",
                  "page.title()", "headless=True", "requirement.marker.evaluate()",
                  "requirement.specifier.contains(installed", "checked > 0"]:
        assert check in script
    # The probe never mounts real data/secrets or invokes a submit endpoint.
    assert not re.search(r"\s(?:-v|--volume|--env-file)\s", script)
    assert "/submit" not in script


@pytest.mark.parametrize("step", [step for step in docker_job()["steps"] if "run" in step],
                         ids=lambda step: step["name"])
def test_docker_ci_shell_commands_and_python_heredoc_parse(step):
    script = step["run"]
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash syntax validation requires Bash; native Docker CI runs on Linux")
    result = subprocess.run([bash, "-n"], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    if "<<'PY'" in script:
        python = script.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        ast.parse(python)


def test_host_python_and_dashboard_ci_install_the_same_audited_lock():
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'))
    for name in ('api-tests', 'frontend-e2e'):
        steps = workflow['jobs'][name]['steps']
        installs = [step['run'] for step in steps if 'pip install -r ' in step.get('run', '')]
        assert installs
        assert all('-r requirements.lock.txt' in command for command in installs)
        assert all('--no-deps' not in command for command in installs)
        setup = next(step for step in steps if step.get('uses', '').startswith('actions/setup-python@'))
        assert setup['with']['cache-dependency-path'] == 'requirements.lock.txt'
