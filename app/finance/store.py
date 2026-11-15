"""
Victor Personal Finance, Expense & Bill Management Agent — SQLite Store.

Provides persistent, restart-safe, ACID-compliant storage for:
- Transactions (income, expense, refund)
- Categories
- Bills (one-time and recurring)
- Budgets and threshold tracking
- Subscriptions
- Receipt/invoice metadata and hash deduplication
- Audit trail

All calculations and queries are 100% deterministic with SQLite indexes.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, List, Optional, Tuple

from app.finance.models import (
    DEFAULT_CATEGORIES,
    Bill,
    BillRecurrence,
    BillStatus,
    Budget,
    BudgetPeriod,
    Subscription,
    SubscriptionStatus,
    Transaction,
    TransactionType,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "finance.db"


class FinanceStore:
    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Categories
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    name TEXT PRIMARY KEY,
                    description TEXT,
                    created_at REAL NOT NULL
                );
            """)

            # Transactions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    transaction_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'INR',
                    category TEXT NOT NULL,
                    subcategory TEXT,
                    merchant_or_payee TEXT NOT NULL,
                    transaction_date TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    description TEXT,
                    receipt_ref TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(transaction_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(transaction_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_txn_merchant ON transactions(merchant_or_payee);")

            # Bills
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bills (
                    bill_id TEXT PRIMARY KEY,
                    provider_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    expected_amount REAL NOT NULL,
                    due_date TEXT NOT NULL,
                    recurrence TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    amount_paid REAL NOT NULL DEFAULT 0.0,
                    last_payment_date TEXT,
                    next_due_date TEXT,
                    notes TEXT,
                    invoice_ref TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bill_due_date ON bills(due_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bill_status ON bills(status);")

            # Budgets
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS budgets (
                    budget_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    period TEXT NOT NULL,
                    category TEXT,
                    limit_amount REAL NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    alert_thresholds TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)

            # Subscriptions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    service_name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'INR',
                    billing_frequency TEXT NOT NULL,
                    next_renewal_date TEXT NOT NULL,
                    payment_method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_renewal ON subscriptions(next_renewal_date);")

            # Receipts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS receipt_records (
                    receipt_id TEXT PRIMARY KEY,
                    invoice_number TEXT,
                    merchant TEXT,
                    amount REAL,
                    invoice_date TEXT,
                    file_hash TEXT,
                    metadata_json TEXT,
                    created_at REAL NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rcpt_inv ON receipt_records(invoice_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rcpt_hash ON receipt_records(file_hash);")

            # Audit Log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS financial_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    details TEXT,
                    timestamp REAL NOT NULL
                );
            """)

            # Populate default categories if empty
            cursor.execute("SELECT COUNT(*) FROM categories;")
            if cursor.fetchone()[0] == 0:
                now = time.time()
                for cat in DEFAULT_CATEGORIES:
                    cursor.execute(
                        "INSERT OR IGNORE INTO categories (name, description, created_at) VALUES (?, ?, ?);",
                        (cat, f"Default category for {cat}", now),
                    )

            # Migrate legacy 'txn_%' IDs to standard monthly format (e.g. NOVT001)
            cursor.execute(
                "SELECT transaction_id, transaction_date, created_at FROM transactions WHERE transaction_id LIKE 'txn_%' ORDER BY transaction_date ASC, created_at ASC;"
            )
            legacy_rows = cursor.fetchall()
            if legacy_rows:
                logger.info(f"[FinanceStore] Migrating {len(legacy_rows)} legacy transaction IDs to monthly format...")
                for row in legacy_rows:
                    old_id = row["transaction_id"]
                    t_date = row["transaction_date"]
                    dt = None
                    try:
                        date_str = str(t_date).strip().replace("Z", "+00:00")
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                dt = datetime.datetime.strptime(date_str[:19], fmt)
                                break
                            except Exception:
                                continue
                        if dt is None:
                            dt = datetime.datetime.fromisoformat(date_str)
                    except Exception:
                        dt = datetime.datetime.now()

                    m_abbr = dt.strftime("%b").upper()
                    m_pfx = f"{m_abbr}T"

                    cursor.execute(
                        "SELECT transaction_id FROM transactions WHERE UPPER(transaction_id) LIKE ?;",
                        (f"{m_pfx}%",)
                    )
                    existing = [r[0].upper().strip() for r in cursor.fetchall() if not r[0].startswith("txn_")]
                    m_nums = [int(x[len(m_pfx):]) for x in existing if x[len(m_pfx):].isdigit()]
                    nxt = max(m_nums) + 1 if m_nums else 1
                    new_id = f"{m_pfx}{nxt:03d}"

                    cursor.execute(
                        "UPDATE transactions SET transaction_id = ? WHERE transaction_id = ?;",
                        (new_id, old_id)
                    )
                    logger.info(f"[FinanceStore] Migrated transaction {old_id} -> {new_id}")

            conn.commit()

    # =========================================================================
    # CATEGORIES
    # =========================================================================
    def list_categories(self) -> List[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM categories ORDER BY name ASC;")
            return [row["name"] for row in cursor.fetchall()]

    def add_category(self, name: str, description: str = "") -> bool:
        norm = name.strip().title()
        if not norm:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO categories (name, description, created_at) VALUES (?, ?, ?);",
                (norm, description, time.time()),
            )
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # TRANSACTIONS
    # =========================================================================
    def generate_next_transaction_id(self, date_str: Optional[str] = None) -> str:
        """
        Generates a unique monthly formatted transaction ID:
        e.g., 'NOVT001', containing Month abbreviation ('NOV'), 'T' (Transaction),
        and the 3-digit transaction sequence number of that specific month ('001').
        """
        dt = None
        if date_str:
            date_cleaned = str(date_str).strip().replace("Z", "+00:00")
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.datetime.strptime(date_cleaned[:19], fmt)
                    break
                except Exception:
                    continue
            if dt is None:
                try:
                    dt = datetime.datetime.fromisoformat(date_cleaned)
                except Exception:
                    pass
        if dt is None:
            dt = datetime.datetime.now()

        month_abbr = dt.strftime("%b").upper()
        prefix = f"{month_abbr}T"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT transaction_id FROM transactions WHERE UPPER(transaction_id) LIKE ?;",
                (f"{prefix}%",),
            )
            rows = cursor.fetchall()

            max_num = 0
            for row in rows:
                tid = str(row["transaction_id"]).upper().strip()
                suffix = tid[len(prefix):]
                if suffix.isdigit():
                    num = int(suffix)
                    if num > max_num:
                        max_num = num

            next_num = max_num + 1
            cand_id = f"{prefix}{next_num:03d}"

            # Safety against race/collision
            while True:
                cursor.execute(
                    "SELECT 1 FROM transactions WHERE UPPER(transaction_id) = UPPER(?);",
                    (cand_id,),
                )
                if not cursor.fetchone():
                    break
                next_num += 1
                cand_id = f"{prefix}{next_num:03d}"

            return cand_id

    def add_transaction(self, txn: Transaction) -> str:
        if txn.amount <= 0:
            raise ValueError(f"Transaction amount must be strictly greater than 0, got {txn.amount}")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO transactions (
                    transaction_id, transaction_type, amount, currency, category, subcategory,
                    merchant_or_payee, transaction_date, payment_method, description,
                    receipt_ref, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    txn.transaction_id,
                    txn.transaction_type.value,
                    round(txn.amount, 2),
                    txn.currency,
                    txn.category,
                    txn.subcategory,
                    txn.merchant_or_payee,
                    txn.transaction_date,
                    txn.payment_method,
                    txn.description,
                    txn.receipt_ref,
                    txn.created_at,
                    txn.updated_at,
                ),
            )
            self._log_audit_conn(conn, "CREATE", "TRANSACTION", txn.transaction_id, f"{txn.transaction_type.value} of {txn.amount} {txn.currency} to {txn.merchant_or_payee}")
            conn.commit()
        return txn.transaction_id

    def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        norm = (transaction_id or "").strip()
        if not norm:
            return None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE LOWER(transaction_id) = LOWER(?);", (norm,))
            row = cursor.fetchone()
            if not row:
                return None
            return Transaction.from_dict(dict(row))

    def update_transaction(self, txn: Transaction) -> bool:
        if txn.amount <= 0:
            raise ValueError(f"Transaction amount must be strictly greater than 0, got {txn.amount}")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            txn.updated_at = time.time()
            cursor.execute(
                """
                UPDATE transactions SET
                    transaction_type = ?, amount = ?, currency = ?, category = ?, subcategory = ?,
                    merchant_or_payee = ?, transaction_date = ?, payment_method = ?,
                    description = ?, receipt_ref = ?, updated_at = ?
                WHERE LOWER(transaction_id) = LOWER(?);
                """,
                (
                    txn.transaction_type.value,
                    round(txn.amount, 2),
                    txn.currency,
                    txn.category,
                    txn.subcategory,
                    txn.merchant_or_payee,
                    txn.transaction_date,
                    txn.payment_method,
                    txn.description,
                    txn.receipt_ref,
                    txn.updated_at,
                    txn.transaction_id.strip(),
                ),
            )
            self._log_audit_conn(conn, "UPDATE", "TRANSACTION", txn.transaction_id, f"Updated amount to {txn.amount}")
            conn.commit()
            return cursor.rowcount > 0

    def delete_transaction(self, transaction_id: str) -> bool:
        norm = (transaction_id or "").strip()
        if not norm:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transactions WHERE LOWER(transaction_id) = LOWER(?);", (norm,))
            deleted = cursor.rowcount > 0
            if deleted:
                self._log_audit_conn(conn, "DELETE", "TRANSACTION", norm, "Deleted transaction")
            conn.commit()
            return deleted

    def find_transaction_to_delete(
        self,
        identifier: Optional[str] = None,
        merchant: Optional[str] = None,
        amount: Optional[float] = None,
        category: Optional[str] = None,
    ) -> Optional[Transaction]:
        """
        Intelligently resolves a transaction candidate for deletion across multiple strategies:
        1. Exact or case-insensitive ID match (e.g. 'NOVT001', 'novt001').
        2. Cleaned ID match (e.g. 'NOVT 001', 'NOVT-001', 'novt 1' -> 'NOVT001').
        3. Numeric sequence match (e.g. '1', '001', '#1' -> matches current/recent month 'T001').
        4. Relative keywords ('last', 'latest', 'recent').
        5. Amount, merchant, and/or category matching against recent records.
        """
        raw_id = (identifier or "").strip()

        # Strategy 1: Explicit relative keyword or empty without other filters
        if raw_id.lower() in ("last", "latest", "recent") or (not raw_id and merchant is None and amount is None and category is None):
            recent = self.list_transactions(limit=1)
            return recent[0] if recent else None

        # Strategy 2: Exact or case-insensitive ID check
        if raw_id:
            direct = self.get_transaction(raw_id)
            if direct:
                return direct

            # Normalize spaces, hyphens, hashes: e.g. "NOVT 001" -> "NOVT001", "novt-1" -> "NOVT1"
            clean = raw_id.replace(" ", "").replace("-", "").replace("#", "").upper()
            direct = self.get_transaction(clean)
            if direct:
                return direct

            # If user said "NOVT1" or "NOV T 1", pad numeric suffix: "NOVT1" -> "NOVT001"
            import re
            m = re.match(r"^([A-Z]{3}T)(\d+)$", clean)
            if m:
                pfx, num_part = m.group(1), m.group(2)
                padded_id = f"{pfx}{int(num_part):03d}"
                direct = self.get_transaction(padded_id)
                if direct:
                    return direct

            # Strategy 3: Pure digits or "T" + digits: e.g. "1", "001", "T001", "T1"
            digit_str = None
            if clean.isdigit():
                digit_str = clean
            elif clean.startswith("T") and clean[1:].isdigit():
                digit_str = clean[1:]

            if digit_str:
                target_suffix = f"T{int(digit_str):03d}"
                # Search transactions ending with this suffix, ordered by transaction_date desc
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT * FROM transactions WHERE UPPER(transaction_id) LIKE ? ORDER BY transaction_date DESC, created_at DESC LIMIT 5;",
                        (f"%{target_suffix}",),
                    )
                    rows = cursor.fetchall()
                    if rows:
                        return Transaction.from_dict(dict(rows[0]))

            # Strategy 4: What if raw_id is actually an amount or merchant string mistakenly placed in identifier?
            # E.g. raw_id = "350" or "350.00" or "₹350"
            if amount is None:
                cleaned_amt = raw_id.replace("₹", "").replace("Rs", "").replace("rs", "").replace(",", "").strip()
                try:
                    parsed_amt = float(cleaned_amt)
                    if parsed_amt > 0:
                        amount = parsed_amt
                        raw_id = ""  # Cleared so it doesn't block merchant check
                except ValueError:
                    pass

            # E.g. raw_id = "Auto wala" or "Biryani House" -> treat as merchant if not set
            if raw_id and not merchant:
                merchant = raw_id

        # Strategy 5: Filter recent transactions by amount, merchant, and category
        candidates = self.list_transactions(limit=50)

        # Apply amount filter if specified (tolerance 0.05)
        if amount is not None:
            amt_val = float(amount)
            candidates = [t for t in candidates if abs(t.amount - amt_val) < 0.05]

        # Apply merchant / payee fuzzy/substring filter if specified
        if merchant:
            m_lower = merchant.lower().strip()
            # Try exact/substring match on merchant_or_payee or description
            m_matched = [
                t for t in candidates
                if m_lower in t.merchant_or_payee.lower() or m_lower in (t.description or "").lower()
            ]
            if m_matched:
                candidates = m_matched
            else:
                # If no direct match in amount-filtered candidates, search across all recent transactions
                all_recent = self.list_transactions(limit=50)
                fallback_m = [
                    t for t in all_recent
                    if m_lower in t.merchant_or_payee.lower() or m_lower in (t.description or "").lower()
                ]
                if fallback_m:
                    if amount is not None:
                        # Find closest matching amount
                        closest = min(fallback_m, key=lambda t: abs(t.amount - float(amount)))
                        return closest
                    return fallback_m[0]

        # Apply category filter if specified
        if category:
            c_lower = category.lower().strip()
            c_matched = [t for t in candidates if c_lower == t.category.lower()]
            if c_matched:
                candidates = c_matched

        if candidates:
            return candidates[0]

        return None

    def list_transactions(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category: Optional[str] = None,
        txn_type: Optional[TransactionType | str] = None,
        merchant: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Transaction]:
        query = "SELECT * FROM transactions WHERE 1=1"
        params: List[Any] = []

        if start_date:
            query += " AND transaction_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND transaction_date <= ?"
            params.append(end_date)
        if category:
            query += " AND category = ?"
            params.append(category)
        if txn_type:
            val = txn_type.value if isinstance(txn_type, TransactionType) else str(txn_type).upper()
            query += " AND transaction_type = ?"
            params.append(val)
        if merchant:
            query += " AND merchant_or_payee LIKE ?"
            params.append(f"%{merchant}%")

        query += " ORDER BY transaction_date DESC, created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [Transaction.from_dict(dict(row)) for row in cursor.fetchall()]

    def check_duplicate_transaction(
        self,
        amount: float,
        merchant_or_payee: str,
        transaction_date: str,
        threshold_hours: float = 24.0,
    ) -> Optional[Transaction]:
        """
        Detects if a transaction with the same amount, payee, and close timestamp exists.
        """
        # Search transactions with exact amount and matching payee
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM transactions
                WHERE amount = ? AND LOWER(merchant_or_payee) = LOWER(?)
                ORDER BY created_at DESC LIMIT 5;
                """,
                (round(amount, 2), merchant_or_payee.strip()),
            )
            rows = cursor.fetchall()
            if not rows:
                return None

            # Parse transaction_date and compare within threshold window
            try:
                base_dt = datetime.datetime.fromisoformat(transaction_date.replace("Z", "+00:00"))
            except Exception:
                try:
                    base_dt = datetime.datetime.strptime(transaction_date[:10], "%Y-%m-%d")
                except Exception:
                    base_dt = datetime.datetime.now()

            for row in rows:
                cand = Transaction.from_dict(dict(row))
                try:
                    cand_dt = datetime.datetime.fromisoformat(cand.transaction_date.replace("Z", "+00:00"))
                except Exception:
                    try:
                        cand_dt = datetime.datetime.strptime(cand.transaction_date[:10], "%Y-%m-%d")
                    except Exception:
                        continue
                diff = abs((base_dt - cand_dt).total_seconds()) / 3600.0
                if diff <= threshold_hours:
                    return cand
            return None

    # =========================================================================
    # BILLS
    # =========================================================================
    def add_bill(self, bill: Bill) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO bills (
                    bill_id, provider_name, category, expected_amount, due_date, recurrence,
                    status, payment_method, amount_paid, last_payment_date, next_due_date,
                    notes, invoice_ref, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    bill.bill_id,
                    bill.provider_name,
                    bill.category,
                    round(bill.expected_amount, 2),
                    bill.due_date,
                    bill.recurrence.value,
                    bill.status.value,
                    bill.payment_method,
                    round(bill.amount_paid, 2),
                    bill.last_payment_date,
                    bill.next_due_date,
                    bill.notes,
                    bill.invoice_ref,
                    bill.created_at,
                    bill.updated_at,
                ),
            )
            self._log_audit_conn(conn, "CREATE", "BILL", bill.bill_id, f"Bill for {bill.provider_name} of {bill.expected_amount} due {bill.due_date}")
            conn.commit()
        return bill.bill_id

    def get_bill(self, bill_id: str) -> Optional[Bill]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bills WHERE bill_id = ?;", (bill_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Bill.from_dict(dict(row))

    def update_bill(self, bill: Bill) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            bill.updated_at = time.time()
            cursor.execute(
                """
                UPDATE bills SET
                    provider_name = ?, category = ?, expected_amount = ?, due_date = ?,
                    recurrence = ?, status = ?, payment_method = ?, amount_paid = ?,
                    last_payment_date = ?, next_due_date = ?, notes = ?, invoice_ref = ?,
                    updated_at = ?
                WHERE bill_id = ?;
                """,
                (
                    bill.provider_name,
                    bill.category,
                    round(bill.expected_amount, 2),
                    bill.due_date,
                    bill.recurrence.value,
                    bill.status.value,
                    bill.payment_method,
                    round(bill.amount_paid, 2),
                    bill.last_payment_date,
                    bill.next_due_date,
                    bill.notes,
                    bill.invoice_ref,
                    bill.updated_at,
                    bill.bill_id,
                ),
            )
            self._log_audit_conn(conn, "UPDATE", "BILL", bill.bill_id, f"Updated bill {bill.bill_id} status={bill.status.value}")
            conn.commit()
            return cursor.rowcount > 0

    def delete_bill(self, bill_id: str) -> bool:
        """Deletes a bill record from persistent storage."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM bills WHERE bill_id = ?;", (bill_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                self._log_audit_conn(conn, "DELETE", "BILL", bill_id, f"Deleted bill {bill_id}")
            return deleted

    def mark_bill_paid(
        self,
        bill_id: str,
        amount_paid: float,
        payment_date: Optional[str] = None,
    ) -> Tuple[Optional[Bill], Optional[Bill]]:
        """
        Marks a bill as paid or partially paid.
        If fully paid and recurring, automatically computes and schedules the next cycle.
        Returns: (updated_current_bill, spawned_next_bill_if_recurring)
        """
        bill = self.get_bill(bill_id)
        if not bill:
            return None, None

        pay_dt = payment_date or time.strftime("%Y-%m-%d")
        total_paid = round(bill.amount_paid + amount_paid, 2)
        bill.amount_paid = total_paid
        bill.last_payment_date = pay_dt

        spawned_bill: Optional[Bill] = None

        if total_paid >= bill.expected_amount:
            bill.status = BillStatus.PAID
            # If recurring, spawn next cycle
            if bill.recurrence != BillRecurrence.NONE:
                next_date = self._calculate_next_recurrence_date(bill.due_date, bill.recurrence)
                spawned_bill = Bill(
                    bill_id=f"bill_{hashlib.md5(f'{bill.provider_name}_{next_date}_{time.time()}'.encode()).hexdigest()[:10]}",
                    provider_name=bill.provider_name,
                    category=bill.category,
                    expected_amount=bill.expected_amount,
                    due_date=next_date,
                    recurrence=bill.recurrence,
                    status=BillStatus.PENDING,
                    payment_method=bill.payment_method,
                    amount_paid=0.0,
                    notes=f"Recurring cycle spawned after payment of {bill.bill_id}",
                    invoice_ref=None,
                )
                bill.next_due_date = next_date
        else:
            bill.status = BillStatus.PARTIALLY_PAID

        self.update_bill(bill)
        if spawned_bill:
            self.add_bill(spawned_bill)

        return bill, spawned_bill

    @staticmethod
    def _calculate_next_recurrence_date(current_date_str: str, recurrence: BillRecurrence) -> str:
        try:
            dt = datetime.datetime.strptime(current_date_str[:10], "%Y-%m-%d")
        except Exception:
            dt = datetime.datetime.now()

        if recurrence == BillRecurrence.MONTHLY:
            # Advance 1 month
            month = dt.month + 1
            year = dt.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            # Adjust for variable month day length (e.g. Feb)
            import calendar
            max_day = calendar.monthrange(year, month)[1]
            day = min(dt.day, max_day)
            next_dt = dt.replace(year=year, month=month, day=day)
        elif recurrence == BillRecurrence.WEEKLY:
            next_dt = dt + datetime.timedelta(days=7)
        elif recurrence == BillRecurrence.QUARTERLY:
            month = dt.month + 3
            year = dt.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            import calendar
            max_day = calendar.monthrange(year, month)[1]
            day = min(dt.day, max_day)
            next_dt = dt.replace(year=year, month=month, day=day)
        elif recurrence == BillRecurrence.YEARLY:
            next_dt = dt.replace(year=dt.year + 1)
        else:
            next_dt = dt
        return next_dt.strftime("%Y-%m-%d")

    def list_bills(
        self,
        status: Optional[BillStatus | str] = None,
        category: Optional[str] = None,
    ) -> List[Bill]:
        query = "SELECT * FROM bills WHERE 1=1"
        params: List[Any] = []

        if status:
            val = status.value if isinstance(status, BillStatus) else str(status).upper()
            query += " AND status = ?"
            params.append(val)
        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY due_date ASC, provider_name ASC;"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [Bill.from_dict(dict(row)) for row in cursor.fetchall()]

    def get_pending_and_overdue_bills(self) -> List[Bill]:
        today = time.strftime("%Y-%m-%d")
        # Update any pending bills past due date to OVERDUE
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE bills SET status = 'OVERDUE' WHERE status = 'PENDING' AND due_date < ?;",
                (today,),
            )
            conn.commit()

        return self.list_bills(status=None)

    # =========================================================================
    # BUDGETS
    # =========================================================================
    def set_budget(self, budget: Budget) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            thresholds_str = ",".join(str(x) for x in budget.alert_thresholds)
            cursor.execute(
                """
                INSERT INTO budgets (
                    budget_id, name, period, category, limit_amount, start_date, end_date,
                    alert_thresholds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(budget_id) DO UPDATE SET
                    name = excluded.name,
                    period = excluded.period,
                    category = excluded.category,
                    limit_amount = excluded.limit_amount,
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    alert_thresholds = excluded.alert_thresholds,
                    updated_at = excluded.updated_at;
                """,
                (
                    budget.budget_id,
                    budget.name,
                    budget.period.value,
                    budget.category,
                    round(budget.limit_amount, 2),
                    budget.start_date,
                    budget.end_date,
                    thresholds_str,
                    budget.created_at,
                    time.time(),
                ),
            )
            self._log_audit_conn(conn, "SAVE", "BUDGET", budget.budget_id, f"Budget {budget.name}: limit {budget.limit_amount}")
            conn.commit()
        return budget.budget_id

    def get_budget(self, budget_id: str) -> Optional[Budget]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM budgets WHERE budget_id = ?;", (budget_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Budget.from_dict(dict(row))

    def list_budgets(self) -> List[Budget]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM budgets ORDER BY name ASC;")
            return [Budget.from_dict(dict(row)) for row in cursor.fetchall()]

    def delete_budget(self, budget_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM budgets WHERE budget_id = ?;", (budget_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                self._log_audit_conn(conn, "DELETE", "BUDGET", budget_id, "Deleted budget")
            conn.commit()
            return deleted

    # =========================================================================
    # SUBSCRIPTIONS
    # =========================================================================
    def add_subscription(self, sub: Subscription) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO subscriptions (
                    subscription_id, service_name, amount, currency, billing_frequency,
                    next_renewal_date, payment_method, status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    sub.subscription_id,
                    sub.service_name,
                    round(sub.amount, 2),
                    sub.currency,
                    sub.billing_frequency,
                    sub.next_renewal_date,
                    sub.payment_method,
                    sub.status.value,
                    sub.notes,
                    sub.created_at,
                    sub.updated_at,
                ),
            )
            self._log_audit_conn(conn, "CREATE", "SUBSCRIPTION", sub.subscription_id, f"Subscription {sub.service_name} {sub.amount}")
            conn.commit()
        return sub.subscription_id

    def get_subscription(self, subscription_id: str) -> Optional[Subscription]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE subscription_id = ?;", (subscription_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Subscription.from_dict(dict(row))

    def update_subscription(self, sub: Subscription) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            sub.updated_at = time.time()
            cursor.execute(
                """
                UPDATE subscriptions SET
                    service_name = ?, amount = ?, currency = ?, billing_frequency = ?,
                    next_renewal_date = ?, payment_method = ?, status = ?, notes = ?, updated_at = ?
                WHERE subscription_id = ?;
                """,
                (
                    sub.service_name,
                    round(sub.amount, 2),
                    sub.currency,
                    sub.billing_frequency,
                    sub.next_renewal_date,
                    sub.payment_method,
                    sub.status.value,
                    sub.notes,
                    sub.updated_at,
                    sub.subscription_id,
                ),
            )
            self._log_audit_conn(conn, "UPDATE", "SUBSCRIPTION", sub.subscription_id, f"Updated {sub.service_name} status={sub.status.value}")
            conn.commit()
            return cursor.rowcount > 0

    def list_subscriptions(self, status: Optional[SubscriptionStatus | str] = None) -> List[Subscription]:
        query = "SELECT * FROM subscriptions WHERE 1=1"
        params: List[Any] = []
        if status:
            val = status.value if isinstance(status, SubscriptionStatus) else str(status).upper()
            query += " AND status = ?"
            params.append(val)
        query += " ORDER BY next_renewal_date ASC, service_name ASC;"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [Subscription.from_dict(dict(row)) for row in cursor.fetchall()]

    def delete_subscription(self, subscription_id: str) -> bool:
        """Deletes a tracked subscription from persistent storage."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM subscriptions WHERE subscription_id = ?;", (subscription_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                self._log_audit_conn(conn, "DELETE", "SUBSCRIPTION", subscription_id, f"Deleted subscription {subscription_id}")
            return deleted

    # =========================================================================
    # RECEIPTS & DEDUPLICATION
    # =========================================================================
    def record_receipt(
        self,
        receipt_id: str,
        invoice_number: Optional[str],
        merchant: Optional[str],
        amount: Optional[float],
        invoice_date: Optional[str],
        file_hash: Optional[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO receipt_records (
                    receipt_id, invoice_number, merchant, amount, invoice_date, file_hash, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    receipt_id,
                    invoice_number,
                    merchant,
                    amount,
                    invoice_date,
                    file_hash,
                    json.dumps(metadata or {}),
                    time.time(),
                ),
            )
            conn.commit()

    def check_duplicate_receipt(
        self,
        invoice_number: Optional[str] = None,
        file_hash: Optional[str] = None,
        merchant: Optional[str] = None,
        amount: Optional[float] = None,
        date: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Exact file hash match
            if file_hash:
                cursor.execute("SELECT * FROM receipt_records WHERE file_hash = ? LIMIT 1;", (file_hash,))
                row = cursor.fetchone()
                if row:
                    return {"reason": "Exact file hash matched previous receipt", "receipt": dict(row)}

            # 2. Invoice number + merchant match
            if invoice_number and merchant:
                cursor.execute(
                    "SELECT * FROM receipt_records WHERE LOWER(invoice_number) = LOWER(?) AND LOWER(merchant) = LOWER(?) LIMIT 1;",
                    (invoice_number.strip(), merchant.strip()),
                )
                row = cursor.fetchone()
                if row:
                    return {"reason": f"Invoice number '{invoice_number}' already recorded for {merchant}", "receipt": dict(row)}

            # 3. Same merchant, date, amount
            if merchant and amount and date:
                cursor.execute(
                    "SELECT * FROM receipt_records WHERE LOWER(merchant) = LOWER(?) AND amount = ? AND invoice_date = ? LIMIT 1;",
                    (merchant.strip(), round(amount, 2), date[:10]),
                )
                row = cursor.fetchone()
                if row:
                    return {"reason": f"Duplicate receipt detected: {merchant} of {amount} on {date[:10]}", "receipt": dict(row)}

        return None

    # =========================================================================
    # AUDIT LOGGING
    # =========================================================================
    def _log_audit_conn(self, conn: sqlite3.Connection, action: str, entity_type: str, entity_id: str, details: str) -> None:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO financial_audit_log (action, entity_type, entity_id, details, timestamp)
            VALUES (?, ?, ?, ?, ?);
            """,
            (action, entity_type, entity_id, details, time.time()),
        )
