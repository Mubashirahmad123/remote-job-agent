"""Deterministic, quote-verified evidence extractor (Phase 2).

Produces the `matching_evidence` dict consumed by tools/matching_shadow:
gate fields (work_mode, job_country, allowed_work_locations, worldwide,
seniority, role_family, visa_sponsorship), required/preferred requirement
groups, and a provenance "facts" map whose every value has been verified
verbatim. Invariants, each enforced by tests:
1. NO QUOTE, NO FACT: a value is emitted only when its quote occurs
   verbatim in the same normalized source text (verify()).
2. A bare word "remote" never sets a mode, a location, or worldwide.
3. Job text is untrusted DATA: this module never follows instructions
   found in a posting; it only pattern-matches. (No LLM here; the LLM
   proposal path, if ever added, is bound to a JSON schema and re-checked
   by the same quote rule.)
4. Ambiguous skill spellings never produce requirements: bare "express"
   and bare "node" are intentionally ABSENT from the token table.
5. Worker permission ONLY from explicit eligibility phrasing ("open to",
   "can be based in", "must be based in", "right to work in", "candidates
   in", "hiring in"). A bare address/HQ/country mention is NOT permission.
6. Unverified facts are DROPPED, not reported.
"""
import re

from tools.matching_locations import (
    CANONICAL_COUNTRIES,
    _normalize_region,
    drop_unverified,
    eligibility_phrases,
    fact,
    job_country_from_text,
    normalize_text,
    verify as _verify,
    with_provenance,
    work_mode as _work_mode,
)

EXTRACTOR_VERSION = "extract-v3"

# ── Seniority ───────────────────────────────────────────────────────────────
SENIORITY_LABELS = (
    ("intern", "intern"),
    ("junior", "junior"),
    ("entry[- ]level", "junior"),
    ("graduate", "junior"),
    ("medior", "mid"),
    ("mid[- ]level", "mid"),
    ("senior", "senior"),
    ("lead", "lead"),
    ("principal", "principal"),
    ("staff", "staff"),
    ("head of", "lead"),
    ("teamleiter|(?<!software)leiter(?:in)?", "lead"),
    # German compounds are ONE word ("Softwarearchitekt"), so the word
    # boundary must not sit in front of "architekt".
    ("softwarearchitekt(?:in)?|\\barchitekt(?:in)?\\b", "senior"),
)
# Trailing boundary is load-bearing (D8): without it "internal" matches
# "intern" and "leading"/"leadership" match "lead". The 2026-11 live run
# labelled 89/312 jobs "intern" from the word "internal" alone.
_SENIORITY_RES = [(label, re.compile(rf"\b(?:{pattern})\b", re.I))
                  for pattern, label in SENIORITY_LABELS]

# Level words that may appear in an explicit level statement. Prose verbs are
# deliberately absent: "you will lead code reviews" is not a level.
_LEVEL_WORD_LABELS = {
    "intern": "intern", "junior": "junior", "entry level": "junior",
    "graduate": "junior", "medior": "mid",
    "mid level": "mid", "senior": "senior", "lead": "lead",
    "principal": "principal", "staff": "staff", "head of": "lead",
}
_LEVEL_WORD_RE = "|".join(re.escape(word) for word in
                          sorted(_LEVEL_WORD_LABELS, key=len, reverse=True))

# A level word in description PROSE is not evidence unless the sentence
# states the level: "we are looking for a Senior Backend Engineer",
# "Seniority: senior", "this is a lead role". Anything else stays not_stated.
_EXPLICIT_LEVEL_RE = re.compile(
    r"(?:this is|this role is|the role is|the position is|"
    r"we are hiring(?: for)?|we're hiring(?: for)?|"
    r"we are looking for|we're looking for|looking for)\s+"
    r"(?:a|an)?\s*(?P<prefix>" + _LEVEL_WORD_RE + r")\b"
    r"|(?:seniority|level)\s*[:\-]\s*(?P<labelled>" + _LEVEL_WORD_RE + r")\b"
    r"|(?P<suffix>" + _LEVEL_WORD_RE + r")\s+(?:level|role|position)\b",
    re.I)


# Explicitly stated OVERALL experience ranges only: "5+ years of experience",
# "5 years in software development", "0 to 4 yrs". Per-skill years like
# "5+ years of React" are requirement context, not seniority.
_YEARS_RE = re.compile(
    r"(?P<lo>\d)\s*(?:to|-)\s*(?P<hi>\d)\s*(?:\+)?\s*(?:years|yrs|jahre)"
    r"|(?P<lo2>\d)\s*\+\s*(?:years|yrs)\s+(?:of\s+)?(?:experience|software development|in software)"
    r"|mindestens\s*(?P<lo3>\d)\s*(?:Jahre)"
    r"|at least\s*(?P<lo4>\d)\s*(?:years|yrs)"
    r"|(?P<lo5>\d)\s*(?:years|yrs)\s+(?:of\s+)?(?:experience|software development)",
    re.I)


def _locate_fact(value, needle: str, haystack: str, field: str) -> dict:
    """Fact whose span is relative to ``haystack`` (always the combined text).

    The module verifies every fact against the combined source text, so a fact
    found in the description must be re-located there instead of keeping a
    description-relative span (which would never verify). Returns {} rather
    than an unverifiable fact.
    """
    if not needle:
        return {}
    hit = re.search(re.escape(needle), haystack, re.I)
    return fact(value, hit, field) if hit else {}


def _seniority_label_from_title(title: str):
    for label_value, pattern in _SENIORITY_RES:
        hit = pattern.search(title or "")
        if hit:
            return label_value, hit
    return None, None


def _seniority_label_from_explicit_statement(text: str):
    if not text:
        return None, None
    match = _EXPLICIT_LEVEL_RE.search(text)
    if not match:
        return None, None
    word = next((group for group in (match.group("prefix"),
                                     match.group("labelled"),
                                     match.group("suffix")) if group), None)
    if not word:
        return None, None
    return _LEVEL_WORD_LABELS.get(" ".join(word.lower().split())), match


def seniority_evidence(title: str, text: str, combined: str | None = None):
    """(label|None, years_lo|None, years_hi|None, facts, not_stated|False).

    Evidence sources, in order:
    1. a seniority label in the TITLE (the only place a level is a fact about
       the role rather than a word in a sentence),
    2. an explicit level statement in the description ("we are looking for a
       Senior Backend Engineer", "Seniority: lead", "this is a lead role"),
    3. an explicit overall-experience range ("5+ years of experience").

    Ordinary prose never produces a label (D8): "you will lead code reviews"
    and "our internal platform" are not seniority evidence.

    not_stated is True when NO seniority evidence exists at all — distinct
    from "unknown", which means evidence exists but is unverifiable.
    """
    title = title or ""
    text = text or ""
    haystack = combined if combined is not None else f"{title}\n{text}"
    facts: dict = {}
    lo = hi = None

    range_m = _YEARS_RE.search(text) or _YEARS_RE.search(title)
    if range_m:
        if range_m.group("lo") and range_m.group("hi"):
            lo, hi = int(range_m.group("lo")), int(range_m.group("hi"))
        elif range_m.group("lo2"):
            lo, hi = int(range_m.group("lo2")), None
        elif range_m.group("lo3") or range_m.group("lo4"):
            lo, hi = int(range_m.group("lo3") or range_m.group("lo4")), None
        elif range_m.group("lo5"):
            lo, hi = int(range_m.group("lo5")), None
        years_fact = _locate_fact({"lo": lo, "hi": hi}, range_m.group(0),
                                  haystack, "description")
        if years_fact:
            facts["years"] = years_fact

    label = None
    hit = None
    field = "title"
    title_label, title_hit = _seniority_label_from_title(title)
    if title_label:
        label, hit = title_label, title_hit
    else:
        desc_label, desc_hit = _seniority_label_from_explicit_statement(text)
        if desc_label:
            label, hit, field = desc_label, desc_hit, "explicit_level_statement"

    if label and hit is not None:
        located = _locate_fact(label, hit.group(0), haystack, field)
        if located:
            facts["seniority"] = located
        else:
            # Label decided the gate but cannot be quoted verbatim: do not
            # ship a decision that claims evidence it cannot show.
            label = None

    not_stated = (label is None and lo is None)
    return label, lo, hi, facts, not_stated


# ── Role family + responsibility hints ─────────────────────────────────────
# Single source of truth for title -> family mapping. Used by both the
# extractor (role_family_evidence) and the policy gate (infer_title_family).
# Order matters: first match wins. Specific role types before generic "software".
FAMILY_PATTERNS = {
    "fullstack": r"full[ -]?stack|fullstack",
    "backend": r"back[ -]?end|backend|node(?:\.js|js)?|\bpython\b",
    "frontend": r"front[ -]?end|frontend|react(?:\.js|js)?|next(?:\.js|js)?",
    "software": r"software developer|programmer|web developer|golang|\bgo (?:developer|lang)|devops?|devops engineer",
}
RESPONSIBILITY_PATTERNS = {
    "architect": r"architect(?:ure)? (?:own(?:s|ing)|role)|overall architecture|"
                 r"softwarearchitekt(?:in)?|system(?:s)? architect",
    "forward_deployed": r"forward deployed|forwarddeployed",
    "devrel": r"developer relations|developer advocate|devrel",
    "support": r"(?:technical )?support engineer",
    "research": r"research engineer|research scientist|applied scientist",
    "data_infra": r"infrastructure engineer|data iron|data (?:engineer|platform)|"
                  r"site reliability|platform engineer",
    "hardware_eda": r"\bEDA\b|hardware engineer|semiconductor",
    "security": r"security engineer|application security|appsec",
    "ml": r"machine learning engineer|ml engineer",
}
FAMILY_RES = [(name, re.compile(rf"\b(?:{pattern})", re.I))
              for name, pattern in FAMILY_PATTERNS.items()]
RESP_RES = [(name, re.compile(rf"(?:{pattern})", re.I))
            for name, pattern in RESPONSIBILITY_PATTERNS.items()]


def role_family_evidence(title: str, description_used: str | None):
    """(family|None, facts list).

    Explicit responsibility hints (architect, forward-deployed, devrel,
    support, research, data/infra, hardware/EDA, security, ml) are facts
    even when a family name also matches: an "architect" title that says
    Fullstack stays family=fullstack but carries the architect hint, and
    the Phase 4 gate treats architect-family jobs as REVIEW, not pass.
    Family=None stays unresolved (UNKNOWN) — never guessed.
    """
    hay = f"{title or ''}\n{description_used or ''}".strip()
    facts = []
    for name, pattern in RESP_RES:
        hit = pattern.search(hay)
        if hit:
            facts.append(fact(name, hit, "hint"))
    family_hit = None
    if title:
        for name, pattern in FAMILY_RES:
            hit = pattern.search(title)
            if hit:
                family_hit = fact(name, hit, "title")
                break
    return family_hit["value"] if family_hit else None, facts


# ── Visa sponsorship / work authorization (explicit only) ───────────────────
_SPONSOR_NEG = re.compile(
    r"no (?:visa )?sponsorship|without (?:visa )?sponsorship|"
    r"unable to (?:provide|offer) sponsorship|"
    r"do(?:es)? not (?:currently )?(?:provide|offer|support) (?:visa )?sponsorship",
    re.I)
_SPONSOR_POS = re.compile(
    r"(?:visa )?sponsorship (?:is |will be )?(?:available|provided|offered)|"
    r"we (?:provide|offer|do )?(?:support )?(?:visa )?sponsorship|"
    r"sponsoring visas?", re.I)
_MUST_ALREADY = re.compile(
    r"must (?:already |currently )?(?:be|have) (?:legally )?(?:authorized|eligible) to work|"
    r"authorized to work in|right to work in|work permit|"
    r"must be based in|must (?:reside|live) in", re.I)


def sponsorship_evidence(text: str):
    """(visa_sponsorship or None, facts). Negation beats positive; the
    absence of either stays None = unknown, never a silent pass."""
    neg = _SPONSOR_NEG.search(text)
    if neg:
        return False, {"visa_sponsorship": fact(False, neg)}
    pos = _SPONSOR_POS.search(text)
    if pos:
        return True, {"visa_sponsorship": fact(True, pos)}
    must = _MUST_ALREADY.search(text)
    if must:
        return None, {"must_already_be_authorized": fact(True, must)}
    return None, {}


# ── Requirements (technology tokens, OR groups, negations) ──────────────────
# Context rules from the 30-Oct evidence, applied at token level:
# - bare "express" and bare "node" are NOT here, by design
# - "js", "ts" single letters require surrounding context — skipped entirely.
TECH_TOKENS = {
    "javascript": r"javascript|(?<=java)\bscript\b",
    "typescript": r"typescript",
    "python": r"\bpython\b",
    "react": r"\breact\b(?! native)",
    "vue": r"\bvue\b",
    "svelte": r"\bsvelte\b",
    "angular": r"\bangular(?:js)?\b",
    "next": r"next\.js|\bnextjs\b",
    "nuxt": r"nuxt\.js|\bnuxtjs\b",
    "express": r"express\.js|expressjs|(?:\bexpress\b.{0,15}(?:framework|server))",
    "node": r"node\.js|nodejs",
    "django": r"\bdjango\b",
    "flask": r"\bflask\b",
    "fastapi": r"fastapi",
    "postgresql": r"postgres(?:ql)?",
    "mysql": r"\bmysql\b",
    "mongodb": r"mongo(?:db)?",
    "redis": r"\bredis\b",
    "sql": r"\bsql\b(?!(ite|server))",
    "graphql": r"\bgraphql\b",
    "rest": r"rest(?:ful)? ?api|restful",
    "golang": r"\bgolang\b|\bgo (?:developer|lang|runtime|scheduler)\b",
    "java": r"\bjava\b(?!\s*script)",
    "dotnet": r"\.net\b|dotnet|c#",
    "php": r"\bphp\b",
    "ruby": r"\bruby\b|\brails\b",
    "kotlin": r"\bkotlin\b",
    "swift": r"\bswift\b",
    "rust": r"\brust\b",
    "go": r"\bgolang\b",
    "aws": r"\baws\b|amazon web services",
    "gcp": r"\bgcp\b|google cloud",
    "azure": r"\bazure\b",
    "docker": r"\bdocker\b",
    "kubernetes": r"kubernetes|\bk8s\b",
    "terraform": r"\bterraform\b",
    "tailwind": r"tailwind",
    "redux": r"\bredux\b|rtk query",
    "zod": r"\bzod\b",
    "vite": r"\bvite\b",
    "vitest": r"\bvitest\b",
    "jest": r"\bjest\b",
    "cypress": r"\bcypress\b",
    "playwright": r"\bplaywright\b",
    "rabbitmq": r"rabbitmq",
    "kafka": r"kafka",
    "celery": r"\bcelery\b",
    "prisma": r"\bprisma\b",
    "sequelize": r"sequelize",
    "typeorm": r"typeorm",
    "spring": r"\bspring\b",
    "laravel": r"laravel",
    "websocket": r"websockets?",
    "css": r"\bcss\b",
    "html": r"\bhtml\b",
    # practices/soft are recorded with type so coverage skips them
    "agile": r"\bagile\b", "scrum": r"\bscrum\b", "git": r"\bgit\b",
}
_TECH_RES = {token: re.compile(pattern, re.I)
             for token, pattern in TECH_TOKENS.items()}
_PRACTICE_TOKENS = frozenset({"agile", "scrum", "git"})


def _token_spans(line: str) -> dict:
    """Token -> list of (start, end) spans in this line."""
    spans = {}
    for token, pattern in _TECH_RES.items():
        hits = [m.span() for m in pattern.finditer(line)]
        if hits:
            spans.setdefault(token, []).extend(hits)
    return spans


def _is_negated(line: str, start: int) -> bool:
    """Critical hard rule: 'no PHP' must never become a PHP gap. A token
    is negated when no/not/none/without/lacking occurs in the 40 chars
    before its span."""
    prefix = line[max(0, start - 40):start].lower()
    return bool(re.search(r"\b(?:no|not|none|without|lacking|no longer)\b", prefix))


_OR_CONNECTOR_ONLY = re.compile(r"^(?:/|\bor\b|\bund\b|\|)$", re.I)


def _or_groups(spans: dict, line: str) -> list[list[str]]:
    """Alternatives with ONLY an OR connector between adjacent token spans
    ('React or Vue', 'Kafka/RabbitMQ') merge into one group; prose between
    distinct asks ('React or Vue experience with Node') does not. No fuzzy
    matching — spans and connectors decide."""
    ordered = sorted(((token, start, end) for token, hit_list in spans.items()
                      for (start, end) in hit_list), key=lambda x: x[1])
    if not ordered:
        return []
    groups = []
    current = [ordered[0]]
    for prev, this in zip(ordered, ordered[1:]):
        if this[0] == prev[0]:
            continue
        connector = line[prev[2]:this[1]].strip()
        if _OR_CONNECTOR_ONLY.fullmatch(connector):
            current.append(this)
        else:
            groups.append(current)
            current = [this]
    groups.append(current)
    return [sorted({token for token, _s, _e in group}) for group in groups]


# ── Requirement sections and modality (D1) ─────────────────────────────────
# What a mention means depends on the block it sits in. The previous code had
# ONE mutable `section` that started at "required" and persisted forever, so
# "Responsibilities: maintain JavaScript services" and "Our tech stack: ..."
# both became required technologies, and one "Nice to have:" sentence turned
# every later paragraph into a preference.
#
# Rules here:
# - a HEADING is a segment that is only the marker ("Requirements:", "Nice to
#   have:") and it changes the section for the segments that follow;
# - an INLINE marker ("Nice to have: Docker") applies to that segment only;
# - a new heading replaces the old one, so a section never leaks past it;
# - with no section at all, text is a `mention` unless it carries requirement
#   modality ("must", "proficiency in", "experience with"), because a bare
#   technology name is not an ask.
REQUIREMENT_CLASSES = ("required", "preferred", "optional", "mention",
                       "responsibility")

_SECTION_PATTERNS = (
    ("preferred", re.compile(
        r"^(?:nice[- ]to[- ]have|preferred(?: qualifications| skills)?|"
        r"bonus(?: points)?|good to have|desirable|pluses?)\b\s*[:\-–]?\s*", re.I)),
    ("responsibility", re.compile(
        r"^(?:responsibilities|what you(?:'|’)ll do|what you will do|"
        r"the role|about the role|day[- ]to[- ]day|your (?:tasks|"
        r"responsibilities)|tasks|aufgaben|deine aufgaben)\b\s*[:\-–]?\s*", re.I)),
    ("mention", re.compile(
        r"^(?:(?:our|the|your)\s+)?(?:tech(?:nology)? stack|stack|"
        r"technologies(?: we use)?|tools we use|technologien|"
        r"about (?:us|the company|the team)|benefits|perks|we offer|"
        r"why join(?: us)?)\b\s*[:\-–]?\s*", re.I)),
    ("optional", re.compile(
        r"^(?:optional|not required|nicht erforderlich)\b\s*[:\-–]?\s*", re.I)),
    ("required", re.compile(
        r"^(?:requirements?|required|must[- ]haves?|qualifications|"
        r"what you(?:'|’)ll need|what we(?:'|’)re looking for|"
        r"you(?:'|’)ll have|you have|your profile|dein profil|"
        r"skills|anforderungen|voraussetzungen)\b\s*[:\-–]?\s*", re.I)),
)
_MODALITY_REQUIRED = re.compile(
    r"\b(?:must|required|requirement|essential|mandatory|"
    r"proficien(?:t|cy) (?:in|with)|experience (?:in|with)|"
    r"strong (?:knowledge|experience|understanding)|"
    r"solid (?:knowledge|experience|understanding)|"
    r"expertise (?:in|with)|knowledge of|familiarity with|"
    r"hands[- ]on experience)\b", re.I)
_MODALITY_OPTIONAL = re.compile(
    r"\b(?:optional|not required|nice to have but|wünschenswert)\b", re.I)
_BULLET = re.compile(r"^[\s>\-*•·‣–]*([0-9]+[.)]\s*)?", re.I)


def _match_section(segment: str):
    """(section, remainder, is_heading) for a segment starting with a marker."""
    for name, pattern in _SECTION_PATTERNS:
        hit = pattern.match(segment)
        if hit:
            remainder = segment[hit.end():].lstrip(" :;-–—•*").strip()
            return name, remainder, not remainder
    return None, segment, False


def requirement_items(text: str) -> list[str]:
    """Requirement-bearing segments: bullets, numbered items and sentences.

    Splitting happens per LINE and per SENTENCE, because postings mix
    'Requirements:' headers and 'Nice to have: Docker' markers inside a
    single paragraph; a comma-separated list ('Python, Django,
    PostgreSQL') is AND, not OR, so commas never form alternatives.
    """
    items = []
    for line in text.splitlines():
        core = _BULLET.sub("", line.strip())
        if not core:
            continue
        for segment in re.split(r"(?<=[.;!?])\s+", core):
            segment = segment.strip()
            if len(segment) < 3:
                continue
            items.append(segment)
    return items


def requirements_evidence(text: str):
    """(required, preferred, facts dict), each requirement
    {alternatives, evidence, type, class, essential}.

    `required` is the only bucket that can create a coverage gap. `preferred`
    and `optional` mentions are recorded for the reviewer but never gate.
    `mention` and `responsibility` are recorded as evidence only: a technology
    named in "Our stack:" or "Responsibilities:" is not an ask.

    `facts["requirements"]` carries the completeness tuple needed to tell "this
    posting has no requirements section" from "we extracted nothing", which is
    the difference between an honest REVIEW and a false rejection (D2).
    """
    buckets = {name: [] for name in REQUIREMENT_CLASSES}
    facts: dict = {}
    section = None
    sections_seen: set[str] = set()

    for segment in requirement_items(text):
        section_name, remainder, is_heading = _match_section(segment)
        if section_name:
            sections_seen.add(section_name)
            # Demoting sections ("Responsibilities:", "Our stack:") apply at
            # once, even with content on the same line: the safe direction is
            # fewer false requirements. Promoting sections only persist as a
            # bare heading, so one "Nice to have: Docker" sentence cannot
            # reclassify the rest of the paragraph.
            if section_name in {"mention", "responsibility"} or is_heading:
                section = section_name
            if is_heading:
                continue
            removed = segment[:len(segment) - len(remainder)]
            segment = remainder
            if not segment:
                continue
            requirement_class = section_name
            negation_scope = removed
        else:
            requirement_class = section
            if requirement_class is None:
                requirement_class = ("required" if _MODALITY_REQUIRED.search(segment)
                                     else "mention")
            elif (requirement_class in {"mention", "responsibility"}
                  and _MODALITY_REQUIRED.search(segment)):
                # "Our stack: Python" is a mention; "You must know Python" is not.
                requirement_class = "required"
            negation_scope = ""

        if _MODALITY_OPTIONAL.search(segment) or requirement_class == "optional":
            requirement_class = "optional"

        spans = _token_spans(segment)
        if not spans:
            continue
        if re.search(r"\b(?:no|not|without)\b", negation_scope, re.I):
            facts.setdefault("negations", []).append({"quote": segment[:160]})
            continue
        verified_spans = {t: [(s, e) for (s, e) in hit_list
                              if not _is_negated(segment, s)]
                          for t, hit_list in spans.items()}
        verified_spans = {t: h for t, h in verified_spans.items() if h}
        if not verified_spans:
            facts.setdefault("negations", []).append({"quote": segment[:160]})
            continue
        essential = bool(re.search(r"\b(?:must|required|essential|mandatory)\b",
                                   segment, re.I))
        bucket = "required" if requirement_class == "required" else "preferred"
        for group in _or_groups(verified_spans, segment):
            item = {
                "alternatives": sorted(set(group)),
                "evidence": segment[:160],
                "essential": essential,
                "class": requirement_class,
            }
            item["type"] = "practice" if all(
                t in _PRACTICE_TOKENS for t in item["alternatives"]) else "technology"
            buckets[bucket].append(item)

    required, preferred = buckets["required"], buckets["preferred"]
    # Non-gating mentions share the `preferred` bucket (they are recorded, not
    # asked for), so they must be counted by class — reading buckets["mention"]
    # reported zero forever.
    mention_items = [i for i in preferred if i["class"] == "mention"]
    responsibility_items = [i for i in preferred
                            if i["class"] == "responsibility"]
    # Only a genuine requirements/qualifications heading counts. A page that
    # only ever says "Nice to have:" has told us what is *not* mandatory, which
    # is not the same as telling us what is.
    required_section_found = "required" in sections_seen
    count = {
        "required": len(required),
        "preferred": len([i for i in preferred if i["class"] == "preferred"]),
        "optional": len([i for i in preferred if i["class"] == "optional"]),
        "mention": len(mention_items),
        "responsibility": len(responsibility_items),
    }
    facts["requirements"] = {
        # D2: complete means "a requirements/qualifications section was located
        # AND produced at least one required technology". Before this, complete
        # was bool(required), so a bare tech-stack paragraph unlocked the
        # essential-gap auto-rejection on the weakest possible evidence.
        "complete": bool(required) and required_section_found,
        "section_found": required_section_found,
        "count": count,
        "mention": mention_items,
        "responsibility": responsibility_items,
    }
    return required, preferred, facts



def extract_matching_evidence(job: dict) -> dict:
    """Full evidence bundle for one job; every field is UNKNOWN unless a
    verbatim quote verified it. Unverified facts are DROPPED, not reported.
    """
    title = normalize_text(job.get("job_title") or "")
    description = normalize_text(
        job.get("description") or job.get("summary") or "")
    location_field = normalize_text(str(job.get("timezone") or ""))
    apply_url = str(job.get("apply_url") or "")
    combined = f"{title}\n{location_field}\n{description}"
    gate_text_for_sources = {
        "title": title, "description": description, "location_field": location_field}

    evidence: dict = {"extractor_version": EXTRACTOR_VERSION}
    facts: dict = {"sources": {"title_len": len(title),
                               "description_len": len(description)}}

    # ── work mode ──────────────────────────────────────────────────
    mode, mode_fact = _work_mode(combined)
    if mode_fact:
        facts["work_mode"] = mode_fact
        evidence["work_mode"] = mode

    # ── worker permission ONLY from eligibility phrasing ───────────
    # region_facts is NOT used for allowed_work_locations — it matches
    # bare country mentions (HQ, timezone, address) which are NOT permission.
    perm_regions = eligibility_phrases(combined)
    verified_perms = {}
    for canonical, one_fact in perm_regions.items():
        if _verify(one_fact, combined):
            verified_perms[canonical] = one_fact

    if verified_perms:
        facts["worker_permission"] = verified_perms
        non_worldwide = {k for k in verified_perms if k != "worldwide"}
        if "worldwide" in verified_perms and not non_worldwide:
            evidence["worldwide"] = True
            evidence["allowed_work_locations"] = []
        else:
            evidence["worldwide"] = False
            evidence["allowed_work_locations"] = sorted(verified_perms)

    # ── job country from gazetteer (never from worker-permission list) ─
    location_tags_text = " ".join(job.get("location_tags") or [])
    country_fact = job_country_from_text(combined, apply_url, location_field,
                                         location_tags_text, title)
    # D5: each fact's span is relative to the string it was extracted from, so
    # verify against THAT string. Verifying everything against `combined` used
    # to silently drop every location_tags and URL-slug country — the very
    # evidence the scraper does populate.
    country_sources = {
        "location_tags": location_tags_text,
        "title": title,
        "tz_field": location_field,
        "url_slug": apply_url,
        "text": combined,
    }
    verified_country = {}
    for canonical, one_fact in country_fact.items():
        source_text = country_sources.get(one_fact.get("field"), combined)
        if _verify(one_fact, source_text):
            verified_country[canonical] = with_provenance(one_fact, "gazetteer")
    if verified_country:
        facts["job_country"] = verified_country
        first_country, first_fact = next(iter(verified_country.items()))
        evidence["job_country"] = first_country
        evidence["job_city"] = first_fact.get("city")

    # ── sponsorship ────────────────────────────────────────────────
    sponsor, sponsor_facts = sponsorship_evidence(combined)
    if sponsor_facts:
        facts.update(sponsor_facts)
        if sponsor is not None:
            evidence["visa_sponsorship"] = sponsor

    # ── seniority ─────────────────────────────────────────────────
    label, lo, hi, s_facts, not_stated = seniority_evidence(
        title, description, combined)
    if s_facts:
        facts.update(s_facts)
    if label:
        evidence["seniority"] = label
        # Carry the quote and span at the top level so they flow into JobEvidence
        s_fact = s_facts.get("seniority")
        if s_fact:
            evidence["seniority_quote"] = s_fact.get("quote", "")
            evidence["seniority_span"] = s_fact.get("span", [])
    if lo is not None:
        evidence["years_min"] = lo
    if hi is not None:
        evidence["years_max"] = hi
    evidence["seniority_not_stated"] = not_stated

    # ── role family + responsibility hints ─────────────────────────
    family, family_facts = role_family_evidence(title, description)
    if family:
        evidence["role_family"] = family
    if family_facts:
        facts["hints"] = family_facts

    # ── requirements ──────────────────────────────────────────────
    required, preferred, req_facts = requirements_evidence(description)
    if req_facts:
        facts.update(req_facts)
    req_meta = req_facts.get("requirements", {})
    evidence["requirements"] = {
        "required": required,
        "preferred": preferred,
        "complete": bool(req_meta.get("complete")),
        "extractor_version": EXTRACTOR_VERSION,
    }
    # D2: completeness is a fact about the SOURCE, not about extraction luck.
    evidence["description_completeness"] = {
        "description_present": bool(description.strip()),
        "description_length": len(description),
        "requirements_section_found": bool(req_meta.get("section_found")),
        "requirements_count": req_meta.get("count", {}),
        "extraction_confidence": _extraction_confidence(
            bool(req_meta.get("section_found")),
            int(req_meta.get("count", {}).get("required", 0) or 0)),
    }

    # ── DROP unverified facts ─────────────────────────────────────
    facts = drop_unverified(facts, combined)
    facts["verify"] = {"all_verified": True, "rejected": [], "dropped": []}
    evidence["facts"] = facts
    return evidence


def _extraction_confidence(section_found: bool, required_count: int) -> str:
    """Categorical, not a fake probability.

    - requirements_section: a requirements/qualifications heading was located
      and produced at least one required technology;
    - modality_only: technologies were found only through requirement wording,
      with no section heading;
    - none: no required technology was extracted at all.
    """
    if section_found and required_count:
        return "requirements_section"
    if required_count:
        return "modality_only"
    return "none"

