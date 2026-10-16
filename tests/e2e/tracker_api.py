"""Isolated E2E server: real tracker routes/services over a fake Sheets boundary.

Only started explicitly by harness.mjs with RJA_E2E_TRACKER=1. Test controls
never exist in api.app. No Google credentials, real sheets or job boards used.
The worksheet persists across dashboard reloads for this subprocess only.
"""

import asyncio
import os
import threading
from copy import deepcopy

if os.getenv("RJA_E2E_TRACKER") != "1":
    raise RuntimeError("tracker_api is an opt-in E2E fixture, not a production entry point")

from fastapi.responses import JSONResponse

from api import cache
from api.app import create_app
from tools import sheet_writer
from tools.application_tracker import APPLIED_HEADERS

REVIEW_STATUSES = [
    "review", "filled_ready", "filled_ready_submit_disabled", "needs_review",
    "custom_questions", "package_only", "email_draft", "playwright_not_installed",
    "playwright_failed", "dream_manual", "submit_unverified", "failed_refunded",
    "filled_future",
]
STATUSES = ["applied", "submitted", *REVIEW_STATUSES, "interviewing", "interview",
            "offer", "rejected", "withdrawn", "ghosted"]
SEED = [
    {
        "job_fingerprint": f"e2e-{status}", "apply_url": f"https://example.invalid/tracker/{status}",
        "company": f"Fixture {status}", "job_title": "Frontend Developer",
        "status": status, "match_score": "82", "notes": "Original note",
        "applied_date": "2026-10-01 10:00", "follow_up_date": "2026-10-08",
        "source": "manual",
    }
    for status in STATUSES
]
SEED.append({
    "apply_url": "https://example.invalid/tracker/url-only?role=frontend&ref=one%2Ftwo#apply",
    "company": "URL-only fixture", "job_title": "Backend Developer",
    "status": "applied", "notes": "Keep this note", "match_score": "77",
})
HEADERS = [*APPLIED_HEADERS, "job_fingerprint", "applied_at"]
HEADER_MODES = {"compact": APPLIED_HEADERS, "autoapply": sheet_writer.APPLIED_COLUMNS}


class Worksheet:
    def __init__(self):
        self.lock = threading.RLock()
        self.fail_write = False
        self.reset(SEED)

    def reset(self, rows, headers=None):
        headers = HEADERS if headers is None else headers
        with self.lock:
            self.values = [list(headers)] + [
                [str(row.get(key) or "") for key in headers] for row in rows
            ]
            self.fail_write = False

    def get_all_values(self):
        with self.lock:
            return deepcopy(self.values)

    def append_row(self, row):
        with self.lock:
            if self.fail_write:
                raise RuntimeError("injected fake worksheet write failure")
            self.values.append(list(row))

    def update_cell(self, row, column, value):
        with self.lock:
            if self.fail_write:
                raise RuntimeError("injected fake worksheet write failure")
            while len(self.values[row - 1]) < column:
                self.values[row - 1].append("")
            self.values[row - 1][column - 1] = str(value)


worksheet = Worksheet()


class Spreadsheet:
    def worksheet(self, name):
        if name != "APPLIED":
            raise AssertionError(f"unexpected fixture worksheet: {name}")
        return worksheet


# Stub only external/local-personal-data boundaries. Leave routes, schemas,
# cache invalidation, URL resolution, mark_applied and update_status real.
sheet_writer.get_sheet = lambda: Spreadsheet()
cache._read_tab_values = lambda tab: worksheet.get_all_values() if tab == "APPLIED" else []
cache._load_enrichment_map = lambda force=False: {}
cache.get_cv_profile = lambda force=False: None
cache.list_cv_variants = lambda: []
cache.refresh()
app = create_app()
controls = {"fail_get": False, "fail_patch_status": 0, "fail_refresh": False}
requests = []
patch_gate = asyncio.Event()
patch_gate.set()


@app.middleware("http")
async def tracker_fixture(request, call_next):
    path = request.url.path
    if path == "/__test__/tracker/reset" and request.method == "POST":
        payload = await request.json()
        worksheet.reset(payload.get("rows", SEED), HEADER_MODES.get(payload.get("header_mode")))
        controls.update(fail_get=False, fail_patch_status=0, fail_refresh=False)
        requests.clear()
        patch_gate.set()
        cache.refresh()
        return JSONResponse({"ok": True})
    if path == "/__test__/tracker/control" and request.method == "POST":
        payload = await request.json()
        for key in controls:
            if key in payload:
                controls[key] = payload[key]
        if "fail_write" in payload:
            worksheet.fail_write = payload["fail_write"]
        if "hold_patch" in payload:
            if payload["hold_patch"]:
                patch_gate.clear()
            else:
                patch_gate.set()
        return JSONResponse({"ok": True})
    if path == "/__test__/tracker/state" and request.method == "GET":
        return JSONResponse({"rows": cache._rows_to_dicts(worksheet.get_all_values()),
                             "requests": deepcopy(requests)})
    if path.startswith("/api/tracker"):
        entry = {"method": request.method, "path": path}
        if request.method in {"POST", "PATCH"}:
            entry["body"] = await request.json()
        requests.append(entry)
        if request.method == "PATCH":
            await patch_gate.wait()
            if controls["fail_patch_status"]:
                return JSONResponse({"detail": "injected tracker refusal"},
                                    status_code=controls["fail_patch_status"])
        if request.method == "GET" and controls["fail_get"]:
            return JSONResponse({"detail": "injected tracker read failure"}, status_code=502)
    if path == "/api/jobs/refresh" and controls["fail_refresh"]:
        return JSONResponse({"detail": "injected refresh failure"}, status_code=502)
    return await call_next(request)
