"""
tools/glm_client.py
Minimal Zhipu GLM client over its OpenAI-compatible HTTP endpoint.

WHY THIS FILE EXISTS — read before "simplifying" it back to the zhipuai SDK
---------------------------------------------------------------------------
`zhipuai` pins `pyjwt>=2.8.0,<2.9.0`. `crewai` pins `pyjwt>=2.13.0,<3`. Those
two ranges do not intersect, so listing both in requirements.txt makes the
dependency set UNSATISFIABLE: `pip install -r requirements.txt` dies with
`ResolutionImpossible` and `docker build` fails at Dockerfile:25. The error is
quoted in CHANGELOG.md (2026-10-08). zhipuai's last release was 2025-08-25
and every 2.1.x release has the same pin, so waiting for an upstream fix is not
a strategy.

The SDK only ever does two things this project needs:

  1. turn `GLM_API_KEY` into an `Authorization: Bearer` value, and
  2. POST an OpenAI-shaped chat completion to
     https://open.bigmodel.cn/api/paas/v4/chat/completions

Both are implemented here in a few dozen lines using the stdlib plus `requests`,
which is already a hard dependency and is already how the Groq and Mistral
rungs of the same fallback chain are called (see AGENTS.md). Dropping the SDK
therefore costs nothing except a transitive dependency we cannot afford.

Auth detail that is easy to get wrong: by default the SDK does NOT send the raw
key. It splits the key on "." into `id` and `secret`, then signs an HS256 JWT
whose `exp` and `timestamp` are in MILLISECONDS (not seconds). `auth_header`
below reproduces that exactly, and falls back to sending the key verbatim when
it has no "." — which is what the SDK does when its token cache is disabled and
what single-token Zhipu keys require.
"""

import base64
import hashlib
import hmac
import json
import os
import time

try:
    import requests
except ImportError:  # pragma: no cover - requests is a hard dependency
    requests = None

# Base URL taken from zhipuai/_client.py so the path stays in sync with the SDK.
GLM_BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
CHAT_COMPLETIONS_PATH = "/chat/completions"

# 2026-11-05: Zhipu decommissioned the bare `glm-4` model ID — every request
# now fails with error 1211 "模型不存在，请检查模型代码" (model does not exist),
# which knocked this leg of the fallback chain dead while the key and request
# shape were fine. `glm-4.5-flash` is the current FREE-tier OpenAI-compatible
# model, which suits this chain's role as fallback #4; callers override via
# GLM_MODEL when they want glm-4.6/4.7/5.x. One constant so the next model
# retirement is a one-line fix, not a grep-and-hope.
_SAFE_DEFAULT_MODEL = "glm-4.5-flash"

# Model IDs known to be retired at bigmodel.cn. An explicit operator override
# naming a dead ID is a config error, and honouring it dead-legs the chain
# (every call raises, the run falls through to Ollama). dotenv cannot save a
# running process here either: load_dotenv() never overrides an already-set
# env var, so a stale shell/container keeps serving GLM_MODEL=glm-4 even after
# .env is fixed. Explicit + wrong loses to the safe default.
_RETIRED_MODELS = frozenset({"glm-4"})

_env_model = os.getenv("GLM_MODEL", "").strip()
DEFAULT_MODEL = _SAFE_DEFAULT_MODEL if _env_model in _RETIRED_MODELS or not _env_model else _env_model


def resolve_model(env_value: str | None) -> str:
    """Env value or default, refusing retired model IDs.

    Call sites read GLM_MODEL independently of this module's import-time
    constant, so the retirement guard must be shared: a process that kept
    exporting GLM_MODEL=glm-4 (dotenv never overrides an existing env var)
    must not dead-leg the fallback chain.
    """
    value = (env_value or "").strip()
    return _SAFE_DEFAULT_MODEL if value in _RETIRED_MODELS or not value else value

# Mirrors zhipuai/core/_jwt_token.py: the token lives 30 s longer than the
# SDK's 3-minute cache, and both fields are milliseconds since the epoch.
_CACHE_TTL_SECONDS = 3 * 60
API_TOKEN_TTL_SECONDS = _CACHE_TTL_SECONDS + 30


def _b64url(raw: bytes) -> str:
    """Base64url without padding, as RFC 7515 requires for JWT segments."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_token(api_key: str, now_ms: int | None = None) -> str:
    """Sign an HS256 JWT for a Zhipu ``id.secret`` style key.

    Byte-for-byte equivalent of ``zhipuai.core._jwt_token.generate_token``,
    including the non-standard ``sign_type`` header and millisecond timestamps.
    Unlike the SDK this is not cached: a request here costs microseconds and a
    fresh token is always valid, whereas a cached one can expire mid-call.
    """
    try:
        key_id, secret = api_key.split(".")
    except ValueError:
        # The SDK raises "invalid api_key" here. Keep the same behaviour so a
        # misconfigured key surfaces as an auth error rather than a 200 from
        # some other branch.
        raise ValueError(f"invalid api_key: expected 'id.secret', got a key with {api_key.count('.')} dots")

    if now_ms is None:
        now_ms = int(round(time.time() * 1000))

    # Byte-exact with what pyjwt emits for the SDK, including the key order and
    # the compact separators: {"alg":"HS256","sign_type":"SIGN","typ":"JWT"}.
    # pyjwt merges its default "typ" AFTER the caller-supplied headers, which is
    # why it sorts last. Verified against zhipuai 2.1.5.20250825 in
    # tests/test_glm_client.py - keep this assertion if you touch the ordering.
    header = _b64url(
        json.dumps({"alg": "HS256", "sign_type": "SIGN", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = _b64url(
        json.dumps(
            {
                "api_key": key_id,
                "exp": now_ms + API_TOKEN_TTL_SECONDS * 1000,
                "timestamp": now_ms,
            },
            separators=(",", ":"),
        ).encode()
    )

    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64url(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def auth_header(api_key: str) -> str:
    """Return the `Authorization` value the GLM endpoint expects.

    A key containing "." is the legacy `id.secret` form and must be signed.
    Anything else is already a bearer token and is sent verbatim.
    """
    if "." in api_key:
        return f"Bearer {generate_token(api_key)}"
    return f"Bearer {api_key}"


def is_available(api_key: str) -> bool:
    """Whether GLM can be used at all: a key is configured and `requests` imported."""
    return bool(api_key) and requests is not None


def call_glm(prompt: str, api_key: str, model: str, timeout: int = 120) -> str:
    """One-shot chat completion. Returns the assistant text or raises.

    Raises ``Exception`` on any failure so the caller's fallback chain can move
    on to the next provider — the chain treats a raised exception as "this rung
    is broken", which is the correct reading of an HTTP 4xx/5xx here.
    """
    if requests is None:
        raise Exception("GLM not available: requests is not installed")
    if not api_key:
        raise Exception("GLM not available: GLM_API_KEY is not set")

    resp = requests.post(
        GLM_BASE_URL + CHAT_COMPLETIONS_PATH,
        headers={
            "Authorization": auth_header(api_key),
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    try:
        resp.raise_for_status()
    except Exception as exc:
        # Reproduce Zhipu's error body (e.g. 1211 model-not-exist) in the
        # message. A bare "400 Client Error" made this 4xx undiagnosable: the
        # actual cause ("模型不存在") lived in the hidden response text.
        body = ""
        try:
            body = resp.text[:500] or ""
        except Exception:
            pass
        detail = f"{body} ({exc})".strip() or repr(exc)
        raise Exception(f"GLM HTTP {resp.status_code}: {detail}") from exc
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise Exception(f"GLM returned unexpected response: {data}")
    if not content or not content.strip():
        raise Exception("GLM returned empty response")
    return content.strip()
