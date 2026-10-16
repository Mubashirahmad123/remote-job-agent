#!/usr/bin/env python3
"""Preserve a CI command's failure and surface its output in check annotations.

Raw Actions logs use a separate download host, which is not always reachable
from review environments. Bounded failure annotations remain available through
the GitHub Checks API. This wrapper never retries or suppresses a failed gate.
"""
from __future__ import annotations

import subprocess
import sys

MAX_ANNOTATION_CHARS = 24000


def escape_message(message: str) -> str:
    """Escape workflow-command data, including injected command/newline text."""
    return message.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def main(command: list[str] | None = None) -> int:
    command = sys.argv[1:] if command is None else command
    if not command:
        print('Usage: ci_failure_report.py COMMAND [ARG ...]', file=sys.stderr)
        return 2
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors='replace')
    except OSError as error:
        print(f'::error title=CI command could not start::{escape_message(str(error))}')
        return 127
    print(result.stdout, end='', flush=True)
    if result.returncode:
        tail = result.stdout[-MAX_ANNOTATION_CHARS:]
        print(f'\n::error title=CI command failed::{escape_message(tail)}', flush=True)
    # Match a shell's conventional exit status when a child died by signal.
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
