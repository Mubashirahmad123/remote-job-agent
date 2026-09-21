"""
tools/cv_matcher.py
Local keyword-based job scoring with fuzzy matching and synonym expansion.
No API calls — runs entirely offline.
"""

import re
from typing import Dict, List, Set
from pathlib import Path
import json

# =============================================================================
# SYNONYM & EXPANSION MAPS
# =============================================================================

_SYNONYM_PATTERNS = {}  # cache compiled regexes so we don't recompile per job

def _syn_pattern(syn: str) -> re.Pattern:
    """
    Word-boundary-safe match that also works for synonyms starting/ending
    in punctuation (e.g. '.net', 'c#', 'c++', 'ci/cd'), where Python's \\b
    fails because \\b only fires between a word char and a non-word char.
    """
    if syn not in _SYNONYM_PATTERNS:
        _SYNONYM_PATTERNS[syn] = re.compile(
            r"(?<![a-z0-9])" + re.escape(syn) + r"(?![a-z0-9])",
            re.IGNORECASE,
        )
    return _SYNONYM_PATTERNS[syn]

SKILL_SYNONYMS = {
    # Languages (language names/dialects only — NOT frameworks built on them)
    "python": ["python", "python3", "py"],
    "javascript": ["javascript", "js", "es6", "node", "nodejs", "node.js"],
    "typescript": ["typescript", "ts"],
    "java": ["java", "jvm"],
    "go": ["golang", "go lang"],
    "ruby": ["ruby"],
    "php": ["php"],
    "c++": ["c++", "cpp"],
    "c#": ["c#", "csharp"],
    "rust": ["rust"],
    "kotlin": ["kotlin"],
    "swift": ["swift"],

    # Frontend
    "react": ["react", "reactjs", "react.js"],
    "nextjs": ["nextjs", "next.js", "gatsby"],
    "redux": ["redux"],
    "vue": ["vue", "vuejs", "vue.js"],
    "nuxt": ["nuxt", "nuxtjs"],
    "angular": ["angular", "angularjs", "angular.js"],

    # Backend / Frameworks
    "django": ["django", "django-rest-framework", "drf"],
    "flask": ["flask"],
    "fastapi": ["fastapi"],
    "spring": ["spring", "springboot", "spring-boot", "spring cloud"],
    "express": ["express", "expressjs", "express.js"],
    "rails": ["rails", "ruby on rails", "ror"],
    "laravel": ["laravel"],
    "symfony": ["symfony"],
    "wordpress": ["wordpress"],
    "dotnet": [".net", "dotnet", "asp.net", "asp.net core", ".net core"],
    "qt": ["qt"],
    "cmake": ["cmake"],
    "cargo": ["cargo"],

    # Databases
    "postgresql": ["postgresql", "postgres", "psql", "pg"],
    "mysql": ["mysql", "mariadb"],
    "sql": ["sql"],
    "mongodb": ["mongodb", "mongo", "nosql"],
    "redis": ["redis", "redis cache"],
    "sqlite": ["sqlite"],

    # DevOps / Cloud
    "docker": ["docker", "containerization", "containers"],
    "aws": ["aws", "amazon web services", "ec2", "s3", "lambda", "cloudwatch"],
    "gcp": ["gcp", "google cloud", "google cloud platform"],
    "azure": ["azure", "microsoft azure"],
    "kubernetes": ["kubernetes", "k8s", "helm"],
    "terraform": ["terraform", "iac", "infrastructure as code"],
    "ci/cd": ["ci/cd", "github actions", "gitlab ci", "jenkins", "travis"],

    # Mobile
    "react native": ["react native", "react-native"],
    "flutter": ["flutter", "dart"],
    "ios": ["ios", "objective-c", "objectivec"],
    "android": ["android"],

    # General
    "rest api": ["rest", "restful", "graphql", "openapi", "swagger"],
    "git": ["git", "github", "gitlab", "bitbucket", "version control"],
    "agile": ["agile", "scrum", "kanban"],
    "testing": ["testing", "jest", "pytest", "unittest", "tdd", "unit test", "integration test"],
}

# =============================================================================
# REJECTION KEYWORDS (non-dev roles to exclude)
# =============================================================================

# Title-only patterns: role/seniority signals that must ONLY fire on the
# job title. Searching these in summary/company causes false positives
# (e.g. "content management APIs", "Principal Investments LLC").
TITLE_ONLY_PATTERNS = [
    # Non-dev roles
    r"\bservice desk\b", r"\bhelp desk\b", r"\bit support\b", r"\btechnical support\b",
    r"\bcustomer support\b", r"\bsystems engineer\b(?!.*software)",  # systems engineer but not software systems
    r"\bnetwork engineer\b", r"\bnetwork administrator\b",
    r"\bsecurity engineer\b", r"\bcybersecurity\b", r"\bpenetration tester\b",
    r"\bdevops\b", r"\bsre\b", r"\bsite reliability\b",
    r"\bdata scientist\b", r"\bdata analyst\b", r"\bml engineer\b", r"\bmachine learning\b",
    r"\bai engineer\b", r"\bai researcher\b", r"\bdeep learning\b", r"\bnlp engineer\b",
    r"\bqa engineer\b", r"\btest engineer\b", r"\bautomation tester\b", r"\bmanual tester\b",
    r"\bquality assurance\b",
    r"\bgame developer\b", r"\bgame designer\b", r"\bunity developer\b", r"\bunreal engine\b",
    r"\bembedded\b", r"\bfirmware\b", r"\bhardware\b", r"\bchip design\b", r"\bvlsi\b",
    r"\bsalesforce\b", r"\bapex\b", r"\bvisualforce\b", r"\bsalesforce developer\b",
    r"\bnetsuite\b", r"\bdynamics 365\b", r"\bd365\b", r"\bsap\b", r"\berp\b",
    r"\bservicenow\b", r"\bworkday\b", r"\bsharepoint\b",
    r"\bmulesoft\b", r"\bintegration engineer\b", r"\betl\b", r"\bdata engineer\b(?!.*software)",
    r"\bmainframe\b", r"\bcobol\b", r"\bas400\b", r"\brpg\b",
    r"\bmanufacturing\b", r"\bfabrication\b", r"\bwelding\b", r"\baeronautical\b",
    r"\bcomint\b", r"\bcesm\b", r"\bcecm\b",  # military/intel systems
    r"\bproduction engineer\b(?!.*software)", r"\bplatform engineer\b(?!.*software)",
    r"\bscrum master\b", r"\bproduct owner\b", r"\bproject manager\b", r"\bprogram manager\b",
    r"\btechnical writer\b", r"\bdocumentation\b",
    r"\bux designer\b", r"\bui designer\b", r"\bgraphic designer\b", r"\bproduct designer\b",
    # Narrow role phrases — bare "\bcontent\b"/"\bseo\b" rejected real dev
    # jobs mentioning "content management" or "contentful". Require a role noun.
    r"\bdigital marketing\b", r"\bcontent (writer|creator|strategist|marketer|manager|specialist|seo)\b",
    r"\bseo (specialist|analyst|consultant|manager|strategist|writer)\b", r"\bsocial media\b",
    r"\bsolutions architect\b(?!.*software)", r"\benterprise architect\b",
    r"\bconsultant\b", r"\bstrategy\b", r"\banalyst\b(?!.*software|systems)",

    # Seniority gates (optional — remove if you want senior roles)
    r"\bprincipal\b", r"\bstaff engineer\b", r"\bdistinguished\b", r"\bfellow\b",
    r"\bcto\b", r"\bvp of engineering\b", r"\bhead of engineering\b",
    r"\bdirector of engineering\b", r"\bsenior director\b",

    # Non-standard dev
    r"\btutor\b", r"\binstructor\b", r"\bteacher\b", r"\blecturer\b",
    r"\bfreelance\b.*\bdeveloper\b",  # vague freelance gigs
    r"\bintern\b",  # remove if you want internships
    r"\bvolunteer\b",
]

# Strict body signals: only multi-word, unambiguous role phrases. Single
# generic words (content, seo, principal, analyst...) must NOT appear here.
BODY_REJECTION_PATTERNS = [
    r"\bservice desk\b", r"\bhelp desk\b", r"\btechnical support\b",
    r"\bnetwork engineer\b", r"\bnetwork administrator\b",
    r"\bsecurity engineer\b", r"\bcybersecurity\b", r"\bpenetration tester\b",
    r"\bdata scientist\b", r"\bdata analyst\b", r"\bmachine learning\b",
    r"\bquality assurance\b", r"\bqa engineer\b", r"\btest engineer\b",
    r"\bgame developer\b", r"\bgame designer\b",
    r"\bsalesforce developer\b", r"\bvisualforce\b",
    r"\bscrum master\b", r"\bproduct owner\b", r"\bproject manager\b",
    r"\btechnical writer\b", r"\bux designer\b", r"\bui designer\b",
    r"\bcontent writer\b", r"\bcontent strategist\b", r"\bseo specialist\b",
]

# Back-compat alias (deprecated — use TITLE_ONLY_PATTERNS instead).
REJECTION_PATTERNS = TITLE_ONLY_PATTERNS

# Skills that count as "core stack" — language/framework/db.
# Only these participate in the main coverage ratio; everything else
# (git, agile, testing, docker, aws, etc.) is a minor bonus only.
CORE_CATEGORIES = {
    "python", "javascript", "typescript", "java", "go", "ruby", "php",
    "c++", "c#", "rust", "kotlin", "swift",
    "react", "nextjs", "redux", "vue", "nuxt", "angular",
    "django", "flask", "fastapi", "spring", "express", "rails",
    "laravel", "symfony", "wordpress", "dotnet", "qt", "cmake", "cargo",
    "postgresql", "mysql", "sql", "mongodb", "redis", "sqlite",
    "react native", "flutter", "ios", "android",
}

# =============================================================================
# SCORING ENGINE
# =============================================================================

class CVMatcher:
    def __init__(self, cv_profile: Dict):
        self.cv_profile = cv_profile
        self.cv_skills = self._extract_cv_skills()
        self.cv_title_keywords = self._extract_title_keywords()

    def _extract_cv_skills(self) -> Set[str]:
        """Extract and normalize all skills from CV profile."""
        skills = set()

        # Direct skills
        for skill in self.cv_profile.get("skills", []):
            skills.add(self._normalize(skill))

        # Frameworks count as skills too
        for fw in self.cv_profile.get("frameworks", []):
            skills.add(self._normalize(fw))

        # Databases
        for db in self.cv_profile.get("databases", []):
            skills.add(self._normalize(db))

        # Languages
        for lang in self.cv_profile.get("languages", []):
            skills.add(self._normalize(lang))

        # Infer from experience descriptions
        for exp in self.cv_profile.get("experience", []):
            desc = exp.get("description", "")
            for skill in self._extract_skills_from_text(desc):
                skills.add(skill)

        return skills

    def _extract_title_keywords(self) -> Set[str]:
        """Extract role keywords from CV (e.g., 'backend', 'frontend', 'fullstack')."""
        titles = self.cv_profile.get("preferred_titles", [])
        text = " ".join(titles).lower()
        keywords = set()
        for word in ["backend", "frontend", "fullstack", "full stack", "web", "software", "mobile", "api"]:
            if word in text:
                keywords.add(word.replace(" ", ""))
        return keywords

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize a skill string. Keeps spaces so multi-word skills
        (e.g. 'react native', 'rest api', 'ci/cd') still match dictionary keys."""
        text = text.lower().strip()
        text = text.replace(".", "")
        text = re.sub(r"\s+", " ", text)          # collapse multiple spaces into one
        return re.sub(r"[^a-z0-9+#/ ]", "", text)  # keep letters, digits, +, #, /, and single spaces

    def _extract_skills_from_text(self, text: str) -> List[str]:
        text_lower = text.lower()
        found = []
        for skill, synonyms in SKILL_SYNONYMS.items():
            for syn in synonyms:
                if _syn_pattern(syn).search(text_lower):
                    found.append(skill)
                    break
        return found

    def _job_text_to_skills(self, job_text: str) -> Set[str]:
        text_lower = job_text.lower()
        found = set()
        for skill, synonyms in SKILL_SYNONYMS.items():
            for syn in synonyms:
                if _syn_pattern(syn).search(text_lower):
                    found.add(skill)
                    break
        return found

    def should_reject(self, job: Dict) -> tuple[bool, str]:
        """
        Returns (should_reject, reason).
        True if job is NOT a software/web dev role.

        Title-only patterns fire on the title alone (company names like
        "Principal Investments" must not reject). Body patterns are a
        strict multi-word subset applied to summary + tech stack only.
        """
        title = (job.get("job_title") or "").lower()
        summary = (job.get("summary") or "").lower()
        tech_stack = (job.get("tech_stack") or "").lower()

        for pattern in TITLE_ONLY_PATTERNS:
            if re.search(pattern, title, re.IGNORECASE):
                return True, f"Rejected by title pattern: {pattern}"

        body = f"{summary} {tech_stack}"
        for pattern in BODY_REJECTION_PATTERNS:
            if re.search(pattern, body, re.IGNORECASE):
                return True, f"Rejected by body pattern: {pattern}"

        # Must contain at least one dev indicator (title + body, not company)
        combined = f"{title} {summary} {tech_stack}"

        # Must contain at least one dev indicator
        dev_indicators = [
            "developer", "engineer", "programmer", "software", "web", "backend",
            "frontend", "fullstack", "full stack", "web developer", "software engineer",
            "application developer", "web engineer", "software developer"
        ]
        if not any(ind in combined for ind in dev_indicators):
            return True, "No dev role indicators found"

        return False, ""

    def score(self, job: Dict) -> Dict:
        title = job.get("job_title") or ""
        summary = job.get("summary") or ""
        tech_stack = job.get("tech_stack") or ""

        job_text = f"{title} {summary} {tech_stack}".lower()

        job_skills = self._job_text_to_skills(job_text)

        if not job_skills:
            return {"score": 0, "match_reason": "No recognizable tech skills in job"}

        core_job_skills = job_skills & CORE_CATEGORIES
        bonus_job_skills = job_skills - CORE_CATEGORIES

        cv_skills = self.cv_skills

        # Direct matches
        direct_matches = cv_skills & job_skills

        # Expanded matches (synonym-based)
        expanded_matches = set()
        for cv_skill in cv_skills:
            if cv_skill in SKILL_SYNONYMS:
                for syn in SKILL_SYNONYMS[cv_skill]:
                    if _syn_pattern(syn).search(job_text):
                        expanded_matches.add(cv_skill)
                        break

        all_matches = direct_matches | expanded_matches
        core_matches = all_matches & CORE_CATEGORIES
        bonus_matches = all_matches & bonus_job_skills

        # Main score: coverage of the job's CORE stack only (not diluted by
        # generic tooling like git/agile/testing/docker).
        if core_job_skills:
            core_coverage = len(core_matches) / len(core_job_skills)
        else:
            # No recognizable core stack in the posting — don't reward this
            # with full coverage. Only title/bonus points can lift the score.
            core_coverage = 0

        # Small bonus for matching generic/tooling skills (git, agile, testing, docker, etc.)
        bonus_points = min(len(bonus_matches) * 2, 5)

        # Bonus: exact (non-synonym) core matches weighted higher
        exact_bonus = len(direct_matches & CORE_CATEGORIES) * 3

        # Title alignment bonus — capped so title text alone can't dominate the score
        title_bonus = 0
        job_title_norm = title.lower()
        for kw in self.cv_title_keywords:
            if kw in job_title_norm.replace(" ", ""):
                title_bonus += 10
        title_bonus = min(title_bonus, 10)

        # Seniority alignment
        seniority_bonus = 0
        cv_seniority = self.cv_profile.get("seniority", "mid").lower()
        if cv_seniority in job_title_norm:
            seniority_bonus = 5

        score = min(100, int(core_coverage * 70 + exact_bonus + bonus_points + title_bonus + seniority_bonus))

        matched_skills = sorted(all_matches)[:10]
        match_reason = f"Matched: {', '.join(matched_skills)}" if matched_skills else "Weak skill overlap"

        return {
            "score": score,
            "match_reason": match_reason,
            "cv_skills_found": len(cv_skills),
            "job_skills_found": len(job_skills),
            "core_job_skills": len(core_job_skills),
            "core_matches": len(core_matches),
            "overlap": len(all_matches),
            "direct_matches": sorted(direct_matches),
            "expanded_matches": sorted(expanded_matches - direct_matches),
        }


# =============================================================================
# PUBLIC API
# =============================================================================

def score_job(cv_profile: Dict, job: Dict) -> Dict:
    """Score a single job. Returns job dict with score fields added."""
    matcher = CVMatcher(cv_profile)

    # First: rejection check
    rejected, reason = matcher.should_reject(job)
    if rejected:
        job["match_score"] = 0
        job["match_reason"] = f"REJECTED: {reason}"
        job["rejected"] = True
        return job

    # Then: scoring
    result = matcher.score(job)
    job["match_score"] = result["score"]
    job["match_reason"] = result["match_reason"]
    job["rejected"] = False
    job["_match_details"] = result  # For debugging

    return job


def score_jobs(cv_profile: Dict, jobs: List[Dict]) -> List[Dict]:
    """Score all jobs, filter out rejected, sort by score descending."""
    scored = []
    rejected_count = 0
    low_match_count = 0

    for job in jobs:
        scored_job = score_job(cv_profile, job)

        if scored_job.get("rejected"):
            rejected_count += 1
            continue

        score = scored_job.get("match_score", 0)
        if score >= 70:
            scored.append(scored_job)
        else:
            low_match_count += 1
            # Still keep low matches for debugging, but mark them
            scored_job["_below_threshold"] = True
            scored.append(scored_job)

    # Sort: high matches first, then by score
    scored.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    print(f"\n📊 Scoring results:")
    print(f"   Rejected: {rejected_count} | Low match (<70): {low_match_count} | Passed (≥70): {len([j for j in scored if not j.get('_below_threshold')])}")

    return scored