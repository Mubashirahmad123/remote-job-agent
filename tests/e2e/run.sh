#!/usr/bin/env bash
# Frontend E2E smoke runner.
#   ./tests/e2e/run.sh
# Requires: venv/ (python deps) and `npm install` inside tests/e2e once.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

if [ ! -x "$REPO/venv/bin/python" ]; then
  echo "error: $REPO/venv not found — create it and install requirements first." >&2
  exit 1
fi
if [ ! -d "$HERE/node_modules" ]; then
  echo "installing e2e deps (jsdom)…"
  (cd "$HERE" && npm install --silent)
fi
cd "$HERE"
exec node --test smoke.test.mjs
