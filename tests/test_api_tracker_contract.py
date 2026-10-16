"""Tracker routing/auth/error contracts and E2E-runner integration guards.

The Node suite exercises real tracker services against a fake worksheet. These
unit tests isolate the HTTP contract, especially legacy URL-keyed rows.
"""

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from api import cache
from api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT = "tracker-contract-fingerprint"
URL = "https://example.invalid/jobs/frontend?source=e2e&ref=one%2Ftwo#apply"


@pytest.fixture
def tracker_client(monkeypatch):
    calls = []
    monkeypatch.setenv("API_TOKEN", "tracker-contract-only-token")

    def update(key, status, notes):
        calls.append((key, status, notes))
        return {"job_title": "Frontend Developer", "company": "Fixture",
                "apply_url": URL, "status": status, "notes": notes}

    monkeypatch.setattr(cache, "update_tracker_and_get", update)
    with TestClient(create_app(), headers={"Authorization": "Bearer tracker-contract-only-token"}) as client:
        yield client, calls


@pytest.mark.parametrize("key", [FINGERPRINT, URL])
def test_patch_accepts_fingerprint_and_encoded_full_url_keys(tracker_client, key):
    client, calls = tracker_client

    async def send():
        # The pinned Starlette's legacy httpx TestClient branch unquotes an
        # already-decoded URL.path again. ASGITransport decodes once, like
        # uvicorn (also covered over real HTTP in tracker.test.mjs).
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app),
                                     base_url="http://testserver", headers=client.headers) as http:
            return await http.patch(f"/api/tracker/{quote(key, safe='')}",
                                    json={"status": "interviewing"})

    response = asyncio.run(send())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "interviewing"
    assert calls == [(key, "interviewing", "")]


@pytest.mark.parametrize("status", ["applied", "interviewing", "offer", "rejected", "withdrawn", "ghosted"])
def test_patch_accepts_only_documented_backend_statuses(tracker_client, status):
    client, calls = tracker_client
    response = client.patch(f"/api/tracker/{FINGERPRINT}", json={"status": status})
    assert response.status_code == 200
    assert calls[-1][1] == status


@pytest.mark.parametrize("status", ["review", "filled_ready", "interview", "hired", ""])
def test_ui_column_or_fill_labels_are_not_sent_as_backend_update_statuses(tracker_client, status):
    client, calls = tracker_client
    response = client.patch(f"/api/tracker/{FINGERPRINT}", json={"status": status})
    assert response.status_code == 400
    assert calls == []


def test_patch_normalizes_status_and_forwards_explicit_new_notes_once(tracker_client):
    client, calls = tracker_client
    response = client.patch(f"/api/tracker/{FINGERPRINT}",
                            json={"status": " INTERVIEWING ", "notes": "New recruiter reply"})
    assert response.status_code == 200
    assert calls == [(FINGERPRINT, "interviewing", "New recruiter reply")]


@pytest.mark.parametrize("key", [FINGERPRINT, URL])
def test_path_converter_does_not_bypass_auth(tracker_client, key):
    client, calls = tracker_client
    response = client.patch(f"/api/tracker/{quote(key, safe='')}", json={"status": "offer"},
                            headers={"Authorization": ""})
    assert response.status_code == 401
    assert calls == []


@pytest.mark.parametrize("exception,status", [(LookupError, 404), (ValueError, 400), (RuntimeError, 502)])
def test_update_failures_are_non_success_responses(tracker_client, monkeypatch, exception, status):
    client, _ = tracker_client

    def fail(*args):
        raise exception("fixture-only-storage-detail")

    monkeypatch.setattr(cache, "update_tracker_and_get", fail)
    response = client.patch(f"/api/tracker/{FINGERPRINT}", json={"status": "offer"})
    assert response.status_code == status
    if status == 502:
        assert "incident" in response.json()["detail"]
        assert "fixture-only-storage-detail" not in response.text


def test_missing_updated_row_returns_404(tracker_client, monkeypatch):
    client, _ = tracker_client
    monkeypatch.setattr(cache, "update_tracker_and_get", lambda *args: None)
    response = client.patch(f"/api/tracker/{FINGERPRINT}", json={"status": "offer"})
    assert response.status_code == 404


def test_tracker_controls_do_not_exist_in_the_production_app(tracker_client):
    client, _ = tracker_client
    for path in ["/__test__/tracker/reset", "/__test__/tracker/control"]:
        assert client.post(path, json={}).status_code == 405  # static mount, no test route
    assert client.get("/__test__/tracker/state").status_code == 404


def test_all_e2e_entrypoints_execute_the_tracker_suite():
    package = json.loads((ROOT / "tests/e2e/package.json").read_text(encoding="utf-8"))
    assert "smoke.test.mjs" in package["scripts"]["test"]
    assert "tracker.test.mjs" in package["scripts"]["test"]
    assert "environment.test.mjs" in package["scripts"]["test"]
    assert "review.test.mjs" in package["scripts"]["test"]
    shell = (ROOT / "tests/e2e/run.sh").read_text(encoding="utf-8")
    assert 'exec npm test' in shell
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["frontend-e2e"]["steps"]
    assert any(step.get("run", "").strip() == "npm test --prefix tests/e2e" for step in steps)
