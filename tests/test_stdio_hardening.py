"""Regression for redirected Windows/cp1252 output, without requiring Windows."""
import os
import subprocess
import sys
import textwrap

import pytest

from tools.stdio import harden_stdio


def _cp1252_python(code, tmp_path):
    env = os.environ.copy()
    env.update(PYTHONIOENCODING="cp1252:strict", PYTHONUTF8="0")
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), str(tmp_path)],
        env=env, capture_output=True, timeout=30,
    )


def test_api_hardens_stdout_and_stderr_before_review_worker_runs(tmp_path):
    process = _cp1252_python(
        """
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from api.app import create_app
        from agents.auto_applier import generate_apply_package

        create_app()
        assert sys.stdout.encoding.lower() in ('cp1252', 'windows-1252')
        assert sys.stdout.errors == sys.stderr.errors == 'backslashreplace'
        def work():
            print('scrape 📦 ✅')
            print('failure ❌', file=sys.stderr)
            return generate_apply_package(
                {'job_title': 'Developer 🚀', 'company': 'Test',
                 'apply_url': 'https://example.invalid/job'},
                None, 'Synthetic cover', output_folder=sys.argv[1])
        with ThreadPoolExecutor() as pool:
            path = pool.submit(work).result()
        assert path is not None
        """,
        tmp_path,
    )
    assert process.returncode == 0, process.stderr.decode("cp1252", "replace")
    assert b"scrape " in process.stdout
    assert b"\\U0001f4e6" in process.stdout
    assert b"failure " in process.stderr
    assert (next(tmp_path.iterdir()) / "index.html").is_file()


def test_package_success_and_error_handler_do_not_print_unicode(tmp_path):
    # Direct library calls should not depend on the API having run first.
    process = _cp1252_python(
        """
        import sys
        from agents.auto_applier import generate_apply_package
        job = {'company': 'Test', 'job_title': 'Developer'}
        assert generate_apply_package(job, None, 'cover', output_folder=sys.argv[1])
        assert generate_apply_package(job, None, 'cover', output_folder='') is None
        print('ok')
        """,
        tmp_path,
    )
    assert process.returncode == 0, process.stderr.decode("cp1252", "replace")
    assert b"ok" in process.stdout
    assert b"UnicodeEncodeError" not in process.stderr


def test_missing_or_unconfigurable_streams_do_not_block_the_other(monkeypatch):
    calls = []

    class Broken:
        def reconfigure(self, **kwargs):
            raise RuntimeError("not supported")

    class Good:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", Broken())
        patch.setattr(sys, "stderr", Good())
        harden_stdio()
        harden_stdio()
    assert calls == [{"errors": "backslashreplace"}] * 2


def test_stream_without_reconfigure_is_supported(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", object())
        harden_stdio()
