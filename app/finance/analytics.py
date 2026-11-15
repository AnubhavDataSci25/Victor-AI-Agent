"""
Victor Personal Finance, Expense & Bill Management Agent — Deterministic Analytics.

Executes 100% deterministic mathematical calculations, SQL aggregations, and
comparisons over verified financial records. Zero LLM hallucinations for math or sums.
"""

from __future__ import annotations

import calendar
import datetime
import logging
import time
from typing import Any, Dict, List, Optional

from app.finance.models import (
    BillStatus,
    Budget,
    BudgetPeriod,
    SubscriptionStatus,
    Transaction,
    TransactionType,
)
from app.finance.store import FinanceStore

logger = logging.getLogger(__name__)


class FinanceAnalytics:
    def __init__(self, store: Optional[FinanceStore] = None) -> None:
        self.store = store or FinanceStore()

    def get_summary_by_date_range(
        self,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """
        Calculates exact income, expense, refund totals, net cash flow, and savings rate.
        Dates formatted as 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'.
        """
        txns = self.store.list_transactions(start_date=start_date, end_date=end_date, limit=10000)

        total_income = 0.0
        total_expense = 0.0
        total_refund = 0.0
        category_breakdown: Dict[str, float] = {}
        category_counts: Dict[str, int] = {}

        for t in txns:
            amt = round(t.amount, 2)
            if t.transaction_type == TransactionType.INCOME:
                total_income += amt
            elif t.transaction_type == TransactionType.EXPENSE:
                total_expense += amt
                cat = t.category or "Others"
                category_breakdown[cat] = round(category_breakdown.get(cat, 0.0) + amt, 2)
                category_counts[cat] = category_counts.get(cat, 0) + 1
            elif t.transaction_type == TransactionType.REFUND:
                total_refund += amt

        total_income = round(total_income, 2)
        total_expense = round(total_expense, 2)
        total_refund = round(total_refund, 2)
        net_cash_flow = round(total_income - total_expense + total_refund, 2)

        savings_rate = 0.0
        if total_income > 0:
            savings_rate = round((net_cash_flow / total_income) * 100.0, 1)

        # Sort categories by total expenditure descending
        sorted_categories = sorted(
            [
                {
                    "category": cat,
                    "amount": amt,
                    "count": category_counts[cat],
                    "percentage": round((amt / total_expense) * 100.0, 1) if total_expense > 0 else 0.0,
                }
                for cat, amt in category_breakdown.items()
            ],
            key=lambda x: x["amount"],
            reverse=True,
        )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "transaction_count": len(txns),
            "total_income": total_income,
            "total_expense": total_expense,
            "total_refund": total_refund,
            "net_cash_flow": net_cash_flow,
            "savings_rate_pct": savings_rate,
            "category_breakdown": sorted_categories,
        }

    def get_monthly_report(self, year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Any]:
        """Generates a complete monthly report for the specified or current month."""
        now = datetime.datetime.now()
        y = year or now.year
        m = month or now.month
        num_days = calendar.monthrange(y, m)[1]

        start_date = f"{y:04d}-{m:02d}-01 00:00:00"
        end_date = f"{y:04d}-{m:02d}-{num_days:02d} 23:59:59"

        summary = self.get_summary_by_date_range(start_date, end_date)
        summary["month_name"] = calendar.month_name[m]
        summary["year"] = y
        summary["month"] = m

        # Top 5 highest individual expenses
        txns = self.store.list_transactions(start_date=start_date, end_date=end_date, txn_type=TransactionType.EXPENSE, limit=1000)
        sorted_txns = sorted(txns, key=lambda t: t.amount, reverse=True)
        summary["top_expenses"] = [
            {
                "transaction_id": t.transaction_id,
                "merchant": t.merchant_or_payee,
                "amount": t.amount,
                "category": t.category,
                "date": t.transaction_date,
            }
            for t in sorted_txns[:5]
        ]

        # Budget utilization for this month
        budgets = self.check_all_budget_utilizations(y, m)
        summary["budgets"] = budgets

        overall_b = next((b for b in budgets if str(b.get("category", "")).strip().lower() in ("all", "overall")), None)
        if overall_b:
            summary["remaining_budget"] = overall_b["remaining_amount"]
            summary["overall_budget_limit"] = overall_b["limit_amount"]
            summary["overall_budget_spent"] = overall_b["spent_amount"]
        elif budgets:
            total_limit = sum(b["limit_amount"] for b in budgets)
            total_spent = sum(b["spent_amount"] for b in budgets)
            summary["remaining_budget"] = max(0.0, round(total_limit - total_spent, 2))
            summary["overall_budget_limit"] = total_limit
            summary["overall_budget_spent"] = total_spent
        else:
            summary["remaining_budget"] = None
            summary["overall_budget_limit"] = None
            summary["overall_budget_spent"] = 0.0

        return summary

    def get_daily_summary(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """Calculates today's or target day's spending and income."""
        date_str = target_date or time.strftime("%Y-%m-%d")
        start_date = f"{date_str} 00:00:00"
        end_date = f"{date_str} 23:59:59"
        res = self.get_summary_by_date_range(start_date, end_date)
        res["target_date"] = date_str
        return res

    def get_weekly_report(self, reference_date: Optional[str] = None) -> Dict[str, Any]:
        """Generates a report for the 7-day period ending on reference_date (or today)."""
        ref = datetime.datetime.strptime(reference_date[:10], "%Y-%m-%d") if reference_date else datetime.datetime.now()
        start_dt = ref - datetime.timedelta(days=6)
        start_date = f"{start_dt.strftime('%Y-%m-%d')} 00:00:00"
        end_date = f"{ref.strftime('%Y-%m-%d')} 23:59:59"
        res = self.get_summary_by_date_range(start_date, end_date)
        res["period"] = "weekly"
        return res

    def compare_months(
        self,
        year1: int,
        month1: int,
        year2: int,
        month2: int,
    ) -> Dict[str, Any]:
        """
        Deterministically compares two calendar months and calculates category-by-category variances.
        """
        rep1 = self.get_monthly_report(year1, month1)
        rep2 = self.get_monthly_report(year2, month2)

        exp_diff = round(rep2["total_expense"] - rep1["total_expense"], 2)
        inc_diff = round(rep2["total_income"] - rep1["total_income"], 2)
        exp_pct_change = round((exp_diff / rep1["total_expense"]) * 100.0, 1) if rep1["total_expense"] > 0 else 0.0

        cats1 = {c["category"]: c["amount"] for c in rep1["category_breakdown"]}
        cats2 = {c["category"]: c["amount"] for c in rep2["category_breakdown"]}
        all_cats = set(cats1.keys()) | set(cats2.keys())

        category_diffs = []
        for cat in sorted(all_cats):
            a1 = cats1.get(cat, 0.0)
            a2 = cats2.get(cat, 0.0)
            diff = round(a2 - a1, 2)
            pct = round((diff / a1) * 100.0, 1) if a1 > 0 else (100.0 if a2 > 0 else 0.0)
            category_diffs.append({
                "category": cat,
                "amount_m1": a1,
                "amount_m2": a2,
                "diff": diff,
                "pct_change": pct,
            })

        # Sort by largest absolute difference
        category_diffs.sort(key=lambda x: abs(x["diff"]), reverse=True)

        return {
            "month1": f"{rep1['month_name']} {year1}",
            "month2": f"{rep2['month_name']} {year2}",
            "total_expense_m1": rep1["total_expense"],
            "total_expense_m2": rep2["total_expense"],
            "expense_diff": exp_diff,
            "expense_pct_change": exp_pct_change,
            "total_income_m1": rep1["total_income"],
            "total_income_m2": rep2["total_income"],
            "income_diff": inc_diff,
            "category_differences": category_diffs,
            "biggest_increase_category": next((c for c in category_diffs if c["diff"] > 0), None),
            "biggest_decrease_category": next((c for c in category_diffs if c["diff"] < 0), None),
        }

    def check_all_budget_utilizations(self, year: int, month: int) -> List[Dict[str, Any]]:
        """
        Calculates exact utilization percentage for all configured budgets for the month.
        Flags threshold alerts (70%, 90%, 100%).
        """
        num_days = calendar.monthrange(year, month)[1]
        start_date = f"{year:04d}-{month:02d}-01 00:00:00"
        end_date = f"{year:04d}-{month:02d}-{num_days:02d} 23:59:59"

        budgets = self.store.list_budgets()
        results = []

        for b in budgets:
            # Query actual spent
            spent = self._calculate_spent_for_budget(b, start_date, end_date)
            limit = b.limit_amount
            remaining = max(0.0, round(limit - spent, 2))
            pct_used = round((spent / limit) * 100.0, 1) if limit > 0 else 0.0

            alert = None
            if pct_used >= 100.0:
                alert = "OVER_BUDGET"
            elif pct_used >= 90.0:
                alert = "CRITICAL_90"
            elif pct_used >= 70.0:
                alert = "WARNING_70"

            p_str = b.period.value.lower() if hasattr(b.period, "value") else str(b.period).lower()
            results.append({
                "budget_id": b.budget_id,
                "id": b.budget_id,
                "name": b.name,
                "period": p_str,
                "category": b.category or "Overall",
                "limit_amount": limit,
                "spent_amount": spent,
                "remaining_amount": remaining,
                "percentage_used": pct_used,
                "alert": alert,
            })

        return results

    def _calculate_spent_for_budget(self, budget: Budget, start_date: str, end_date: str) -> float:
        # Determine effective date range
        s_date = budget.start_date if budget.period == BudgetPeriod.CUSTOM and budget.start_date else start_date
        e_date = budget.end_date if budget.period == BudgetPeriod.CUSTOM and budget.end_date else end_date

        cat_filter = budget.category if (budget.category and budget.category.strip().lower() not in ("all", "overall")) else None

        txns = self.store.list_transactions(
            start_date=s_date,
            end_date=e_date,
            category=cat_filter,
            txn_type=TransactionType.EXPENSE,
            limit=10000,
        )
        total = sum(t.amount for t in txns)
        return round(total, 2)

    def get_recurring_commitments_summary(self) -> Dict[str, Any]:
        """Calculates total monthly recurring expenses: bills and active subscriptions."""
        bills = self.store.list_bills(status=BillStatus.PENDING)
        active_subs = self.store.list_subscriptions(status=SubscriptionStatus.ACTIVE)

        pending_bills_total = sum(b.remaining_amount for b in bills)

        # Monthly subscription expenditure
        monthly_sub_burn = 0.0
        for sub in active_subs:
            freq = (sub.billing_frequency or "monthly").lower()
            if "year" in freq or "annual" in freq:
                monthly_sub_burn += sub.amount / 12.0
            elif "quarter" in freq:
                monthly_sub_burn += sub.amount / 3.0
            elif "week" in freq:
                monthly_sub_burn += sub.amount * 4.33
            else:
                monthly_sub_burn += sub.amount

        monthly_sub_burn = round(monthly_sub_burn, 2)
        total_monthly_commitments = round(pending_bills_total + monthly_sub_burn, 2)

        return {
            "pending_bills_count": len(bills),
            "pending_bills_total": round(pending_bills_total, 2),
            "active_subscriptions_count": len(active_subs),
            "monthly_subscription_burn": monthly_sub_burn,
            "total_monthly_recurring_commitments": total_monthly_commitments,
            "bills": [b.to_dict() for b in bills],
            "subscriptions": [s.to_dict() for s in active_subs],
        }
