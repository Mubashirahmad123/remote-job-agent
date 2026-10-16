"""CI diagnostics must expose failures without weakening their exit status."""
import subprocess
import sys
from types import SimpleNamespace

from deploy import ci_failure_report as report


def test_success_prints_output_without_error_annotation(capsys):
    assert report.main([sys.executable, '-c', "print('passed')"]) == 0
    assert capsys.readouterr().out == 'passed\n'


def test_failure_preserves_exit_status_and_reports_stderr(capsys):
    assert report.main([sys.executable, '-c',
                        "import sys; print('failure detail', file=sys.stderr); sys.exit(3)"]) == 3
    output = capsys.readouterr().out
    assert 'failure detail' in output
    assert '::error title=CI command failed::failure detail%0A' in output


def test_workflow_command_data_is_escaped():
    assert report.escape_message('100%\r\n::warning::injected') == '100%25%0D%0A::warning::injected'


def test_annotation_is_bounded_but_full_log_is_preserved(monkeypatch, capsys):
    message = 'PREFIX' + 'x' * report.MAX_ANNOTATION_CHARS
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=message, returncode=1))
    assert report.main(['synthetic-command']) == 1
    output = capsys.readouterr().out
    log, annotation = output.split('\n::error title=CI command failed::')
    assert log == message
    assert 'PREFIX' not in annotation
    assert len(annotation.rstrip('\n')) == report.MAX_ANNOTATION_CHARS


def test_missing_command_and_missing_binary_fail_closed(capsys):
    assert report.main([]) == 2
    assert 'Usage:' in capsys.readouterr().err
    assert report.main(['nonexistent-rja-test-command-83f78']) == 127
    assert 'CI command could not start' in capsys.readouterr().out


def test_signal_failure_remains_nonzero(monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='', returncode=-9))
    assert report.main(['synthetic-command']) == 137
