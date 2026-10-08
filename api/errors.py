"""Internal failures become responses that help the operator without
describing the server to the caller.

Every 502 in this API used to be `detail=f"<action> failed: {e}"`, forwarding
whatever Python produced straight to the client. In practice that looked like:

    {"detail": "Resume generation failed: expected str, bytes or os.PathLike
     object, not NoneType"}

That is the real message this was found with, and it is the worst of both
worlds. Useless to the operator — it names no file, no line, no cause, so
the one person who could act on it has to go read the logs anyway. Useful to
anyone probing the API — exception text is a free description of the internal
call graph and the libraries in use, and when the failure comes from a path or
a connection string it carries the server's filesystem layout with it.
`FileNotFoundError` is the concrete case: `str(e)` *is* the absolute path, so
`GET /api/apply/{fp}/screenshot` was happy to reply
`[Errno 2] No such file or directory: '/app/screenshots/ab12.png'` and confirm
exactly where artifacts live inside the container.

The fix is not to hide the error, it is to send it somewhere it can be acted
on: the full traceback goes to the server log under a short incident id, and
the same id goes to the caller. "Resume generation failed, incident 3f9a1c2b"
is now greppable in `docker compose logs api`, which is more than the raw
exception text ever was.

What this deliberately does NOT touch: errors whose messages are written for
the user. A `ValueError` from `cache.refresh` says "Unknown tab 'X'. Choose
from: ALL JOBS, TOP MATCHES, ..." and a `RuntimeError` from `runs` says a
scrape is already active — those are the API being helpful, and routing them
through here would make the dashboard worse without hiding anything. Only the
broad `except Exception` handlers, which catch failures nobody designed a
message for, use this module.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

__all__ = ["failure", "missing"]

logger = logging.getLogger("api.errors")


def _incident_id() -> str:
    """8 hex characters.

    Enough to grep a log by and short enough to paste into a chat message. Not
    a secret and not a counter — a counter would tell any caller how many
    failures the server has had, which is its own (small) signal.
    """
    return uuid.uuid4().hex[:8]


def failure(action: str, exc: BaseException, *, status_code: int = 502) -> HTTPException:
    """Log `exc` in full and return a generic HTTPException naming `action`.

    `action` describes the OPERATION ("Resume generation"), never the cause.
    Callers do `raise failure("Resume generation", exc)`.

    Returns the exception rather than raising it so the call site stays a
    one-line `raise` and reads the same as the HTTPException it replaces.
    """
    incident = _incident_id()
    # exc_info=<instance> logs the traceback of that exception specifically,
    # which is what the operator needs: the message alone is what the client
    # already had and could not act on.
    logger.error("%s failed (incident %s): %s", action, incident, exc, exc_info=exc)
    return HTTPException(
        status_code=status_code,
        detail=(
            f"{action} failed. The server logged the details under incident "
            f"{incident}."
        ),
    )


def missing(what: str) -> HTTPException:
    """A 404 that does not say where the thing would have been.

    For the cases where a filesystem error escapes as "the artifact is gone":
    the caller needs to know it is missing, not what path was tried.
    """
    return HTTPException(status_code=404, detail=f"{what} not found")
