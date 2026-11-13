"""
Victor Autonomous Email Assistant — BaseTool Registrations.

All tools execute through Victor's Central Tool Gateway, PermissionEngine,
and ResultVerifier.
"""

from __future__ import annotations

from typing import Any, Optional

from app.email_assistant.manager import EmailAssistantManager
from app.email_assistant.models import ScheduledEmailStatus
from app.tools.base import BaseTool
from app.tools.permissions import PermissionLevel

_GLOBAL_EMAIL_MANAGER: Optional[EmailAssistantManager] = None


def get_email_assistant_manager() -> EmailAssistantManager:
    global _GLOBAL_EMAIL_MANAGER
    if _GLOBAL_EMAIL_MANAGER is None:
        _GLOBAL_EMAIL_MANAGER = EmailAssistantManager()
    return _GLOBAL_EMAIL_MANAGER


class GmailConnectTool(BaseTool):
    name = "gmail_connect"
    description = (
        "Manages official Gmail OAuth 2.0 connection: check connection status, "
        "authorize Gmail in the browser, or disconnect/revoke credentials."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "connect", "disconnect"],
                "description": "Action to perform (default: 'status').",
            }
        },
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    def _mgr(self) -> EmailAssistantManager:
        return self.manager or get_email_assistant_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        action = (args.get("action") or "status").lower()
        mgr = self._mgr()
        try:
            if action == "connect":
                res = await mgr.provider.oauth.authorize_interactive(timeout_seconds=180.0)  # type: ignore[attr-defined]
                return f"Sir, Gmail is now connected for {res.get('account_email')}."
            elif action == "disconnect":
                await mgr.provider.disconnect()
                return "Sir, Gmail has been disconnected and local credentials have been wiped."
            else:
                st = await mgr.provider.get_status()
                if st.get("connected"):
                    return f"Gmail is connected as {st.get('account_email')} (Scopes: {', '.join(st.get('scopes', []))})."
                if not st.get("client_configured"):
                    return (
                        "Gmail is not connected yet, and OAuth client credentials are not configured. "
                        "Please set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env or add config/gmail_oauth_client.json."
                    )
                return "Gmail is not connected yet. Ask me to connect Gmail to start OAuth 2.0 authorization."
        except Exception as e:
            return f"Error: {e}"


class EmailComposeDraftTool(BaseTool):
    name = "email_compose_draft"
    description = (
        "Composes a complete email draft from natural-language instructions (professional, academic, "
        "internship, job_application, interview, follow_up, business, casual), resolves contacts, "
        "validates attachments, and returns a full preview for user approval. NEVER sends automatically."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "instruction": {"type": "string", "description": "What the email should say and its purpose."},
            "to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email(s) or contact name(s)."},
            "cc": {"type": "array", "items": {"type": "string"}, "description": "Optional CC recipient(s)."},
            "bcc": {"type": "array", "items": {"type": "string"}, "description": "Optional BCC recipient(s)."},
            "tone": {"type": "string", "description": "Tone/style (e.g. professional, academic, internship, polite, casual)."},
            "attachment_paths": {"type": "array", "items": {"type": "string"}, "description": "User-selected local file paths to attach."},
        },
        "required": ["instruction"],
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.compose_draft(
                instruction=args.get("instruction", ""),
                to=args.get("to"),
                cc=args.get("cc"),
                bcc=args.get("bcc"),
                tone=args.get("tone") or "professional",
                attachment_paths=args.get("attachment_paths"),
            )
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailEditDraftTool(BaseTool):
    name = "email_edit_draft"
    description = (
        "Edits the current or specified email draft (e.g., 'Make it more professional', 'Shorten it', "
        "'Change subject', 'Add CC', 'Save as draft', or 'Discard draft'). Invalidates prior approval."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "edit_instruction": {"type": "string", "description": "How to revise the email body/tone."},
            "draft_id": {"type": "string", "description": "Optional draft ID (defaults to latest active draft)."},
            "to": {"type": "array", "items": {"type": "string"}, "description": "Updated To recipients."},
            "cc": {"type": "array", "items": {"type": "string"}, "description": "Updated CC recipients."},
            "bcc": {"type": "array", "items": {"type": "string"}, "description": "Updated BCC recipients."},
            "subject": {"type": "string", "description": "New explicit subject line."},
            "attachment_paths": {"type": "array", "items": {"type": "string"}, "description": "Updated attachment file paths."},
            "save_to_gmail": {"type": "boolean", "description": "If true, saves/updates the draft in Gmail Drafts."},
            "discard": {"type": "boolean", "description": "If true, discards the draft."},
        },
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.edit_draft(
                edit_instruction=args.get("edit_instruction", ""),
                draft_id=args.get("draft_id"),
                to=args.get("to"),
                cc=args.get("cc"),
                bcc=args.get("bcc"),
                subject=args.get("subject"),
                attachment_paths=args.get("attachment_paths"),
                save_to_gmail=bool(args.get("save_to_gmail", False)),
                discard=bool(args.get("discard", False)),
            )
            if not res.get("success"):
                return f"Error: {res.get('message')}"
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailPreviewDraftTool(BaseTool):
    name = "email_preview_draft"
    description = "Shows the complete preview (To, CC, BCC, Subject, Attachments, Body) of the active email draft."
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string", "description": "Optional draft ID."},
        },
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        did = args.get("draft_id")
        draft = mgr.store.get_draft(did) if did else mgr.store.get_latest_active_draft()
        if not draft:
            return "No active email draft found."
        return mgr.format_draft_preview(draft)


class EmailSendApprovedTool(BaseTool):
    name = "email_send_approved"
    description = (
        "Sends the previewed email draft via Gmail API ONLY after explicit user confirmation "
        "(user_confirmed=true). Never call without explicit user approval."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string", "description": "Optional draft ID (defaults to latest active draft)."},
            "user_confirmed": {"type": "boolean", "description": "Must be true only after explicit user approval."},
            "purpose": {"type": "string", "description": "Email purpose tag (e.g. general, follow_up)."},
        },
        "required": ["user_confirmed"],
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.approve_and_send(
                draft_id=args.get("draft_id"),
                user_confirmed=bool(args.get("user_confirmed", False)),
                purpose=args.get("purpose") or "general",
            )
            if not res.get("success"):
                return f"Error: {res.get('message')}"
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailScheduleSendTool(BaseTool):
    name = "email_schedule_send"
    description = (
        "Schedules an approved email draft for future delivery at a specific date/time, "
        "and optionally creates a persistent follow-up reminder."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "send_at": {"type": "string", "description": "Natural-language or ISO date/time (e.g. 'tomorrow at 9:00 AM')."},
            "draft_id": {"type": "string", "description": "Optional draft ID."},
            "user_confirmed": {"type": "boolean", "description": "Must be true only after explicit user approval."},
            "follow_up_after": {"type": "string", "description": "Optional follow-up reminder time (e.g. 'in 3 days at 10 AM')."},
            "follow_up_note": {"type": "string", "description": "Optional note for the follow-up reminder."},
        },
        "required": ["send_at", "user_confirmed"],
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.schedule_email(
                send_at_text=args.get("send_at", ""),
                draft_id=args.get("draft_id"),
                user_confirmed=bool(args.get("user_confirmed", False)),
                follow_up_after_text=args.get("follow_up_after"),
                follow_up_note=args.get("follow_up_note"),
            )
            if not res.get("success"):
                return f"Error: {res.get('message')}"
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailManageScheduledTool(BaseTool):
    name = "email_manage_scheduled"
    description = "Lists or cancels pending scheduled emails."
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "cancel"], "description": "Action to perform."},
            "schedule_id": {"type": "string", "description": "Schedule ID to cancel when action='cancel'."},
        },
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        action = (args.get("action") or "list").lower()
        if action == "cancel":
            sid = (args.get("schedule_id") or "").strip()
            rec = mgr.store.get_scheduled_email(sid)
            if not rec:
                return f"Error: Scheduled email '{sid}' not found."
            rec.status = ScheduledEmailStatus.CANCELLED
            mgr.store.save_scheduled_email(rec)
            return f"Sir, scheduled email '{rec.subject}' ({sid}) has been cancelled."

        items = mgr.store.list_scheduled_emails(ScheduledEmailStatus.PENDING)
        if not items:
            return "You have no pending scheduled emails."
        from datetime import datetime
        lines = [f"Pending scheduled emails ({len(items)}):"]
        for it in items:
            dt = datetime.fromtimestamp(it.send_at).strftime("%Y-%m-%d %I:%M %p")
            lines.append(f"- [{it.schedule_id}] To: {', '.join(it.to)} | Subject: {it.subject} | Send at: {dt}")
        return "\n".join(lines)


class EmailInboxSearchTool(BaseTool):
    name = "email_inbox_search"
    description = (
        "Searches or lists emails from Gmail using the official Gmail API "
        "(e.g. 'Check my latest emails', 'Find email from HR', 'Show unread emails')."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query (e.g. 'from:hr', 'interview', or empty for latest)."},
            "max_results": {"type": "integer", "description": "Max emails to return (default: 8)."},
            "unread_only": {"type": "boolean", "description": "If true, only retrieve unread emails."},
        },
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.search_inbox(
                query=args.get("query", ""),
                max_results=int(args.get("max_results", 8) or 8),
                unread_only=bool(args.get("unread_only", False)),
            )
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailReadMessageTool(BaseTool):
    name = "email_read_message"
    description = "Reads the full content of a specific Gmail message by message_id."
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message ID."},
        },
        "required": ["message_id"],
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.read_message(args.get("message_id", ""))
            if not res.get("success"):
                return f"Error: {res.get('message')}"
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailSummarizeInboxTool(BaseTool):
    name = "email_summarize_inbox"
    description = "Summarizes important, unread, or query-matching Gmail messages concisely."
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Optional Gmail filter query (e.g. 'newer_than:1d')."},
            "unread_only": {"type": "boolean", "description": "Summarize unread emails only."},
            "max_results": {"type": "integer", "description": "Max emails to include (default: 8)."},
        },
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.summarize_inbox(
                query=args.get("query", ""),
                max_results=int(args.get("max_results", 8) or 8),
                unread_only=bool(args.get("unread_only", False)),
            )
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailDraftReplyTool(BaseTool):
    name = "email_draft_reply"
    description = (
        "Drafts a context-aware reply to a specific Gmail message while preserving conversation "
        "threading (threadId, In-Reply-To, References). Returns preview and requires approval before sending."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "message_id": {"type": "string", "description": "Gmail message ID to reply to."},
            "instruction": {"type": "string", "description": "What to say in the reply (e.g. 'Accept the interview')."},
            "attachment_paths": {"type": "array", "items": {"type": "string"}, "description": "Optional attachments."},
        },
        "required": ["message_id", "instruction"],
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        try:
            res = await mgr.draft_reply(
                message_id=args.get("message_id", ""),
                instruction=args.get("instruction", ""),
                attachment_paths=args.get("attachment_paths"),
            )
            if not res.get("success"):
                return f"Error: {res.get('message')}"
            return res["message"]
        except Exception as e:
            return f"Error: {e}"


class EmailAutoSendPolicyTool(BaseTool):
    name = "email_auto_send_policy"
    description = (
        "Views or configures Victor's restricted auto-send policy (disabled by default; "
        "requires explicit recipient allowlist, purpose allowlist, and daily cap)."
    )
    permission_level = PermissionLevel.SAFE
    timeout_seconds: float = 180.0
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "enable", "disable"], "description": "Policy action."},
            "allowed_recipients": {"type": "array", "items": {"type": "string"}, "description": "Trusted recipient emails."},
            "allowed_purposes": {"type": "array", "items": {"type": "string"}, "description": "Allowed purpose tags."},
            "max_per_day": {"type": "integer", "description": "Max auto-sends per day (default: 5)."},
        },
    }

    def __init__(self, manager: EmailAssistantManager | None = None) -> None:
        self.manager = manager

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self.manager or get_email_assistant_manager()
        action = (args.get("action") or "status").lower()
        policy = mgr.store.get_auto_send_policy()
        if action == "disable":
            policy.enabled = False
            mgr.store.save_auto_send_policy(policy)
            return "Restricted email auto-send is now DISABLED."
        if action == "enable":
            if args.get("allowed_recipients") is not None:
                policy.allowed_recipients = list(args["allowed_recipients"])
            if args.get("allowed_purposes") is not None:
                policy.allowed_purposes = list(args["allowed_purposes"])
            if args.get("max_per_day") is not None:
                policy.max_per_day = max(1, min(int(args["max_per_day"]), 20))
            if not policy.allowed_recipients:
                return "Error: Cannot enable restricted auto-send without at least one explicit allowed_recipient."
            policy.enabled = True
            mgr.store.save_auto_send_policy(policy)
            return f"Restricted auto-send ENABLED for {policy.allowed_recipients} (max {policy.max_per_day}/day)."

        return (
            f"Auto-send policy: enabled={policy.enabled}, allowed_recipients={policy.allowed_recipients}, "
            f"allowed_purposes={policy.allowed_purposes}, max_per_day={policy.max_per_day}, sent_today={policy.sent_today}."
        )
