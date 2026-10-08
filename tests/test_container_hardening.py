"""The container must not run as root (M2).

`Dockerfile` had no `USER` directive, so PID 1 in all three services was root.
docker-compose bind-mounts `./.env` and `./keys.json` into every one of them —
`:ro` prevents writes but not reads — and the api container runs a headless
browser that navigates to URLs taken from scraped job postings.

So the realistic worst case was: a browser or scraper compromise (the two
findings fixed immediately before this one, H2 and H3, were exactly the paths
in) lands a shell as root in a container holding the Google service-account
private key and every API key in `.env`. Dropping to an unprivileged user does
not by itself make those files unreadable — the mount owner still decides that —
but it removes root, which is the difference between "read a mounted secret" and
"also own the container, its filesystem and the kernel attack surface it
presents".

The operational hazard this has to respect: the UID must match the owner of the
host directories compose bind-mounts (./data, ./logs, ./resumes,
./screenshots, ...). Get that wrong and the app starts cleanly and then cannot
write to its own volumes — a permission failure that surfaces at the worst
possible moment and looks nothing like a security change. So the UID is a build
arg, deploy/setup-vm.sh derives it from the deploying user and records it in
.env, and the tests below pin all three ends to the same default so they cannot
drift apart.

These are static checks: no docker daemon is available here, so the image itself
is verified by the CI `docker` job. What this file guarantees is that the
hardening is present and internally consistent.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The one default all three ends must agree on.
EXPECTED_DEFAULT_UID = "1000"
EXPECTED_DEFAULT_GID = "1000"


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def _dockerfile_instructions(text):
    """(instruction, arguments, line-number) for each Dockerfile instruction,
    joined across line continuations."""
    logical = []
    buffer = ""
    start = 0
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not buffer:
            start = index
        if not stripped or stripped.startswith("#"):
            # Docker removes whole-line comments before parsing, including ones
            # sitting between continuation lines, so they are not part of any
            # instruction. The buffer survives, so a comment mid-continuation is
            # simply skipped.
            continue
        buffer = f"{buffer} {stripped}".strip() if buffer else stripped
        if buffer.endswith("\\"):
            buffer = buffer[:-1].strip()
            continue
        if buffer:
            parts = buffer.split(None, 1)
            logical.append((parts[0].upper(), parts[1] if len(parts) > 1 else "", start))
        buffer = ""
    return logical


# --- the runtime user --------------------------------------------------------


def test_the_image_runs_as_an_unprivileged_user():
    instructions = _dockerfile_instructions(_read("Dockerfile"))
    users = [args for name, args, _ in instructions if name == "USER"]
    assert users, "Dockerfile has no USER directive — the container runs as root"
    assert users[-1].strip() != "root", "the final USER is root"
    assert len(users) == 1, (
        f"more than one USER directive ({users}); a later `USER root` would undo "
        "the drop, which is how this regresses in practice"
    )


def test_the_user_is_created_before_it_is_used():
    instructions = _dockerfile_instructions(_read("Dockerfile"))
    creates = [line for name, args, line in instructions if name == "RUN" and "useradd" in args]
    uses = [line for name, args, line in instructions if name == "USER"]
    assert creates, "no useradd in any RUN — USER would name a user that does not exist"
    assert uses, "no USER directive"
    assert creates[0] < uses[0], "USER appears before the user is created"


def test_the_uid_comes_from_a_build_arg_with_the_expected_default():
    dockerfile = _read("Dockerfile")
    uid = re.search(r"^ARG\s+APP_UID=(\d+)\s*$", dockerfile, re.M)
    gid = re.search(r"^ARG\s+APP_GID=(\d+)\s*$", dockerfile, re.M)
    assert uid, "APP_UID is not a build ARG with a numeric default"
    assert gid, "APP_GID is not a build ARG with a numeric default"
    assert uid.group(1) == EXPECTED_DEFAULT_UID
    assert gid.group(1) == EXPECTED_DEFAULT_GID
    # The ARGs must actually reach the account, or the build arg is decoration.
    assert re.search(r'useradd[^\n]*--uid\s+"\$\{APP_UID\}"', dockerfile), "useradd ignores APP_UID"
    assert re.search(r'groupadd[^\n]*--gid\s+"\$\{APP_GID\}"', dockerfile), "groupadd ignores APP_GID"


def test_the_source_copy_is_owned_by_the_runtime_user():
    dockerfile = _read("Dockerfile")
    copies = re.findall(r"^COPY\s+(.*)$", dockerfile, re.M)
    app_copy = [c for c in copies if c.rstrip().endswith(". .")]
    assert app_copy, "no `COPY . .` found; the instruction shape changed"
    assert "--chown=agent:agent" in app_copy[0], (
        "COPY . . without --chown leaves the source root-owned, so the runtime "
        "user cannot write anything it needs to inside /app. Use --chown rather "
        "than a later `chown -R`: a separate chown writes every file into a "
        "second layer and roughly doubles the image size."
    )


def test_the_volume_mount_points_are_owned_by_the_runtime_user():
    dockerfile = _read("Dockerfile")
    assert re.search(r"chown\s+-R\s+agent:agent\s+/app", dockerfile), (
        "the mkdir'd volume mount points are not chowned to the runtime user"
    )
    for directory in ("data", "logs", "apply_packages", "cover_letters", "resumes", "screenshots", "cache"):
        assert re.search(rf"mkdir\s+-p[^\n]*\b{directory}\b", dockerfile), (
            f"{directory}/ is no longer created in the image"
        )


# --- Playwright, which root installs and the runtime user must read -----------


def test_playwright_browsers_are_not_under_root():
    """Installed as root (apt needs it), read at runtime as `agent`. The default
    location /root/.cache/ms-playwright is unreadable to the runtime user, and
    the failure is a confusing "Executable doesn't exist" at the first apply."""
    dockerfile = _read("Dockerfile")
    match = re.search(r"PLAYWRIGHT_BROWSERS_PATH=(\S+)", dockerfile)
    assert match, "PLAYWRIGHT_BROWSERS_PATH is not set; Playwright will default to /root/.cache"
    path = match.group(1).rstrip(" \\")
    assert not path.startswith("/root"), f"{path} is unreachable by a non-root runtime user"
    # It must be an ENV, not just an ARG or an inline prefix on the install
    # command: Playwright resolves it again when the browser launches.
    env_blocks = [args for name, args, _ in _dockerfile_instructions(dockerfile) if name == "ENV"]
    assert any("PLAYWRIGHT_BROWSERS_PATH" in block for block in env_blocks), (
        "PLAYWRIGHT_BROWSERS_PATH must be set with ENV so it is still present at "
        "runtime, not only during `playwright install`"
    )
    install = [
        line
        for name, args, line in _dockerfile_instructions(dockerfile)
        if name == "RUN" and "playwright install" in args
    ]
    assert install, "the playwright install step disappeared"
    user_line = [line for name, args, line in _dockerfile_instructions(dockerfile) if name == "USER"][0]
    assert install[0] < user_line, "the browser must be installed before dropping privileges"


# --- the two ends must agree -------------------------------------------------


def test_compose_passes_the_uid_to_every_service_that_builds():
    compose = yaml.safe_load(_read("docker-compose.yml"))
    builders = {
        name: service["build"]
        for name, service in compose["services"].items()
        if isinstance(service.get("build"), dict)
    }
    assert builders, "no service uses the long-form build; the args cannot be passed"
    assert set(builders) == {"scheduler", "runner", "api"}, sorted(builders)
    for name, build in builders.items():
        args = build.get("args") or {}
        assert args.get("APP_UID") == f"${{RJA_APP_UID:-{EXPECTED_DEFAULT_UID}}}", (
            f"{name} does not pass APP_UID from RJA_APP_UID with the right default"
        )
        assert args.get("APP_GID") == f"${{RJA_APP_GID:-{EXPECTED_DEFAULT_GID}}}", (
            f"{name} does not pass APP_GID from RJA_APP_GID with the right default"
        )


def test_setup_vm_records_the_uid_where_compose_can_interpolate_it():
    script = _read("deploy/setup-vm.sh")
    assert "RJA_APP_UID" in script, "setup-vm.sh never writes RJA_APP_UID"
    assert re.search(r'id\s+-u', script), "setup-vm.sh does not derive the UID from the deploying user"
    # Compose interpolates ${RJA_APP_UID} from ./.env, so that is where it must go.
    assert re.search(r">>\s*\.env", script), "the IDs are not appended to .env"
    assert re.search(r'chown\s+-R\s+"\$\{TARGET_UID\}:\$\{TARGET_GID\}"', script), (
        "the bind-mounted volumes must be chowned by NUMERIC id — chowning by "
        "name leaves the container user, which has the same UID but a different "
        "name, unable to write them"
    )


def test_env_example_documents_the_runtime_user():
    example = _read(".env.example")
    assert re.search(rf"^RJA_APP_UID={EXPECTED_DEFAULT_UID}\s*$", example, re.M)
    assert re.search(rf"^RJA_APP_GID={EXPECTED_DEFAULT_GID}\s*$", example, re.M)


def test_all_three_defaults_agree():
    """The Dockerfile ARG, the compose interpolation fallback and .env.example
    are three independent places stating one number. If they drift, the image
    builds with one UID and the volumes are owned by another."""
    dockerfile = _read("Dockerfile")
    compose = _read("docker-compose.yml")
    example = _read(".env.example")
    assert re.search(rf"^ARG\s+APP_UID={EXPECTED_DEFAULT_UID}\s*$", dockerfile, re.M)
    assert re.search(rf"RJA_APP_UID:-{EXPECTED_DEFAULT_UID}", compose)
    assert re.search(rf"^RJA_APP_UID={EXPECTED_DEFAULT_UID}\s*$", example, re.M)


# --- unrelated hardening that must survive this change -----------------------


def test_the_api_port_is_still_localhost_only():
    """Touching the compose file is a good moment to lose this. The API must not
    be published on 0.0.0.0: Caddy is the public entry point, and a directly
    reachable API also gets to pick its own X-Forwarded-For (see
    tests/test_proxy_header_trust.py)."""
    compose = yaml.safe_load(_read("docker-compose.yml"))
    ports = compose["services"]["api"]["ports"]
    assert ports == ["127.0.0.1:8000:8000"], ports


def test_the_internal_subnet_is_still_pinned():
    compose = yaml.safe_load(_read("docker-compose.yml"))
    subnets = compose["networks"]["default"]["ipam"]["config"]
    assert len(subnets) == 1 and "subnet" in subnets[0], subnets
