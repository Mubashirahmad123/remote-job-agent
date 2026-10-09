"""Resume generator grounding tests — isolated (never calls LLMs or PDFs)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.resume_generator import (
    _build_smart_prompt,
    _strip_llm_footer,
    generate_resume_for_job,
)


JOB = {
    "job_title": "Full Stack Developer",
    "company": "TestCorp",
    "tech_stack": "React, Node.js, PostgreSQL",
    "summary": "We need a full stack developer to build our SaaS platform.",
    "apply_url": "https://example.com/job/123",
}

CV_PROFILE = {
    "name": "Mubashir Ahmad",
    "email": "me@example.com",
    "phone": "+10000000000",
    "location": "Remote",
    "skills": ["React", "Python", "FastAPI"],
    "frameworks": ["Next.js"],
    "databases": ["PostgreSQL"],
    "languages": ["JavaScript"],
    "experience": [
        {"title": "Software Engineer", "company": "RealCo",
         "duration": "2022 - Present", "description": "Built real things"},
    ],
    "education": [
        {"degree": "BSc Computer Science", "institution": "Real University",
         "year": "2022"},
    ],
}


class TestPromptGrounding:
    """CV projects must reach the LLM and be pinned as the only allowed source."""

    def test_prompt_contains_grounding_rules(self):
        prompt = _build_smart_prompt(JOB, CV_PROFILE, "Some CV text.")
        assert "GROUNDING RULES" in prompt
        assert "NEVER invent" in prompt

    def test_prompt_contains_projects_instruction(self):
        prompt = _build_smart_prompt(JOB, CV_PROFILE, "Some CV text.")
        assert "PROJECTS:" in prompt
        assert "## Projects" in prompt
        assert "ACTUAL" in prompt

    def test_long_cv_tail_survives_truncation(self):
        """Projects live at the end of a CV — head-only truncation erased them.

        6000 chars of filler + a PROJECTS section at the tail: the old
        base_text[:4500] cut dropped the projects entirely; head+tail keeps it.
        """
        filler = ("Did various things at various places. " * 150)  # ~6000 chars
        cv_text = filler + "\n\nPROJECTS\n- Built JobAgent: an autonomous job-application pipeline\n"
        prompt = _build_smart_prompt(JOB, CV_PROFILE, cv_text)
        assert "Built JobAgent" in prompt, (
            "PROJECTS section at the CV tail was truncated away — "
            "the LLM would invent its own projects."
        )
        assert "[...middle omitted...]" in prompt

    def test_short_cv_not_marked_truncated(self):
        cv_text = "Short CV. " * 10
        prompt = _build_smart_prompt(JOB, CV_PROFILE, cv_text)
        assert "[...middle omitted...]" not in prompt

    def test_skill_match_lists_matching_cv_skills(self):
        prompt = _build_smart_prompt(JOB, CV_PROFILE, "Some CV text.")
        assert "MATCHING SKILLS FROM YOUR CV" in prompt
        assert "React" in prompt


class TestLlmFooterStrip:
    """LLM-added footers must never reach the PDF or the preview markdown."""

    def test_strips_keywords_footer_after_education(self):
        text = (
            "# Mubashir Nazir\n\n## Education\n"
            "B.Tech, Mechanical Engineering - University of Kashmir | 2019 - 2023\n"
            "---\n"
            "Keywords: TypeScript, Node.js, React, AI automation.\n"
        )
        clean = _strip_llm_footer(text)
        assert "Keywords:" not in clean
        assert "---" not in clean
        assert clean.rstrip().endswith("2019 - 2023")

    def test_strips_bulleted_keywords_line(self):
        text = "# Name\n\n## Skills\n- x\n\n- Keywords: Python, FastAPI\n"
        clean = _strip_llm_footer(text)
        assert "Keywords" not in clean
        assert "- x" in clean

    def test_keeps_keyword_optimization_bullets(self):
        """A legit bullet mentioning keywords (no colon right after) survives."""
        text = "## Experience\n- Led keyword optimization for search ranking\n"
        assert _strip_llm_footer(text) == text.strip("\n")

    def test_strips_mid_document_separator(self):
        """A stray '---' renders as literal text in the PDF — removed anywhere."""
        text = "# Name\n\n---\n\n## Skills\n- x\n"
        clean = _strip_llm_footer(text)
        assert "---" not in clean

    def test_strips_other_hr_variants(self):
        text = "# Name\n\n***\n\n## Skills\n- x\n\n___\n"
        clean = _strip_llm_footer(text)
        assert "***" not in clean
        assert "___" not in clean

    def test_empty_text_passthrough(self):
        assert _strip_llm_footer("") == ""
        assert _strip_llm_footer(None) is None


class TestGenerateOutParam:
    """generate_resume_for_job must surface the resume text via ``out``."""

    def test_out_receives_resume_text(self, monkeypatch, tmp_path):
        import tools.resume_generator as rg

        monkeypatch.setattr(rg, "generate_tailored_resume",
                            lambda job, cv_profile=None: "# Name\n\n## Skills\n- x\n")
        monkeypatch.setattr(rg, "save_resume_pdf",
                            lambda *a, **kw: str(tmp_path / "r.pdf"))
        produced = {}
        result = generate_resume_for_job(dict(JOB), output_folder=str(tmp_path),
                                         skip_existing=False, out=produced)
        assert result == str(tmp_path / "r.pdf")
        assert produced["resume_text"].startswith("# Name")

    def test_out_present_even_on_empty_text(self, monkeypatch, tmp_path):
        import tools.resume_generator as rg

        monkeypatch.setattr(rg, "generate_tailored_resume",
                            lambda job, cv_profile=None: "")
        produced = {}
        result = generate_resume_for_job(dict(JOB), output_folder=str(tmp_path),
                                         skip_existing=False, out=produced)
        assert result is None
        assert produced["resume_text"] == ""

    def test_backward_compatible_without_out(self, monkeypatch, tmp_path):
        import tools.resume_generator as rg

        monkeypatch.setattr(rg, "generate_tailored_resume",
                            lambda job, cv_profile=None: "# Name\n")
        monkeypatch.setattr(rg, "save_resume_pdf",
                            lambda *a, **kw: str(tmp_path / "r.pdf"))
        result = generate_resume_for_job(dict(JOB), output_folder=str(tmp_path),
                                         skip_existing=False)
        assert result == str(tmp_path / "r.pdf")
