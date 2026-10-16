"""Negative control, copied into a disposable project by environment.test.mjs.

Deliberately omit the two auth pins to reproduce the historical late-dotenv
failure. Never launched in the real checkout. Report statuses/booleans only,
not credentials; no LLM parsing, Sheets requests or production auth bypass.
"""

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# This script must only run in the disposable source copy with a dummy .env.
root = Path(__file__).resolve().parent
if not (root / "environment-fixture.marker").is_file():
    raise RuntimeError("env_probe requires the disposable environment fixture")

from api.app import create_app

os.environ.pop("API_TOKEN", None)
os.environ.pop("APPLY_API_TOKEN", None)
with TestClient(create_app()) as client:
    before = client.get("/api/stats")
    imported_before = "tools.cv_parser" in sys.modules
    profile = client.get("/api/cv/profile")
    after = client.get("/api/stats")
    parser = sys.modules.get("tools.cv_parser")
    result = {
        "stats_before": before.status_code,
        "profile": profile.status_code,
        "stats_after": after.status_code,
        "parser_was_lazy": not imported_before,
        "parser_from_fixture": bool(parser) and Path(parser.__file__).resolve() == root / "tools/cv_parser.py",
        "api_token_loaded": bool(os.getenv("API_TOKEN")),
        "apply_token_loaded": bool(os.getenv("APPLY_API_TOKEN")),
    }
print("ENV_PROBE_RESULT " + json.dumps(result))
