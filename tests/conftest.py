"""Test hermeticity: never inherit the developer's real .env tokens.

`agents/*` call `load_dotenv()` at import, so a local `.env` containing
`API_TOKEN` / `APPLY_API_TOKEN` (even a trailing-comment artifact like
`API_TOKEN=  # comment`, which python-dotenv parses as a garbage non-empty
value) leaks into the test process and flips every unauthenticated route to
401. Tests that need a token set it explicitly via `monkeypatch.setenv`;
everything else must see a clean slate.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _clear_api_tokens(monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("APPLY_API_TOKEN", raising=False)
