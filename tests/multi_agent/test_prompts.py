"""
Tests for Multi-Agent prompt builders and required planning sections.
"""

from app.multi_agent.prompts import (
    build_chatgpt_prompt_engineering_prompt,
    build_claude_development_prompt,
    build_gemini_research_prompt,
    build_revision_prompt,
)


def test_build_gemini_research_prompt():
    prompt = build_gemini_research_prompt("CAREER_LENS", "AI career recommendation platform")

    # Verify project name and filename contract
    assert "CAREER_LENS" in prompt
    assert "CAREER_LENS_IDEA_README.md" in prompt
    assert "Gemini" in prompt

    # Verify comprehensive A-to-Z research sections required
    required_keywords = [
        "concept & vision",
        "problem statement",
        "objectives",
        "target audience",
        "real-world applications",
        "market relevance",
        "requirements",
        "technology stack",
        "system architecture",
        "implementation approach",
        "development timeline",
        "complexity",
        "risks",
        "limitations",
        "future scope",
        "deployment",
    ]
    prompt_lower = prompt.lower()
    for kw in required_keywords:
        assert kw in prompt_lower, f"Missing required keyword: {kw}"

    # Verify single markdown artifact rule
    assert "generate exactly one" in prompt_lower


def test_build_chatgpt_prompt_engineering_prompt():
    readme_content = "# Sample Readme Content for App"
    prompt = build_chatgpt_prompt_engineering_prompt("MY_APP", readme_content)

    assert "MY_APP" in prompt
    assert "MY_APP_DEVELOPMENT_SPECIFICATION.md" in prompt
    assert readme_content in prompt
    assert "ChatGPT" in prompt
    assert "Claude" in prompt
    assert "Development Specification" in prompt


def test_build_claude_development_prompt():
    spec_content = "# Approved Development Specification"
    prompt = build_claude_development_prompt("MY_APP", spec_content)

    assert "MY_APP" in prompt
    assert spec_content in prompt
    assert "Project Development Agent" in prompt
    assert "Claude" in prompt


def test_build_revision_prompt():
    rev_prompt = build_revision_prompt("Gemini", "Please switch backend to FastAPI and add JWT authentication.")
    assert "GEMINI" in rev_prompt or "Gemini" in rev_prompt
    assert "FastAPI and add JWT authentication" in rev_prompt
    assert "USER AUDIT" in rev_prompt
