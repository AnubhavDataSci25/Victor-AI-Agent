"""
Coding Model Provider adapter layer for Victor 2.0.

Defines the CodingModelProvider interface and provides a production-grade
Groq implementation (defaulting to openai/gpt-oss-20b). Isolates inference
so alternative models/providers can be swapped without changing Victor's core.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.coding.models import (
    CodingFixPlan,
    CodingPlan,
    CompactProjectContext,
    FileAction,
    FileActionType,
)
from app.logging import get_logger

logger = get_logger("coding.provider")


def _clean_json_text(raw_text: str) -> str:
    """Extracts JSON substring if wrapped in markdown fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        # Match ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1).strip()
    return text


class CodingModelProvider(ABC):
    """Abstract interface for coding-specific inference models."""

    @abstractmethod
    async def plan_and_generate_code(
        self,
        task: str,
        context: CompactProjectContext,
        relevant_files: list[dict[str, str]] | None = None,
    ) -> CodingPlan:
        """Generate a structured plan with file modifications and execution command."""
        raise NotImplementedError

    @abstractmethod
    async def analyze_and_fix(
        self,
        task: str,
        context: CompactProjectContext,
        failed_command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        files_modified: list[FileAction],
    ) -> CodingFixPlan:
        """Analyze command failure / error output and generate corrective actions."""
        raise NotImplementedError


class GroqCodingModelProvider(CodingModelProvider):
    """
    Groq coding adapter using fast specialized inference (e.g. openai/gpt-oss-20b).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-20b",
        api_base: str = "https://api.groq.com/openai/v1",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            logger.warning("GroqCodingModelProvider initialized without an API key.")
        self.api_key = api_key
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    async def plan_and_generate_code(
        self,
        task: str,
        context: CompactProjectContext,
        relevant_files: list[dict[str, str]] | None = None,
    ) -> CodingPlan:
        """Ask Groq to reason through the task and output a structured CodingPlan."""
        system_prompt = (
            "You are Victor's specialized coding reasoning engine. "
            "Analyze the project structure and task, then produce a precise, deterministic coding plan.\n"
            "You must return ONLY a JSON object matching this schema:\n"
            "{\n"
            '  "task_summary": "Brief summary of what you are building/changing",\n'
            '  "actions": [\n'
            "    {\n"
            '      "path": "relative/path/to/file.py",\n'
            '      "action_type": "create_file" | "modify_file" | "create_directory",\n'
            '      "content": "Full source code for the file (for create_file or modify_file)",\n'
            '      "reason": "Why this file was created/modified"\n'
            "    }\n"
            "  ],\n"
            '  "run_command": "Command to run in project root to verify or test the change (e.g. python hello.py, pytest), or null",\n'
            '  "expected_outcome": "Expected terminal output or behavior",\n'
            '  "notes": "Any important notes or caveats"\n'
            "}\n\n"
            "RULES:\n"
            "1. Output valid JSON only. No markdown conversational commentary outside the JSON.\n"
            "2. Ensure all file paths are relative to the project root (e.g. 'hello.py', 'app/routes/predict.py').\n"
            "3. Write complete, high-quality, production-ready code in 'content'. Do not use placeholders or 'rest of code here'.\n"
            "4. Choose safe, targeted verification commands (e.g. 'python hello.py' or 'pytest tests/test_feature.py')."
        )

        files_context = relevant_files or context.relevant_files
        user_prompt_parts = [
            f"PROJECT: {context.project_name}",
            f"TYPE: {context.metadata.project_type.value} (Language: {context.metadata.language}, Framework: {context.metadata.framework or 'None'})",
            f"PACKAGE MANAGER: {context.metadata.package_manager or 'default'}",
            "\nDIRECTORY SKELETON:\n" + context.skeleton_tree,
        ]

        if context.key_file_summaries:
            user_prompt_parts.append("\nKEY CONFIGURATIONS:")
            for cfg_name, cfg_preview in context.key_file_summaries.items():
                user_prompt_parts.append(f"--- {cfg_name} ---\n{cfg_preview}")

        if files_context:
            user_prompt_parts.append("\nRELEVANT SOURCE CODE:")
            for item in files_context:
                user_prompt_parts.append(f"--- {item.get('path')} ---\n{item.get('content')}")

        user_prompt_parts.append(f"\nTASK:\n{task}")
        user_prompt = "\n".join(user_prompt_parts)

        data = await self._send_request(system_prompt, user_prompt)
        try:
            return CodingPlan.model_validate(data)
        except Exception as exc:
            logger.error(f"Failed to parse CodingPlan from Groq response: {exc}. Raw: {data}")
            # Construct a safe fallback plan from partial fields
            return CodingPlan(
                task_summary=data.get("task_summary", task),
                actions=[
                    FileAction(
                        path=a.get("path", "script.py"),
                        action_type=FileActionType(a.get("action_type", "create_file")),
                        content=a.get("content", ""),
                        reason=a.get("reason", ""),
                    )
                    for a in data.get("actions", [])
                ],
                run_command=data.get("run_command"),
                expected_outcome=data.get("expected_outcome", ""),
                notes=data.get("notes", ""),
            )

    async def analyze_and_fix(
        self,
        task: str,
        context: CompactProjectContext,
        failed_command: str,
        stdout: str,
        stderr: str,
        exit_code: int,
        files_modified: list[FileAction],
    ) -> CodingFixPlan:
        """Analyze terminal error output and produce targeted corrective FileActions."""
        system_prompt = (
            "You are Victor's specialized code debugging and error analysis engine. "
            "A verification command failed during execution. Analyze the error output, "
            "determine the root cause, and provide a targeted fix.\n"
            "Return ONLY a JSON object matching this schema:\n"
            "{\n"
            '  "error_analysis": "Concise root cause explanation",\n'
            '  "fix_summary": "What changes are being made to fix it",\n'
            '  "actions": [\n'
            "    {\n"
            '      "path": "relative/path/to/file.py",\n'
            '      "action_type": "modify_file" | "create_file",\n'
            '      "content": "Complete corrected file content",\n'
            '      "reason": "Why this fix resolves the error"\n'
            "    }\n"
            "  ],\n"
            '  "run_command": "Command to re-run the verification"\n'
            "}\n\n"
            "RULES:\n"
            "1. Output valid JSON only.\n"
            "2. Provide full corrected file content for any modified file.\n"
            "3. Do not invent new dependencies unless strictly needed."
        )

        user_prompt_parts = [
            f"ORIGINAL TASK: {task}",
            f"PROJECT: {context.project_name} ({context.metadata.language})",
            f"FAILED COMMAND: {failed_command}",
            f"EXIT CODE: {exit_code}",
            f"STDOUT:\n{stdout[:2000] if stdout else '(empty)'}",
            f"STDERR:\n{stderr[:2000] if stderr else '(empty)'}",
            "\nRECENTLY MODIFIED FILES:",
        ]
        for f in files_modified:
            user_prompt_parts.append(f"--- {f.path} ({f.action_type}) ---\n{f.content[:2000]}")

        user_prompt = "\n".join(user_prompt_parts)
        data = await self._send_request(system_prompt, user_prompt)
        try:
            return CodingFixPlan.model_validate(data)
        except Exception as exc:
            logger.error(f"Failed to parse CodingFixPlan: {exc}")
            return CodingFixPlan(
                error_analysis=data.get("error_analysis", "Execution failed."),
                fix_summary=data.get("fix_summary", "Applying corrections."),
                actions=[
                    FileAction(
                        path=a.get("path", "script.py"),
                        action_type=FileActionType(a.get("action_type", "modify_file")),
                        content=a.get("content", ""),
                        reason=a.get("reason", ""),
                    )
                    for a in data.get("actions", [])
                ],
                run_command=data.get("run_command", failed_command),
            )

    async def _send_request(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.error(f"Groq API error {resp.status_code}: {resp.text}")
                resp.raise_for_status()

            body = resp.json()
            raw_content = body["choices"][0]["message"]["content"]
            clean_text = _clean_json_text(raw_content)
            return json.loads(clean_text)
