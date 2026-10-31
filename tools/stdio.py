"""Make status output safe on redirected, non-UTF-8 consoles.

The application still contains Unicode status messages. Preserve the stream's
existing encoding (a parent process may be decoding it) but escape characters
that encoding cannot represent instead of letting diagnostic output fail the
operation it describes. Streams without reconfigure(), such as some test and
embedding streams, are left alone.
"""

import sys


def harden_stdio() -> None:
    """Best-effort hardening of both streams, independently and idempotently."""
    for stream in (sys.stdout, sys.stderr):
        try:
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(errors="backslashreplace")
        except Exception:
            # Closed/captured streams or streams that cannot be reconfigured
            # must not stop the app, or prevent the other stream being fixed.
            pass
