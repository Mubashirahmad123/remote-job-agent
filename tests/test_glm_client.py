"""
tests/test_glm_client.py

Guards two things that are easy to break silently:

1. ``tools/glm_client.py`` must authenticate to Zhipu GLM exactly the way the
   ``zhipuai`` SDK did. The token vectors below were captured from
   ``zhipuai==2.1.5.20250825``'s own ``core/_jwt_token.generate_token`` with a
   frozen clock, so this test proves equivalence without needing the SDK (or
   pyjwt) installed. If a vector ever fails, GLM calls are being rejected.

2. ``zhipuai`` must not come back into requirements.txt. It pins
   ``pyjwt>=2.8.0,<2.9.0``; crewai pins ``pyjwt>=2.13.0,<3``. Both present makes
   the dependency set unsatisfiable and ``docker build`` fail (the original log
   is docker-build-error.txt). The tests at the bottom fail the build locally
   rather than waiting for CI or for a broken image.
"""

import base64
import hashlib
import hmac
import json
import pathlib
import re

import pytest

from tools import glm_client

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Vectors captured from zhipuai==2.1.5.20250825 (core/_jwt_token.generate_token)
# with time.time() frozen at NOW_MS / 1000. Do not "clean these up" - they are
# the only evidence that our signer matches the SDK's.
# ---------------------------------------------------------------------------
SDK_KEY = "abcd1234efgh5678.SECRETabcdef0123456789SECRET"
NOW_MS = 1_760_000_000_000
SDK_HEADER_B64 = "eyJhbGciOiJIUzI1NiIsInNpZ25fdHlwZSI6IlNJR04iLCJ0eXAiOiJKV1QifQ"
SDK_PAYLOAD_B64 = (
    "eyJhcGlfa2V5IjoiYWJjZDEyMzRlZmdoNTY3OCIsImV4cCI6MTc2MDAwMDIxMDAwMCwi"
    "dGltZXN0YW1wIjoxNzYwMDAwMDAwMDAwfQ"
)
SDK_SIGNATURE = "unG5A9Togw9e9n5c9Kiz55DA3M22yx7gJPnvue8S6bw"
SDK_TOKEN = f"{SDK_HEADER_B64}.{SDK_PAYLOAD_B64}.{SDK_SIGNATURE}"


def _b64d(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


class _FakeResponse:
    def __init__(self, payload, status=200, raise_exc=None):
        self._payload = payload
        self.status_code = status
        self._raise_exc = raise_exc
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._payload


class _FakeRequests:
    """Stand-in for the `requests` module; records the call it was given."""

    def __init__(self, response):
        self.response = response
        self.calls = []
        self.post = self._post

    def _post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.response


class _FrozenTime:
    """Stand-in for the `time` module with a fixed clock."""

    def __init__(self, now_ms):
        self._now = now_ms / 1000.0

    def time(self):
        return self._now


@pytest.fixture
def frozen_clock(monkeypatch):
    """Pin glm_client's clock to the vector's timestamp.

    `generate_token()` reads the wall clock, so any test that compares two
    separately-produced tokens is racing the millisecond boundary: it passes
    almost always and fails occasionally for no reason related to the code. Both
    tests below were flaky this way before the clock was frozen.
    """
    monkeypatch.setattr(glm_client, "time", _FrozenTime(NOW_MS))


@pytest.fixture
def fake_requests(monkeypatch):
    """Install a fake `requests` so call_glm can be tested with no network."""

    def _install(response):
        fake = _FakeRequests(response)
        monkeypatch.setattr(glm_client, "requests", fake)
        return fake

    return _install


def _ok_response(content="  hello from GLM  "):
    return _FakeResponse({"choices": [{"message": {"role": "assistant", "content": content}}]})


# ---------------------------------------------------------------------------
# 1. Token signing must be identical to the SDK
# ---------------------------------------------------------------------------


class TestTokenMatchesTheZhipuaiSdk:
    def test_full_token_is_byte_identical_to_the_sdk(self):
        assert glm_client.generate_token(SDK_KEY, now_ms=NOW_MS) == SDK_TOKEN

    def test_header_segment_matches(self):
        header = glm_client.generate_token(SDK_KEY, now_ms=NOW_MS).split(".")[0]
        assert header == SDK_HEADER_B64

    def test_header_json_includes_the_non_standard_sign_type_field(self):
        # pyjwt merges its default "typ" AFTER the caller's headers, which is
        # why "typ" sorts last on the wire. Key order is part of the vector.
        raw = _b64d(SDK_HEADER_B64).decode()
        assert raw == '{"alg":"HS256","sign_type":"SIGN","typ":"JWT"}'
        assert raw == _b64d(glm_client.generate_token(SDK_KEY, now_ms=NOW_MS).split(".")[0]).decode()

    def test_payload_json_is_compact_and_ordered_like_the_sdk(self):
        raw = _b64d(glm_client.generate_token(SDK_KEY, now_ms=NOW_MS).split(".")[1]).decode()
        assert raw == (
            '{"api_key":"abcd1234efgh5678","exp":1760000210000,"timestamp":1760000000000}'
        )

    def test_payload_carries_the_key_id_not_the_whole_key(self):
        payload = json.loads(_b64d(glm_client.generate_token(SDK_KEY, now_ms=NOW_MS).split(".")[1]))
        assert payload["api_key"] == SDK_KEY.split(".")[0]
        assert SDK_KEY.split(".")[1] not in json.dumps(payload)

    def test_expiry_is_210_seconds_after_timestamp_in_milliseconds(self):
        # The SDK uses CACHE_TTL_SECONDS (180) + 30, and both fields are ms.
        payload = json.loads(_b64d(glm_client.generate_token(SDK_KEY, now_ms=NOW_MS).split(".")[1]))
        assert payload["exp"] - payload["timestamp"] == 210_000
        assert payload["timestamp"] == NOW_MS

    def test_timestamps_are_milliseconds_not_seconds(self):
        payload = json.loads(_b64d(glm_client.generate_token(SDK_KEY, now_ms=NOW_MS).split(".")[1]))
        # A seconds-based `exp` here would be a year in the past, and every
        # request would 401 - the single most likely mistake in this file.
        assert payload["exp"] > 10**12
        assert glm_client.API_TOKEN_TTL_SECONDS == 210

    def test_signature_is_hs256_over_the_signing_input_with_the_secret_half(self):
        token = glm_client.generate_token(SDK_KEY, now_ms=NOW_MS)
        header, payload, signature = token.split(".")
        expected = base64.urlsafe_b64encode(
            hmac.new(
                SDK_KEY.split(".")[1].encode(),
                f"{header}.{payload}".encode("ascii"),
                hashlib.sha256,
            ).digest()
        ).decode().rstrip("=")
        assert signature == expected

    def test_base64url_segments_are_unpadded_per_rfc7515(self):
        for segment in glm_client.generate_token(SDK_KEY, now_ms=NOW_MS).split("."):
            assert "=" not in segment
            assert "+" not in segment and "/" not in segment

    def test_a_key_without_a_dot_is_rejected_like_the_sdk(self):
        # The SDK raises Exception("invalid api_key"); we raise ValueError, which
        # the fallback chain catches the same way.
        with pytest.raises(ValueError, match="invalid api_key"):
            glm_client.generate_token("no-dot-here", now_ms=NOW_MS)

    def test_default_now_is_the_current_wall_clock_in_milliseconds(self):
        import time

        # generate_token rounds to the nearest ms exactly like the SDK does, so
        # compare against rounded bounds with 1 ms of slack: truncating here
        # makes the test flaky whenever the fractional part crosses .5.
        before = round(time.time() * 1000) - 1
        payload = json.loads(_b64d(glm_client.generate_token(SDK_KEY).split(".")[1]))
        after = round(time.time() * 1000) + 1
        assert before <= payload["timestamp"] <= after
        assert payload["exp"] == payload["timestamp"] + 210_000

    def test_each_call_makes_a_fresh_token_rather_than_reusing_a_cached_one(self):
        # The SDK cached tokens for 3 minutes; we deliberately do not, so a long
        # running process can never present an expired token.
        first = glm_client.generate_token(SDK_KEY, now_ms=NOW_MS)
        later = glm_client.generate_token(SDK_KEY, now_ms=NOW_MS + 10 * 60 * 1000)
        assert first != later


# ---------------------------------------------------------------------------
# 2. auth_header: sign legacy keys, pass modern single tokens through
# ---------------------------------------------------------------------------


class TestAuthHeader:
    def test_id_dot_secret_key_is_signed(self, frozen_clock):
        header = glm_client.auth_header(SDK_KEY)
        assert header.startswith("Bearer ")
        token = header.removeprefix("Bearer ")
        assert token == glm_client.generate_token(SDK_KEY)
        assert token == SDK_TOKEN, "auth_header must produce the SDK's exact token"
        assert token != SDK_KEY, "the raw key must never be sent for an id.secret key"

    def test_single_token_key_is_sent_verbatim(self):
        # Zhipu also issues keys with no dot; the SDK sends those as-is when its
        # token cache is disabled. Signing one would corrupt it.
        raw = "a-plain-bearer-token-without-a-dot"
        assert glm_client.auth_header(raw) == f"Bearer {raw}"

    def test_signed_token_has_three_dot_separated_segments(self):
        token = glm_client.auth_header(SDK_KEY).removeprefix("Bearer ")
        assert len(token.split(".")) == 3


# ---------------------------------------------------------------------------
# 3. Availability gating
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_false_without_a_key(self):
        assert glm_client.is_available("") is False

    def test_false_when_requests_could_not_be_imported(self, monkeypatch):
        monkeypatch.setattr(glm_client, "requests", None)
        assert glm_client.is_available(SDK_KEY) is False

    def test_true_with_both(self, fake_requests):
        fake_requests(_ok_response())
        assert glm_client.is_available(SDK_KEY) is True


# ---------------------------------------------------------------------------
# 4. call_glm: the HTTP contract
# ---------------------------------------------------------------------------


class TestCallGlm:
    def test_posts_to_the_openai_compatible_chat_completions_url(self, fake_requests):
        fake = fake_requests(_ok_response())
        glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")
        assert fake.calls[0]["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    def test_url_is_configurable_for_a_proxy_or_a_regional_endpoint(self, monkeypatch, fake_requests):
        fake = fake_requests(_ok_response())
        monkeypatch.setattr(glm_client, "GLM_BASE_URL", "https://internal.example/api/paas/v4")
        glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")
        assert fake.calls[0]["url"] == "https://internal.example/api/paas/v4/chat/completions"

    def test_sends_bearer_auth_json_content_type_model_and_one_user_message(
        self, fake_requests, frozen_clock
    ):
        fake = fake_requests(_ok_response())
        glm_client.call_glm("write a cover letter", api_key=SDK_KEY, model="glm-4")
        call = fake.calls[0]
        assert call["headers"]["Content-Type"] == "application/json"
        assert call["headers"]["Authorization"] == f"Bearer {SDK_TOKEN}"
        assert call["headers"]["Authorization"] == glm_client.auth_header(SDK_KEY)
        assert call["json"] == {
            "model": "glm-4",
            "messages": [{"role": "user", "content": "write a cover letter"}],
        }

    def test_the_model_is_passed_through_so_glm_model_is_honoured(self, fake_requests):
        fake = fake_requests(_ok_response())
        glm_client.call_glm("x", api_key=SDK_KEY, model="glm-4-plus")
        assert fake.calls[0]["json"]["model"] == "glm-4-plus"

    def test_returns_stripped_assistant_content(self, fake_requests):
        fake_requests(_ok_response("  hello from GLM  "))
        assert glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4") == "hello from GLM"

    def test_has_a_timeout_so_a_hung_provider_cannot_stall_the_chain(self, fake_requests):
        fake = fake_requests(_ok_response())
        glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")
        assert fake.calls[0]["timeout"] == 120

    def test_timeout_is_overridable(self, fake_requests):
        fake = fake_requests(_ok_response())
        glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4", timeout=5)
        assert fake.calls[0]["timeout"] == 5

    def test_raises_on_http_error_so_the_fallback_chain_moves_on(self, fake_requests):
        fake_requests(_FakeResponse({}, status=401, raise_exc=Exception("401 Client Error")))
        with pytest.raises(Exception, match="401"):
            glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")

    def test_raise_for_status_is_always_called(self, fake_requests):
        # A 4xx/5xx with a parseable body must still fail: without this the chain
        # would "succeed" with an error message as the generated cover letter.
        response = _ok_response()
        fake_requests(response)
        glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")
        assert response.raise_for_status_called is True

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"choices": []},
            {"choices": [{}]},
            {"choices": [{"message": {}}]},
            {"choices": [{"message": {"content": None}}]},
            None,
        ],
    )
    def test_raises_on_a_malformed_response_instead_of_indexerror(self, fake_requests, payload):
        fake_requests(_FakeResponse(payload))
        with pytest.raises(Exception):
            glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")

    def test_raises_on_empty_content(self, fake_requests):
        fake_requests(_ok_response("   "))
        with pytest.raises(Exception, match="empty response"):
            glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")

    def test_raises_when_requests_is_missing(self, monkeypatch):
        monkeypatch.setattr(glm_client, "requests", None)
        with pytest.raises(Exception, match="requests is not installed"):
            glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")

    def test_raises_when_the_key_is_missing(self, fake_requests):
        fake_requests(_ok_response())
        with pytest.raises(Exception, match="GLM_API_KEY is not set"):
            glm_client.call_glm("hi", api_key="", model="glm-4")

    def test_never_leaks_the_api_key_into_an_exception_message(self, fake_requests):
        # Errors from this chain get printed and appended to a user-visible
        # "all providers failed" message, so the signed token must not ride along.
        fake_requests(_FakeResponse({}, status=500, raise_exc=Exception("500 Server Error")))
        try:
            glm_client.call_glm("hi", api_key=SDK_KEY, model="glm-4")
        except Exception as exc:
            assert SDK_KEY not in str(exc)
            assert SDK_KEY.split(".")[1] not in str(exc)


# ---------------------------------------------------------------------------
# 5. The three consumers use the HTTP client and never import the SDK
# ---------------------------------------------------------------------------

CONSUMERS = ["agents/gemini_tools.py", "tools/cv_parser.py", "tools/resume_generator.py"]


class TestConsumersWiredToTheHttpClient:
    @pytest.mark.parametrize("relpath", CONSUMERS)
    def test_does_not_import_the_zhipuai_sdk(self, relpath):
        src = (REPO_ROOT / relpath).read_text()
        assert not re.search(r"^\s*(from|import)\s+zhipuai", src, re.M), relpath
        assert "ZhipuAI(" not in src, relpath

    @pytest.mark.parametrize("relpath", CONSUMERS)
    def test_imports_glm_client(self, relpath):
        src = (REPO_ROOT / relpath).read_text()
        assert "glm_client" in src, relpath

    @pytest.mark.parametrize("relpath", CONSUMERS)
    def test_call_glm_delegates_to_the_shared_client(self, relpath):
        src = (REPO_ROOT / relpath).read_text()
        assert "_glm.call_glm(prompt, api_key=GLM_API_KEY, model=GLM_MODEL)" in src, relpath

    @pytest.mark.parametrize("relpath", CONSUMERS)
    def test_glm_still_degrades_gracefully_without_the_dependency(self, relpath):
        # GLM_AVAILABLE must be False (not a crash) when the import fails, so the
        # fallback chain skips rung 3 instead of taking the whole pipeline down.
        src = (REPO_ROOT / relpath).read_text()
        assert re.search(r"except ImportError:\s*\n\s*GLM_AVAILABLE = False", src), relpath

    def test_cv_parser_tolerates_being_run_as_a_script(self):
        # Its docstring documents `python tools/cv_parser.py <cv.pdf>`, which puts
        # tools/ (not the repo root) on sys.path[0]. Without the flat fallback
        # import that documented invocation would break.
        src = (REPO_ROOT / "tools/cv_parser.py").read_text()
        assert re.search(r"^\s*import glm_client as _glm", src, re.M)

    def test_all_three_modules_import_without_zhipuai_installed(self):
        import importlib

        for module in ("tools.glm_client", "tools.cv_parser", "tools.resume_generator", "agents.gemini_tools"):
            importlib.import_module(module)

    def test_glm_is_disabled_when_no_key_is_configured(self, monkeypatch):
        # Proves the availability gate is driven by the key, not by an import
        # that used to be the zhipuai SDK.
        monkeypatch.setattr(glm_client, "requests", _FakeRequests(_ok_response()))
        assert glm_client.is_available("") is False
        assert glm_client.is_available("some.key") is True


# ---------------------------------------------------------------------------
# 6. Dependency hygiene: the conflict that broke `docker build` must stay fixed
# ---------------------------------------------------------------------------


def _parse_requirements(path):
    """name -> specifier, ignoring comments, options and env markers."""
    out = {}
    for line in (REPO_ROOT / path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", line)
        if m:
            out.setdefault(m.group(1).lower().replace("_", "-"), m.group(2).strip())
    return out


class TestDependencyHygiene:
    def test_zhipuai_is_not_a_dependency(self):
        # zhipuai needs pyjwt<2.9.0, crewai needs pyjwt>=2.13.0. Re-adding it
        # makes `pip install -r requirements.txt` ResolutionImpossible and the
        # Docker image unbuildable. See tools/glm_client.py's docstring.
        assert "zhipuai" not in _parse_requirements("requirements.txt")

    def test_pyjwt_is_not_pinned_below_the_crewai_floor(self):
        req = _parse_requirements("requirements.txt")
        if "pyjwt" in req:
            m = re.search(r"<\s*([0-9.]+)", req["pyjwt"])
            assert not m or m.group(1) > "2.13.0", (
                "pyjwt is capped below 2.13.0, which crewai==1.14.7 requires"
            )

    def test_the_lock_covers_every_direct_requirement(self):
        req = _parse_requirements("requirements.txt")
        lock = _parse_requirements("requirements.lock.txt")
        missing = sorted(set(req) - set(lock))
        assert not missing, (
            f"{missing} in requirements.txt but not in requirements.lock.txt - "
            "regenerate with: uv pip compile requirements.txt -o requirements.lock.txt --universal"
        )

    def test_exact_pins_agree_between_requirements_and_the_lock(self):
        req = _parse_requirements("requirements.txt")
        lock = _parse_requirements("requirements.lock.txt")
        wrong = []
        for name in sorted(set(req) & set(lock)):
            m = re.fullmatch(r"==\s*([A-Za-z0-9_.\-+]+)", req[name])
            if m and lock[name].lstrip("=") != m.group(1):
                wrong.append(f"{name}: requirements pins =={m.group(1)}, lock has {lock[name]}")
        assert not wrong, "; ".join(wrong)

    def test_the_lock_keeps_platform_markers_so_it_installs_on_linux(self):
        lock_text = (REPO_ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
        # pywin32 is Windows-only. Unmarked, it makes the lock uninstallable on
        # the Oracle ARM VM - which is exactly what the previous lock did.
        pywin = [ln for ln in lock_text.splitlines() if ln.lower().startswith("pywin32==")]
        if pywin:
            assert "sys_platform" in pywin[0], f"pywin32 lost its marker: {pywin[0]!r}"
        assert "--universal" in lock_text, "lock header must record the --universal flag"

    def test_argon2_is_in_both_files(self):
        # Regression guard for the original finding that started this check.
        assert "argon2-cffi" in _parse_requirements("requirements.txt")
        assert "argon2-cffi" in _parse_requirements("requirements.lock.txt")
