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


def test_strict_cp1252_negative_control_reproduces_unicode_error(tmp_path):
    # A green hardening test is meaningful only if the same runner/pipe fails
    # without the fix; this also proves the Windows CI actually uses cp1252.
    process = _cp1252_python("print('package 📦')", tmp_path)
    assert process.returncode != 0
    assert b"UnicodeEncodeError" in process.stderr


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


def test_cp1252_real_review_worker_creates_package_without_live_services(tmp_path):
    # Exercise the original route -> worker -> real package boundary. Material
    # generation and the ATS browser are faked, but the worker, SQLite claims
    # and package writer are real; no live job or application is contacted.
    process = _cp1252_python(
        """
        import os
        import sys
        import threading
        from pathlib import Path

        root = Path(sys.argv[1])
        sys.path.insert(0, str(Path.cwd()))  # imports still resolve after chdir
        os.chdir(root)
        os.environ.update({
            'PYTHON_DOTENV_DISABLED': '1',
            'SUBMIT_ENABLED': 'false', 'SUBMIT_DRY_RUN': 'false',
            'API_TOKEN': '', 'APPLY_API_TOKEN': '',
            'AUTH_DB_PATH': str(root / 'auth.db'),
            'APPLY_STATE_DB_PATH': str(root / 'apply.db'),
            'APPLY_FILL_TIMEOUT': '20',
        })
        from api.app import create_app
        from api import apply as service, cache
        from agents import auto_applier
        from fastapi.testclient import TestClient

        main_thread = threading.get_ident()
        real_package = auto_applier.generate_apply_package
        def package(*args, **kwargs):
            assert threading.get_ident() != main_thread
            print('review worker 📦', flush=True)
            return real_package(*args, **kwargs)
        auto_applier.generate_apply_package = package
        cache.get_job = lambda fp: {
            'job_fingerprint': fp, 'job_title': 'Developer 🚀',
            'company': 'Synthetic', 'apply_url': 'https://example.invalid/job',
            'match_score': 80,
        }
        service._prepare_submit_materials = lambda job: {
            'resume_path': None, 'cover_letter_text': 'Synthetic cover',
        }
        service._fill_ats_form = lambda *args, **kwargs: None
        with TestClient(create_app()) as client:
            response = client.post('/api/apply/windows-encoding', json={'mode': 'review'})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['status'] == 'package_only', result
            assert result['submit_enabled'] is False
            assert (Path(result['package_path']) / 'index.html').is_file()
        """,
        tmp_path,
    )
    assert process.returncode == 0, process.stderr.decode("cp1252", "replace")
    assert b"review worker \\U0001f4e6" in process.stdout


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
