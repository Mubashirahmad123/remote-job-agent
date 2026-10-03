"""Canonical board/source names — shared by the write and read paths.

Why this exists
---------------
`agents/scrapper.py` sets `job["source"] = board` in 22 places, where `board`
is the key from MASTER_BOARDS/ADDITIONAL_BOARDS. Several of those keys point at
the *same provider*, so one board shows up under several names and every
by-source view splits:

    RemoteOKAPI        == RemoteOK        (identical URL https://remoteok.com/api)
    Remojobs-Frontend  == Remotive        (remotive.com/api with ?search=frontend)
    Remojobs-Backend   == Remotive        (…?search=backend)
    Remojobs-Fullstack == Remotive        (…?search=fullstack)
    FounditIN          == Naukri          (identical URL naukri.com/remote-developer-jobs)

Consequences this fixes: `/api/stats` `by_source` counts one provider twice,
the dashboard sources grid shows duplicate cards competing for the top-8 slots,
and the Job Desk source dropdown offers two entries that each return half the
rows.

Applied on BOTH sides deliberately:
  * write — `tools.sheet_writer.prepare_job_for_sheet`, one choke point for
    every board and parser, so new rows land canonical;
  * read  — `api.cache`, because rows already written to the Sheet under the
    old names must merge too. A write-only fix would leave the split visible
    until the sheet is rebuilt.

Kept deliberately dumb: an explicit alias table, no fuzzy matching. An unknown
board passes through unchanged (new boards must not be silently renamed).
"""

from typing import Dict

# lowercase lookup key -> canonical display name.
SOURCE_ALIASES: Dict[str, str] = {
    # Same URL, two board entries (double-fetched every run).
    "remoteokapi": "RemoteOK",
    "remote ok": "RemoteOK",
    "remoteok.com": "RemoteOK",
    # Remotive API hit three more times with ?search= params. These are not a
    # separate board called "Remojobs" (README listed them as HTML boards —
    # they are Remotive API calls).
    "remojobs": "Remotive",
    "remojobs-frontend": "Remotive",
    "remojobs-backend": "Remotive",
    "remojobs-fullstack": "Remotive",
    "remotive.com": "Remotive",
    # FounditIN's configured URL is naukri.com, so its rows are Naukri rows.
    # Labelling them FounditIN misattributes the data. (Both are bot-walled and
    # currently yield nothing — see PRODUCTION.md §7 — so this is about not
    # lying in the source column if either ever starts returning rows.)
    "founditin": "Naukri",
    # Casing/spacing drift seen in sheet rows written by older runs.
    "weworkremotely": "WeWorkRemotely",
    "we work remotely": "WeWorkRemotely",
    "wwr": "WeWorkRemotely",
    "authenticjobs": "AuthenticJobs",
    "workingnomads": "WorkingNomads",
    "working nomads": "WorkingNomads",
    "ycombinator": "YCombinator",
    "y combinator": "YCombinator",
}

# Canonical spellings, so a differently-cased row ("remotive", "REMOTIVE")
# normalizes to the house style without needing an alias entry each.
CANONICAL_SOURCES = (
    "RemoteOK", "Remotive", "Arbeitnow", "Himalayas", "Jobicy", "TheMuse",
    "Adzuna", "WorkingNomads", "AuthenticJobs", "WeWorkRemotely", "Wellfound",
    "YCombinator", "Jobspresso", "Arc", "Lemon", "FlexJobs", "RemoteCo",
    "JustRemote", "NoDesk", "RemoteTech", "GoRemote", "Remote4me",
    "DailyRemote", "RemoteFrontendJobs", "FindBacon", "LandingJobs",
    "WeAreDevelopers", "NoFluffJobs", "JustJoinIt", "CWJobs", "WorkInStartups",
    "BuiltIn", "Dice", "GulfTalent", "Naukri", "NaukriGulf", "Shine",
    "TimesJobs", "TrueUp", "RemoteRocketship", "RemoteJobsCom", "Remotees",
    "EU Remote Jobs",
)

_CANONICAL_BY_KEY = {name.lower(): name for name in CANONICAL_SOURCES}


def canonical_source(name) -> str:
    """Return the canonical display name for a board/source label.

    Unknown names pass through with surrounding whitespace stripped — a new
    board must never be silently renamed into an existing one.
    """
    raw = str(name or "").strip()
    if not raw:
        return ""
    key = " ".join(raw.lower().split())
    alias = SOURCE_ALIASES.get(key)
    if alias:
        return alias
    return _CANONICAL_BY_KEY.get(key, raw)


def is_alias(name) -> bool:
    """True when `name` is a non-canonical label that maps onto another."""
    raw = str(name or "").strip()
    if not raw:
        return False
    return canonical_source(raw) != raw
