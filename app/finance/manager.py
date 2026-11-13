"""
Victor Personal Finance, Expense & Bill Management Agent — Main Orchestrator.

Coordinates database persistence, deterministic analytics, receipt OCR intelligence,
reminders, budgets, subscriptions, and financial Q&A.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.finance.analytics import FinanceAnalytics
from app.finance.models import (
    DEFAULT_CATEGORIES,
    Bill,
    BillRecurrence,
    BillStatus,
    Budget,
    BudgetPeriod,
    ReceiptScanResult,
    Subscription,
    SubscriptionStatus,
    Transaction,
    TransactionType,
)
from app.finance.qa_engine import FinanceQAEngine
from app.finance.receipt_processor import ReceiptProcessor
from app.finance.reminder_integration import FinanceBillReminderManager
from app.finance.store import FinanceStore

logger = logging.getLogger(__name__)

_GLOBAL_FINANCE_MANAGER: Optional[FinanceManager] = None


def get_finance_manager() -> FinanceManager:
    global _GLOBAL_FINANCE_MANAGER
    if _GLOBAL_FINANCE_MANAGER is None:
        _GLOBAL_FINANCE_MANAGER = FinanceManager()
    return _GLOBAL_FINANCE_MANAGER


class FinanceManager:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.store = FinanceStore(db_path=db_path)
        self.analytics = FinanceAnalytics(self.store)
        self.receipt_processor = ReceiptProcessor(self.store)
        self.reminder_manager = FinanceBillReminderManager(self.store)
        self.qa_engine = FinanceQAEngine(self.store, self.analytics)

    # =========================================================================
    # TRANSACTIONS
    # =========================================================================
    def record_transaction(
        self,
        amount: float,
        transaction_type: str = "EXPENSE",
        category: str = "Others",
        subcategory: Optional[str] = None,
        merchant_or_payee: str = "Unknown",
        transaction_date: Optional[str] = None,
        payment_method: str = "UPI",
        description: str = "",
        receipt_ref: Optional[str] = None,
        bypass_duplicate_check: bool = False,
    ) -> Dict[str, Any]:
        """Records an expense, income, or refund with validation and budget checking."""
        if amount <= 0:
            return {"success": False, "error": f"Transaction amount must be strictly greater than 0, got {amount}"}

        # Normalize type
        try:
            t_type = TransactionType(transaction_type.upper())
        except ValueError:
            t_type = TransactionType.EXPENSE

        date_str = transaction_date or time.strftime("%Y-%m-%d %H:%M:%S")

        # Duplicate detection check
        if not bypass_duplicate_check:
            dup = self.store.check_duplicate_transaction(amount, merchant_or_payee, date_str)
            if dup:
                return {
                    "success": False,
                    "is_duplicate": True,
                    "duplicate_transaction_id": dup.transaction_id,
                    "message": (
                        f"Potential duplicate transaction detected: A {dup.transaction_type.value} of ₹{dup.amount:.2f} "
                        f"to '{dup.merchant_or_payee}' already exists on {dup.transaction_date}. "
                        "Confirm if you want to record this anyway."
                    ),
                }

        # Normalize category
        norm_cat = self._normalize_category(category)

        txn_id = f"txn_{uuid.uuid4().hex[:10]}"
        txn = Transaction(
            transaction_id=txn_id,
            transaction_type=t_type,
            amount=round(amount, 2),
            currency="INR",
            category=norm_cat,
            subcategory=subcategory,
            merchant_or_payee=merchant_or_payee.strip() or "Unknown",
            transaction_date=date_str,
            payment_method=payment_method,
            description=description,
            receipt_ref=receipt_ref,
        )

        self.store.add_transaction(txn)
        logger.info(f"[FinanceManager] Recorded {t_type.value} ID: {txn_id} Amount: {amount} {norm_cat}")

        # Check if any budget thresholds were crossed by this expense
        budget_alerts = []
        if t_type == TransactionType.EXPENSE:
            import datetime
            now_dt = datetime.datetime.now()
            budgets = self.analytics.check_all_budget_utilizations(now_dt.year, now_dt.month)
            for b in budgets:
                if b["category"] in (norm_cat, "Overall") and b.get("alert"):
                    budget_alerts.append(
                        f"Alert: {b['name']} ({b['category']}) has reached {b['percentage_used']}% of ₹{b['limit_amount']:.2f} limit!"
                    )

        return {
            "success": True,
            "transaction_id": txn_id,
            "transaction": txn.to_dict(),
            "budget_alerts": budget_alerts,
            "message": f"Successfully recorded {t_type.value} of ₹{txn.amount:.2f} for '{txn.merchant_or_payee}' ({norm_cat}).",
        }

    def update_transaction(self, transaction_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Updates specific fields of an existing transaction."""
        txn = self.store.get_transaction(transaction_id)
        if not txn:
            return {"success": False, "error": f"Transaction '{transaction_id}' not found."}

        if "amount" in kwargs:
            amt = float(kwargs["amount"])
            if amt <= 0:
                return {"success": False, "error": "Amount must be strictly greater than 0"}
            txn.amount = round(amt, 2)
        if "category" in kwargs and kwargs["category"]:
            txn.category = self._normalize_category(kwargs["category"])
        if "merchant_or_payee" in kwargs and kwargs["merchant_or_payee"]:
            txn.merchant_or_payee = str(kwargs["merchant_or_payee"]).strip()
        if "description" in kwargs:
            txn.description = str(kwargs["description"])
        if "payment_method" in kwargs and kwargs["payment_method"]:
            txn.payment_method = str(kwargs["payment_method"])
        if "transaction_date" in kwargs and kwargs["transaction_date"]:
            txn.transaction_date = str(kwargs["transaction_date"])
        if "transaction_type" in kwargs and kwargs["transaction_type"]:
            txn.transaction_type = TransactionType(str(kwargs["transaction_type"]).upper())

        updated = self.store.update_transaction(txn)
        return {
            "success": updated,
            "transaction": txn.to_dict(),
            "message": f"Transaction '{transaction_id}' updated successfully.",
        }

    def delete_transaction(self, transaction_id: str) -> Dict[str, Any]:
        """Deletes a transaction from the persistent store."""
        deleted = self.store.delete_transaction(transaction_id)
        if deleted:
            return {"success": True, "message": f"Transaction '{transaction_id}' was successfully deleted."}
        return {"success": False, "error": f"Transaction '{transaction_id}' not found."}

    def list_transactions(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Lists transactions matching criteria."""
        txns = self.store.list_transactions(**kwargs)
        return [t.to_dict() for t in txns]

    # =========================================================================
    # BILLS & REMINDERS
    # =========================================================================
    def add_bill(
        self,
        provider_name: str,
        expected_amount: float,
        due_date: str,
        category: str = "Bills",
        recurrence: str = "MONTHLY",
        payment_method: str = "UPI",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Creates a bill and schedules proactive reminders in the ReminderScheduler."""
        if expected_amount <= 0:
            return {"success": False, "error": "Expected bill amount must be greater than 0"}

        try:
            rec = BillRecurrence(recurrence.upper())
        except ValueError:
            rec = BillRecurrence.MONTHLY

        bill_id = f"bill_{uuid.uuid4().hex[:10]}"
        norm_cat = self._normalize_category(category)

        bill = Bill(
            bill_id=bill_id,
            provider_name=provider_name.strip(),
            category=norm_cat,
            expected_amount=round(expected_amount, 2),
            due_date=due_date[:10],
            recurrence=rec,
            status=BillStatus.PENDING,
            payment_method=payment_method,
            notes=notes,
        )

        self.store.add_bill(bill)
        # Schedule reminders via existing scheduler
        self.reminder_manager.schedule_bill_reminders(bill)

        return {
            "success": True,
            "bill_id": bill_id,
            "bill": bill.to_dict(),
            "message": f"Scheduled bill '{provider_name}' of ₹{bill.expected_amount:.2f} due on {bill.due_date}.",
        }

    def pay_bill(
        self,
        bill_id: str,
        amount_paid: Optional[float] = None,
        payment_date: Optional[str] = None,
        record_as_expense: bool = True,
    ) -> Dict[str, Any]:
        """
        Marks a bill as paid (or partially paid), cancels pending reminders,
        spawns next recurring bill occurrence if applicable, and records an expense.
        """
        bill = self.store.get_bill(bill_id)
        if not bill:
            return {"success": False, "error": f"Bill '{bill_id}' not found."}

        paid_amount = amount_paid if (amount_paid is not None and amount_paid > 0) else bill.remaining_amount
        pay_dt = payment_date or time.strftime("%Y-%m-%d")

        updated_bill, next_bill = self.store.mark_bill_paid(bill_id, paid_amount, pay_dt)
        if not updated_bill:
            return {"success": False, "error": "Failed updating bill payment status."}

        # Update reminders
        if updated_bill.status == BillStatus.PAID:
            self.reminder_manager.cancel_bill_reminders(bill_id)
            if next_bill:
                self.reminder_manager.schedule_bill_reminders(next_bill)

        # Record corresponding expense transaction
        txn_dict = None
        if record_as_expense:
            txn_res = self.record_transaction(
                amount=paid_amount,
                transaction_type="EXPENSE",
                category=updated_bill.category,
                merchant_or_payee=updated_bill.provider_name,
                transaction_date=f"{pay_dt} {time.strftime('%H:%M:%S')}",
                payment_method=updated_bill.payment_method,
                description=f"Bill payment for {updated_bill.provider_name} ({bill_id})",
                bypass_duplicate_check=True,
            )
            txn_dict = txn_res.get("transaction")

        msg = f"Marked bill '{updated_bill.provider_name}' as {updated_bill.status.value} (Paid: ₹{paid_amount:.2f})."
        if next_bill:
            msg += f" Next recurring cycle scheduled for {next_bill.due_date}."

        return {
            "success": True,
            "bill": updated_bill.to_dict(),
            "next_cycle_bill": next_bill.to_dict() if next_bill else None,
            "transaction": txn_dict,
            "message": msg,
        }

    def list_bills(self, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        bills = self.store.list_bills(status=status, category=category)
        return [b.to_dict() for b in bills]

    def postpone_bill_reminder(self, bill_id: str, days: int = 1) -> Dict[str, Any]:
        success = self.reminder_manager.postpone_bill_reminder(bill_id, days=days)
        if success:
            return {"success": True, "message": f"Bill reminder postponed by {days} day(s)."}
        return {"success": False, "error": f"Reminder for bill '{bill_id}' not found."}

    # =========================================================================
    # BUDGETS
    # =========================================================================
    def set_budget(
        self,
        name: str,
        limit_amount: float,
        period: str = "MONTHLY",
        category: Optional[str] = None,
        alert_thresholds: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Sets or modifies a budget limit."""
        if limit_amount <= 0:
            return {"success": False, "error": "Budget limit must be greater than 0"}

        try:
            p_val = BudgetPeriod(period.upper())
        except ValueError:
            p_val = BudgetPeriod.MONTHLY

        cat_val = self._normalize_category(category) if category else None
        b_id = f"bgt_{hashlib.md5(f'{name}_{cat_val}_{p_val.value}'.encode()).hexdigest()[:10]}"

        budget = Budget(
            budget_id=b_id,
            name=name.strip(),
            period=p_val,
            category=cat_val,
            limit_amount=round(limit_amount, 2),
            alert_thresholds=alert_thresholds or [0.70, 0.90, 1.00],
        )

        self.store.set_budget(budget)
        return {
            "success": True,
            "budget_id": b_id,
            "budget": budget.to_dict(),
            "message": f"Configured {budget.period.value} budget '{budget.name}' of ₹{budget.limit_amount:.2f} for {budget.category or 'Overall'}.",
        }

    def get_budget_status(self) -> List[Dict[str, Any]]:
        import datetime
        now = datetime.datetime.now()
        return self.analytics.check_all_budget_utilizations(now.year, now.month)

    def delete_budget(self, budget_id: str) -> Dict[str, Any]:
        deleted = self.store.delete_budget(budget_id)
        return {"success": deleted, "message": f"Budget '{budget_id}' deleted." if deleted else "Budget not found."}

    # =========================================================================
    # SUBSCRIPTIONS
    # =========================================================================
    def add_subscription(
        self,
        service_name: str,
        amount: float,
        billing_frequency: str = "monthly",
        next_renewal_date: Optional[str] = None,
        payment_method: str = "Credit Card",
        notes: str = "",
    ) -> Dict[str, Any]:
        """Tracks a recurring digital or offline subscription."""
        if amount <= 0:
            return {"success": False, "error": "Subscription amount must be greater than 0"}

        renewal = next_renewal_date or time.strftime("%Y-%m-%d")
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"

        sub = Subscription(
            subscription_id=sub_id,
            service_name=service_name.strip(),
            amount=round(amount, 2),
            currency="INR",
            billing_frequency=billing_frequency.lower(),
            next_renewal_date=renewal[:10],
            payment_method=payment_method,
            status=SubscriptionStatus.ACTIVE,
            notes=notes,
        )

        self.store.add_subscription(sub)
        return {
            "success": True,
            "subscription_id": sub_id,
            "subscription": sub.to_dict(),
            "message": f"Tracking subscription for '{service_name}' of ₹{sub.amount:.2f}/{sub.billing_frequency} (Renewal: {sub.next_renewal_date}).",
        }

    def list_subscriptions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        subs = self.store.list_subscriptions(status=status)
        return [s.to_dict() for s in subs]

    # =========================================================================
    # RECEIPT SCANNING
    # =========================================================================
    async def scan_receipt(
        self,
        file_path_or_bytes: str | Path | bytes,
        filename: Optional[str] = None,
        auto_record_transaction: bool = False,
    ) -> Dict[str, Any]:
        """Scans a receipt/invoice document and optionally records the transaction."""
        scan = await self.receipt_processor.process_receipt_file(file_path_or_bytes, filename=filename)

        recorded_txn = None
        if auto_record_transaction and not scan.is_duplicate and scan.total_amount:
            txn_res = self.record_transaction(
                amount=scan.total_amount,
                transaction_type="EXPENSE",
                category=scan.suggested_category,
                merchant_or_payee=scan.merchant or "Scanned Merchant",
                transaction_date=scan.invoice_date or time.strftime("%Y-%m-%d %H:%M:%S"),
                payment_method=scan.payment_method or "UPI",
                description=f"Scanned invoice #{scan.invoice_number or 'N/A'}",
                receipt_ref=scan.invoice_number,
            )
            recorded_txn = txn_res.get("transaction")

            # Store receipt record in database for deduplication
            raw_b = file_path_or_bytes if isinstance(file_path_or_bytes, bytes) else Path(file_path_or_bytes).read_bytes()
            self.store.record_receipt(
                receipt_id=f"rcpt_{uuid.uuid4().hex[:10]}",
                invoice_number=scan.invoice_number,
                merchant=scan.merchant,
                amount=scan.total_amount,
                invoice_date=scan.invoice_date,
                file_hash=self.receipt_processor.compute_file_hash(raw_b),
                metadata=scan.to_dict(),
            )

        return {
            "success": True,
            "scan_result": scan.to_dict(),
            "recorded_transaction": recorded_txn,
            "message": (
                f"Receipt scanned: {scan.merchant} for ₹{scan.total_amount or 0.0:.2f} ({scan.suggested_category})."
                if not scan.is_duplicate
                else f"Duplicate receipt detected: {scan.duplicate_reason}"
            ),
        }

    # =========================================================================
    # ANALYTICS & QA
    # =========================================================================
    def generate_report(
        self,
        report_type: str = "monthly",
        year: Optional[int] = None,
        month: Optional[int] = None,
        date_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates deterministic financial reports (daily, weekly, monthly, commitments)."""
        r_type = report_type.lower()
        if r_type == "daily":
            return self.analytics.get_daily_summary(date_str)
        elif r_type == "weekly":
            return self.analytics.get_weekly_report(date_str)
        elif r_type in ("recurring", "commitments"):
            return self.analytics.get_recurring_commitments_summary()
        else:
            return self.analytics.get_monthly_report(year=year, month=month)

    async def answer_financial_query(self, query: str) -> str:
        """Grounds and answers natural language financial questions."""
        return await self.qa_engine.answer_financial_query(query)

    def _normalize_category(self, cat: Optional[str]) -> str:
        if not cat:
            return "Others"
        for standard in DEFAULT_CATEGORIES:
            if standard.lower() == cat.strip().lower():
                return standard
        return cat.strip().title()
