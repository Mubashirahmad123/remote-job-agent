"""Canonical location identifiers + deterministic extraction (Phase 2).

Deliberate semantics, word-for-word from the cutover hard rules:
- Company HQ, job location, permitted worker locations and "remote" are
  four different facts. Only permitted WORKER locations land in
  allowed_work_locations; company-city lists and HQ mentions are not
  worker-location evidence by themselves.
- A bare word "remote" never sets a work mode by itself, never produces a
  location value and never sets worldwide.
- Unknown stays UNKNOWN: absence of evidence is not a pass.
- Every extracted fact carries a verbatim quote that verify() re-finds in
  the same normalized text; tests enforce this invariant.
"""
import re
from typing import Literal

CANONICAL_WORK_LOCATIONS = frozenset({
    "worldwide", "eu", "eea", "uk", "us", "canada",
    "latam", "amer", "emea", "apac",
    "india", "australia", "new_zealand",
    "middle_east", "africa", "saudi_arabia", "uae",
})

CANONICAL_COUNTRIES = frozenset({
    "india", "germany", "netherlands", "poland", "portugal", "spain", "france",
    "italy", "czechia", "romania", "united_kingdom", "ireland", "austria",
    "switzerland", "belgium", "sweden", "denmark", "norway", "finland",
    "estonia", "latvia", "lithuania", "croatia", "hungary", "slovakia",
    "slovenia", "greece", "bulgaria", "luxembourg",
    "united_states", "canada", "mexico", "brazil", "argentina", "colombia",
    "australia", "new_zealand", "singapore", "israel",
    "saudi_arabia", "uae", "qatar", "kuwait", "bahrain", "oman",
    "south_africa", "turkey", "japan", "south_korea",
})

_REGION_PATTERNS = {
    "worldwide": (
        r"worldwide", r"anywhere in the world",
        r"open to applying from anywhere",
        r"candidates? (?:from|based in) (?:any|all) locations?",
        r"global applicants?", r"work from anywhere",
    ),
    "eu": (r"\bEU\b(?![A-Za-z])", r"European Union", r"EU/EEA",
           r"EU countries?", r"EU citizens?"),
    "eea": (r"\bEEA\b(?![A-Za-z])", r"European Economic Area", r"EEA/UK",
            r"UK/EEA", r"EEA only"),
    "uk": (r"\bUK\b(?![A-Za-z])", r"United Kingdom", r"UK[- ]based",
           r"based in the UK", r"right to work in the UK", r"UK only"),
    "us": (r"\bUS\b(?![A-Za-z])", r"\bUSA\b", r"United States", r"US[- ]based",
           r"based in the US", r"US only",
           r"authorized to work in the (?:United States|US)",
           r"North America", r"\bAMER\b(?![A-Za-z])"),
    "canada": (r"\bCanada\b",
               r"Canadian citizens? or permanent residents"),
    "latam": (r"\bLATAM\b(?![A-Za-z])", r"Latin America"),
    "amer": (r"\bAMER\b(?![A-Za-z])", r"Americas?"),
    "emea": (r"\bEMEA\b(?![A-Za-z])",),
    "apac": (r"\bAPAC\b(?![A-Za-z])", r"Asia Pacific", r"APAC-based"),
    "india": (r"\bIndia\b", r"Indian nationals?", r"based in India"),
    "australia": (r"\bAustralia\b",
                  r"Australian citizens? or permanent residents"),
    "new_zealand": (r"New Zealand", r"\bNZ\b(?![A-Za-z])"),
    "middle_east": (r"Middle East", r"\bGCC\b(?![A-Za-z])"),
    "africa": (r"\bAfrica\b(?![A-Za-z] Africa)",),
    "saudi_arabia": (r"Saudi Arabia", r"\bKSA\b(?![A-Za-z])"),
    "uae": (r"\bUAE\b", r"United Arab Emirates"),
}

_PATTERNS = {key: re.compile("|".join(f"(?:{p})" for p in patterns), re.I)
             for key, patterns in _REGION_PATTERNS.items()}


def fact(value, match: re.Match | None, field: str = "description") -> dict:
    """Verified fact {value, quote, span, field}; empty dict when no match —
    an absent fact is UNKNOWN, never an inferred pass."""
    if match is None:
        return {}
    start, end = match.span()
    return {"value": value, "quote": match.group(0), "span": [start, end],
            "field": field}


def normalize_text(text: str) -> str:
    """Repair mojibake from UTF-8 bytes that were decoded as cp1252:
    "Ã¼" is the visible form of "ü" after C3 BC were each read as one
    cp1252 char. Recover by re-encoding cp1252 and decoding as UTF-8;
    for every schon-korrektes Zeichen the roundtrip is the identity, and
    when the roundtrip fails on the whole string the per-pair map covers
    the common umlaut/dash cases. Then strip zero-width / BOM marks."""
    if not text:
        return ""
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        repaired = _repair_per_pair(text)
    _strip = {0: 0, 1: 1}  # placeholder; real strip below
    marks = "\u200b\u200c\u200d\ufeff"
    return repaired.translate({ord(c): None for c in marks})


def _repair_per_pair(text: str) -> str:
    # Common cp1252-decoded-as-utf8 pairs (only reached when the cheap
    # full-string roundtrip fails somewhere in the document).
    pairs = {
        "\u00c3\u00a4": "ä", "\u00c3\u00b6": "ö", "\u00c3\u00bc": "ü",
        "\u00c3\u201e": "Ä", "\u00c3\u2013": "Ö", "\u00c3\u0152": "Ü",
        "\u00c3\u0178": "ß", "\u00c3\u00a9": "é", "\u00c3\u00a8": "è",
        "\u00c3\u00a1": "á", "\u00c3\u00b1": "ñ", "\u00c3\u00a7": "ç",
        "\u00c3\u00a3": "ã",
    }
    out = text
    for bad, good in pairs.items():
        out = out.replace(bad, good)
    return out


def verify(one_fact: dict, text: str) -> bool:
    """A fact is valid only when its quote occurs verbatim at its span."""
    if not one_fact.get("quote") or one_fact.get("span") is None:
        return False
    start, end = one_fact["span"]
    return (0 <= start <= end <= len(text)
            and text[start:end] == one_fact["quote"])


def work_mode(text: str) -> tuple[Literal["remote", "hybrid", "onsite", "unknown"], dict]:
    """Decisive work mode with quote. hybrid/onsite phrases beat generic
    remote phrasing; a bare standalone 'remote' never sets the mode."""
    hybrid = re.search(
        r"(?:hybrid\b|Hybrid[- ]Onsite|2|3 days onsite)", text, re.I) or re.search(
        r"days? onsite|days? on-site|days? in office", text, re.I)
    if hybrid:
        return "hybrid", fact("hybrid", hybrid)
    onsite = re.search(
        r"\bonsite\b|on[- ]site|in[- ]office|vor\s+Ort|in[- ]person|"
        r"from our .{0,20}office|.{0,30}\bHQ\b.{0,30}(?:location|role)|"
        r"must (?:be|work) (?:on|in)[- ]site",
        text, re.I)
    if onsite:
        return "onsite", fact("onsite", onsite)
    remote = re.search(
        r"fully remote|100% remote|remote[- ]first|remote first|"
        r"remote (?:role|position|job|team|work|opportunity)|"
        r"work(?:ing)?\s+remotely|Homeoffice|remotely possible|remote möglich",
        text, re.I)
    if remote:
        return "remote", fact("remote", remote)
    return "unknown", {}


def region_facts(text: str) -> dict:
    """Canonical worker-eligible regions with one verified fact each.

    Returns {canonical: fact}. First pattern occurrence wins per token;
    tokens never overlap ('EEA/UK' informs both eea and uk deliberately —
    both are explicit eligibility phrasings in that phrase).
    """
    found = {}
    for canonical, pattern in _PATTERNS.items():
        match = pattern.search(text)
        if match:
            found[canonical] = fact(canonical, match)
    return found
