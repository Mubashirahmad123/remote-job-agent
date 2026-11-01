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
"""
import re

from tools.matching_locations import (
    fact,
    normalize_text,
    region_facts,
    work_mode as _work_mode,
    verify as _verify,
)

EXTRACTOR_VERSION = "extract-v1"

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
_SENIORITY_RES = [(label, re.compile(rf"\b(?:{pattern})", re.I))
                  for pattern, label in SENIORITY_LABELS]

# Explicitly stated year ranges: "0 to 4 yrs", "2-4 years", "5+ years",
# "mindestens 3 jahre". Range wins over label words; label words alone do
# not create a numeric claim.
_YEARS_RE = re.compile(
    r"(?P<lo>\d)\s*(?:to|-|â€“)\s*(?P<hi>\d)\s*(?:\+)?\s*(?:years|yrs|jahre)"
    r"|(?P<lo2>\d)\s*\+\s*(?:years|yrs|jahre)"
    r"|mindestens\s*(?P<lo3>\d)\s*(?:Jahre)"
    r"|at least\s*(?P<lo4>\d)\s*(?:years|yrs)", re.I)


def seniority_evidence(title: str, text: str):
    """(label|None, years_lo|None, years_hi|None, facts).

    A derived label from a year range is recorded on the range quote; an
    explicit label word wins and carries its own quote. Neither present
    → (None, None, None, {}) — UNKNOWN, never a pass.
    """
    facts: dict = {}
    lo = hi = None
    range_m = _YEARS_RE.search(text) or _YEARS_RE.search(title or "")
    if range_m:
        if range_m.group("lo") and range_m.group("hi"):
            lo, hi = int(range_m.group("lo")), int(range_m.group("hi"))
        elif range_m.group("lo2"):
            lo, hi = int(range_m.group("lo2")), None
        elif range_m.group("lo3") or range_m.group("lo4"):
            lo, hi = int(range_m.group("lo3") or range_m.group("lo4")), None
        facts["years"] = fact({"lo": lo, "hi": hi}, range_m)
    label = None
    search_text = f"{title}\n{text}".strip() if title and text else (title or text)
    for label_value, pattern in _SENIORITY_RES:
        hit_title = pattern.search(title or "")
        hit = hit_title or pattern.search(text)
        if hit:
            label = label_value
            facts["seniority"] = fact(label_value, hit,
                                      "title" if hit_title else "description")
            break
    return label, lo, hi, facts


# ── Role family + responsibility hints ─────────────────────────────────────
FAMILY_PATTERNS = {
    "fullstack": r"full[ -]?stack|fullstack",
    "backend": r"back[ -]?end|backend",
    "frontend": r"front[ -]?end|frontend",
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
    the Phase 3 gate treats architect-family jobs as REVIEW, not pass.
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
# - "js", "ts" single letters require surrounding context (JS/TS acronyms
#   trailing a product name) — skipped entirely to stay deterministic.
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
_SECTION_PREFERRED = re.compile(
    r"nice[- ]to[- ]have|preferred|desirable|bonus (?:points|skills)?|"
    r"good to have|plus(?:es)?\b", re.I)
_SECTION_REQUIRED = re.compile(
    r"required|must[- ]have|requirements|we (?:expect|need)|"
    r"you(?:')?(?:ll| will)? (?:have|need|bring)|qualifications", re.I)
_BULLET = re.compile(r"^[\s>\-*•·‣–]*([0-9]+[.)]\s*)?", re.I)


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


def _token_spans(line: str) -> dict:
    """Token -> list of (start, end) spans in this line."""
    spans = {}
    for token, pattern in _TECH_RES.items():
        hits = [m.span() for m in pattern.finditer(line)]
        if hits:
            spans.setdefault(token, []).extend(hits)
    return spans


def requirements_evidence(text: str):
    """(required, preferred, facts dict):
    each requirement {alternatives, evidence, type, essential}.
    Negations are dropped with a recorded quote; practices/soft skills
    carry type practice/soft and never enter coverage."""
    required, preferred, facts = [], [], {}
    section = "required"
    for segment in requirement_items(text):
        # Inline section markers switch the section for the REST of the
        # segment: 'Nice to have: Docker' is PREFERRED Docker, not required.
        marker = None
        for pattern, name in ((_SECTION_PREFERRED, "preferred"),
                              (_SECTION_REQUIRED, "required")):
            hit = pattern.search(segment)
            if hit:
                marker = (hit, name)
                break
        if marker:
            hit, name = marker
            remainder = segment[hit.end():].lstrip(" :;-•*").strip()
            if not remainder:
                section = name
                continue
            # A NEGATED marker ("Not required: Ruby on Rails", "No
            # experience with PHP") states the item is NOT wanted — the
            # tokens must be dropped, not re-labelled as requirements.
            # The negation can sit before the marker ("Not required:") or
            # inside it, so both are checked.
            negation_scope = f"{segment[:hit.start()]} {hit.group(0)}"
            if re.search(r"\b(?:no|not|without)\b", negation_scope, re.I):
                facts.setdefault("negations", []).append({"quote": segment[:160]})
                continue
            section = name
            segment = remainder
        spans = _token_spans(segment)
        if not spans:
            continue
        verified_spans = {t: [(s, e) for (s, e) in hit_list
                              if not _is_negated(segment, s)]
                          for t, hit_list in spans.items()}
        verified_spans = {t: h for t, h in verified_spans.items() if h}
        if not verified_spans:
            facts.setdefault("negations", []).append({"quote": segment[:160]})
            continue
        out_list = required if section == "required" else preferred
        # `essential` means EXPLICITLY required ("must", "required",
        # "essential", "mandatory"). A plain requirement section is NOT
        # enough: an essential gap triggers a hard REJECT in the scorer,
        # and a false rejection of a suitable job is the worst outcome.
        essential = bool(re.search(r"\b(?:must|required|essential|mandatory)\b",
                                   segment, re.I))
        for group in _or_groups(verified_spans, segment):
            out_list.append({
                "alternatives": sorted(set(group)),
                "evidence": segment[:160],
                "essential": essential,
            })
    # Practice/soft typing (Phase 3 gate needs the split; coverage only
    # counts technology).
    for bucket in (required, preferred):
        for requirement in bucket:
            requirement["type"] = "practice" if all(
                t in _PRACTICE_TOKENS for t in requirement["alternatives"]) else "technology"
    facts["requirements"] = {
        "complete": bool(required),
        "count": {"required": len(required), "preferred": len(preferred)},
    }
    return required, preferred, facts


def extract_matching_evidence(job: dict) -> dict:
    """Full evidence bundle for one job; every field is UNKNOWN unless a
    verbatim quote verified it. The shadow hook reads the flat gate keys;
    the maintainable truth lives in "facts"."""
    title = normalize_text(job.get("job_title") or "")
    description = normalize_text(
        job.get("description") or job.get("summary") or "")
    location_field = normalize_text(str(job.get("timezone") or ""))
    combined = f"{title}\n{location_field}\n{description}"
    gate_text_for_sources = {
        "title": title, "description": description, "location_field": location_field}

    evidence: dict = {"extractor_version": EXTRACTOR_VERSION}
    facts: dict = {"sources": {"title_len": len(title),
                               "description_len": len(description)}}

    # work mode: decisive quote required; bare remote never suffices
    mode, mode_fact = _work_mode(combined)
    if mode_fact:
        facts["work_mode"] = mode_fact
        evidence["work_mode"] = mode

    # worker-allowed regions (explicit eligibility phrasing only)
    regions = {}
    for canonical, one_fact in region_facts(combined).items():
        if _verify(one_fact, combined):
            regions[canonical] = one_fact
    if regions:
        facts["region_facts"] = regions
        non_worldwide = {k for k in regions if k != "worldwide"}
        if "worldwide" in regions and not non_worldwide:
            evidence["worldwide"] = True
            evidence["allowed_work_locations"] = []
        elif regions:
            # explicit list only: WHAT is quoted is what counts
            evidence["worldwide"] = False
            evidence["allowed_work_locations"] = sorted(regions)
        else:
            facts["region_conflict"] = regions

    # sponsorship + 'must already be authorized' phrases
    sponsor, sponsor_facts = sponsorship_evidence(combined)
    if sponsor_facts:
        facts.update(sponsor_facts)
        if sponsor is not None:
            evidence["visa_sponsorship"] = sponsor

    # job country (where the posting sits) — different fact from regions
    country_fact = _job_country(combined)
    if country_fact:
        facts["job_country"] = country_fact
        evidence["job_country"] = country_fact["value"]

    # seniority (label words or year ranges)
    label, lo, hi, s_facts = seniority_evidence(title, description)
    if s_facts:
        facts.update(s_facts)
    if label:
        evidence["seniority"] = label
    if lo is not None:
        evidence["years_min"] = lo
    if hi is not None:
        evidence["years_max"] = hi

    # role family + responsibility hints
    family, family_facts = role_family_evidence(title, description)
    if family:
        evidence["role_family"] = family
    if family_facts:
        facts["hints"] = family_facts

    # requirements
    required, preferred, req_facts = requirements_evidence(description)
    if req_facts:
        facts.update(req_facts)
    evidence["requirements"] = {
        "required": required,
        "preferred": preferred,
        "complete": bool(req_facts.get("requirements", {}).get("complete")),
        "extractor_version": EXTRACTOR_VERSION,
    }

    facts["verify"] = _self_verify(facts, gate_text_for_sources)
    evidence["facts"] = facts
    return evidence


def _job_country(combined: str):
    """Where the job sits. Longest canonical country names first."""
    import tools.matching_locations as L
    for canonical in sorted(L.CANONICAL_COUNTRIES, key=lambda c: -len(c)):
        display = canonical.replace("_", " ")
        match = re.search(rf"\b{re.escape(display)}\b", combined, re.I)
        if match:
            return fact(canonical, match)
    return None


def _self_verify(facts: dict, texts: dict) -> dict:
    """Every fact's quote must re-find verbatim in the normalized source
    text bundle (spans index into the combined bundle; the quote is the
    portable, human-checkable part). Any failure is REPORTED, never
    silently dropped: the top-level report drives the extractor's honest
    completeness signal."""
    combined = "\n".join(v for v in texts.values() if v)
    report = {"all_verified": True, "rejected": []}

    def check(name, one_fact):
        quote = one_fact.get("quote") or ""
        if not quote or quote not in combined:
            report["all_verified"] = False
            report["rejected"].append(name)

    for name, value in facts.items():
        if isinstance(value, dict) and value.get("quote"):
            check(name, value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("quote"):
                    check(name, item)
    return report

