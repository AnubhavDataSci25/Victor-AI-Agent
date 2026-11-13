"""
Victor Personal Finance, Expense & Bill Management Agent — Data Models.

Defines typed, immutable schemas for transactions, bills, budgets, subscriptions,
receipts, and analytics with deterministic validation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import time
from typing import Any, List, Optional


class TransactionType(str, Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    REFUND = "REFUND"


class BillStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class BillRecurrence(str, Enum):
    NONE = "NONE"
    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"


class BudgetPeriod(str, Enum):
    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"
    CUSTOM = "CUSTOM"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


DEFAULT_CATEGORIES = [
    "Food",
    "Shopping",
    "Travel",
    "Education",
    "Healthcare",
    "Bills",
    "Rent",
    "Utilities",
    "Entertainment",
    "Subscriptions",
    "Personal Care",
    "Electronics",
    "Investments",
    "Income",
    "Others",
]


@dataclass
class Transaction:
    transaction_id: str
    transaction_type: TransactionType
    amount: float
    currency: str = "INR"
    category: str = "Others"
    subcategory: Optional[str] = None
    merchant_or_payee: str = "Unknown"
    transaction_date: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    payment_method: str = "UPI"
    description: str = ""
    receipt_ref: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["transaction_type"] = self.transaction_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transaction:
        copied = dict(data)
        if isinstance(copied.get("transaction_type"), str):
            copied["transaction_type"] = TransactionType(copied["transaction_type"].upper())
        return cls(**copied)


@dataclass
class Bill:
    bill_id: str
    provider_name: str
    category: str = "Bills"
    expected_amount: float = 0.0
    due_date: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))
    recurrence: BillRecurrence = BillRecurrence.MONTHLY
    status: BillStatus = BillStatus.PENDING
    payment_method: str = "UPI"
    amount_paid: float = 0.0
    last_payment_date: Optional[str] = None
    next_due_date: Optional[str] = None
    notes: str = ""
    invoice_ref: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def remaining_amount(self) -> float:
        return max(0.0, round(self.expected_amount - self.amount_paid, 2))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["recurrence"] = self.recurrence.value
        d["status"] = self.status.value
        d["remaining_amount"] = self.remaining_amount
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bill:
        copied = dict(data)
        copied.pop("remaining_amount", None)
        if isinstance(copied.get("recurrence"), str):
            copied["recurrence"] = BillRecurrence(copied["recurrence"].upper())
        if isinstance(copied.get("status"), str):
            copied["status"] = BillStatus(copied["status"].upper())
        return cls(**copied)


@dataclass
class Budget:
    budget_id: str
    name: str
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    category: Optional[str] = None  # None indicates overall budget
    limit_amount: float = 0.0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    alert_thresholds: List[float] = field(default_factory=lambda: [0.70, 0.90, 1.00])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["period"] = self.period.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Budget:
        copied = dict(data)
        if isinstance(copied.get("period"), str):
            copied["period"] = BudgetPeriod(copied["period"].upper())
        if isinstance(copied.get("alert_thresholds"), str):
            # Parse comma-separated thresholds
            copied["alert_thresholds"] = [float(x.strip()) for x in copied["alert_thresholds"].split(",") if x.strip()]
        return cls(**copied)


@dataclass
class Subscription:
    subscription_id: str
    service_name: str
    amount: float
    currency: str = "INR"
    billing_frequency: str = "monthly"  # monthly, yearly, quarterly
    next_renewal_date: str = field(default_factory=lambda: time.strftime("%Y-%m-%d"))
    payment_method: str = "Credit Card"
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Subscription:
        copied = dict(data)
        if isinstance(copied.get("status"), str):
            copied["status"] = SubscriptionStatus(copied["status"].upper())
        return cls(**copied)


@dataclass
class ReceiptScanResult:
    merchant: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    total_amount: Optional[float] = None
    currency: str = "INR"
    tax_or_gst: Optional[float] = None
    items: List[dict[str, Any]] = field(default_factory=list)
    payment_method: Optional[str] = None
    suggested_category: str = "Shopping"
    confidence: float = 0.0
    raw_text: str = ""
    is_duplicate: bool = False
    duplicate_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
