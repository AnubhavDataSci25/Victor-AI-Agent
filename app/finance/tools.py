"""
Victor Personal Finance, Expense & Bill Management Agent — BaseTool Implementations.

All tools execute through Victor's Central Tool Gateway, PermissionEngine,
and ResultVerifier.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.finance.manager import FinanceManager, get_finance_manager
from app.tools.base import BaseTool
from app.tools.permissions import PermissionLevel


class FinanceRecordTransactionTool(BaseTool):
    name = "finance_record_transaction"
    description = (
        "Records a personal financial expense, income, or refund. "
        "Supports amount, category (Food, Shopping, Travel, Bills, Rent, Entertainment, Healthcare, etc.), "
        "payee/merchant, payment method (UPI, Cash, Card, NetBanking), and notes. Checks for duplicates automatically."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "amount": {"type": "number", "description": "Transaction amount in rupees (strictly greater than 0)."},
            "transaction_type": {
                "type": "string",
                "enum": ["EXPENSE", "INCOME", "REFUND"],
                "description": "Type of transaction (default: 'EXPENSE').",
            },
            "category": {"type": "string", "description": "Expense/Income category (e.g. Food, Shopping, Travel, Bills, Salary)."},
            "merchant_or_payee": {"type": "string", "description": "Store, business, friend, or source name (e.g. Swiggy, Amazon, BESCOM, Employer)."},
            "payment_method": {"type": "string", "description": "Payment mode used (e.g. UPI, Cash, Credit Card, Debit Card, NetBanking)."},
            "description": {"type": "string", "description": "Optional notes or item description."},
            "date": {"type": "string", "description": "Optional date string (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS). Defaults to current time."},
        },
        "required": ["amount"],
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        amount = float(args.get("amount", 0.0))
        t_type = args.get("transaction_type", "EXPENSE")
        cat = args.get("category", "Others")
        merchant = args.get("merchant_or_payee", "Unknown")
        pay_method = args.get("payment_method", "UPI")
        desc = args.get("description", "")
        date_str = args.get("date")

        res = mgr.record_transaction(
            amount=amount,
            transaction_type=t_type,
            category=cat,
            merchant_or_payee=merchant,
            payment_method=pay_method,
            description=desc,
            transaction_date=date_str,
        )

        if not res["success"]:
            return res.get("message") or res.get("error", "Failed to record transaction.")

        msg = res["message"]
        if res.get("budget_alerts"):
            msg += "\n" + "\n".join(res["budget_alerts"])
        return f"Sir, {msg}"


class FinanceUpdateTransactionTool(BaseTool):
    name = "finance_update_transaction"
    description = "Updates or corrects an existing financial transaction (e.g. correcting yesterday's food expense amount or category)."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "transaction_id": {"type": "string", "description": "ID of the transaction to update (e.g. txn_12345)."},
            "amount": {"type": "number", "description": "Corrected amount."},
            "category": {"type": "string", "description": "Corrected category."},
            "merchant_or_payee": {"type": "string", "description": "Corrected payee/merchant."},
            "description": {"type": "string", "description": "Updated notes."},
        },
        "required": ["transaction_id"],
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        txn_id = args.get("transaction_id", "")
        res = mgr.update_transaction(txn_id, **args)
        if res["success"]:
            return f"Sir, {res['message']}"
        return f"Error: {res.get('error', 'Could not update transaction.')}"


class FinanceDeleteTransactionTool(BaseTool):
    name = "finance_delete_transaction"
    description = "Deletes a duplicate or cancelled transaction from persistent storage."
    permission_level = PermissionLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "transaction_id": {"type": "string", "description": "ID of the transaction to delete."},
        },
        "required": ["transaction_id"],
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        txn_id = args.get("transaction_id", "")
        res = mgr.delete_transaction(txn_id)
        if res["success"]:
            return f"Sir, {res['message']}"
        return f"Error: {res.get('error', 'Transaction not found.')}"


class FinanceListTransactionsTool(BaseTool):
    name = "finance_list_transactions"
    description = "Lists and filters transactions by date range, category, type (EXPENSE, INCOME, REFUND), or merchant."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "Filter from date (YYYY-MM-DD)."},
            "end_date": {"type": "string", "description": "Filter to date (YYYY-MM-DD)."},
            "category": {"type": "string", "description": "Filter by category."},
            "transaction_type": {"type": "string", "enum": ["EXPENSE", "INCOME", "REFUND"], "description": "Filter by type."},
            "merchant": {"type": "string", "description": "Search by payee/merchant name."},
            "limit": {"type": "integer", "description": "Maximum transactions to return (default 20)."},
        },
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        limit = args.get("limit", 20)
        txns = mgr.list_transactions(limit=limit, **args)
        if not txns:
            return "Sir, no transactions matched your query."

        lines = [f"Found {len(txns)} transaction(s):"]
        for t in txns[:limit]:
            lines.append(f"• [{t['transaction_id']}] {t['transaction_date'][:10]} | {t['transaction_type']}: ₹{t['amount']:.2f} to {t['merchant_or_payee']} ({t['category']}) via {t['payment_method']}")
        return "\n".join(lines)


class FinanceScanReceiptTool(BaseTool):
    name = "finance_scan_receipt"
    description = (
        "Scans an invoice or receipt image/PDF, extracts merchant, date, invoice number, items, "
        "tax/GST, and total amount, checks for duplicates, and optionally auto-saves the transaction."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the receipt/invoice image or PDF file."},
            "auto_record": {"type": "boolean", "description": "Whether to automatically record the extracted expense (default: false)."},
        },
        "required": ["file_path"],
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        file_path = args.get("file_path", "")
        auto_rec = bool(args.get("auto_record", False))

        res = await mgr.scan_receipt(file_path, auto_record_transaction=auto_rec)
        scan = res.get("scan_result", {})

        if scan.get("is_duplicate"):
            return f"⚠️ Duplicate Receipt: {scan.get('duplicate_reason')}. Total: ₹{scan.get('total_amount', 0):.2f} from {scan.get('merchant')}."

        output = [
            f"📄 Scanned Receipt for: {scan.get('merchant', 'Unknown')}",
            f"• Invoice #: {scan.get('invoice_number') or 'N/A'}",
            f"• Date: {scan.get('invoice_date') or 'N/A'}",
            f"• Total Amount: ₹{scan.get('total_amount') or 0.0:.2f}",
            f"• Tax/GST: ₹{scan.get('tax_or_gst') or 0.0:.2f}",
            f"• Suggested Category: {scan.get('suggested_category')}",
        ]
        if res.get("recorded_transaction"):
            output.append("✓ Transaction was automatically recorded in your financial records.")
        else:
            output.append("Sir, would you like me to record this expense?")

        return "\n".join(output)


class FinanceManageBillTool(BaseTool):
    name = "finance_manage_bill"
    description = (
        "Manages recurring and one-time bills (electricity, water, internet, rent, recharge, credit cards). "
        "Supports creating a bill, listing pending/overdue bills, and postponing payment reminders."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "postpone"],
                "description": "Action to perform (default: 'list').",
            },
            "provider_name": {"type": "string", "description": "Bill provider or utility (e.g. BESCOM, Airtel Wi-Fi, Landlord)."},
            "expected_amount": {"type": "number", "description": "Expected amount in rupees."},
            "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)."},
            "category": {"type": "string", "description": "Bill category (default: 'Bills')."},
            "recurrence": {
                "type": "string",
                "enum": ["NONE", "MONTHLY", "WEEKLY", "QUARTERLY", "YEARLY"],
                "description": "Recurrence frequency (default: 'MONTHLY').",
            },
            "bill_id": {"type": "string", "description": "Bill ID for postponing."},
            "postpone_days": {"type": "integer", "description": "Days to postpone reminder (default: 1)."},
        },
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        action = args.get("action", "list").lower()

        if action == "create":
            provider = args.get("provider_name", "")
            amt = float(args.get("expected_amount", 0.0))
            due = args.get("due_date", "")
            cat = args.get("category", "Bills")
            rec = args.get("recurrence", "MONTHLY")

            if not provider or amt <= 0 or not due:
                return "Error: provider_name, expected_amount (>0), and due_date are required to schedule a bill."

            res = mgr.add_bill(provider, amt, due, category=cat, recurrence=rec)
            return f"Sir, {res['message']}"

        elif action == "postpone":
            bid = args.get("bill_id", "")
            days = args.get("postpone_days", 1)
            res = mgr.postpone_bill_reminder(bid, days=days)
            return res.get("message") or res.get("error", "Failed postponing reminder.")

        else:
            bills = mgr.list_bills(status="PENDING")
            if not bills:
                return "Sir, you have no pending bills scheduled at this time."
            lines = [f"Pending Bills ({len(bills)}):"]
            for b in bills:
                lines.append(f"• [{b['bill_id']}] {b['provider_name']} — ₹{b['remaining_amount']:.2f} due on {b['due_date']} (Recurrence: {b['recurrence']})")
            return "\n".join(lines)


class FinancePayBillTool(BaseTool):
    name = "finance_pay_bill"
    description = (
        "Marks a bill as paid (or partially paid). Automatically records the payment as an expense, "
        "stops pending reminders, and schedules the next recurring cycle if applicable."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "bill_id": {"type": "string", "description": "ID of the bill to mark paid."},
            "amount_paid": {"type": "number", "description": "Amount paid (defaults to full remaining amount)."},
            "payment_date": {"type": "string", "description": "Date of payment (YYYY-MM-DD). Defaults to today."},
        },
        "required": ["bill_id"],
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        bid = args.get("bill_id", "")
        amt = args.get("amount_paid")
        pay_date = args.get("payment_date")

        res = mgr.pay_bill(bid, amount_paid=float(amt) if amt is not None else None, payment_date=pay_date)
        if res["success"]:
            return f"Sir, {res['message']}"
        return f"Error: {res.get('error', 'Could not record bill payment.')}"


class FinanceManageBudgetTool(BaseTool):
    name = "finance_manage_budget"
    description = "Configures monthly, weekly, or category budgets, and checks real-time budget utilization."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "status", "delete"],
                "description": "Action: 'set' budget limit, 'status' to review utilizations, 'delete' to remove.",
            },
            "name": {"type": "string", "description": "Budget name (e.g. 'Monthly Food Budget', 'Overall Monthly Limit')."},
            "limit_amount": {"type": "number", "description": "Maximum spending limit in rupees."},
            "category": {"type": "string", "description": "Specific category to track (leave empty for overall budget)."},
            "period": {"type": "string", "enum": ["MONTHLY", "WEEKLY"], "description": "Budget cycle period."},
            "budget_id": {"type": "string", "description": "Budget ID for deletion."},
        },
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        action = args.get("action", "status").lower()

        if action == "set":
            name = args.get("name", "Budget")
            limit = float(args.get("limit_amount", 0.0))
            cat = args.get("category")
            period = args.get("period", "MONTHLY")

            if limit <= 0:
                return "Error: limit_amount must be greater than 0."

            res = mgr.set_budget(name, limit, period=period, category=cat)
            return f"Sir, {res['message']}"

        elif action == "delete":
            bid = args.get("budget_id", "")
            res = mgr.delete_budget(bid)
            return res.get("message") or "Budget not found."

        else:
            status = mgr.get_budget_status()
            if not status:
                return "Sir, no budgets are currently configured. You can ask me to set an overall or category budget."
            lines = ["Current Budget Status:"]
            for b in status:
                alert_flag = f" [⚠️ {b['alert']}]" if b.get("alert") else ""
                lines.append(
                    f"• {b['name']} ({b['category']}): Spent ₹{b['spent_amount']:.2f} of ₹{b['limit_amount']:.2f} "
                    f"({b['percentage_used']}% used, ₹{b['remaining_amount']:.2f} remaining){alert_flag}"
                )
            return "\n".join(lines)


class FinanceManageSubscriptionTool(BaseTool):
    name = "finance_manage_subscription"
    description = "Tracks recurring digital and physical subscriptions (Netflix, Spotify, ChatGPT, Gym, Software)."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list"], "description": "Action (default: 'list')."},
            "service_name": {"type": "string", "description": "Subscription name (e.g. Netflix, Spotify)."},
            "amount": {"type": "number", "description": "Subscription charge in rupees."},
            "billing_frequency": {"type": "string", "description": "Frequency: monthly, yearly, quarterly."},
            "next_renewal_date": {"type": "string", "description": "Next renewal date (YYYY-MM-DD)."},
            "payment_method": {"type": "string", "description": "Payment method (e.g. Credit Card, UPI Autopay)."},
        },
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        action = args.get("action", "list").lower()

        if action == "add":
            service = args.get("service_name", "")
            amt = float(args.get("amount", 0.0))
            freq = args.get("billing_frequency", "monthly")
            renewal = args.get("next_renewal_date")
            pay_method = args.get("payment_method", "Credit Card")

            if not service or amt <= 0:
                return "Error: service_name and amount (>0) are required."

            res = mgr.add_subscription(service, amt, billing_frequency=freq, next_renewal_date=renewal, payment_method=pay_method)
            return f"Sir, {res['message']}"

        else:
            subs = mgr.list_subscriptions(status="ACTIVE")
            if not subs:
                return "Sir, you currently have no active subscriptions being tracked."
            lines = [f"Active Subscriptions ({len(subs)}):"]
            for s in subs:
                lines.append(f"• {s['service_name']} — ₹{s['amount']:.2f}/{s['billing_frequency']} (Renews: {s['next_renewal_date']})")
            return "\n".join(lines)


class FinanceGenerateReportTool(BaseTool):
    name = "finance_generate_report"
    description = (
        "Generates 100% deterministic financial reports and analytics (daily, weekly, monthly, "
        "annual, month-to-month comparisons, and recurring monthly commitments)."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "report_type": {
                "type": "string",
                "enum": ["monthly", "daily", "weekly", "commitments", "compare"],
                "description": "Report type (default: 'monthly').",
            },
            "year": {"type": "integer", "description": "Target year (e.g. 2026)."},
            "month": {"type": "integer", "description": "Target month (1-12)."},
            "date": {"type": "string", "description": "Target date for daily report (YYYY-MM-DD)."},
            "compare_year": {"type": "integer", "description": "Baseline year for month comparison."},
            "compare_month": {"type": "integer", "description": "Baseline month for comparison (1-12)."},
        },
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        r_type = args.get("report_type", "monthly").lower()
        y = args.get("year")
        m = args.get("month")
        dt_str = args.get("date")

        if r_type == "compare":
            cy = args.get("compare_year") or y
            cm = args.get("compare_month")
            if not m or not cm:
                return "Error: month and compare_month are required for comparison."
            comp = mgr.analytics.compare_months(cy, cm, y or cy, m)
            lines = [
                f"Financial Comparison: {comp['month1']} vs {comp['month2']}",
                f"• Total Expenses: ₹{comp['total_expense_m1']:.2f} → ₹{comp['total_expense_m2']:.2f} (Diff: ₹{comp['expense_diff']:+.2f}, {comp['expense_pct_change']:+.1f}%)",
                f"• Total Income: ₹{comp['total_income_m1']:.2f} → ₹{comp['total_income_m2']:.2f}",
            ]
            if comp.get("biggest_increase_category"):
                bic = comp["biggest_increase_category"]
                lines.append(f"• Largest Increase: {bic['category']} (+₹{bic['diff']:.2f}, {bic['pct_change']}%)")
            return "\n".join(lines)

        rep = mgr.generate_report(report_type=r_type, year=y, month=m, date_str=dt_str)

        if r_type in ("recurring", "commitments"):
            return (
                f"Recurring Commitments Summary:\n"
                f"• Monthly Subscription Burn: ₹{rep['monthly_subscription_burn']:.2f} ({rep['active_subscriptions_count']} services)\n"
                f"• Pending Bills Total: ₹{rep['pending_bills_total']:.2f} ({rep['pending_bills_count']} bills)\n"
                f"• Total Monthly Recurring Commitments: ₹{rep['total_monthly_recurring_commitments']:.2f}"
            )

        lines = [
            f"Financial Summary ({rep.get('month_name', '')} {rep.get('year', '')}):",
            f"• Total Income: ₹{rep['total_income']:.2f}",
            f"• Total Expenses: ₹{rep['total_expense']:.2f}",
            f"• Net Cash Flow: ₹{rep['net_cash_flow']:.2f}",
            f"• Savings Rate: {rep['savings_rate_pct']}%",
            f"• Total Transactions: {rep['transaction_count']}",
        ]

        if rep.get("category_breakdown"):
            lines.append("\nTop Categories:")
            for c in rep["category_breakdown"][:5]:
                lines.append(f"  - {c['category']}: ₹{c['amount']:.2f} ({c['percentage']}%) [{c['count']} txns]")

        if rep.get("top_expenses"):
            lines.append("\nHighest Individual Expenses:")
            for te in rep["top_expenses"][:3]:
                lines.append(f"  - {te['merchant']}: ₹{te['amount']:.2f} ({te['category']} on {te['date'][:10]})")

        return "\n".join(lines)


class FinanceQueryTool(BaseTool):
    name = "finance_query"
    description = (
        "Answers natural-language financial questions with zero hallucination. "
        "Supports questions like 'Can I afford a 5000 rupee purchase?', 'Why did I spend more this month?', "
        "'How much did I spend on food?', 'Which category consumes most of my budget?'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Natural language financial question to answer."},
        },
        "required": ["question"],
    }

    def __init__(self, manager: Optional[FinanceManager] = None) -> None:
        self.manager = manager

    def _mgr(self) -> FinanceManager:
        return self.manager or get_finance_manager()

    async def execute(self, args: dict[str, Any]) -> str:
        mgr = self._mgr()
        q = args.get("question", "")
        return await mgr.answer_financial_query(q)
