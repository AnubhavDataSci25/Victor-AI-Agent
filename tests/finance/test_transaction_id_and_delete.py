"""
Unit tests for Monthly Transaction ID generation (e.g. NOVT001)
and multi-layer intelligent transaction deletion in Victor Personal Finance.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import pytest

from app.finance.manager import FinanceManager
from app.finance.models import Transaction, TransactionType
from app.finance.store import FinanceStore
from app.finance.tools import FinanceDeleteTransactionTool


@pytest.fixture
def temp_store(tmp_path: Path) -> FinanceStore:
    db_file = tmp_path / "test_tx_ids.db"
    return FinanceStore(db_path=db_file)


@pytest.fixture
def temp_manager(tmp_path: Path) -> FinanceManager:
    db_file = tmp_path / "test_tx_mgr.db"
    return FinanceManager(db_path=db_file)


def test_monthly_transaction_id_format(temp_store: FinanceStore):
    # Test current date
    id1 = temp_store.generate_next_transaction_id("2026-11-14 10:00:00")
    assert id1 == "NOVT001"

    # Add transaction with this ID
    temp_store.add_transaction(
        Transaction(
            transaction_id=id1,
            transaction_type=TransactionType.EXPENSE,
            amount=100.0,
            currency="INR",
            category="Food",
            merchant_or_payee="Tea Shop",
            transaction_date="2026-11-14 10:00:00",
            payment_method="UPI",
        )
    )

    # Next one should be NOVT002
    id2 = temp_store.generate_next_transaction_id("2026-11-14 11:00:00")
    assert id2 == "NOVT002"

    # December transaction should have DECT001
    id_dec = temp_store.generate_next_transaction_id("2026-12-01 09:00:00")
    assert id_dec == "DECT001"


def test_manager_records_with_monthly_id(temp_manager: FinanceManager):
    rec = temp_manager.record_transaction(
        amount=250.0,
        merchant_or_payee="Metro Ticket",
        category="Travel",
        transaction_date="2026-11-14 12:00:00",
    )
    assert rec["success"] is True
    assert rec["transaction_id"].startswith("NOVT")
    assert rec["transaction_id"] == "NOVT001"

    rec2 = temp_manager.record_transaction(
        amount=50.0,
        merchant_or_payee="Snacks",
        category="Food",
        transaction_date="2026-11-14 13:00:00",
    )
    assert rec2["success"] is True
    assert rec2["transaction_id"] == "NOVT002"


def test_delete_by_exact_and_case_insensitive_id(temp_manager: FinanceManager):
    rec = temp_manager.record_transaction(
        amount=350.0,
        merchant_or_payee="Auto wala",
        category="Travel",
        transaction_date="2026-11-13 14:00:00",
    )
    tx_id = rec["transaction_id"]  # e.g. NOVT001

    # Delete using lowercase
    del_res = temp_manager.delete_transaction(tx_id.lower())
    assert del_res["success"] is True
    assert del_res["transaction_id"] == tx_id
    assert temp_manager.store.get_transaction(tx_id) is None


def test_delete_by_cleaned_id_with_spaces_and_hashes(temp_manager: FinanceManager):
    rec = temp_manager.record_transaction(
        amount=400.0,
        merchant_or_payee="Book Store",
        category="Education",
        transaction_date="2026-11-14 10:00:00",
    )
    tx_id = rec["transaction_id"]  # e.g. NOVT001

    # Delete using "NOV T 001" or "#novt-001"
    del_res = temp_manager.delete_transaction("#novt-001")
    assert del_res["success"] is True
    assert del_res["transaction_id"] == tx_id
    assert temp_manager.store.get_transaction(tx_id) is None


def test_delete_by_number_shortcut(temp_manager: FinanceManager):
    rec = temp_manager.record_transaction(
        amount=120.0,
        merchant_or_payee="Juice Bar",
        category="Food",
        transaction_date="2026-11-14 15:00:00",
    )
    tx_id = rec["transaction_id"]  # NOVT001

    # Delete using "1" or "001"
    del_res = temp_manager.delete_transaction("1")
    assert del_res["success"] is True
    assert del_res["transaction_id"] == tx_id
    assert temp_manager.store.get_transaction(tx_id) is None


def test_delete_by_merchant_name(temp_manager: FinanceManager):
    temp_manager.record_transaction(
        amount=750.0,
        merchant_or_payee="Biryani House",
        category="Food",
        transaction_date="2026-11-14 16:00:00",
    )
    # Delete by merchant parameter or passed in transaction_id
    del_res = temp_manager.delete_transaction(merchant="Biryani")
    assert del_res["success"] is True
    assert "Biryani House" in del_res["message"]

    # Delete where LLM passed merchant string into transaction_id
    temp_manager.record_transaction(
        amount=350.0,
        merchant_or_payee="Auto wala",
        category="Travel",
        transaction_date="2026-11-14 17:00:00",
    )
    del_res2 = temp_manager.delete_transaction(transaction_id="Auto wala")
    assert del_res2["success"] is True
    assert "Auto wala" in del_res2["message"]


def test_delete_by_amount(temp_manager: FinanceManager):
    temp_manager.record_transaction(
        amount=899.0,
        merchant_or_payee="Headphones Store",
        category="Electronics",
        transaction_date="2026-11-14 18:00:00",
    )
    # LLM passes amount in amount or transaction_id="899"
    del_res = temp_manager.delete_transaction(amount=899.0)
    assert del_res["success"] is True
    assert "Headphones Store" in del_res["message"]

    # Also test transaction_id="₹899"
    temp_manager.record_transaction(
        amount=899.0,
        merchant_or_payee="Headphones Store 2",
        category="Electronics",
        transaction_date="2026-11-14 18:30:00",
    )
    del_res2 = temp_manager.delete_transaction(transaction_id="₹899")
    assert del_res2["success"] is True


def test_delete_last_transaction(temp_manager: FinanceManager):
    temp_manager.record_transaction(amount=10.0, merchant_or_payee="Item 1")
    temp_manager.record_transaction(amount=20.0, merchant_or_payee="Item 2")

    del_res = temp_manager.delete_transaction("last")
    assert del_res["success"] is True
    assert "Item 2" in del_res["message"]


@pytest.mark.asyncio
async def test_finance_delete_tool_execution(temp_manager: FinanceManager):
    temp_manager.record_transaction(
        amount=350.0,
        merchant_or_payee="Auto wala",
        category="Travel",
        transaction_date="2026-11-14 12:00:00",
    )

    tool = FinanceDeleteTransactionTool(manager=temp_manager)

    # 1. Test by merchant
    msg = await tool.execute({"merchant": "auto"})
    assert "Sir, " in msg
    assert "Auto wala" in msg
    assert "successfully deleted" in msg

    # 2. Record and delete by ID
    rec = temp_manager.record_transaction(
        amount=750.0,
        merchant_or_payee="Biryani House",
        category="Food",
        transaction_date="2026-11-14 13:00:00",
    )
    tid = rec["transaction_id"]

    msg2 = await tool.execute({"transaction_id": tid.lower()})
    assert "Sir, " in msg2
    assert tid in msg2
    assert "successfully deleted" in msg2
