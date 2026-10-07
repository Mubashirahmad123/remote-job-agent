"""Create or reset a dashboard login user (username + Argon2id password).

Usage:
    python create_user.py <username> [password]

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


def main() -> int:
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print(__doc__)
        return 2

    # Same bounds the server enforces, read from api/auth.py itself so this
    # script can never drift from what /api/auth/login will actually accept.
    from api.auth import (
        _PASSWORD_MIN_LENGTH,
        _password_max_length,
        create_user,
        update_password,
    )

    minimum, maximum = _PASSWORD_MIN_LENGTH, _password_max_length()
    username = sys.argv[1]
    if len(sys.argv) == 3:
        password = sys.argv[2]
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
        user_id = create_user(username, password)
        print(f"Created user '{username}' (id {user_id}).")
    except ValueError as e:
        message = str(e)
        if "already exists" in message:
            if not update_password(username, password):
                print(f"Error: could not update password for '{username}'.")
                return 1
            # update_password also deletes every session for this user, so a
            # reset genuinely ends a stolen cookie rather than leaving it valid
            # for the rest of its TTL. Say so — it is the point of resetting.
            print(
                f"User '{username}' already existed — password reset and all "
                "their active sessions revoked (they must sign in again)."
            )
        else:
            print(f"Error: {message}")
            return 1

    print("Login next at http://127.0.0.1:8000/ (uvicorn must be running).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
