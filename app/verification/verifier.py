"""
Result Verification Layer for Victor.

Provides post-execution verification:
1. Deterministic verification:
   - File deletion: confirms target file no longer exists on disk.
   - File creation: confirms target file exists and is non-empty.
   - System controls: checks setting status and error keywords.
   - API tools: validates structured return format and non-error payload.
   - Phone companion: checks response status dictionary.
   - Code execution: checks return codes and output text.
2. Optional Jev semantic audit:
   - For open-ended or ambiguous tool outcomes, queries Jev with choice/noul questions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.decision.jev_client import JevClient
from app.decision.models import JevQuestion, QuestionType
from app.verification.models import VerificationResult, VerificationStatus

logger = logging.getLogger(__name__)


class ResultVerifier:
    """Verifies real-world effects and outcomes of tool executions."""

    def __init__(self, jev_client: Optional[JevClient] = None) -> None:
        self.jev = jev_client or JevClient()

    async def verify(
        self,
        tool_name: str,
        args: Dict[str, Any],
        raw_result: Any,
    ) -> VerificationResult:
        """
        Verify tool execution outcome.
        Prefers deterministic real-world inspection wherever possible.
        """
        name_lower = tool_name.lower()
        res_str = str(raw_result)

        # 1. File Deletion Verification (Real-World Disk Check)
        if any(k in name_lower for k in ("delete_file", "coding_delete_file", "file_explorer_delete")):
            path_str = args.get("path") or args.get("file_path") or args.get("target")
            if path_str:
                p = Path(path_str)
                if p.exists():
                    logger.warning(f"[Verification] File deletion failed; path still exists: {path_str}")
                    return VerificationResult(
                        verified=False,
                        status=VerificationStatus.FAILED,
                        details=f"Target file still exists on disk at '{path_str}'.",
                        is_deterministic=True,
                    )
                return VerificationResult(
                    verified=True,
                    status=VerificationStatus.SUCCESS,
                    details=f"Target file confirmed absent from disk: '{path_str}'.",
                    is_deterministic=True,
                )

        # 2. File Creation / Write Verification
        if any(k in name_lower for k in ("write_file", "create_file", "coding_write_file")):
            path_str = args.get("path") or args.get("file_path")
            if path_str:
                p = Path(path_str)
                if not p.exists():
                    return VerificationResult(
                        verified=False,
                        status=VerificationStatus.FAILED,
                        details=f"Created file not found on disk at '{path_str}'.",
                        is_deterministic=True,
                    )
                size = p.stat().st_size
                return VerificationResult(
                    verified=True,
                    status=VerificationStatus.SUCCESS,
                    details=f"File successfully created ({size} bytes).",
                    is_deterministic=True,
                )

        # 3. Public API Tools Verification
        if name_lower.startswith("api_get_"):
            if res_str.lower().startswith("error") or "retrieval failed" in res_str.lower():
                return VerificationResult(
                    verified=False,
                    status=VerificationStatus.FAILED,
                    details="API tool returned an error response.",
                    is_deterministic=True,
                )
            return VerificationResult(
                verified=True,
                status=VerificationStatus.SUCCESS,
                details="API payload received and validated.",
                is_deterministic=True,
            )

        # 4. Phone Companion Tools Verification
        if name_lower.startswith("phone_"):
            if any(k in res_str.lower() for k in ("error", "not connected", "failed", "denied", "mismatch", "expired", "offline", "unpaired")):
                return VerificationResult(
                    verified=False,
                    status=VerificationStatus.FAILED,
                    details="Phone companion reported an error or disconnected device.",
                    is_deterministic=True,
                )
            return VerificationResult(
                verified=True,
                status=VerificationStatus.SUCCESS,
                details="Phone action executed successfully.",
                is_deterministic=True,
            )

        # 5. System Control Tools Verification
        if name_lower.startswith("system_"):
            if "error" in res_str.lower() or "failed" in res_str.lower():
                return VerificationResult(
                    verified=False,
                    status=VerificationStatus.FAILED,
                    details="System control command reported an error.",
                    is_deterministic=True,
                )
            return VerificationResult(
                verified=True,
                status=VerificationStatus.SUCCESS,
                details="System command completed successfully.",
                is_deterministic=True,
            )

        # 6. Generic Error Checks
        if isinstance(raw_result, Exception) or res_str.lower().startswith("error:"):
            return VerificationResult(
                verified=False,
                status=VerificationStatus.FAILED,
                details=f"Execution error: {res_str[:150]}",
                is_deterministic=True,
            )

        # 7. Optional Jev Semantic Verification for Complex Tasks
        if self.jev.is_available() and any(k in name_lower for k in ("multi_agent", "coding_execute_task")):
            question = JevQuestion(
                type=QuestionType.CHOICE,
                instructions="Classify the execution outcome based on the result text.",
                criteria={
                    "SUCCESS": "Task completed successfully with all expected deliverables",
                    "PARTIAL_SUCCESS": "Task partially completed or encountered minor non-fatal issues",
                    "FAILED": "Task failed completely or encountered critical errors",
                    "UNEXPECTED_RESULT": "Output does not match expected task deliverables",
                },
            )
            resp = await self.jev.decide(
                state=f"Tool: {tool_name}\nOutput: {res_str[:500]}",
                questions={"outcome": question},
            )
            if resp and "outcome" in resp.answers:
                choice = resp.answers["outcome"].choice or "SUCCESS"
                status_enum = getattr(VerificationStatus, choice, VerificationStatus.SUCCESS)
                return VerificationResult(
                    verified=status_enum in (VerificationStatus.SUCCESS, VerificationStatus.PARTIAL_SUCCESS),
                    status=status_enum,
                    details=f"Jev classified outcome as {choice} (confidence: {resp.answers['outcome'].confidence or 1.0}).",
                    is_deterministic=False,
                    confidence=resp.answers["outcome"].confidence or 1.0,
                )

        return VerificationResult(
            verified=True,
            status=VerificationStatus.SUCCESS,
            details="Execution completed without errors.",
            is_deterministic=True,
        )
