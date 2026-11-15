"""
Integration and REST API tests for Victor Finance Dashboard endpoints (/api/finance/*).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.finance.api import router as finance_router
from app.finance.manager import FinanceManager
from app.finance.store import FinanceStore
from app.reminders.store import ReminderStore


@pytest.fixture
def client_env(tmp_path: Path):
    db_file = tmp_path / "test_api_finance.db"
    rem_file = tmp_path / "test_api_reminders.db"

    mgr = FinanceManager(db_path=db_file)
    mgr.reminder_manager.reminder_store = ReminderStore(db_path=str(rem_file))

    test_app = FastAPI()
    test_app.include_router(finance_router)

    with patch("app.finance.api.get_finance_manager", return_value=mgr):
        with TestClient(test_app) as client:
            yield client, mgr


def test_get_categories(client_env):
    client, mgr = client_env
    res = client.get("/api/finance/categories")
    assert res.status_code == 200
    data = res.json()
    assert "categories" in data
    assert "Food" in data["categories"]


def test_add_category(client_env):
    client, mgr = client_env
    payload = {"name": "Gaming", "subcategories": ["Steam", "PlayStation"]}
    res = client.post("/api/finance/categories", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res2 = client.get("/api/finance/categories")
    assert "Gaming" in res2.json()["categories"]


def test_transaction_crud_flow(client_env):
    client, mgr = client_env

    # 1. Create Transaction
    tx_payload = {
        "transaction_type": "expense",
        "amount": 850.50,
        "category": "Food",
        "merchant": "Swiggy Test Diner",
        "date": "2026-11-14",
        "payment_method": "UPI",
        "description": "Lunch meeting",
    }
    create_res = client.post("/api/finance/transactions", json=tx_payload)
    assert create_res.status_code == 200
    tx_data = create_res.json()["transaction"]
    tx_id = tx_data["id"]
    assert tx_data["amount"] == 850.50

    # 2. Get Transaction by ID
    get_res = client.get(f"/api/finance/transactions/{tx_id}")
    assert get_res.status_code == 200
    assert get_res.json()["transaction"]["merchant"] == "Swiggy Test Diner"

    # 3. List Transactions
    list_res = client.get("/api/finance/transactions?category=Food")
    assert list_res.status_code == 200
    assert len(list_res.json()["transactions"]) >= 1

    # 4. Patch Transaction
    patch_res = client.patch(f"/api/finance/transactions/{tx_id}", json={"amount": 900.0})
    assert patch_res.status_code == 200
    assert patch_res.json()["transaction"]["amount"] == 900.0

    # 5. Summary calculation
    summary_res = client.get("/api/finance/summary?period=2026-11")
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["total_expenses"] == 900.0

    # 6. Delete Transaction
    del_res = client.delete(f"/api/finance/transactions/{tx_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify deleted
    get_after_del = client.get(f"/api/finance/transactions/{tx_id}")
    assert get_after_del.status_code == 404


def test_budget_flow(client_env):
    client, mgr = client_env

    # 1. Create Budget
    b_payload = {
        "category": "Food",
        "period": "monthly",
        "limit_amount": 5000.0,
    }
    res = client.post("/api/finance/budgets", json=b_payload)
    assert res.status_code == 200
    b_id = res.json()["budget"]["id"]

    # 2. List Budgets
    list_res = client.get("/api/finance/budgets")
    assert list_res.status_code == 200
    assert len(list_res.json()["budgets"]) == 1

    # 3. Delete Budget
    del_res = client.delete(f"/api/finance/budgets/{b_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


def test_bill_and_payment_flow(client_env):
    client, mgr = client_env

    # 1. Create Bill
    bill_payload = {
        "title": "Airtel Fiber Broadband",
        "amount": 1179.0,
        "due_date": "2026-11-20",
        "category": "Utilities",
        "recurrence": "monthly",
        "payment_method": "UPI",
    }
    res = client.post("/api/finance/bills", json=bill_payload)
    assert res.status_code == 200
    bill_id = res.json()["bill"]["id"]

    # 2. List Bills
    bills_res = client.get("/api/finance/bills")
    assert bills_res.status_code == 200
    assert any(b["id"] == bill_id for b in bills_res.json()["bills"])

    # 3. Postpone Bill
    postpone_res = client.post(f"/api/finance/bills/{bill_id}/postpone?days=3")
    assert postpone_res.status_code == 200
    assert postpone_res.json()["bill"]["due_date"] == "2026-11-23"

    # 4. Pay Bill
    pay_res = client.post(f"/api/finance/bills/{bill_id}/pay?payment_method=UPI")
    assert pay_res.status_code == 200
    assert pay_res.json()["bill"]["status"] == "paid"

    # Check that transaction was created automatically
    txs_res = client.get("/api/finance/transactions?category=Utilities")
    assert txs_res.status_code == 200
    assert any("Airtel Fiber Broadband" in t["merchant"] for t in txs_res.json()["transactions"])

    # 5. Delete Bill
    del_res = client.delete(f"/api/finance/bills/{bill_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


def test_subscription_flow(client_env):
    client, mgr = client_env

    # 1. Create Subscription
    sub_payload = {
        "service_name": "Spotify Premium Individual",
        "amount": 119.0,
        "billing_cycle": "monthly",
        "next_renewal_date": "2026-12-05",
        "category": "Entertainment",
        "payment_method": "Auto-debit",
    }
    res = client.post("/api/finance/subscriptions", json=sub_payload)
    assert res.status_code == 200
    sub_id = res.json()["subscription"]["id"]

    # 2. List Subscriptions
    subs_res = client.get("/api/finance/subscriptions")
    assert subs_res.status_code == 200
    assert len(subs_res.json()["subscriptions"]) == 1

    # 3. Delete Subscription
    del_res = client.delete(f"/api/finance/subscriptions/{sub_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


def test_month_comparison_endpoint(client_env):
    client, mgr = client_env

    # Record expense in month 1
    client.post(
        "/api/finance/transactions",
        json={
            "transaction_type": "expense",
            "amount": 2000.0,
            "category": "Food",
            "merchant": "Groceries",
            "date": "2026-10-15",
        },
    )

    # Record expense in month 2
    client.post(
        "/api/finance/transactions",
        json={
            "transaction_type": "expense",
            "amount": 3500.0,
            "category": "Food",
            "merchant": "Fine Dining",
            "date": "2026-11-10",
        },
    )

    res = client.get("/api/finance/comparison?month1=2026-10&month2=2026-11")
    assert res.status_code == 200
    data = res.json()
    assert "October 2026" in data["month1"]
    assert "November 2026" in data["month2"]
    assert data["diff"] == 1500.0
    assert data["pct_change"] == 75.0
    assert data["category_diffs"]["Food"] == 1500.0
