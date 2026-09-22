"""
Master Orchestrator for Multi-Agent Planning & Execution.

Coordinates Gemini (Research), ChatGPT (Prompt Engineering), and Claude (Development)
with strict human gating, revision tracking, and artifact persistence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import MultiAgentConfig, load_config
from app.logging import get_logger
from app.multi_agent.browser_agent import MultiAgentBrowserManager
from app.multi_agent.models import (
    AgentRole,
    MultiAgentStage,
    ReviewAction,
    WorkflowState,
)
from app.multi_agent.prompts import (
    build_chatgpt_prompt_engineering_prompt,
    build_claude_development_prompt,
    build_gemini_research_prompt,
    build_revision_prompt,
)

logger = get_logger("multi_agent.orchestrator")


class MultiAgentOrchestrator:
    """
    State machine orchestrating the 3 AI platforms with mandatory human approval checkpoints.
    """

    def __init__(
        self,
        config: MultiAgentConfig | None = None,
        browser_manager: MultiAgentBrowserManager | None = None,
    ) -> None:
        self.config = config or load_config().multi_agent
        self.browser_manager = browser_manager or MultiAgentBrowserManager(
            downloads_dir=self.config.downloads_dir
        )
        self.state: WorkflowState | None = None

    @staticmethod
    def _sanitize_project_name(raw_name: str) -> str:
        clean = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_name.strip())
        clean = re.sub(r"_+", "_", clean).strip("_")
        return clean.upper() if clean else "PROJECT"

    async def start_project(self, idea: str, project_name: str | None = None) -> dict[str, Any]:
        """
        Initiates the planning workflow:
        1. Sets stage to IDEA_RECEIVED -> GEMINI_RESEARCH
        2. Opens dedicated Gemini tab
        3. Sends research prompt
        4. Halts at GEMINI_REVIEW_REQUIRED for user audit
        """
        if not idea or not idea.strip():
            return {
                "status": "error",
                "message": "Project idea cannot be empty.",
            }

        name = self._sanitize_project_name(project_name or idea[:25])
        self.state = WorkflowState(
            project_name=name,
            original_idea=idea.strip(),
            current_stage=MultiAgentStage.IDEA_RECEIVED,
        )

        logger.info(f"Starting Multi-Agent project planning for '{name}'")
        self.state.transition_to(MultiAgentStage.GEMINI_RESEARCH, active_agent=AgentRole.GEMINI_RESEARCHER)

        research_prompt = build_gemini_research_prompt(name, idea)
        output = None
        try:
            output = await self.browser_manager.send_prompt_and_receive(
                role=AgentRole.GEMINI_RESEARCHER,
                prompt=research_prompt,
                timeout_seconds=self.config.browser_timeout_seconds,
            )
        except Exception as exc:
            logger.warning(f"Browser interaction for Gemini research encountered issue: {exc}. Attempting direct LLM fallback...")
            try:
                output = await self.browser_manager.generate_direct_llm_fallback(
                    role=AgentRole.GEMINI_RESEARCHER,
                    prompt=research_prompt,
                )
            except Exception as fb_exc:
                logger.error(f"Both browser and direct fallback failed for Gemini: {fb_exc}")
                return {
                    "status": "error",
                    "stage": self.state.current_stage.value,
                    "message": f"Gemini research stage failed: {exc} (Fallback failed: {fb_exc})",
                }

        self.state.current_output = output
        self.state.transition_to(MultiAgentStage.GEMINI_REVIEW_REQUIRED)

        filename = f"{self.state.project_name}_IDEA_README.md"
        return {
            "status": "review_required",
            "stage": self.state.current_stage.value,
            "project_name": self.state.project_name,
            "active_agent": "Gemini (Research & Planning Agent)",
            "artifact_name": filename,
            "message": (
                "Gemini has completed comprehensive project research. "
                "AUDIT REQUIRED: Please review the generated README below. "
                "You must explicitly Approve, Reject, or Request Changes before Victor proceeds."
            ),
            "content": output,
        }

    async def review_artifact(self, action: ReviewAction | str, feedback: str = "") -> dict[str, Any]:
        """
        Human-in-the-loop audit checkpoint handler:
        - Evaluates user approval, rejection, or revision requests.
        - Strictly gates handoffs between agents.
        """
        if not self.state:
            return {
                "status": "error",
                "message": "No active project workflow. Call start_project first.",
            }

        if isinstance(action, str):
            try:
                action = ReviewAction(action.lower().strip())
            except ValueError:
                return {
                    "status": "error",
                    "message": f"Invalid review action: '{action}'. Must be 'approve', 'reject', or 'request_changes'.",
                }

        # --- Stage 1 Review: GEMINI_REVIEW_REQUIRED ---
        if self.state.current_stage in (MultiAgentStage.GEMINI_REVIEW_REQUIRED, MultiAgentStage.GEMINI_REVISION):
            if action == ReviewAction.APPROVE:
                self.state.gemini_approved = True
                self.state.transition_to(MultiAgentStage.GEMINI_APPROVED)

                approved_readme = (self.state.current_output or "").strip()
                if len(approved_readme) < 50 or approved_readme == "Response captured.":
                    readme_file = self.browser_manager.downloads_dir / f"{self.state.project_name}_IDEA_README.md"
                    if readme_file.exists():
                        f_text = readme_file.read_text(encoding="utf-8").strip()
                        if len(f_text) > 50 and f_text != "Response captured.":
                            approved_readme = f_text

                    if len(approved_readme) < 50 or approved_readme == "Response captured.":
                        logger.info("Approved README was invalid or empty. Generating comprehensive research via fallback...")
                        research_prompt = build_gemini_research_prompt(self.state.project_name, self.state.original_idea)
                        approved_readme = await self.browser_manager.generate_direct_llm_fallback(
                            role=AgentRole.GEMINI_RESEARCHER,
                            prompt=research_prompt,
                        )

                self.state.current_output = approved_readme
                # Save approved README to local Downloads
                filename = f"{self.state.project_name}_IDEA_README.md"
                saved_path = self.browser_manager.save_artifact(filename, approved_readme)
                self.state.add_artifact(filename, str(saved_path), MultiAgentStage.README_DOWNLOADED, approved=True)
                self.state.transition_to(MultiAgentStage.README_DOWNLOADED)

                # Advance to ChatGPT in a NEW dedicated tab
                logger.info("Gemini research approved. Transitioning to ChatGPT Prompt Engineering Agent...")
                self.state.transition_to(
                    MultiAgentStage.CHATGPT_PROMPT_ENGINEERING,
                    active_agent=AgentRole.CHATGPT_PROMPT_ENGINEER,
                )

                prompt_eng_instruction = build_chatgpt_prompt_engineering_prompt(
                    self.state.project_name, approved_readme
                )

                chatgpt_output = None
                try:
                    chatgpt_output = await self.browser_manager.send_prompt_and_receive(
                        role=AgentRole.CHATGPT_PROMPT_ENGINEER,
                        prompt=prompt_eng_instruction,
                        timeout_seconds=self.config.browser_timeout_seconds,
                    )
                except Exception as exc:
                    logger.warning(f"Browser interaction for ChatGPT prompt engineering failed: {exc}. Attempting direct LLM fallback...")
                    try:
                        chatgpt_output = await self.browser_manager.generate_direct_llm_fallback(
                            role=AgentRole.CHATGPT_PROMPT_ENGINEER,
                            prompt=prompt_eng_instruction,
                        )
                    except Exception as fb_exc:
                        logger.error(f"Both browser and direct fallback failed for ChatGPT: {fb_exc}")
                        return {
                            "status": "error",
                            "stage": self.state.current_stage.value,
                            "message": f"ChatGPT prompt engineering stage failed: {exc} (Fallback failed: {fb_exc})",
                        }

                self.state.current_output = chatgpt_output
                self.state.transition_to(MultiAgentStage.CHATGPT_REVIEW_REQUIRED)

                return {
                    "status": "review_required",
                    "stage": self.state.current_stage.value,
                    "project_name": self.state.project_name,
                    "active_agent": "ChatGPT (Prompt Engineering & Specification Agent)",
                    "artifact_name": f"{self.state.project_name}_DEVELOPMENT_SPECIFICATION.md",
                    "downloaded_readme": str(saved_path),
                    "message": (
                        f"Approved research downloaded to: {saved_path}.\n"
                        "ChatGPT has transformed the research into a development specification & prompt package. "
                        "AUDIT REQUIRED: Please review the prompt package below. "
                        "You must explicitly Approve, Reject, or Request Changes before Victor proceeds to Claude."
                    ),
                    "content": chatgpt_output,
                }

            elif action == ReviewAction.REQUEST_CHANGES:
                if not feedback or not feedback.strip():
                    return {
                        "status": "error",
                        "message": "Feedback is required when requesting revisions.",
                    }

                rev_num = self.state.record_revision(
                    MultiAgentStage.GEMINI_REVISION, feedback, self.state.current_output
                )
                self.state.transition_to(MultiAgentStage.GEMINI_REVISION)

                # Send revision prompt back to Gemini in the SAME tab
                rev_prompt = build_revision_prompt("Gemini", feedback)
                updated_output = None
                try:
                    updated_output = await self.browser_manager.send_prompt_and_receive(
                        role=AgentRole.GEMINI_RESEARCHER,
                        prompt=rev_prompt,
                        timeout_seconds=self.config.browser_timeout_seconds,
                    )
                except Exception as exc:
                    logger.warning(f"Browser revision failed for Gemini: {exc}. Attempting direct LLM fallback...")
                    try:
                        updated_output = await self.browser_manager.generate_direct_llm_fallback(
                            role=AgentRole.GEMINI_RESEARCHER,
                            prompt=rev_prompt,
                        )
                    except Exception as fb_exc:
                        return {
                            "status": "error",
                            "stage": self.state.current_stage.value,
                            "message": f"Gemini revision failed: {exc} (Fallback failed: {fb_exc})",
                        }

                self.state.current_output = updated_output
                self.state.transition_to(MultiAgentStage.GEMINI_REVIEW_REQUIRED)

                return {
                    "status": "review_required",
                    "stage": self.state.current_stage.value,
                    "project_name": self.state.project_name,
                    "revision": rev_num,
                    "message": (
                        f"Gemini has revised the research README based on your feedback (Revision {rev_num}). "
                        "AUDIT REQUIRED: Please review the updated README below and Approve or Request Changes."
                    ),
                    "content": updated_output,
                }

            elif action == ReviewAction.REJECT:
                return {
                    "status": "rejected",
                    "stage": self.state.current_stage.value,
                    "message": "Research README was rejected by user. The workflow is paused.",
                }

        # --- Stage 2 Review: CHATGPT_REVIEW_REQUIRED ---
        elif self.state.current_stage in (MultiAgentStage.CHATGPT_REVIEW_REQUIRED, MultiAgentStage.CHATGPT_REVISION):
            if action == ReviewAction.APPROVE:
                self.state.chatgpt_approved = True
                self.state.transition_to(MultiAgentStage.CHATGPT_APPROVED)

                approved_spec = (self.state.current_output or "").strip()
                if len(approved_spec) < 50 or approved_spec == "Response captured.":
                    spec_file = self.browser_manager.downloads_dir / f"{self.state.project_name}_DEVELOPMENT_SPECIFICATION.md"
                    if spec_file.exists():
                        f_text = spec_file.read_text(encoding="utf-8").strip()
                        if len(f_text) > 50 and f_text != "Response captured.":
                            approved_spec = f_text

                    if len(approved_spec) < 50 or approved_spec == "Response captured.":
                        logger.info("Approved specification was invalid or empty. Generating complete specification via fallback...")
                        readme_content = self.state.original_idea
                        readme_file = self.browser_manager.downloads_dir / f"{self.state.project_name}_IDEA_README.md"
                        if readme_file.exists():
                            f_readme = readme_file.read_text(encoding="utf-8").strip()
                            if len(f_readme) > 50 and f_readme != "Response captured.":
                                readme_content = f_readme
                        prompt_eng_instruction = build_chatgpt_prompt_engineering_prompt(
                            self.state.project_name, readme_content
                        )
                        approved_spec = await self.browser_manager.generate_direct_llm_fallback(
                            role=AgentRole.CHATGPT_PROMPT_ENGINEER,
                            prompt=prompt_eng_instruction,
                        )

                self.state.current_output = approved_spec
                # Save approved specification to local Downloads
                spec_filename = f"{self.state.project_name}_DEVELOPMENT_SPECIFICATION.md"
                saved_spec_path = self.browser_manager.save_artifact(spec_filename, approved_spec)
                self.state.add_artifact(spec_filename, str(saved_spec_path), MultiAgentStage.CHATGPT_APPROVED, approved=True)

                # Advance to Claude in a THIRD dedicated tab
                logger.info("ChatGPT specification approved. Transitioning to Claude Development Agent...")
                self.state.transition_to(
                    MultiAgentStage.CLAUDE_DEVELOPMENT,
                    active_agent=AgentRole.CLAUDE_DEVELOPER,
                )

                dev_instruction = build_claude_development_prompt(
                    self.state.project_name, approved_spec
                )

                claude_output = None
                try:
                    claude_output = await self.browser_manager.send_prompt_and_receive(
                        role=AgentRole.CLAUDE_DEVELOPER,
                        prompt=dev_instruction,
                        timeout_seconds=self.config.browser_timeout_seconds,
                    )
                except Exception as exc:
                    logger.warning(f"Browser interaction for Claude development failed: {exc}. Attempting direct LLM fallback...")
                    try:
                        claude_output = await self.browser_manager.generate_direct_llm_fallback(
                            role=AgentRole.CLAUDE_DEVELOPER,
                            prompt=dev_instruction,
                        )
                    except Exception as fb_exc:
                        logger.error(f"Both browser and direct fallback failed for Claude: {fb_exc}")
                        return {
                            "status": "error",
                            "stage": self.state.current_stage.value,
                            "message": f"Claude development handoff failed: {exc} (Fallback failed: {fb_exc})",
                        }

                self.state.current_output = claude_output
                self.state.claude_approved = True
                self.state.transition_to(MultiAgentStage.DEVELOPMENT_COMPLETE)

                return {
                    "status": "development_started",
                    "stage": self.state.current_stage.value,
                    "project_name": self.state.project_name,
                    "active_agent": "Claude (Project Development Agent)",
                    "downloaded_spec": str(saved_spec_path),
                    "message": (
                        f"Development specification saved to: {saved_spec_path}.\n"
                        "Claude has received the approved development specification "
                        "and has commenced software implementation."
                    ),
                    "content": claude_output,
                }

            elif action == ReviewAction.REQUEST_CHANGES:
                if not feedback or not feedback.strip():
                    return {
                        "status": "error",
                        "message": "Feedback is required when requesting revisions.",
                    }

                rev_num = self.state.record_revision(
                    MultiAgentStage.CHATGPT_REVISION, feedback, self.state.current_output
                )
                self.state.transition_to(MultiAgentStage.CHATGPT_REVISION)

                rev_prompt = build_revision_prompt("ChatGPT", feedback)
                updated_spec = None
                try:
                    updated_spec = await self.browser_manager.send_prompt_and_receive(
                        role=AgentRole.CHATGPT_PROMPT_ENGINEER,
                        prompt=rev_prompt,
                        timeout_seconds=self.config.browser_timeout_seconds,
                    )
                except Exception as exc:
                    logger.warning(f"Browser revision failed for ChatGPT: {exc}. Attempting direct LLM fallback...")
                    try:
                        updated_spec = await self.browser_manager.generate_direct_llm_fallback(
                            role=AgentRole.CHATGPT_PROMPT_ENGINEER,
                            prompt=rev_prompt,
                        )
                    except Exception as fb_exc:
                        return {
                            "status": "error",
                            "stage": self.state.current_stage.value,
                            "message": f"ChatGPT revision failed: {exc} (Fallback failed: {fb_exc})",
                        }

                self.state.current_output = updated_spec
                self.state.transition_to(MultiAgentStage.CHATGPT_REVIEW_REQUIRED)

                return {
                    "status": "review_required",
                    "stage": self.state.current_stage.value,
                    "project_name": self.state.project_name,
                    "revision": rev_num,
                    "message": (
                        f"ChatGPT has revised the development specification based on your feedback (Revision {rev_num}). "
                        "AUDIT REQUIRED: Please review the updated specification below and Approve or Request Changes."
                    ),
                    "content": updated_spec,
                }

            elif action == ReviewAction.REJECT:
                return {
                    "status": "rejected",
                    "stage": self.state.current_stage.value,
                    "message": "Development specification was rejected by user. The workflow is paused.",
                }

        return {
            "status": "error",
            "message": (
                f"No review action is currently pending for stage '{self.state.current_stage.value}'."
            ),
        }

    def get_status(self) -> dict[str, Any]:
        """Returns the full workflow state, active agent, pending reviews, and artifacts."""
        if not self.state:
            return {
                "active_project": False,
                "message": "No active multi-agent project workflow.",
            }

        artifacts_summary = [
            {"filename": a.filename, "path": a.file_path, "approved": a.approved}
            for a in self.state.artifacts
        ]

        is_review_pending = self.state.current_stage in (
            MultiAgentStage.GEMINI_REVIEW_REQUIRED,
            MultiAgentStage.CHATGPT_REVIEW_REQUIRED,
        )

        return {
            "active_project": True,
            "project_name": self.state.project_name,
            "original_idea": self.state.original_idea,
            "current_stage": self.state.current_stage.value,
            "active_agent": self.state.active_agent.value if self.state.active_agent else None,
            "review_pending": is_review_pending,
            "gemini_approved": self.state.gemini_approved,
            "chatgpt_approved": self.state.chatgpt_approved,
            "claude_approved": self.state.claude_approved,
            "revision_count": len(self.state.revision_history),
            "artifacts": artifacts_summary,
            "last_feedback": self.state.last_feedback,
        }

    def download_artifact(self, artifact_type: str | None = None) -> dict[str, Any]:
        """
        Retrieves or saves an artifact from the current workflow.
        artifact_type: Optional specifier (e.g. 'readme', 'specification', or filename).
        """
        if not self.state:
            return {
                "status": "error",
                "message": "No active project workflow. Start a project first.",
            }

        results = []
        for artifact in self.state.artifacts:
            p = Path(artifact.file_path)
            results.append({
                "filename": artifact.filename,
                "path": str(p),
                "exists": p.exists(),
                "approved": artifact.approved,
                "stage": artifact.stage.value,
            })

        target = (artifact_type or "").lower().strip()
        if target:
            matched = [
                r for r in results
                if target in r["filename"].lower() or target in r["stage"].lower()
            ]
            if matched:
                return {
                    "status": "success",
                    "artifacts": matched,
                    "downloads_dir": str(self.browser_manager.downloads_dir),
                }
            # If not yet saved in artifacts list but current_output exists
            if self.state.current_output:
                fn = f"{self.state.project_name}_{target.upper()}.md"
                p = self.browser_manager.save_artifact(fn, self.state.current_output)
                return {
                    "status": "success",
                    "message": f"Saved current output as {fn}",
                    "artifacts": [{"filename": fn, "path": str(p), "exists": True}],
                    "downloads_dir": str(self.browser_manager.downloads_dir),
                }
            return {
                "status": "not_found",
                "message": f"No artifact matching '{artifact_type}' found.",
                "available_artifacts": results,
            }

        return {
            "status": "success",
            "artifacts": results,
            "downloads_dir": str(self.browser_manager.downloads_dir),
        }
