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

# ── Gazetteer: city -> canonical country ──────────────────────────────────
# Used ONLY for job_country/job_city (where the posting sits), never for
# worker permission. City names are matched with word boundaries.
_CITY_GAZETTEER = {
    # India
    "bangalore": "india", "bengaluru": "india", "mumbai": "india",
    "delhi": "india", "hyderabad": "india", "chennai": "india",
    "pune": "india", "kolkata": "india", "gurgaon": "india",
    "noida": "india", "ahmedabad": "india", "jaipur": "india",
    "srinagar": "india",
    "berlin": "germany", "munich": "germany", "hamburg": "germany",
    "cologne": "germany", "frankfurt": "germany", "stuttgart": "germany",
    "bern": "germany",  # note: Bern is Switzerland; kept here only if text says Germany context
    # Switzerland
    "bern": "switzerland", "zurich": "switzerland", "geneva": "switzerland",
    "basel": "switzerland", "lausanne": "switzerland",
    # UK
    "london": "united_kingdom", "manchester": "united_kingdom",
    "birmingham": "united_kingdom", "edinburgh": "united_kingdom",
    # US
    "new york": "united_states", "nyc": "united_states",
    "san francisco": "united_states", "charlotte": "united_states",
    "chicago": "united_states", "seattle": "united_states",
    "austin": "united_states", "boston": "united_states",
    # etc.
}

# Longest-city-first matching so "San Francisco" wins over "Francisco".
_CITY_PATTERNS = sorted(_CITY_GAZETTEER.keys(), key=len, reverse=True)


def fact(value, match: re.Match | None, field: str = "description") -> dict:
    """Verified fact {value, quote, span, field}; empty dict when no match —
    an absent fact is UNKNOWN, never an inferred pass."""
    if match is None:
        return {}
    start, end = match.span()
    return {"value": value, "quote": match.group(0), "span": [start, end],
            "field": field}


def verify(one_fact: dict, text: str) -> bool:
    """A fact is valid only when its quote occurs verbatim at its span."""
    if not one_fact.get("quote") or one_fact.get("span") is None:
        return False
    start, end = one_fact["span"]
    return (0 <= start <= end <= len(text)
            and text[start:end] == one_fact["quote"])


def drop_unverified(facts: dict, text: str) -> dict:
    """Return facts dict with any entry whose quote doesn't verify against
    text removed. Call this before emitting evidence so unverified facts
    are never shipped."""
    out = {}
    for name, value in facts.items():
        if isinstance(value, dict) and value.get("quote"):
            if verify(value, text):
                out[name] = value
        elif isinstance(value, list):
            kept = []
            for item in value:
                if isinstance(item, dict) and item.get("quote"):
                    if verify(item, text):
                        kept.append(item)
                else:
                    kept.append(item)
            if kept:
                out[name] = kept
        else:
            out[name] = value
    return out


def normalize_text(text: str) -> str:
    """Repair mojibake from UTF-8 bytes that were decoded as cp1252."""
    if not text:
        return ""
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        repaired = _repair_per_pair(text)
    marks = "\u200b\u200c\u200d\ufeff"
    return repaired.translate({ord(c): None for c in marks})


def _repair_per_pair(text: str) -> str:
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


# ── Work mode ─────────────────────────────────────────────────────────────
# "flexible" = "Remote or Hybrid" — the job can be done either way.
def work_mode(text: str) -> tuple[Literal["remote", "onsite", "hybrid", "flexible", "unknown"], dict]:
    """Decisive work mode with quote.

    Returns "flexible" when the posting explicitly offers both remote
    and onsite/hybrid (e.g. "Remote or Hybrid"). A bare standalone
    "remote" never sets the mode.
    """
    # Flexible: explicit "remote or hybrid" / "hybrid or remote"
    flex = re.search(
        r"remote\s*(?:or|/)\s*hybrid|hybrid\s*(?:or|/)\s*remote",
        text, re.I)
    if flex:
        return "flexible", fact("flexible", flex)

    hybrid = re.search(
        r"(?:hybrid\b|Hybrid[- ]Onsite|[23] days onsite)", text, re.I) or re.search(
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
        r"work(?:ing)?\s+remotely|Homeoffice|remotely possible|remote möglich|"
        r"work from anywhere",
        text, re.I)
    if remote:
        return "remote", fact("remote", remote)

    return "unknown", {}


# ── Eligibility phrasing for worker permission ────────────────────────────
# Worker permission ONLY counts when a region appears in an explicit
# eligibility phrase. A bare "United States" or "US timezone" is NOT
# permission — it's a country mention or timezone preference.
_ELIGIBILITY_PHRASES = (
    # Explicit worker-permission phrases with a region group.
    # Region stops at "or"/"and" boundaries so "the EEA or hybrid" matches
    # just "the EEA", not the whole rest of the sentence.
    r"open to candidates? in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"can be based (?:remotely )?in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"must be based in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"right to work in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"candidates? in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"hiring in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"open to (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"(?P<region>[A-Za-z /&]+?) only(?:\s|$|[.,;!])",
    r"based in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    r"located in (?P<region>[A-Za-z /&]+?)(?:\s+or\b|\s+and\b|\s*$|\s*[.,;!])",
    # Worldwide / anywhere — no region group needed
    r"work from anywhere",
    r"anywhere in the world",
    r"open to applying from anywhere",
    r"global applicants?",
    r"\bworldwide\b(?![A-Za-z])",
)

_ELIGIBILITY_RES = [re.compile(p, re.I) for p in _ELIGIBILITY_PHRASES]

# Map region words from eligibility phrases to canonical IDs.
_REGION_ALIASES = {
    "india": "india", "indian": "india",
    "eu": "eu", "european union": "eu", "eea": "eea",
    "european economic area": "eea", "uk": "uk", "united kingdom": "uk",
    "britain": "uk", "us": "us", "usa": "us", "united states": "us",
    "america": "us", "americas": "amer", "amer": "amer",
    "emea": "emea", "eu/eea": "eea", "uk/eea": "eea",
    "latam": "latam", "latin america": "latam",
    "apac": "apac", "asia pacific": "apac",
    "canada": "canada", "australia": "australia",
    "new zealand": "new_zealand",
    "middle east": "middle_east", "africa": "africa",
    "saudi arabia": "saudi_arabia", "uae": "uae",
    "worldwide": "worldwide", "anywhere": "worldwide",
    "anywhere in the world": "worldwide",
    "work from anywhere": "worldwide",
    "all locations": "worldwide", "any location": "worldwide",
}


def _normalize_region(word: str) -> frozenset[str] | None:
    """Map a region word/phrase to canonical ID(s), or None.

    Handles compound regions separated by "/" (e.g. "EEA/UK" -> {eea, uk})
    and strips stop words like "the".
    """
    key = word.strip().lower()
    # Strip leading stop words
    for stop in ("the ", "the\t"):
        if key.startswith(stop):
            key = key[len(stop):]
    # Handle compound regions separated by "/"
    parts = [p.strip() for p in key.split("/")]
    results = set()
    for part in parts:
        canonical = _REGION_ALIASES.get(part)
        if canonical:
            results.add(canonical)
    return frozenset(results) if results else None


def eligibility_phrases(text: str) -> dict:
    """Find explicit worker-permission phrases and map regions to canonical IDs.

    Returns {canonical_id: fact}. Only phrases that explicitly grant or
    restrict worker eligibility count. A bare country mention (HQ, address,
    timezone) does NOT appear here.
    """
    found = {}
    for pattern in _ELIGIBILITY_RES:
        for m in pattern.finditer(text):
            # Patterns with a "region" group extract the region name;
            # patterns without one (worldwide/anywhere) match directly.
            try:
                region_word = m.group("region")
            except IndexError:
                region_word = None
            if region_word:
                canonicals = _normalize_region(region_word)
                if canonicals:
                    for canonical in canonicals:
                        if canonical not in found:
                            found[canonical] = fact(canonical, m, "eligibility_phrase")
            else:
                # Pattern matched directly (e.g. \bworldwide\b)
                matched = m.group(0).lower().strip()
                canonical = _REGION_ALIASES.get(matched)
                if canonical and canonical not in found:
                    found[canonical] = fact(canonical, m, "eligibility_phrase")
    return found


# ── Job country from gazetteer ────────────────────────────────────────────
def job_country_from_text(text: str, url_slug: str = "", tz_field: str = "",
                          location_tags: str = "") -> dict:
    """Extract job_country (where the posting sits) from text, URL slug,
    timezone field, or location_tags using the gazetteer. Never derived
    from worker-permission lists. Returns {canonical_country: fact} or
    empty dict."""
    sources = [
        ("text", text),
        ("url_slug", url_slug),
        ("tz_field", tz_field),
        ("location_tags", location_tags),
    ]
    for source_name, source_text in sources:
        if not source_text:
            continue
        for city in _CITY_PATTERNS:
            pattern = r"\b" + re.escape(city) + r"\b"
            m = re.search(pattern, source_text, re.I)
            if m:
                country = _CITY_GAZETTEER[city]
                return {country: fact(country, m, source_name)}
    return {}
