"""
Predefined system prompts and instructions for Victor's Multi-Agent Module.
Strictly separates responsibilities:
- Gemini: Research & README Agent
- ChatGPT: Prompt Engineering & Specification Agent
- Claude: Project Development Agent
"""

from __future__ import annotations


def build_gemini_research_prompt(project_name: str, idea: str) -> str:
    return (
        f"You are Victor's specialized Project Research & Planning Agent (Gemini).\n\n"
        f"PROJECT NAME: {project_name}\n"
        f"USER IDEA: {idea}\n\n"
        "TASK:\n"
        "Conduct comprehensive, end-to-end (A-to-Z) project research and planning for this idea.\n"
        "Your research must thoroughly analyze and detail each of the following sections:\n"
        "1. Project Concept & Vision\n"
        "2. Problem Statement\n"
        "3. Core Objectives & Key Results (OKRs)\n"
        "4. Target Audience & User Personas\n"
        "5. Real-World Applications & Use Cases\n"
        "6. Market Relevance, Competitor Landscape & Differentiation\n"
        "7. Complete Functional & Non-Functional Requirements (Features List)\n"
        "8. Recommended Technology Stack (Frontend, Backend, Database, Cloud/Infra, Tools)\n"
        "9. System Architecture & High-Level Design\n"
        "10. Implementation Approach & Engineering Strategy\n"
        "11. Estimated Development Timeline & Milestone Breakdown\n"
        "12. Technical Complexity & Resource Requirements\n"
        "13. Project Risks, Vulnerabilities & Mitigation Strategies\n"
        "14. Assumptions, Limitations & Edge Cases\n"
        "15. Future Scope & Roadmap (Phase 2 & Phase 3)\n"
        "16. Deployment, Hosting & DevOps Approach\n\n"
        "OUTPUT FORMAT REQUIREMENT:\n"
        f"Generate exactly ONE complete, downloadable Markdown document titled:\n"
        f"# {project_name}_IDEA_README.md\n\n"
        "Provide thorough, high-value, production-grade documentation that serves as the single source of truth."
    )


def build_chatgpt_prompt_engineering_prompt(project_name: str, approved_readme: str) -> str:
    return (
        f"You are Victor's Master Prompt Engineering & Development Specification Architect (ChatGPT).\n\n"
        f"PROJECT NAME: {project_name}\n\n"
        "INPUT ARTIFACT (APPROVED RESEARCH README):\n"
        "--------------------------------------------------\n"
        f"{approved_readme}\n"
        "--------------------------------------------------\n\n"
        "TASK:\n"
        "Study the approved README above and transform this comprehensive research into a complete, "
        "production-grade Development Specification and Prompt Package for an autonomous coding agent (Claude).\n\n"
        "Your output must include:\n"
        "1. Master System Instructions for the Development Agent\n"
        "2. Step-by-Step Implementation Prompts (ordered sequentially from setup to deployment)\n"
        "3. Detailed Task Prompts for each module/component\n"
        "4. Exact Architecture Guidance & File Structure Plan\n"
        "5. Technical Constraints & Boundary Conditions\n"
        "6. Code Examples & Reference Patterns for key APIs/logic\n"
        "7. Expected Behavior & Acceptance Criteria for each task\n"
        "8. Comprehensive Validation, Testing & Verification Instructions (unit, integration, e2e)\n"
        "9. Critical Edge Cases & Failure Modes to handle\n"
        "10. Security Considerations & Hardening Requirements\n"
        "11. Strict Execution Order & Dependency Prerequisites\n\n"
        "OUTPUT FORMAT REQUIREMENT:\n"
        f"Generate a clean, structured Markdown package titled:\n"
        f"# {project_name}_DEVELOPMENT_SPECIFICATION.md\n"
        "This specification must be actionable, unambiguous, and ready for immediate autonomous execution."
    )


def build_claude_development_prompt(project_name: str, approved_spec: str) -> str:
    return (
        f"You are Victor's specialized Project Development Agent (Claude).\n\n"
        f"PROJECT NAME: {project_name}\n\n"
        "APPROVED DEVELOPMENT SPECIFICATION & PROMPTS:\n"
        "--------------------------------------------------\n"
        f"{approved_spec}\n"
        "--------------------------------------------------\n\n"
        "TASK:\n"
        "You are the implementation agent responsible for building this project.\n"
        "Begin the project implementation in accordance with the approved specification:\n"
        "1. Acknowledge and summarize the implementation strategy and execution order.\n"
        "2. Scaffold the project directory structure and configuration files.\n"
        "3. Implement the core modules step-by-step with clean, production-ready code.\n"
        "4. Provide test scripts and automated verification commands for each component.\n"
        "5. Iterate through implementation, testing, debugging, and verification.\n\n"
        "Proceed with Step 1 of the implementation order now."
    )


def build_revision_prompt(agent_role_name: str, user_feedback: str) -> str:
    return (
        f"REVISION REQUEST FOR {agent_role_name.upper()} FROM USER AUDIT:\n"
        f"The user has audited your generated output and requested the following modifications/corrections:\n\n"
        f"\"{user_feedback}\"\n\n"
        "Please revise and regenerate the complete artifact to incorporate all requested changes while "
        "maintaining the thoroughness, structure, and quality of the previous sections."
    )
