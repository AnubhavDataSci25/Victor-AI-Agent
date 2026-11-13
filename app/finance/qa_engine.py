"""
Victor Personal Finance, Expense & Bill Management Agent — Financial Q&A Engine.

Interprets natural language financial queries, queries the deterministic analytics engine,
and generates grounded explanations. Never hallucinates numbers.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
from typing import Any, Dict, Optional

from google import genai

from app.finance.analytics import FinanceAnalytics
from app.finance.store import FinanceStore

logger = logging.getLogger(__name__)


class FinanceQAEngine:
    def __init__(
        self,
        store: Optional[FinanceStore] = None,
        analytics: Optional[FinanceAnalytics] = None,
    ) -> None:
        self.store = store or FinanceStore()
        self.analytics = analytics or FinanceAnalytics(self.store)
        self._gemini_client: Optional[genai.Client] = None

    def _get_gemini_client(self) -> genai.Client:
        if self._gemini_client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                self._gemini_client = genai.Client(api_key=api_key)
            else:
                self._gemini_client = genai.Client()
        return self._gemini_client

    async def answer_financial_query(self, query: str) -> str:
        """
        Answers a financial question by retrieving real ground-truth figures first,
        then formatting an accurate response.
        """
        q_lower = query.lower()
        now = datetime.datetime.now()

        # 1. Detect Intent: Affordability Check ("Can I afford X?")
        afford_match = re.search(r"can i afford (?:a\s+)?(?:rs\.?|inr|₹)?\s*([0-9,]+(?:\.[0-9]+)?)", q_lower)
        if afford_match:
            amount = float(afford_match.group(1).replace(",", ""))
            return self._handle_affordability_query(amount)

        # 2. Detect Intent: Month Comparison / Why spend more? ("Why did I spend more?", "Compare months")
        if any(k in q_lower for k in ("why did i spend more", "compare", "spending difference", "spend higher")):
            return self._handle_month_comparison_query(now.year, now.month)

        # 3. Detect Intent: Recurring bills & subscriptions
        if any(k in q_lower for k in ("recurring", "commitments", "subscriptions", "monthly bills")):
            return self._handle_recurring_commitments_query()

        # 4. Detect Intent: Category inquiry ("How much on food/travel/etc.?")
        cats = self.store.list_categories()
        matched_cat = next((c for c in cats if c.lower() in q_lower), None)
        if matched_cat and any(k in q_lower for k in ("how much", "what did i spend", "spent on", "total")):
            return self._handle_category_spend_query(matched_cat, now.year, now.month)

        # 5. Detect Intent: Highest / Largest category ("Which category consumes most?")
        if any(k in q_lower for k in ("which category", "biggest expense", "highest spend", "most of my budget")):
            return self._handle_top_category_query(now.year, now.month)

        # 6. General Monthly/Weekly Summary
        if "week" in q_lower:
            rep = self.analytics.get_weekly_report()
            return (
                f"Sir, over the last 7 days, your total expenses were ₹{rep['total_expense']:.2f} "
                f"across {rep['transaction_count']} transactions (Income: ₹{rep['total_income']:.2f}, "
                f"Net Cash Flow: ₹{rep['net_cash_flow']:.2f})."
            )

        # Default: Current Month Summary
        rep = self.analytics.get_monthly_report(now.year, now.month)
        summary_text = (
            f"Sir, for {rep['month_name']} {now.year}, your total expenditure is ₹{rep['total_expense']:.2f} "
            f"against an income of ₹{rep['total_income']:.2f} (Net Cash Flow: ₹{rep['net_cash_flow']:.2f}, "
            f"Savings Rate: {rep['savings_rate_pct']}%)."
        )
        if rep["category_breakdown"]:
            top = rep["category_breakdown"][0]
            summary_text += f" Your top spending category is {top['category']} at ₹{top['amount']:.2f} ({top['percentage']}%)."
        return summary_text

    def _handle_affordability_query(self, purchase_amount: float) -> str:
        now = datetime.datetime.now()
        budgets = self.analytics.check_all_budget_utilizations(now.year, now.month)
        rep = self.analytics.get_monthly_report(now.year, now.month)

        overall_budget = next((b for b in budgets if b["category"] == "Overall"), None)

        if overall_budget:
            rem = overall_budget["remaining_amount"]
            limit = overall_budget["limit_amount"]
            if purchase_amount <= rem:
                after_purchase = round(rem - purchase_amount, 2)
                return (
                    f"Sir, you currently have ₹{rem:.2f} remaining in your overall monthly budget of ₹{limit:.2f}. "
                    f"A purchase of ₹{purchase_amount:.2f} fits within your budget, leaving you with ₹{after_purchase:.2f} remaining."
                )
            else:
                over = round(purchase_amount - rem, 2)
                return (
                    f"Sir, making a purchase of ₹{purchase_amount:.2f} would exceed your remaining monthly budget by ₹{over:.2f} "
                    f"(Current remaining: ₹{rem:.2f} of ₹{limit:.2f} limit)."
                )

        # If no budget set, base on net cash flow
        net = rep["net_cash_flow"]
        if net >= purchase_amount:
            rem_cash = round(net - purchase_amount, 2)
            return (
                f"Sir, no overall budget limit has been configured. Based on this month's net positive cash flow of ₹{net:.2f}, "
                f"you can afford ₹{purchase_amount:.2f}, which would leave ₹{rem_cash:.2f} in net savings."
            )
        else:
            return (
                f"Sir, no overall budget is set. Your current net cash flow for this month is ₹{net:.2f}. "
                f"A purchase of ₹{purchase_amount:.2f} exceeds this month's net cash flow."
            )

    def _handle_month_comparison_query(self, cur_year: int, cur_month: int) -> str:
        prev_m = 12 if cur_month == 1 else cur_month - 1
        prev_y = cur_year - 1 if cur_month == 1 else cur_year

        comp = self.analytics.compare_months(prev_y, prev_m, cur_year, cur_month)
        diff = comp["expense_diff"]
        pct = comp["expense_pct_change"]

        if diff > 0:
            msg = f"Sir, you spent ₹{diff:.2f} (+{pct}%) more in {comp['month2']} compared to {comp['month1']}."
            top_increase = comp["biggest_increase_category"]
            if top_increase:
                msg += f" The largest increase came from {top_increase['category']} (+₹{top_increase['diff']:.2f}, up {top_increase['pct_change']}%)."
        elif diff < 0:
            msg = f"Sir, your spending decreased by ₹{abs(diff):.2f} ({pct}%) in {comp['month2']} compared to {comp['month1']}."
        else:
            msg = f"Sir, your spending in {comp['month2']} was identical to {comp['month1']} (₹{comp['total_expense_m1']:.2f})."
        return msg

    def _handle_category_spend_query(self, category: str, year: int, month: int) -> str:
        rep = self.analytics.get_monthly_report(year, month)
        cat_item = next((c for c in rep["category_breakdown"] if c["category"].lower() == category.lower()), None)
        if not cat_item or cat_item["amount"] == 0:
            return f"Sir, you haven't recorded any expenses in '{category}' for {rep['month_name']} {year}."

        return (
            f"Sir, in {rep['month_name']} {year}, you spent ₹{cat_item['amount']:.2f} on {category} "
            f"across {cat_item['count']} transaction(s), representing {cat_item['percentage']}% of your total monthly expenditure."
        )

    def _handle_top_category_query(self, year: int, month: int) -> str:
        rep = self.analytics.get_monthly_report(year, month)
        if not rep["category_breakdown"]:
            return f"Sir, there are no recorded expenses for {rep['month_name']} {year} yet."
        top = rep["category_breakdown"][0]
        return (
            f"Sir, your largest expense category this month is {top['category']}, with ₹{top['amount']:.2f} spent "
            f"({top['percentage']}% of total expenses) across {top['count']} transaction(s)."
        )

    def _handle_recurring_commitments_query(self) -> str:
        commit = self.analytics.get_recurring_commitments_summary()
        return (
            f"Sir, your total monthly recurring commitments are ₹{commit['total_monthly_recurring_commitments']:.2f}. "
            f"This includes {commit['pending_bills_count']} pending bill(s) totaling ₹{commit['pending_bills_total']:.2f} "
            f"and {commit['active_subscriptions_count']} active subscription(s) totaling ₹{commit['monthly_subscription_burn']:.2f}/month."
        )
