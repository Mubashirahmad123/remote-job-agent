"""Unit tests for the country/location filter in agents/scrapper.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.scrapper import (
    ALLOWED_COUNTRY_TERMS, ALL_COUNTRY_NAMES,
    is_allowed_location, _extract_countries_from_text,
    extract_location_tags
)


class TestCountryFilter:
    """Tests for is_allowed_location and related functions."""

    # ── Detection tests ──
    def test_detect_india(self):
        assert _extract_countries_from_text("Engineer in Bangalore India") >= {"india", "bangalore"}

    def test_detect_pakistan(self):
        assert _extract_countries_from_text("Engineer in Karachi Pakistan") >= {"pakistan", "karachi"}

    def test_detect_usa(self):
        assert _extract_countries_from_text("Engineer in New York USA") >= {"usa", "new york"}

    def test_detect_san_diego(self):
        assert "san diego" in _extract_countries_from_text("Engineer in San Diego")

    def test_detect_portland(self):
        assert "portland" in _extract_countries_from_text("Engineer in Portland")

    def test_detect_washington_dc(self):
        assert "washington dc" in _extract_countries_from_text("Engineer in Washington DC")

    def test_detect_ireland_republic(self):
        assert "ireland republic" in _extract_countries_from_text("Engineer in Ireland Republic")

    def test_no_false_positive_useful(self):
        assert "us" not in _extract_countries_from_text("This product is very useful")

    def test_no_false_positive_land(self):
        assert "la" not in _extract_countries_from_text("Software engineer position")

    # ── Filter logic tests ──
    def test_india_allowed(self):
        assert is_allowed_location({"summary": "Engineer at Bangalore India", "job_title": "Dev", "company": "Co"}) == True

    def test_pakistan_blocked(self):
        assert is_allowed_location({"summary": "Engineer in Karachi", "job_title": "Dev", "company": "Co"}) == False

    def test_usa_allowed(self):
        assert is_allowed_location({"summary": "Engineer in New York USA", "job_title": "Dev", "company": "Co"}) == True

    def test_china_blocked(self):
        assert is_allowed_location({"summary": "Developer in Shanghai", "job_title": "Dev", "company": "Co"}) == False

    def test_uk_allowed(self):
        assert is_allowed_location({"summary": "Developer in London UK", "job_title": "Dev", "company": "Co"}) == True

    def test_germany_allowed(self):
        assert is_allowed_location({"summary": "Engineer in Berlin Germany", "job_title": "Dev", "company": "Co"}) == True

    def test_remote_allowed(self):
        assert is_allowed_location({"summary": "Fully remote position", "job_title": "Dev", "company": "Co"}) == True

    def test_no_location_allowed(self):
        assert is_allowed_location({"summary": "Hiring developer", "job_title": "Dev", "company": "Co"}) == True

    def test_russia_blocked(self):
        assert is_allowed_location({"summary": "Engineer in Moscow Russia", "job_title": "Dev", "company": "Co"}) == False

    def test_canada_allowed(self):
        assert is_allowed_location({"summary": "Developer in Toronto Canada", "job_title": "Dev", "company": "Co"}) == True

    def test_australia_allowed(self):
        assert is_allowed_location({"summary": "Engineer in Sydney Australia", "job_title": "Dev", "company": "Co"}) == True

    def test_mixed_allowed(self):
        """If both an allowed and blocked country mentioned, should ALLOW."""
        assert is_allowed_location({"summary": "Work from India or Pakistan", "job_title": "Dev", "company": "Co"}) == True

    def test_empty_job_allowed(self):
        assert is_allowed_location({}) == True

    def test_timezone_detection(self):
        """Karachi timezone should detect Pakistan and block."""
        assert is_allowed_location({"summary": "Developer", "job_title": "Dev", "company": "Co", "timezone": "Asia/Karachi"}) == False

    # ── Data integrity ──
    def test_allowed_terms_have_no_duplicates(self):
        assert len(ALLOWED_COUNTRY_TERMS) == len(set(ALLOWED_COUNTRY_TERMS))

    def test_geo_terms_in_both_lists(self):
        """Geographic terms in ALLOWED must also be in ALL_COUNTRY_NAMES for detection."""
        geo_terms = {t for t in ALLOWED_COUNTRY_TERMS if len(t) > 2}
        geo_terms -= {
            # Non-geographic terms (timezone, remote signals, etc.)
            "pst", "cest", "cst", "mst", "est", "eet", "gmt", "utc", "cet",
            "eu", "europe", "apac", "latam", "emea", "na remote", "emea remote",
            "us timezone", "eu timezone", "north america", "latin america",
            "asia pacific", "european union",
            "remote", "fully remote", "remote first", "distributed team",
            "worldwide", "global", "anywhere", "anywhere in the world",
        }
        missing = geo_terms - ALL_COUNTRY_NAMES
        assert not missing, f"Missing from ALL_COUNTRY_NAMES: {missing}"
