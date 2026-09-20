"""
Victor 2.0 BaseTool implementations for Multi-Agent Planning & Execution.

Orchestrates Gemini (Research & README), ChatGPT (Prompt Engineering & Specification),
and Claude (Software Development) with strict human approval checkpoints,
artifact isolation in Downloads, and dedicated browser tabs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.multi_agent.orchestrator import MultiAgentOrchestrator
from app.tools.base import BaseTool

logger = get_logger("tools.multi_agent")

_multi_agent_orchestrator: MultiAgentOrchestrator | None = None


def get_multi_agent_orchestrator() -> MultiAgentOrchestrator:
    """Returns or lazily instantiates the module-level orchestrator singleton."""
    global _multi_agent_orchestrator
    if _multi_agent_orchestrator is None:
        _multi_agent_orchestrator = MultiAgentOrchestrator()
    return _multi_agent_orchestrator


def set_multi_agent_orchestrator(orchestrator: MultiAgentOrchestrator | None) -> None:
    """Injects or resets the orchestrator instance (primarily for testing)."""
    global _multi_agent_orchestrator
    _multi_agent_orchestrator = orchestrator


class MultiAgentStartProjectTool(BaseTool):
    """
    Initiates multi-agent planning workflow for a user project idea.
    Prompts Gemini in a dedicated browser tab to produce an A-to-Z research README.
    Halt at GEMINI_REVIEW_REQUIRED for mandatory user review.
    """

    name = "multi_agent_start_project"
    description = (
        "Initiates a Multi-Agent Project Planning workflow across Gemini, ChatGPT, and Claude. "
        "Opens a dedicated Gemini browser tab and sends a comprehensive A-to-Z research prompt "
        "to generate the initial project planning README artifact (<PROJECT_NAME>_IDEA_README.md). "
        "Strictly halts at human audit checkpoint GEMINI_REVIEW_REQUIRED for your review and explicit approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "idea": {
                "type": "string",
                "description": "The user's project idea, concept, problem statement, or requirements.",
            },
            "project_name": {
                "type": "string",
                "description": "Optional concise name for the project (e.g. CareerLens, VictorAI). If omitted, derived from idea.",
            },
        },
        "required": ["idea"],
    }

    async def execute(self, args: dict) -> str:
        idea = args.get("idea", "").strip()
        project_name = args.get("project_name")

        if not idea:
            return "Error: Project idea cannot be empty."

        orchestrator = get_multi_agent_orchestrator()
        result = await orchestrator.start_project(idea=idea, project_name=project_name)

        if result.get("status") == "error":
            return f"Multi-Agent project initiation failed: {result.get('message', 'Unknown error')}"

        stage = result.get("stage", "GEMINI_REVIEW_REQUIRED")
        pname = result.get("project_name", "PROJECT")
        artifact_name = result.get("artifact_name", f"{pname}_IDEA_README.md")
        content = result.get("content", "")

        return (
            f"=== MULTI-AGENT WORKFLOW: STAGE 1 (RESEARCH COMPLETE) ===\n"
            f"Project: {pname}\n"
            f"Current Stage: {stage}\n"
            f"Active Agent: {result.get('active_agent', 'Gemini')}\n"
            f"Artifact: {artifact_name}\n\n"
            f"AUDIT CHECKPOINT: Victor has paused execution. Automatic handoff to ChatGPT is strictly blocked.\n"
            f"Please review the generated README below:\n"
            f"--------------------------------------------------\n"
            f"{content}\n"
            f"--------------------------------------------------\n"
            f"NEXT STEPS: Provide your review decision via 'multi_agent_review_artifact':\n"
            f"- action='approve' -> Downloads README to your Downloads folder and advances to ChatGPT\n"
            f"- action='request_changes', feedback='...' -> Re-prompts Gemini in the same tab with your revisions\n"
            f"- action='reject' -> Halts the planning workflow"
        )


class MultiAgentReviewTool(BaseTool):
    """
    Submits human audit decision for current checkpoint.
    Gates progression between Gemini, ChatGPT, and Claude.
    """

    name = "multi_agent_review_artifact"
    description = (
        "Submit a human-in-the-loop review decision for the current multi-agent workflow checkpoint. "
        "Supported actions:\n"
        "- 'approve': Confirms approval, downloads artifact to Downloads folder, and advances to the next AI agent in a new dedicated tab.\n"
        "- 'request_changes': Keeps the session with the active agent and re-prompts for revisions using provided feedback.\n"
        "- 'reject': Halts the workflow without advancing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["approve", "reject", "request_changes"],
                "description": "Your decision: 'approve', 'reject', or 'request_changes'.",
            },
            "feedback": {
                "type": "string",
                "description": "Required when action is 'request_changes'. Specific instructions or corrections for the agent.",
            },
        },
        "required": ["action"],
    }

    async def execute(self, args: dict) -> str:
        action = args.get("action", "").strip().lower()
        feedback = args.get("feedback", "").strip()

        if not action:
            return "Error: Review action ('approve', 'reject', or 'request_changes') is required."

        orchestrator = get_multi_agent_orchestrator()
        result = await orchestrator.review_artifact(action=action, feedback=feedback)

        status = result.get("status")
        if status == "error":
            return f"Review action failed: {result.get('message')}"

        if status == "rejected":
            return f"Workflow halted: {result.get('message')}"

        stage = result.get("stage")
        pname = result.get("project_name", "")
        content = result.get("content", "")

        # If we reached review_required after revision or ChatGPT prompt engineering
        if status == "review_required":
            active_agent = result.get("active_agent", "Active Agent")
            artifact_name = result.get("artifact_name", "artifact")
            rev = result.get("revision")
            rev_str = f" (Revision {rev})" if rev else ""
            return (
                f"=== MULTI-AGENT WORKFLOW: AUDIT CHECKPOINT{rev_str} ===\n"
                f"Project: {pname}\n"
                f"Current Stage: {stage}\n"
                f"Active Agent: {active_agent}\n"
                f"Artifact: {artifact_name}\n"
                f"Status: {result.get('message')}\n\n"
                f"--------------------------------------------------\n"
                f"{content}\n"
                f"--------------------------------------------------\n"
                f"AUDIT REQUIRED: Use 'multi_agent_review_artifact' with approve, request_changes, or reject."
            )

        # If we transitioned into development
        if status == "development_started":
            return (
                f"=== MULTI-AGENT WORKFLOW: DEVELOPMENT INITIATED ===\n"
                f"Project: {pname}\n"
                f"Stage: {stage}\n"
                f"Active Agent: {result.get('active_agent', 'Claude')}\n"
                f"Approved Specification: {result.get('downloaded_spec')}\n\n"
                f"Status: {result.get('message')}\n"
                f"--------------------------------------------------\n"
                f"{content}\n"
                f"--------------------------------------------------"
            )

        return json.dumps(result, indent=2)


class MultiAgentGetStatusTool(BaseTool):
    """
    Returns the comprehensive state of the multi-agent workflow.
    """

    name = "multi_agent_get_status"
    description = (
        "Retrieves the active state of the Multi-Agent Planning & Execution workflow, "
        "including the current stage, active AI agent (Gemini, ChatGPT, or Claude), "
        "human audit status, approvals, revisions, and downloaded artifacts."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, args: dict) -> str:
        orchestrator = get_multi_agent_orchestrator()
        status = orchestrator.get_status()

        if not status.get("active_project"):
            return "No active multi-agent project workflow currently running."

        artifacts_list = status.get("artifacts", [])
        artifacts_str = (
            "\n".join([f"  - {a.get('filename')} -> {a.get('path')} (Approved: {a.get('approved')})" for a in artifacts_list])
            if artifacts_list
            else "  None yet"
        )

        return (
            f"=== MULTI-AGENT WORKFLOW STATUS ===\n"
            f"Project: {status.get('project_name')}\n"
            f"Current Stage: {status.get('current_stage')}\n"
            f"Active Agent: {status.get('active_agent') or 'None'}\n"
            f"Human Review Pending: {status.get('review_pending')}\n"
            f"Gemini Approved: {status.get('gemini_approved')}\n"
            f"ChatGPT Approved: {status.get('chatgpt_approved')}\n"
            f"Claude Approved: {status.get('claude_approved')}\n"
            f"Revisions Completed: {status.get('revision_count', 0)}\n"
            f"Artifacts:\n{artifacts_str}\n"
            f"Original Idea: {status.get('original_idea')}"
        )


class MultiAgentDownloadArtifactTool(BaseTool):
    """
    Retrieves or downloads project artifacts from Downloads folder.
    """

    name = "multi_agent_download_artifact"
    description = (
        "Retrieve or verify the local path of generated project artifacts "
        "(<PROJECT_NAME>_IDEA_README.md, <PROJECT_NAME>_DEVELOPMENT_SPECIFICATION.md) "
        "stored in the Windows Downloads directory."
    )
    parameters = {
        "type": "object",
        "properties": {
            "artifact_type": {
                "type": "string",
                "description": "Optional artifact filter: 'readme', 'specification', or exact filename. If omitted, lists all artifacts.",
            }
        },
    }

    async def execute(self, args: dict) -> str:
        artifact_type = args.get("artifact_type")
        orchestrator = get_multi_agent_orchestrator()
        result = orchestrator.download_artifact(artifact_type)

        if result.get("status") == "error":
            return f"Error retrieving artifacts: {result.get('message')}"

        if result.get("status") == "not_found":
            return f"Artifact not found: {result.get('message')}"

        artifacts = result.get("artifacts", [])
        if not artifacts:
            return "No artifacts have been generated or saved for this project yet."

        lines = [
            f"Downloads Directory: {result.get('downloads_dir')}",
            "Artifacts Found:",
        ]
        for a in artifacts:
            lines.append(f"- Filename: {a.get('filename')}")
            lines.append(f"  Local Path: {a.get('path')}")
            lines.append(f"  File Exists on Disk: {a.get('exists')}")
            if "approved" in a:
                lines.append(f"  Approved: {a.get('approved')}")

        return "\n".join(lines)
