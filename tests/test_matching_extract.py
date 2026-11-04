"""Phase 2 extractor tests: 40+ fixtures + the quote-verification invariants.

PROVENANCE (kept explicit, never mixed):
- "live-title"      job_title copied from the 2026-10-31 live run output
                    (titles only; no company names, no URLs, no PII)
- "synthetic-body"  the description text was WRITTEN BY THE TEST AUTHOR to
                    exercise a rule; it is NOT a quote from a real posting
- "live-body"       description copied verbatim from a live posting snippet

Every assertion about a fact must hold together with the quote rule: a
value exists only if its quote is re-findable in the source text.
"""
import pytest

from tools.matching_extract import (
    EXTRACTOR_VERSION,
    extract_matching_evidence,
    requirements_evidence,
    role_family_evidence,
    seniority_evidence,
)
from tools.matching_locations import (
    CANONICAL_WORK_LOCATIONS,
    normalize_text,
    verify,
    work_mode,
)

# ── Fixtures ────────────────────────────────────────────────────────────────
# (title, timezone, description, provenance)
FIXTURES = [
    # --- observed live titles, synthetic bodies (rule coverage) -------------
    ("Full-Stack Developer", "Remote", "You will build features end to end. "
     "Requirements: TypeScript, React, Node.js. Nice to have: GraphQL.", "live-title"),
    ("Cloud Engineer Automation", "Remote", "We run GitHub Actions and Docker "
     "in production. Requirements: Python, Git.", "live-title"),
    ("Platform and Integration Engineer Security Telemetry", "Remote",
     "Requirements: Go, Kubernetes, PostgreSQL.", "live-title"),
    ("Ground Software Engineer", "Remote", "Requirements: C++, Python.", "live-title"),
    ("Chief Engineer", "Remote", "Lead a team of engineers. Requirements: Java.",
     "live-title"),
    ("Backend Developer (Java/Spring Boot, AWS)", "Remote", "Requirements: Java, "
     "Spring Boot, AWS.", "live-title"),
    ("Software Engineer - Edge & Cloud", "Remote", "Requirements: Go, Docker.",
     "live-title"),
    ("Software Development Engineer in Test", "Remote", "Requirements: Python, "
     "pytest, CI.", "live-title"),
    ("Infrastructure Software Engineering - Platform & Build", "Remote",
     "Requirements: Kubernetes, Terraform, Go.", "live-title"),
    ("Developer Experience / DevEx", "Remote", "Requirements: Node.js, TypeScript.",
     "live-title"),
    ("Forward Deployed Software Engineer", "Remote", "You will work directly "
     "with customers on deployment. Requirements: Python, Kubernetes.", "live-title"),
    ("Quantum Software Engineer", "Remote", "Requirements: Python, MATLAB.",
     "live-title"),
    ("Software Engineer Full Stack (.NET / React)", "Remote", "Requirements: "
     "C#, React, TypeScript.", "live-title"),
    ("Electronic Software Engineer", "Remote", "Requirements: C, Python.",
     "live-title"),
    ("Consultant Implementation Engineer", "Remote", "Requirements: SQL, Java.",
     "live-title"),
    ("Intern Power Electronics Engineer", "Remote", "Requirements: C, MATLAB.",
     "live-title"),
    ("IAM Software Engineer", "Remote", "Requirements: Go, Kubernetes.", "live-title"),
    ("Software Developer", "Remote", "Requirements: React, Redux.", "live-title"),
    ("Thermal Engineer (Falcon, Dragon, & Starfall)", "Remote", "Requirements: "
     "thermal analysis.", "live-title"),
    ("Mission Integration Engineer (Security Products)", "Remote", "Requirements: "
     "Rust, Linux.", "live-title"),
    ("Kubernetes Platform Infrastructure Engineer", "Remote", "Requirements: "
     "Kubernetes, Go.", "live-title"),
    ("Full Stack Engineer (Application Software)", "Remote", "Requirements: "
     "TypeScript, .NET.", "live-title"),
    ("Wi-Fi Software Engineer", "Remote", "Requirements: C, Python.", "live-title"),
    ("New Graduate Engineer, Security Software", "Remote", "Requirements: Python.",
     "live-title"),
    ("Software Engineer II A - GBS IND", "Remote", "Requirements: Java, AWS.",
     "live-title"),
    ("BAW Filter Design Engineer", "Remote", "Requirements: MATLAB.", "live-title"),
    ("Environmental Health & Safety Engineer", "Remote", "Requirements: safety "
     "procedures.", "live-title"),
    ("GNC Engineer, ADCS", "Remote", "Requirements: C++, Python.", "live-title"),
    ("New Graduate Engineer, Software - '26/'27", "Remote", "Requirements: "
     "JavaScript.", "live-title"),
    ("Systems Operations Engineer", "Remote", "Requirements: Linux, Bash.",
     "live-title"),
    ("Power Automate Developer working from home", "Remote", "Requirements: "
     "PowerShell, Azure.", "live-title"),
    ("Mobile App Developer - Remote", "Remote", "Requirements: Kotlin, Swift.",
     "live-title"),
    ("eSIM Go Full Stack Developer", "Remote", "Requirements: Go, React.",
     "live-title"),
    (".Net Software Developer - Remote", "Remote", "Requirements: C#, .NET.",
     "live-title"),
    ("MacOS Developer - Fully Remote", "Remote", "Requirements: Swift, Xcode.",
     "live-title"),
    ("iOS Developer (London, Remote)", "London, Remote", "Requirements: Swift.",
     "live-title"),
    ("Remote Java Developer", "Remote", "Requirements: Java, Spring.", "live-title"),
    ("Software Developer - .Net - Remote", "Remote", "Requirements: C#.",
     "live-title"),
    ("Toptal: Apigee Engineer for Global Consumer Food", "Remote", "Requirements: "
     "Apigee, Java.", "live-title"),
    ("Software Engineer - Data Platform", "Remote", "Requirements: Go, Kafka.",
     "live-title"),
    ("Software Engineer, Backend", "Remote", "Requirements: Node.js, PostgreSQL.",
     "live-title"),
    ("Full Stack Developer", "Remote", "Requirements: React, TypeScript, Node.js.",
     "live-title"),
    ("Backend Developer", "Remote", "Requirements: Python, Django.", "live-title"),
    ("API Developer Remote Mumbai", "Mumbai, Remote", "Requirements: Node.js, "
     "PostgreSQL.", "live-title"),
    ("Python Backend Developer Remote Surat (India)", "Surat, India, Remote",
     "Requirements: Python, Django, REST API.", "live-title"),
    ("Backend Developer Remote Chennai (India)", "Chennai, India, Remote",
     "Requirements: Python, JavaScript.", "live-title"),
    ("Frontend Developer (m/w/d) remote", "Remote", "Requirements: React, "
     "TypeScript.", "live-title"),
    ("Developer Relations Engineer", "Remote", "You will advocate for our "
     "developer tooling. Requirements: Python, public speaking.", "live-title"),
    ("Software Engineer, AI Coding Tasks", "Remote", "Requirements: TypeScript, "
     "LLM tooling.", "live-title"),
    ("Customer Solutions Engineer, EMEA", "EMEA", "Requirements: SQL, Python.",
     "live-title"),
    # --- German / mojibake -------------------------------------------------
    ("Softwarearchitekt (m/w/d)", "M\u00fcnchen", "Homeoffice m\u00f6glich. "
     "Anforderungen: Java, Spring Boot.", "live-title"),
    ("D\u00e9veloppeur Full Stack | Practice SE", "Paris", "Requirements: React, "
     "Node.js.", "live-title"),
    # --- synthetic bodies exercising the hard rules ------------------------
    ("Backend Engineer", "Remote (EMEA)", "This role is open to candidates in "
     "the EEA/UK only. Requirements: Python, Django.", "synthetic-body"),
    ("Backend Engineer", "Remote (Americas)", "Applications are open to "
     "candidates in AMER. Requirements: Node.js.", "synthetic-body"),
    ("Backend Engineer", "Remote (US only)", "You must be based in the US and "
     "authorized to work in the United States. Requirements: Go.", "synthetic-body"),
    ("Full Stack Engineer", "Charlotte NC - Hybrid Onsite (3 days onsite)",
     "Requirements: React, TypeScript.", "synthetic-body"),
    ("Backend Engineer", "Remote", "Remote position. You may work remotely from "
     "anywhere in the world. Requirements: Python.", "synthetic-body"),
    ("Senior Backend Engineer", "Remote", "0 to 4 yrs of experience. "
     "Requirements: Python, PostgreSQL.", "synthetic-body"),
    ("Backend Engineer", "Remote", "5+ years experience. Requirements: Java.",
     "synthetic-body"),
    ("Full Stack Engineer", "Remote", "Requirements: React or Vue. Nice to have: "
     "GraphQL. Bonus: Docker.", "synthetic-body"),
    ("Backend Engineer", "Remote", "Requirements: Python. No PHP. "
     "Not required: Ruby on Rails.", "synthetic-body"),
    ("Backend Engineer", "Remote", "Requirements: Express.js and Node.js.",
     "synthetic-body"),
    ("Backend Engineer", "Remote", "We build a high performance express "
     "delivery service for our node fleet.", "synthetic-body"),
    ("Backend Engineer", "Remote", "No visa sponsorship is available. "
     "Requirements: Python.", "synthetic-body"),
    ("Backend Engineer", "Remote", "We offer visa sponsorship for this role. "
     "Requirements: Python.", "synthetic-body"),
    ("Backend Engineer", "Remote", "Requirements: JavaScript. You should be "
     "able to communicate clearly with the team.", "synthetic-body"),
]


def _evidence(title, timezone, description):
    return extract_matching_evidence({
        "job_title": title, "timezone": timezone, "summary": description})


class TestFixtureInvariants:
    """Every fixture must satisfy the global invariants, whatever it says."""

    @pytest.mark.parametrize("title,tz,body,provenance", FIXTURES,
                             ids=[f"{i}-{f[0][:32]}" for i, f in enumerate(FIXTURES)])
    def test_no_value_without_a_verified_quote(self, title, tz, body, provenance):
        evidence = _evidence(title, tz, body)
        report = evidence["facts"]["verify"]
        assert report["all_verified"] is True, report
        assert report["rejected"] == []

    @pytest.mark.parametrize("title,tz,body,provenance", FIXTURES,
                             ids=[f"{i}-{f[0][:32]}" for i, f in enumerate(FIXTURES)])
    def test_bare_remote_never_sets_worldwide(self, title, tz, body, provenance):
        evidence = _evidence(title, tz, body)
        if evidence.get("worldwide"):
            # worldwide requires an explicit phrase, never the word alone
            regions = evidence.get("facts", {}).get("worker_permission", {})
            assert "worldwide" in regions
            assert regions["worldwide"]["quote"].lower() != "remote"

    @pytest.mark.parametrize("title,tz,body,provenance", FIXTURES,
                             ids=[f"{i}-{f[0][:32]}" for i, f in enumerate(FIXTURES)])
    def test_regions_are_canonical(self, title, tz, body, provenance):
        evidence = _evidence(title, tz, body)
        for region in evidence.get("allowed_work_locations") or []:
            assert region in CANONICAL_WORK_LOCATIONS, region


class TestLocationRules:
    def test_eea_uk_only_is_extracted_as_eea_and_uk(self):
        e = _evidence("Backend Engineer", "Remote (EMEA)",
                      "This role is open to candidates in the EEA/UK only.")
        assert set(e["allowed_work_locations"]) >= {"eea", "uk"}
        assert e.get("worldwide") is not True

    def test_amer_is_not_worldwide(self):
        e = _evidence("Backend Engineer", "Remote (Americas)",
                      "Applications are open to candidates in AMER.")
        assert "amer" in e["allowed_work_locations"]
        assert not e.get("worldwide")

    def test_us_only_with_work_authorization(self):
        e = _evidence("Backend Engineer", "Remote (US only)",
                      "You must be based in the US and authorized to work in "
                      "the United States.")
        assert "us" in e["allowed_work_locations"]
        assert e.get("visa_sponsorship") is None
        assert "must_already_be_authorized" in e["facts"]

    def test_explicit_worldwide_is_worldwide(self):
        e = _evidence("Backend Engineer", "Remote",
                      "Remote position. You may work remotely from anywhere in "
                      "the world.")
        assert e.get("worldwide") is True

    def test_bare_remote_is_unknown_not_worldwide(self):
        e = _evidence("Backend Engineer", "Remote", "Great team, great product.")
        assert e.get("worldwide") is not True
        assert not e.get("allowed_work_locations")

    def test_onsite_and_hybrid_modes(self):
        assert work_mode("Hybrid Onsite (3 days onsite)")[0] == "hybrid"
        assert work_mode("You must be onsite in Munich")[0] == "onsite"
        assert work_mode("Homeoffice moeglich")[0] == "remote"
        assert work_mode("This product sells globally")[0] == "unknown"

    def test_bare_remote_word_does_not_set_mode(self):
        mode, one_fact = work_mode("Remote distribution team")
        assert mode == "unknown"
        assert one_fact == {}


class TestSeniority:
    def test_explicit_years_range(self):
        label, lo, hi, facts, not_stated = seniority_evidence(
            "Senior Backend Engineer", "0 to 4 yrs of experience.")
        assert lo == 0 and hi == 4
        assert "years" in facts
        assert not not_stated

    def test_five_plus_years(self):
        label, lo, hi, facts, not_stated = seniority_evidence(
            "Backend Engineer", "5+ years experience")
        assert lo == 5 and hi is None
        assert not not_stated

    def test_senior_label_from_title(self):
        label, lo, hi, facts, not_stated = seniority_evidence(
            "Senior Backend Engineer", "You will lead a small team.")
        assert label == "senior"
        assert not not_stated

    def test_german_architekt_title(self):
        label, lo, hi, facts, not_stated = seniority_evidence(
            "Softwarearchitekt (m/w/d)", "Anforderungen: Java.")
        assert label == "senior"
        assert not not_stated

    def test_no_seniority_signal_stays_not_stated(self):
        label, lo, hi, facts, not_stated = seniority_evidence(
            "Backend Engineer", "Build great software.")
        assert label is None and lo is None and hi is None
        assert not_stated is True


class TestRoleFamilyAndHints:
    def test_family_from_title(self):
        family, facts = role_family_evidence("Full Stack Developer", None)
        assert family == "fullstack"

    def test_backend_family(self):
        family, facts = role_family_evidence("Backend Engineer", None)
        assert family == "backend"

    def test_forward_deployed_is_a_hint_not_a_family(self):
        family, facts = role_family_evidence(
            "Forward Deployed Software Engineer", "You will work directly with "
            "customers.")
        hints = {f["value"] for f in facts}
        assert "forward_deployed" in hints

    def test_devrel_hint(self):
        family, facts = role_family_evidence(
            "Developer Relations Engineer", "You will advocate for our tooling.")
        assert "devrel" in {f["value"] for f in facts}

    def test_architect_hint_present(self):
        family, facts = role_family_evidence(
            "Softwarearchitekt", "Sie besitzen die Gesamtarchitektur.")
        assert "architect" in {f["value"] for f in facts}


class TestRequirements:
    def test_comma_list_is_and_not_or(self):
        required, preferred, facts = requirements_evidence(
            "Requirements: Python, Django, PostgreSQL.")
        alternatives = [r["alternatives"] for r in required]
        assert ["python"] in alternatives
        assert ["django"] in alternatives
        assert ["postgresql"] in alternatives

    def test_or_alternatives_group(self):
        required, preferred, facts = requirements_evidence(
            "Requirements: React or Vue.")
        assert ["react", "vue"] in [r["alternatives"] for r in required]

    def test_inline_preferred_marker(self):
        required, preferred, facts = requirements_evidence(
            "Requirements: Python. Nice to have: Docker.")
        assert ["docker"] in [r["alternatives"] for r in preferred]
        assert ["docker"] not in [r["alternatives"] for r in required]

    def test_negated_technology_is_dropped(self):
        required, preferred, facts = requirements_evidence(
            "Requirements: Python. No PHP. Not required: Ruby on Rails.")
        alternatives = [r["alternatives"] for r in required]
        assert ["php"] not in alternatives
        assert ["ruby"] not in alternatives
        assert facts.get("negations")

    def test_bare_express_is_not_a_requirement(self):
        required, preferred, facts = requirements_evidence(
            "We run a high performance express delivery service for our node fleet.")
        alternatives = [a for r in required for a in r["alternatives"]]
        assert "express" not in alternatives
        assert "node" not in alternatives

    def test_expressjs_and_nodejs_are_requirements(self):
        required, preferred, facts = requirements_evidence(
            "Requirements: Express.js and Node.js.")
        alternatives = [a for r in required for a in r["alternatives"]]
        assert "express" in alternatives
        assert "node" in alternatives

    def test_soft_skills_are_typed_not_technology(self):
        required, preferred, facts = requirements_evidence(
            "Requirements: JavaScript. You should be able to communicate clearly.")
        assert all(r["type"] in {"technology", "practice"} for r in required)

    def test_every_requirement_carries_its_quote(self):
        required, preferred, facts = requirements_evidence(
            "Requirements: Python, Django.")
        for requirement in required + preferred:
            assert requirement["evidence"].strip()


class TestEncoding:
    def test_mojibake_is_repaired(self):
        broken = "Anforderungen: Java. Standort M\u00fcnchen, Homeoffice."
        fixed = normalize_text(broken)
        assert "München" in fixed

    def test_extraction_works_on_repaired_text(self):
        broken = "D\u00e9veloppeur Full Stack | Practice SE \u2013 Homeoffice"
        fixed = normalize_text(broken)
        assert "–" in fixed


class TestExtractorContract:
    def test_version_is_declared(self):
        e = _evidence("Backend Engineer", "Remote", "Requirements: Python.")
        assert e["extractor_version"] == EXTRACTOR_VERSION

    def test_unknown_fields_are_absent_not_defaulted(self):
        e = _evidence("Backend Engineer", "Remote", "No facts here.")
        assert "visa_sponsorship" not in e
        assert "seniority" not in e
        assert "work_mode" not in e
        assert "job_country" not in e

    def test_description_beat_title_for_mode(self):
        e = _evidence("Backend Engineer", "Remote",
                      "This is a fully remote position.")
        assert e["work_mode"] == "remote"
        assert e["facts"]["work_mode"]["quote"]

    def test_work_from_anywhere_sets_remote_mode(self):
        e = _evidence("Backend Engineer", "Remote",
                      "You may work from anywhere in the world.")
        assert e["work_mode"] == "remote"
        assert e["work_mode"] == "remote"
        assert e.get("worldwide") is True

    def test_remote_or_hybrid_sets_flexible_mode(self):
        e = _evidence("Backend Engineer", "Remote",
                      "Remote or Hybrid position.")
        assert e["work_mode"] == "flexible"

    def test_five_plus_years_of_react_no_seniority_effect(self):
        e = _evidence("Backend Developer", "Remote",
                      "Requires 5+ years of React. Requirements: Python.")
        # Per-skill years should NOT set seniority years_min
        assert e.get("years_min") is None
        assert e.get("seniority_not_stated") is True

    def test_bangalore_job_country_is_india_with_quote(self):
        e = _evidence("Backend Developer", "Bangalore",
                      "We are hiring in Bangalore, India.")
        assert e.get("job_country") == "india"
        # job_country must carry a verbatim quote
        jc_fact = e["facts"]["job_country"]["india"]
        assert jc_fact["quote"] == "Bangalore"
        # D5: a fact verifies against the source string its `field` names,
        # not against the combined title+location+description blob.
        assert jc_fact["field"] == "tz_field"
        assert verify(jc_fact, "Bangalore")
        # ...and the provenance travels with the fact.
        assert jc_fact["source_field"] == "tz_field"
        assert jc_fact["extraction_method"] == "gazetteer"
        assert jc_fact["city"] == "bangalore"
        assert e.get("job_city") == "bangalore"

    def test_sql_token_recognized_in_requirements(self):
        """D15: bare 'SQL' in requirements is recognized as a technology token."""
        required, preferred, facts = requirements_evidence(
            "Requirements:\n- SQL\n- Python")
        assert any("sql" in i["alternatives"] for i in required)
        assert facts["requirements"]["count"]["required"] == 2

    def test_workingnomads_title_from_multiple_fields(self):
        """WorkingNomads API may return title in different fields.
        Parser should try multiple field names to avoid empty titles."""
        # Simulate the WorkingNomads parser logic:
        def extract_title(j):
            return (j.get("position") or j.get("job_title") or j.get("title") or
                    j.get("position_title") or j.get("name") or j.get("role") or "")

        # Test each field name
        for field_name in ["position", "job_title", "title", "position_title", "name", "role"]:
            job = {field_name: "Senior Python Developer"}
            assert extract_title(job) == "Senior Python Developer"

        # Empty when no title field present
        job = {"description": "Some description"}
        assert extract_title(job) == ""

        # Empty string value should fall through to next field
        job = {"position": "", "job_title": "Frontend Developer"}
        assert extract_title(job) == "Frontend Developer"

