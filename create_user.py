"""Create or reset a dashboard login user (username + Argon2id password).

Usage:
    python create_user.py <username> [password] [--role admin|operator]

Omit the password to be prompted (no echo, typed twice). Safe to re-run for
the same username — it resets that user's password AND revokes every session
they hold, so a reset actually ends a stolen cookie instead of leaving it
valid for the rest of its TTL. Users live in the same SQLite file as the
apply-state store (data/apply_submit.db by default; AUTH_DB_PATH /
APPLY_STATE_DB_PATH override, see api/auth.py).

The moment a user exists, every /api/* route requires a login session
(or the server-side Bearer API_TOKEN) — the open-localhost default ends.
"""

import getpass
import sys


def _parse_args(argv):
    """Split `-h/--help` and `--role X` / `--role=X` from the positional args.

    Returns ``(positional, role, want_help)`` and raises ``ValueError`` on an
    unknown double-dash option.

    Rejecting unknown options is not pedantry. This script used to treat any
    unrecognised argument as a username, so `create_user.py --help` offered to
    create a user literally named `--help` — and since the FIRST user created
    becomes `admin`, one stray flag on a fresh deployment would have locked it
    into authentication with a junk administrator account nobody can name.

    Single-dash arguments stay positional on purpose: a password is allowed to
    begin with `-`, and `--` is honoured as the standard "everything after this
    is a value" separator.
    """
    role = None
    want_help = False
    positional = []
    index = 0
    only_positional = False
    while index < len(argv):
        arg = argv[index]
        if only_positional:
            positional.append(arg)
            index += 1
            continue
        if arg == "--":
            only_positional = True
            index += 1
            continue
        if arg in ("-h", "--help"):
            want_help = True
            index += 1
            continue
        if arg == "--role":
            if index + 1 >= len(argv):
                raise ValueError("--role needs a value (admin or operator)")
            role = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--role="):
            role = arg.split("=", 1)[1]
            index += 1
            continue
        if arg.startswith("--"):
            raise ValueError(f"unknown option: {arg}")
        positional.append(arg)
        index += 1
    return positional, role, want_help


def main() -> int:
    try:
        positional, requested_role, want_help = _parse_args(sys.argv[1:])
    except ValueError as exc:
        print(f"Error: {exc}")
        print(__doc__)
        return 2
    if want_help:
        print(__doc__)
        return 0
    if not positional or len(positional) > 2:
        print(__doc__)
        return 2
    username = positional[0]

    # Same bounds the server enforces, read from api/auth.py itself so this
    # script can never drift from what /api/auth/login will actually accept.
    from api.auth import (
        PASSWORD_MIN_LENGTH,
        VALID_ROLES,
        password_max_length,
        create_user,
        set_user_role,
        update_password,
    )

    if requested_role is not None and requested_role.strip().lower() not in VALID_ROLES:
        print(
            f"Error: --role must be one of: {', '.join(sorted(VALID_ROLES))} "
            f"(got '{requested_role}')."
        )
        return 1

    minimum, maximum = PASSWORD_MIN_LENGTH, password_max_length()
    if len(positional) == 2:
        password = positional[1]
    else:
        password = getpass.getpass(f"Password for '{username}' ({minimum}-{maximum} chars): ")
        confirm = getpass.getpass("Repeat password: ")
        if password != confirm:
            print("Error: passwords do not match.")
            return 1

    if not (minimum <= len(password) <= maximum):
        print(f"Error: password must be {minimum}-{maximum} characters.")
        return 1

    try:
        user_id = create_user(username, password, role=requested_role)
        # Read the role back rather than restating the request: when --role is
        # omitted the server decides (first user -> admin, later -> operator),
        # and printing the wrong thing here would be actively misleading.
        from api.auth import get_user_role

        print(
            f"Created user '{username}' (id {user_id}, role {get_user_role(username)})."
        )
    except ValueError as e:
        message = str(e)
        if "already exists" in message:
            if not update_password(username, password):
                print(f"Error: could not update password for '{username}'.")
                return 1
            # update_password also deletes every session for this user, so a
            # reset genuinely ends a stolen cookie rather than leaving it valid
            # for the rest of its TTL. Say so — it is the point of resetting.
            if requested_role is not None:
                if not set_user_role(username, requested_role):
                    print(f"Error: could not set role for '{username}'.")
                    return 1
            from api.auth import get_user_role

            print(
                f"User '{username}' already existed — password reset, role "
                f"{get_user_role(username)}, and all their active sessions "
                "revoked (they must sign in again)."
            )
        else:
            print(f"Error: {message}")
            return 1

    print("Login next at http://127.0.0.1:8000/ (uvicorn must be running).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
