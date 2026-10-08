#!/usr/bin/env bash
# Frontend E2E smoke runner.
#   ./tests/e2e/run.sh
#
# Requires: a Python environment with requirements.txt installed, and Node 20+.
# `node_modules` is installed on first run.
#
# Interpreter resolution mirrors tests/e2e/harness.mjs exactly — venv/, then
# .venv/, then the ambient interpreter — and the choice is exported as
# RJA_PYTHON so the harness uses the same one this script validated. Keeping the
# two in sync matters: the harness spawns uvicorn, and if it picks an
# interpreter without fastapi the failure surfaces as "API did not start within
# 30s", which points at startup when the real cause is the interpreter.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

PY=""
if [ -n "${RJA_PYTHON:-}" ]; then
  PY="$RJA_PYTHON"
else
  for candidate in "$REPO/venv/bin/python" "$REPO/.venv/bin/python"; do
    if [ -x "$candidate" ]; then PY="$candidate"; break; fi
  done
  if [ -z "$PY" ]; then
    PY="$(command -v python3 2>/dev/null || true)"
  fi
fi

if [ -z "$PY" ]; then
  echo "error: no venv/, .venv/ or python3 found." >&2
  echo "       create one and install deps:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# Fail here with an actionable message rather than inside the harness, where a
# missing dependency reads like a startup timeout.
if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "error: $PY cannot import fastapi/uvicorn." >&2
  echo "       run: $PY -m pip install -r $REPO/requirements.txt" >&2
  exit 1
fi

if [ ! -d "$HERE/node_modules" ]; then
  echo "installing e2e deps (jsdom)…"
  (cd "$HERE" && npm install --silent)
fi

echo "interpreter: $PY"
cd "$HERE"
RJA_PYTHON="$PY" exec node --test smoke.test.mjs
