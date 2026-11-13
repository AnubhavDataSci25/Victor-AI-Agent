"""
Victor Autonomous Email Assistant — Workflow & Security Manager.

Orchestrates:
USER REQUEST -> INTENT EXTRACTION -> CONTEXT RETRIEVAL -> RECIPIENT RESOLUTION ->
DRAFT GENERATION -> VALIDATION -> PREVIEW -> USER APPROVAL -> GMAIL API EXECUTION ->
SEND VERIFICATION -> RESULT REPORT.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import email.utils
import logging
import re
import time
from typing import Any, Optional

from app.email_assistant.attachments import validate_attachment
from app.email_assistant.composer import EmailComposer
from app.email_assistant.gmail_provider import GmailProvider, wrap_untrusted_email
from app.email_assistant.models import (
    AutoSendPolicy,
    EmailAttachment,
    EmailDraft,
    EmailMessageSummary,
    ScheduledEmailRecord,
    ScheduledEmailStatus,
)
from app.email_assistant.provider import EmailProvider
from app.email_assistant.store import EmailAssistantStore

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_email(addr: str) -> bool:
    return bool(_EMAIL_RE.match((addr or "").strip()))


class EmailAssistantManager:
    """Central coordinator for Victor's Autonomous Email Assistant."""

    def __init__(
        self,
        provider: Optional[EmailProvider] = None,
        composer: Optional[EmailComposer] = None,
        store: Optional[EmailAssistantStore] = None,
    ) -> None:
        self.provider: EmailProvider = provider or GmailProvider()
        self.composer: EmailComposer = composer or EmailComposer()
        self.store: EmailAssistantStore = store or EmailAssistantStore()
        self._send_lock = asyncio.Lock()

    async def resolve_recipients(self, raw_list: list[str] | str | None) -> tuple[list[str], list[str], list[str]]:
        """
        Resolve a list of emails or contact names.
        Returns: (resolved_emails, ambiguous_messages, unresolved_queries)
        """
        if not raw_list:
            return [], [], []
        items = [raw_list] if isinstance(raw_list, str) else list(raw_list)
        resolved: list[str] = []
        ambiguous: list[str] = []
        unresolved: list[str] = []

        for item in items:
            s = (item or "").strip()
            if not s:
                continue
            if is_valid_email(s):
                resolved.append(s)
                continue

            if not await self.provider.is_connected():
                unresolved.append(f"{s} (Gmail not connected to search contacts)")
                continue

            matches = await self.provider.search_contacts(s, limit=5)
            if not matches:
                unresolved.append(s)
            elif len(matches) == 1:
                resolved.append(matches[0].email)
            else:
                opts = "; ".join(f"{m.name} <{m.email}>" for m in matches)
                ambiguous.append(f"Multiple contacts match '{s}': {opts}")

        return resolved, ambiguous, unresolved

    def format_draft_preview(self, draft: EmailDraft) -> str:
        to_str = ", ".join(draft.to) if draft.to else "(missing — please specify recipient)"
        cc_str = ", ".join(draft.cc) if draft.cc else "None"
        bcc_str = ", ".join(draft.bcc) if draft.bcc else "None"
        att_str = (
            ", ".join(f"{a.filename} ({a.size_bytes // 1024} KB)" for a in draft.attachments)
            if draft.attachments
            else "None"
        )
        return (
            f"Draft ID: {draft.draft_id}\n"
            f"To: {to_str}\n"
            f"CC: {cc_str} | BCC: {bcc_str}\n"
            f"Subject: {draft.subject}\n"
            f"Attachments: {att_str}\n"
            f"--- Body ---\n{draft.body}\n------------\n"
            "Sir, would you like me to send this email? (Please confirm explicitly, or tell me what to change.)"
        )

    async def compose_draft(
        self,
        instruction: str,
        *,
        to: list[str] | str | None = None,
        cc: list[str] | str | None = None,
        bcc: list[str] | str | None = None,
        tone: str = "professional",
        attachment_paths: list[str] | None = None,
        extra_context: str = "",
    ) -> dict[str, Any]:
        # 1. Validate attachments upfront if provided
        validated_attachments: list[EmailAttachment] = []
        if attachment_paths:
            for p in attachment_paths:
                validated_attachments.append(validate_attachment(p))

        # 2. Generate draft content
        hint_str = ", ".join(to) if isinstance(to, list) else (to or "")
        generated = await self.composer.compose_email(
            instruction=instruction,
            tone=tone,
            recipient_hint=hint_str,
            extra_context=extra_context,
        )

        # 3. Resolve recipients (explicit `to` or extracted `recipient_query`)
        to_inputs = to if to else ([generated["recipient_query"]] if generated.get("recipient_query") else [])
        res_to, amb_to, unres_to = await self.resolve_recipients(to_inputs)
        res_cc, amb_cc, unres_cc = await self.resolve_recipients(cc)
        res_bcc, amb_bcc, unres_bcc = await self.resolve_recipients(bcc)

        draft = EmailDraft(
            to=res_to,
            cc=res_cc,
            bcc=res_bcc,
            subject=generated["subject"],
            body=generated["body"],
            tone=generated["tone"],
            attachments=validated_attachments,
        )
        self.store.save_draft(draft)

        warnings: list[str] = []
        warnings.extend(amb_to + amb_cc + amb_bcc)
        if unres_to or unres_cc or unres_bcc:
            missing = ", ".join(unres_to + unres_cc + unres_bcc)
            warnings.append(f"Could not resolve recipient(s): {missing}. Please provide their exact email address.")

        preview = self.format_draft_preview(draft)
        if warnings:
            preview = "Note: " + " ".join(warnings) + "\n\n" + preview

        return {
            "success": True,
            "draft": draft,
            "warnings": warnings,
            "message": preview,
        }

    async def edit_draft(
        self,
        edit_instruction: str = "",
        *,
        draft_id: Optional[str] = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: Optional[str] = None,
        attachment_paths: list[str] | None = None,
        save_to_gmail: bool = False,
        discard: bool = False,
    ) -> dict[str, Any]:
        draft = self.store.get_draft(draft_id) if draft_id else self.store.get_latest_active_draft()
        if not draft:
            return {"success": False, "message": "No active email draft found to edit."}

        if discard:
            draft.status = "DISCARDED"
            draft.invalidate_approval()
            self.store.save_draft(draft)
            return {"success": True, "message": f"Sir, draft '{draft.draft_id}' has been discarded."}

        # Invalidate any prior approval since draft is being modified
        draft.invalidate_approval()

        warnings: list[str] = []
        if to is not None:
            res_to, amb, unres = await self.resolve_recipients(to)
            draft.to = res_to
            warnings.extend(amb)
            if unres:
                warnings.append(f"Unresolved To recipient(s): {', '.join(unres)}")
        if cc is not None:
            res_cc, amb, unres = await self.resolve_recipients(cc)
            draft.cc = res_cc
            warnings.extend(amb)
            if unres:
                warnings.append(f"Unresolved CC recipient(s): {', '.join(unres)}")
        if bcc is not None:
            res_bcc, amb, unres = await self.resolve_recipients(bcc)
            draft.bcc = res_bcc
            warnings.extend(amb)
            if unres:
                warnings.append(f"Unresolved BCC recipient(s): {', '.join(unres)}")

        if attachment_paths is not None:
            draft.attachments = [validate_attachment(p) for p in attachment_paths]

        if subject is not None and subject.strip():
            draft.subject = subject.strip()

        if edit_instruction and edit_instruction.strip():
            revised = await self.composer.edit_email(draft.subject, draft.body, edit_instruction.strip())
            if subject is None:
                draft.subject = revised["subject"]
            draft.body = revised["body"]

        if save_to_gmail and await self.provider.is_connected():
            draft.provider_draft_id = await self.provider.save_draft(draft)

        self.store.save_draft(draft)
        preview = self.format_draft_preview(draft)
        if save_to_gmail and draft.provider_draft_id:
            preview = f"Saved to Gmail Drafts (ID: {draft.provider_draft_id}).\n\n" + preview
        if warnings:
            preview = "Note: " + " ".join(warnings) + "\n\n" + preview

        return {"success": True, "draft": draft, "message": preview}

    def _check_auto_send_allowed(self, draft: EmailDraft, purpose: str) -> tuple[bool, str]:
        policy = self.store.get_auto_send_policy()
        if not policy.enabled:
            return False, "Auto-send is disabled."
        today = datetime.now().strftime("%Y-%m-%d")
        if policy.last_reset_date != today:
            policy.sent_today = 0
            policy.last_reset_date = today
            self.store.save_auto_send_policy(policy)
        if policy.sent_today >= policy.max_per_day:
            return False, "Auto-send daily limit reached."
        if not draft.to or any(r.lower() not in [a.lower() for a in policy.allowed_recipients] for r in draft.to):
            return False, "Recipient not in trusted auto-send allowlist."
        if purpose.lower() not in [p.lower() for p in policy.allowed_purposes]:
            return False, f"Purpose '{purpose}' is not permitted for auto-send."
        return True, "Trusted auto-send policy matched."

    async def approve_and_send(
        self,
        *,
        draft_id: Optional[str] = None,
        user_confirmed: bool = False,
        purpose: str = "general",
    ) -> dict[str, Any]:
        async with self._send_lock:
            draft = self.store.get_draft(draft_id) if draft_id else self.store.get_latest_active_draft()
            if not draft:
                return {"success": False, "message": "No active email draft found to send."}

            if draft.status == "SENT":
                return {"success": False, "message": f"Draft '{draft.draft_id}' was already sent. Duplicate send blocked."}

            if not draft.to or any(not is_valid_email(addr) for addr in draft.to):
                return {"success": False, "message": "Cannot send: valid 'To' recipient email address is required."}
            if not draft.subject.strip() or not draft.body.strip():
                return {"success": False, "message": "Cannot send: subject and body must not be empty."}

            auto_ok, auto_reason = self._check_auto_send_allowed(draft, purpose)
            if not user_confirmed and not auto_ok:
                preview = self.format_draft_preview(draft)
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message": (
                        "Approval Required: Explicit user confirmation is required before sending.\n\n" + preview
                    ),
                }

            # Re-validate attachments before send
            for att in draft.attachments:
                validate_attachment(att.path)

            draft.mark_approved()
            if not draft.is_approval_valid():
                return {"success": False, "message": "Approval integrity hash check failed. Please preview and confirm again."}

            result = await self.provider.send_email(draft)
            draft.status = "SENT"
            self.store.save_draft(draft)

            if not user_confirmed and auto_ok:
                policy = self.store.get_auto_send_policy()
                policy.sent_today += 1
                policy.last_reset_date = datetime.now().strftime("%Y-%m-%d")
                self.store.save_auto_send_policy(policy)
                logger.info(f"[EmailAssistant] Trusted auto-send executed ({auto_reason}) to {draft.to}")

            verified_note = " and confirmed in Sent" if result.get("verified_in_sent") else ""
            return {
                "success": True,
                "message_id": result.get("message_id"),
                "message": (
                    f"Sir, your email '{draft.subject}' to {', '.join(draft.to)} has been sent"
                    f"{verified_note} (Message ID: {result.get('message_id')})."
                ),
            }

    async def schedule_email(
        self,
        send_at_text: str,
        *,
        draft_id: Optional[str] = None,
        user_confirmed: bool = False,
        follow_up_after_text: Optional[str] = None,
        follow_up_note: Optional[str] = None,
    ) -> dict[str, Any]:
        draft = self.store.get_draft(draft_id) if draft_id else self.store.get_latest_active_draft()
        if not draft:
            return {"success": False, "message": "No active email draft found to schedule."}
        if not draft.to or any(not is_valid_email(addr) for addr in draft.to):
            return {"success": False, "message": "Cannot schedule: valid 'To' recipient email address is required."}
        if not user_confirmed:
            return {
                "success": False,
                "requires_confirmation": True,
                "message": "Approval Required: Please confirm you want to schedule this email.\n\n" + self.format_draft_preview(draft),
            }

        from datetime import timedelta
        from app.reminders.datetime_utils import (
            combine_date_time_to_epoch,
            get_default_timezone,
            parse_date_str,
            parse_time_str,
        )

        def _parse_dt(text: str) -> Optional[datetime]:
            raw = (text or "").strip().lower()
            tz = get_default_timezone()
            now_dt = datetime.now(tz)
            rel = re.match(r"^in\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|hr|hrs|day|days)$", raw)
            if rel:
                val = int(rel.group(1))
                unit = rel.group(2)
                if unit.startswith("min"):
                    return now_dt + timedelta(minutes=val)
                if unit.startswith("h"):
                    return now_dt + timedelta(hours=val)
                return now_dt + timedelta(days=val)
            try:
                return datetime.fromisoformat(text.strip()).replace(tzinfo=tz) if datetime.fromisoformat(text.strip()).tzinfo is None else datetime.fromisoformat(text.strip())
            except Exception:
                pass
            try:
                parts = raw.split(" at ", 1)
                d = parse_date_str(parts[0], tz, now_dt)
                t = parse_time_str(parts[1] if len(parts) > 1 else None)
                epoch = combine_date_time_to_epoch(d, t, tz)
                return datetime.fromtimestamp(epoch, tz=tz)
            except Exception:
                return None

        parsed = _parse_dt(send_at_text)
        if not parsed:
            return {"success": False, "message": f"Could not understand schedule time '{send_at_text}'. Please specify a date and time."}
        send_ts = parsed.timestamp()
        if send_ts <= time.time() - 30:
            return {"success": False, "message": "Scheduled time must be in the future."}

        follow_up_ts: Optional[float] = None
        if follow_up_after_text:
            fp = _parse_dt(follow_up_after_text)
            if fp:
                follow_up_ts = fp.timestamp()

        draft.mark_approved()
        self.store.save_draft(draft)

        rec = ScheduledEmailRecord(
            draft_id=draft.draft_id,
            to=draft.to,
            cc=draft.cc,
            bcc=draft.bcc,
            subject=draft.subject,
            body=draft.body,
            attachments=draft.attachments,
            thread_id=draft.thread_id,
            in_reply_to=draft.in_reply_to,
            references=draft.references,
            approved_hash=draft.approved_hash or draft.compute_content_hash(),
            send_at=send_ts,
            follow_up_at=follow_up_ts,
            follow_up_note=follow_up_note or f"Follow up on '{draft.subject}' with {', '.join(draft.to)}",
        )
        self.store.save_scheduled_email(rec)

        if follow_up_ts:
            self._create_follow_up_reminder(rec)

        friendly_time = parsed.strftime("%Y-%m-%d %I:%M %p")
        return {
            "success": True,
            "schedule_id": rec.schedule_id,
            "message": (
                f"Sir, email '{rec.subject}' to {', '.join(rec.to)} is scheduled for {friendly_time} "
                f"(Schedule ID: {rec.schedule_id})."
            ),
        }

    def _create_follow_up_reminder(self, rec: ScheduledEmailRecord) -> None:
        if not rec.follow_up_at:
            return
        try:
            from app.reminders.models import ReminderRecord
            from app.reminders.scheduler import get_global_reminder_scheduler

            scheduler = get_global_reminder_scheduler()
            rem = ReminderRecord(
                title=rec.follow_up_note or f"Follow up on email '{rec.subject}'",
                due_timestamp=rec.follow_up_at,
                timezone_name="local",
            )
            scheduler.store.create_reminder(rem)
            scheduler.notify_store_updated()
        except Exception as e:
            logger.warning(f"[EmailAssistant] Failed creating follow-up reminder: {e}")

    async def process_due_scheduled_emails(self) -> list[dict[str, Any]]:
        """Execute due scheduled emails if their approved_hash is intact."""
        now = time.time()
        due = self.store.get_due_scheduled_emails(now)
        outcomes: list[dict[str, Any]] = []
        for rec in due:
            if rec.status != ScheduledEmailStatus.PENDING:
                continue
            if rec.compute_current_hash() != rec.approved_hash:
                rec.status = ScheduledEmailStatus.NEEDS_REAPPROVAL
                rec.error_message = "Email content or recipients changed after approval."
                self.store.save_scheduled_email(rec)
                outcomes.append({"schedule_id": rec.schedule_id, "status": rec.status.value})
                continue

            draft = EmailDraft(
                draft_id=rec.draft_id,
                to=rec.to,
                cc=rec.cc,
                bcc=rec.bcc,
                subject=rec.subject,
                body=rec.body,
                attachments=rec.attachments,
                thread_id=rec.thread_id,
                in_reply_to=rec.in_reply_to,
                references=rec.references,
                is_approved=True,
                approved_hash=rec.approved_hash,
            )
            try:
                res = await self.provider.send_email(draft)
                rec.status = ScheduledEmailStatus.SENT
                rec.sent_message_id = res.get("message_id")
                self.store.save_scheduled_email(rec)
                outcomes.append({
                    "schedule_id": rec.schedule_id,
                    "status": "SENT",
                    "message": f"Scheduled email '{rec.subject}' to {', '.join(rec.to)} has been sent.",
                })
            except Exception as e:
                rec.status = ScheduledEmailStatus.FAILED
                rec.error_message = str(e)
                self.store.save_scheduled_email(rec)
                outcomes.append({
                    "schedule_id": rec.schedule_id,
                    "status": "FAILED",
                    "message": f"Scheduled email '{rec.subject}' failed: {e}",
                })
        return outcomes

    async def search_inbox(
        self,
        query: str = "",
        max_results: int = 10,
        unread_only: bool = False,
    ) -> dict[str, Any]:
        msgs = await self.provider.search_messages(query=query, max_results=max_results, unread_only=unread_only)
        if not msgs:
            return {"success": True, "messages": [], "message": "No matching emails found."}

        lines = [f"Found {len(msgs)} email(s):"]
        for i, m in enumerate(msgs, 1):
            unread_tag = "[UNREAD] " if m.is_unread else ""
            lines.append(
                f"{i}. {unread_tag}ID: {m.message_id}\n"
                f"   From: {m.sender}\n"
                f"   Subject: {m.subject}\n"
                f"   Date: {m.date}\n"
                f"   Summary: {m.snippet[:180]}"
            )
        return {
            "success": True,
            "messages": msgs,
            "message": wrap_untrusted_email("\n\n".join(lines)),
        }

    async def read_message(self, message_id: str) -> dict[str, Any]:
        msg = await self.provider.get_message(message_id)
        if not msg:
            return {"success": False, "message": f"Message '{message_id}' not found."}
        formatted = (
            f"Message ID: {msg.message_id} (Thread: {msg.thread_id})\n"
            f"From: {msg.sender}\n"
            f"To: {msg.to}\n"
            f"Subject: {msg.subject}\n"
            f"Date: {msg.date}\n"
            f"--- Content ---\n{msg.body_preview}"
        )
        return {"success": True, "email": msg, "message": wrap_untrusted_email(formatted)}

    async def summarize_inbox(self, query: str = "", max_results: int = 8, unread_only: bool = False) -> dict[str, Any]:
        msgs = await self.provider.search_messages(query=query, max_results=max_results, unread_only=unread_only)
        if not msgs:
            return {"success": True, "message": "No matching emails found to summarize."}
        summary = await self.composer.summarize_messages(msgs, focus=query or ("unread" if unread_only else "important"))
        return {"success": True, "message": wrap_untrusted_email(summary)}

    async def draft_reply(
        self,
        message_id: str,
        instruction: str,
        attachment_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        original = await self.provider.get_message(message_id)
        if not original:
            return {"success": False, "message": f"Original message '{message_id}' not found."}

        _, sender_email = email.utils.parseaddr(original.sender)
        if not is_valid_email(sender_email):
            return {"success": False, "message": f"Could not extract valid reply email from '{original.sender}'."}

        validated_attachments = [validate_attachment(p) for p in (attachment_paths or [])]
        reply_gen = await self.composer.draft_reply(original=original, instruction=instruction)

        draft = EmailDraft(
            to=[sender_email],
            subject=reply_gen["subject"],
            body=reply_gen["body"],
            tone="professional",
            attachments=validated_attachments,
            thread_id=original.thread_id,
            in_reply_to=original.rfc_message_id,
            references=original.references or original.rfc_message_id,
        )
        self.store.save_draft(draft)
        return {"success": True, "draft": draft, "message": self.format_draft_preview(draft)}
