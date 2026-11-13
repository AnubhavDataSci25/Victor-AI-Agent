"""
Comprehensive test suite for Victor's Personal Finance, Expense & Bill Management Agent.

Covers:
- Transactions (expense, income, refund, validation, deduplication)
- Bills (one-time, recurring, partial payment, cycle spawning)
- Budgets (monthly/category utilization, 70%/90%/100% threshold alerts)
- Subscriptions (frequency, monthly burn calculation)
- Receipt & Invoice intelligence
- Deterministic analytics and month-to-month comparisons
- Financial Q&A engine
- ReminderScheduler integration
- ToolRegistry tool registration and execution
"""

from __future__ import annotations

from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.finance.analytics import FinanceAnalytics
from app.finance.manager import FinanceManager
from app.finance.models import (
    BillRecurrence,
    BillStatus,
    BudgetPeriod,
    ReceiptScanResult,
    SubscriptionStatus,
    TransactionType,
)
from app.finance.qa_engine import FinanceQAEngine
from app.finance.receipt_processor import ReceiptProcessor
from app.finance.store import FinanceStore
from app.reminders.models import ReminderStatus
from app.reminders.store import ReminderStore
from app.tools.tool_setup import build_tool_registry


@pytest.fixture
def finance_env(tmp_path: Path):
    db_file = tmp_path / "test_finance.db"
    rem_db = tmp_path / "test_reminders.db"

    store = FinanceStore(db_path=db_file)
    rem_store = ReminderStore(db_path=str(rem_db))

    mgr = FinanceManager(db_path=db_file)
    mgr.reminder_manager.reminder_store = rem_store

    return {
        "store": store,
        "rem_store": rem_store,
        "manager": mgr,
        "db_path": db_file,
    }


# =============================================================================
# 1. EXPENSE, INCOME & REFUND TRANSACTIONS
# =============================================================================
def test_record_expense_income_and_refund(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    # 1. Valid Expense
    res_exp = mgr.record_transaction(
        amount=450.0,
        transaction_type="EXPENSE",
        category="Food",
        merchant_or_payee="Swiggy",
        payment_method="UPI",
        description="Dinner with friends",
    )
    assert res_exp["success"] is True
    assert res_exp["transaction"]["amount"] == 450.0
    assert res_exp["transaction"]["category"] == "Food"

    # 2. Valid Income
    res_inc = mgr.record_transaction(
        amount=15000.0,
        transaction_type="INCOME",
        category="Income",
        merchant_or_payee="Employer Corp",
        payment_method="NetBanking",
        description="Monthly stipend",
    )
    assert res_inc["success"] is True
    assert res_inc["transaction"]["amount"] == 15000.0
    assert res_inc["transaction"]["transaction_type"] == "INCOME"

    # 3. Valid Refund
    res_ref = mgr.record_transaction(
        amount=200.0,
        transaction_type="REFUND",
        category="Shopping",
        merchant_or_payee="Amazon",
        payment_method="UPI",
    )
    assert res_ref["success"] is True
    assert res_ref["transaction"]["transaction_type"] == "REFUND"

    # 4. Invalid Amount rejection
    inv = mgr.record_transaction(amount=-50.0)
    assert inv["success"] is False
    assert "greater than 0" in inv["error"]


def test_transaction_update_and_delete(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    rec = mgr.record_transaction(amount=500.0, category="Food", merchant_or_payee="Cafe")
    tid = rec["transaction_id"]

    # Update amount to 350
    upd = mgr.update_transaction(tid, amount=350.0, description="Corrected bill")
    assert upd["success"] is True
    assert upd["transaction"]["amount"] == 350.0

    # Delete transaction
    del_res = mgr.delete_transaction(tid)
    assert del_res["success"] is True

    # Confirm deletion
    assert mgr.store.get_transaction(tid) is None


def test_duplicate_transaction_detection(finance_env):
    mgr: FinanceManager = finance_env["manager"]
    now_str = "2026-11-14 12:00:00"

    # Record first transaction
    r1 = mgr.record_transaction(
        amount=1200.0,
        category="Utilities",
        merchant_or_payee="BESCOM",
        transaction_date=now_str,
    )
    assert r1["success"] is True

    # Immediate second transaction with same amount and merchant
    r2 = mgr.record_transaction(
        amount=1200.0,
        category="Utilities",
        merchant_or_payee="BESCOM",
        transaction_date=now_str,
    )
    assert r2["success"] is False
    assert r2.get("is_duplicate") is True
    assert "duplicate" in r2["message"].lower()

    # Bypassing duplicate check allows intentional identical transactions
    r3 = mgr.record_transaction(
        amount=1200.0,
        category="Utilities",
        merchant_or_payee="BESCOM",
        transaction_date=now_str,
        bypass_duplicate_check=True,
    )
    assert r3["success"] is True


# =============================================================================
# 2. BILLS & RECURRENCE
# =============================================================================
def test_bill_scheduling_and_partial_payment(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    res = mgr.add_bill(
        provider_name="Airtel Broadband",
        expected_amount=799.0,
        due_date="2026-11-20",
        recurrence="MONTHLY",
    )
    assert res["success"] is True
    bid = res["bill_id"]
    assert res["bill"]["remaining_amount"] == 799.0

    # Partial payment of 300
    part = mgr.pay_bill(bid, amount_paid=300.0, record_as_expense=True)
    assert part["success"] is True
    assert part["bill"]["status"] == "PARTIALLY_PAID"
    assert part["bill"]["remaining_amount"] == 499.0
    assert part["transaction"] is not None

    # Full remaining payment of 499
    full = mgr.pay_bill(bid, amount_paid=499.0, record_as_expense=True)
    assert full["success"] is True
    assert full["bill"]["status"] == "PAID"
    assert full["bill"]["remaining_amount"] == 0.0

    # Recurring cycle should have spawned next month's bill
    next_cycle = full.get("next_cycle_bill")
    assert next_cycle is not None
    assert next_cycle["provider_name"] == "Airtel Broadband"
    assert next_cycle["expected_amount"] == 799.0
    assert next_cycle["status"] == "PENDING"
    assert "2026-12" in next_cycle["due_date"]


@pytest.mark.asyncio
async def test_bill_reminders_and_overdue_detection(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    # 1. Bill due in 2 days
    mgr.add_bill(provider_name="BESCOM", expected_amount=1450.0, due_date="2026-11-16")
    # 2. Overdue bill
    mgr.add_bill(provider_name="Water Board", expected_amount=400.0, due_date="2026-11-10")

    # Verify reminders scheduled in ReminderStore
    rem_store = finance_env["rem_store"]
    rems = rem_store.list_active_reminders()
    assert any("BESCOM" in r.work_task for r in rems)

    # Check tick hook alerts
    with patch("time.strftime", return_value="2026-11-14"):
        alerts = await mgr.reminder_manager.check_due_bills_tick_hook()
        assert len(alerts) >= 2
        statuses = [a["status"] for a in alerts]
        assert "OVERDUE" in statuses
        assert "UPCOMING" in statuses


# =============================================================================
# 3. BUDGET MANAGEMENT & THRESHOLD ALERTS
# =============================================================================
def test_budget_threshold_alerts(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    # Set Monthly Food budget of 1000
    b_res = mgr.set_budget(name="Food Budget", limit_amount=1000.0, category="Food")
    assert b_res["success"] is True

    # Step 1: Spend 600 (60% - No alert)
    r1 = mgr.record_transaction(amount=600.0, category="Food", merchant_or_payee="Groceries")
    assert r1["success"] is True
    assert len(r1["budget_alerts"]) == 0

    # Step 2: Spend 150 (Total 750 = 75% -> Warning 70% threshold crossed)
    r2 = mgr.record_transaction(amount=150.0, category="Food", merchant_or_payee="Snacks")
    assert r2["success"] is True
    assert any("75" in alert or "WARNING" in alert or "75.0%" in alert for alert in r2["budget_alerts"])

    # Step 3: Spend 300 (Total 1050 = 105% -> Over budget alert)
    r3 = mgr.record_transaction(amount=300.0, category="Food", merchant_or_payee="Dinner")
    assert r3["success"] is True
    assert any("105" in alert or "OVER_BUDGET" in alert or "105.0%" in alert for alert in r3["budget_alerts"])


# =============================================================================
# 4. SUBSCRIPTIONS
# =============================================================================
def test_subscription_tracking_and_burn_rate(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    mgr.add_subscription(service_name="Netflix", amount=649.0, billing_frequency="monthly")
    mgr.add_subscription(service_name="Amazon Prime", amount=1499.0, billing_frequency="yearly")

    subs = mgr.list_subscriptions()
    assert len(subs) == 2

    commit = mgr.analytics.get_recurring_commitments_summary()
    # Monthly burn = 649 + (1499 / 12 = ~124.92) = ~773.92
    assert commit["active_subscriptions_count"] == 2
    assert 770.0 <= commit["monthly_subscription_burn"] <= 780.0


# =============================================================================
# 5. DETERMINISTIC ANALYTICS & MONTHLY COMPARISON
# =============================================================================
def test_analytics_and_monthly_comparison(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    # Month 1: October 2026
    mgr.record_transaction(amount=10000.0, transaction_type="INCOME", transaction_date="2026-10-01 10:00:00")
    mgr.record_transaction(amount=2000.0, category="Food", transaction_date="2026-10-05 10:00:00")
    mgr.record_transaction(amount=1000.0, category="Travel", transaction_date="2026-10-10 10:00:00")

    # Month 2: November 2026
    mgr.record_transaction(amount=10000.0, transaction_type="INCOME", transaction_date="2026-11-01 10:00:00")
    mgr.record_transaction(amount=3500.0, category="Food", transaction_date="2026-11-05 10:00:00")
    mgr.record_transaction(amount=500.0, category="Travel", transaction_date="2026-11-10 10:00:00")

    rep_nov = mgr.analytics.get_monthly_report(2026, 11)
    assert rep_nov["total_income"] == 10000.0
    assert rep_nov["total_expense"] == 4000.0
    assert rep_nov["net_cash_flow"] == 6000.0
    assert rep_nov["savings_rate_pct"] == 60.0

    # Compare Oct vs Nov
    comp = mgr.analytics.compare_months(2026, 10, 2026, 11)
    assert comp["total_expense_m1"] == 3000.0
    assert comp["total_expense_m2"] == 4000.0
    assert comp["expense_diff"] == 1000.0
    assert comp["biggest_increase_category"]["category"] == "Food"
    assert comp["biggest_increase_category"]["diff"] == 1500.0


# =============================================================================
# 6. FINANCIAL Q&A GROUNDING (NO HALLUCINATION)
# =============================================================================
@pytest.mark.asyncio
async def test_financial_qa_grounding(finance_env):
    mgr: FinanceManager = finance_env["manager"]

    # Set up budget and transactions
    mgr.set_budget(name="Overall", limit_amount=20000.0)
    mgr.record_transaction(amount=5000.0, category="Food", transaction_date="2026-11-05 10:00:00")

    # Affordability query: Can I afford 5000?
    ans1 = await mgr.answer_financial_query("Can I afford a 5000 rupee purchase?")
    assert "fits within your budget" in ans1 or "remaining" in ans1
    assert "₹15000.00" in ans1 or "15,000" in ans1 or "15000" in ans1

    # Category query: How much on food?
    ans2 = await mgr.answer_financial_query("How much did I spend on food this month?")
    assert "5000.00" in ans2 or "5000" in ans2
    assert "Food" in ans2


# =============================================================================
# 7. RECEIPT OCR & INVOICE INTELLIGENCE
# =============================================================================
@pytest.mark.asyncio
async def test_receipt_scanner_duplicate_prevention(finance_env, tmp_path: Path):
    mgr: FinanceManager = finance_env["manager"]

    sample_receipt = tmp_path / "invoice.jpg"
    sample_receipt.write_bytes(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB\x00C\x00")

    # Mock Gemini extraction response
    mock_json = {
        "merchant": "SuperMart",
        "invoice_number": "INV-9876",
        "invoice_date": "2026-11-14",
        "total_amount": 850.50,
        "currency": "INR",
        "tax_or_gst": 45.0,
        "items": [{"name": "Groceries", "quantity": 1, "price": 850.50}],
        "payment_method": "UPI",
        "suggested_category": "Shopping",
    }

    with patch.object(mgr.receipt_processor, "_extract_with_gemini", return_value=(mock_json, "Raw OCR Text")):
        # First scan with auto-record
        res1 = await mgr.scan_receipt(sample_receipt, auto_record_transaction=True)
        assert res1["success"] is True
        assert res1["scan_result"]["merchant"] == "SuperMart"
        assert res1["scan_result"]["total_amount"] == 850.50
        assert res1["recorded_transaction"] is not None

        # Second scan of identical receipt must be flagged as duplicate
        res2 = await mgr.scan_receipt(sample_receipt, auto_record_transaction=True)
        assert res2["scan_result"]["is_duplicate"] is True
        assert "Duplicate" in res2["message"]
        assert res2["recorded_transaction"] is None  # Never duplicates!


# =============================================================================
# 8. TOOL REGISTRY & GATEWAY EXECUTION
# =============================================================================
@pytest.mark.asyncio
async def test_all_finance_tools_registered_and_executable(finance_env):
    registry = build_tool_registry()

    expected_tools = [
        "finance_record_transaction",
        "finance_update_transaction",
        "finance_delete_transaction",
        "finance_list_transactions",
        "finance_scan_receipt",
        "finance_manage_bill",
        "finance_pay_bill",
        "finance_manage_budget",
        "finance_manage_subscription",
        "finance_generate_report",
        "finance_query",
    ]

    for name in expected_tools:
        tool = registry.get_tool(name)
        assert tool is not None, f"Tool '{name}' is missing from ToolRegistry"

    # Execute finance_record_transaction through tool registry
    rec_tool = registry.get_tool("finance_record_transaction")
    out = await rec_tool.execute({
        "amount": 750.0,
        "category": "Food",
        "merchant_or_payee": f"Biryani House {time.time()}",
        "payment_method": "UPI",
    })
    assert "Sir," in out
    assert "Biryani House" in out


# =============================================================================
# 9. RESTART PERSISTENCE
# =============================================================================
def test_persistence_across_manager_restarts(finance_env):
    mgr: FinanceManager = finance_env["manager"]
    db_path = finance_env["db_path"]

    # Record data
    t_res = mgr.record_transaction(amount=3200.0, category="Electronics", merchant_or_payee="Store")
    tid = t_res["transaction_id"]
    mgr.add_bill(provider_name="Internet", expected_amount=999.0, due_date="2026-11-25")

    # Simulate Victor application restart with new manager instance from same SQLite DB
    restarted_mgr = FinanceManager(db_path=db_path)
    txn = restarted_mgr.store.get_transaction(tid)
    assert txn is not None
    assert txn.amount == 3200.0
    assert txn.category == "Electronics"

    bills = restarted_mgr.list_bills()
    assert any(b["provider_name"] == "Internet" for b in bills)
