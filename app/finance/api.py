"""
Victor Personal Finance — REST API Router.

Exposes verified endpoints for Victor's interactive Finance & Bill Dashboard.
Directly interfaces with the underlying FinanceManager and database.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.finance.manager import get_finance_manager

router = APIRouter(prefix="/api/finance", tags=["finance"])


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------
class TransactionCreateRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount in rupees")
    transaction_type: str = "EXPENSE"
    category: str = "Others"
    subcategory: Optional[str] = None
    merchant_or_payee: Optional[str] = None
    merchant: Optional[str] = None
    payment_method: str = "UPI"
    description: str = ""
    date: Optional[str] = None
    bypass_duplicate_check: bool = False

    def get_merchant(self) -> str:
        return (self.merchant_or_payee or self.merchant or "Unknown").strip()


class TransactionUpdateRequest(BaseModel):
    amount: Optional[float] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    merchant_or_payee: Optional[str] = None
    merchant: Optional[str] = None
    payment_method: Optional[str] = None
    description: Optional[str] = None
    transaction_date: Optional[str] = None
    date: Optional[str] = None
    transaction_type: Optional[str] = None


class CategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""
    subcategories: Optional[List[str]] = None


class BudgetCreateRequest(BaseModel):
    name: Optional[str] = None
    limit_amount: float = Field(..., gt=0)
    period: str = "MONTHLY"
    category: Optional[str] = None
    alert_thresholds: Optional[List[float]] = None

    def get_name(self) -> str:
        if self.name and self.name.strip():
            return self.name.strip()
        cat = self.category or "Overall"
        return f"{cat} Budget"


class BillCreateRequest(BaseModel):
    provider_name: Optional[str] = None
    title: Optional[str] = None
    expected_amount: Optional[float] = None
    amount: Optional[float] = None
    due_date: str = Field(..., min_length=10)
    category: str = "Bills"
    recurrence: str = "MONTHLY"
    payment_method: str = "UPI"
    notes: str = ""

    def get_provider(self) -> str:
        return (self.provider_name or self.title or "Unknown Bill").strip()

    def get_amount(self) -> float:
        val = self.expected_amount if self.expected_amount is not None else self.amount
        if val is None or val <= 0:
            raise ValueError("Amount must be greater than 0")
        return float(val)


class BillPayRequest(BaseModel):
    amount_paid: Optional[float] = None
    payment_date: Optional[str] = None
    payment_method: Optional[str] = "UPI"
    record_as_expense: bool = True


class BillPostponeRequest(BaseModel):
    days: int = Field(default=1, ge=1)


class SubscriptionCreateRequest(BaseModel):
    service_name: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    billing_frequency: Optional[str] = None
    billing_cycle: Optional[str] = None
    next_renewal_date: Optional[str] = None
    category: Optional[str] = "Subscriptions"
    payment_method: str = "Credit Card"
    notes: str = ""

    def get_frequency(self) -> str:
        return (self.billing_frequency or self.billing_cycle or "monthly").lower()


# ---------------------------------------------------------------------------
# Format Normalization Helpers
# ---------------------------------------------------------------------------
def _normalize_tx(tx: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(tx)
    d["id"] = d.get("transaction_id", "")
    d["merchant"] = d.get("merchant_or_payee", "")
    d["date"] = d.get("transaction_date", "")
    return d


def _normalize_bill(bill: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(bill)
    d["id"] = d.get("bill_id", "")
    d["title"] = d.get("provider_name", "")
    d["amount"] = d.get("expected_amount", 0.0)
    if "status" in d:
        d["status"] = str(d["status"]).lower()
    return d


def _normalize_budget(b: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(b)
    d["id"] = d.get("budget_id", "")
    return d


def _normalize_sub(s: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(s)
    d["id"] = d.get("subscription_id", "")
    d["billing_cycle"] = d.get("billing_frequency", "monthly")
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary")
async def get_finance_summary(
    period: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    mgr = get_finance_manager()
    now = datetime.datetime.now()
    y = year or now.year
    m = month or now.month

    if period and "-" in period:
        try:
            parts = period.strip().split("-")
            y = int(parts[0])
            m = int(parts[1])
        except Exception:
            pass

    if start_date and end_date:
        summary = mgr.analytics.get_summary_by_date_range(start_date, end_date)
    else:
        summary = mgr.analytics.get_monthly_report(y, m)

    # Attach recurring commitments info
    commitments = mgr.analytics.get_recurring_commitments_summary()
    summary["recurring_commitments"] = commitments

    # Attach active budgets status
    summary["budgets"] = mgr.analytics.check_all_budget_utilizations(y, m)

    # Attach normalization aliases for frontend / test suites
    summary["total_expenses"] = summary.get("total_expense", 0.0)
    summary["net_savings"] = summary.get("net_cash_flow", 0.0)
    summary["savings_rate"] = summary.get("savings_rate_pct", 0.0)
    if isinstance(summary.get("category_breakdown"), list):
        summary["category_breakdown_dict"] = {
            c["category"]: c["amount"] for c in summary["category_breakdown"]
        }

    return summary


@router.get("/transactions")
async def get_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    transaction_type: Optional[str] = None,
    merchant: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    mgr = get_finance_manager()
    txns = mgr.list_transactions(
        start_date=start_date,
        end_date=end_date,
        category=category,
        txn_type=transaction_type,
        merchant=merchant,
        limit=limit,
        offset=offset,
    )
    normalized = [_normalize_tx(t) for t in txns]
    return {"transactions": normalized, "count": len(normalized)}


@router.get("/transactions/{transaction_id}")
async def get_transaction(transaction_id: str):
    mgr = get_finance_manager()
    tx = mgr.get_transaction(transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    norm = _normalize_tx(tx.to_dict())
    return {"transaction": norm, "status": "ok"}


@router.post("/transactions")
async def create_transaction(req: TransactionCreateRequest):
    mgr = get_finance_manager()
    res = mgr.record_transaction(
        amount=req.amount,
        transaction_type=req.transaction_type,
        category=req.category,
        subcategory=req.subcategory,
        merchant_or_payee=req.get_merchant(),
        transaction_date=req.date,
        payment_method=req.payment_method,
        description=req.description,
        bypass_duplicate_check=req.bypass_duplicate_check,
    )
    if not res.get("success"):
        if res.get("is_duplicate"):
            return {"success": False, "is_duplicate": True, "message": res["message"]}
        raise HTTPException(status_code=400, detail=res.get("error", "Failed recording transaction"))

    tx_dict = res.get("transaction", {})
    if tx_dict:
        res["transaction"] = _normalize_tx(tx_dict)
    res["status"] = "ok"
    return res


@router.patch("/transactions/{transaction_id}")
async def update_transaction(transaction_id: str, req: TransactionUpdateRequest):
    mgr = get_finance_manager()
    update_data = {}
    for k, v in req.dict().items():
        if v is not None:
            if k == "merchant":
                update_data["merchant_or_payee"] = v
            elif k == "date":
                update_data["transaction_date"] = v
            else:
                update_data[k] = v

    res = mgr.update_transaction(transaction_id, **update_data)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("error", "Transaction not found"))

    tx_dict = res.get("transaction", {})
    if tx_dict:
        res["transaction"] = _normalize_tx(tx_dict)
    res["status"] = "ok"
    return res


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(transaction_id: str):
    mgr = get_finance_manager()
    res = mgr.delete_transaction(transaction_id)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("error", "Transaction not found"))
    res["status"] = "deleted"
    return res


@router.get("/categories")
async def get_categories():
    mgr = get_finance_manager()
    cats = mgr.store.list_categories()
    return {"categories": cats, "status": "ok"}


@router.post("/categories")
async def create_category(req: CategoryCreateRequest):
    mgr = get_finance_manager()
    desc = req.description
    if req.subcategories:
        desc = (desc + " " + ", ".join(req.subcategories)).strip()
    ok = mgr.store.add_category(req.name, desc)
    if not ok:
        raise HTTPException(status_code=400, detail="Category already exists or invalid name.")
    return {"success": True, "status": "ok", "category": req.name.strip().title()}


@router.get("/budgets")
async def get_budgets():
    mgr = get_finance_manager()
    budgets = mgr.get_budget_status()
    raw_budgets = [_normalize_budget(b.to_dict()) for b in mgr.store.list_budgets()]
    normalized_status = [_normalize_budget(b) for b in budgets]
    return {"budgets": normalized_status, "definitions": raw_budgets, "status": "ok"}


@router.post("/budgets")
async def create_budget(req: BudgetCreateRequest):
    mgr = get_finance_manager()
    res = mgr.set_budget(
        name=req.get_name(),
        limit_amount=req.limit_amount,
        period=req.period,
        category=req.category or "All",
        alert_thresholds=req.alert_thresholds,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed creating budget"))

    b_dict = res.get("budget", {})
    if b_dict:
        res["budget"] = _normalize_budget(b_dict)
    res["status"] = "ok"
    return res


@router.delete("/budgets/{budget_id}")
async def delete_budget(budget_id: str):
    mgr = get_finance_manager()
    res = mgr.delete_budget(budget_id)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail="Budget not found")
    res["status"] = "deleted"
    return res


@router.get("/bills")
async def get_bills(status: Optional[str] = None, category: Optional[str] = None):
    mgr = get_finance_manager()
    bills = mgr.list_bills(status=status, category=category)
    normalized = [_normalize_bill(b) for b in bills]
    return {"bills": normalized, "count": len(normalized), "status": "ok"}


@router.post("/bills")
async def create_bill(req: BillCreateRequest):
    mgr = get_finance_manager()
    res = mgr.add_bill(
        provider_name=req.get_provider(),
        expected_amount=req.get_amount(),
        due_date=req.due_date,
        category=req.category,
        recurrence=req.recurrence,
        payment_method=req.payment_method,
        notes=req.notes,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed creating bill"))

    bill_dict = res.get("bill", {})
    if bill_dict:
        res["bill"] = _normalize_bill(bill_dict)
    res["status"] = "ok"
    return res


@router.post("/bills/{bill_id}/pay")
async def pay_bill(
    bill_id: str,
    payment_method: Optional[str] = Query(default=None),
    req: Optional[BillPayRequest] = None,
):
    mgr = get_finance_manager()
    amount_paid = req.amount_paid if req else None
    payment_date = req.payment_date if req else None
    record_as_expense = req.record_as_expense if req else True

    res = mgr.pay_bill(
        bill_id=bill_id,
        amount_paid=amount_paid,
        payment_date=payment_date,
        record_as_expense=record_as_expense,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed recording payment"))

    bill_dict = res.get("bill", {})
    if bill_dict:
        res["bill"] = _normalize_bill(bill_dict)
    res["status"] = "ok"
    return res


@router.post("/bills/{bill_id}/postpone")
async def postpone_bill(
    bill_id: str,
    days: Optional[int] = Query(default=None),
    req: Optional[BillPostponeRequest] = None,
):
    mgr = get_finance_manager()
    days_to_postpone = days if days is not None else (req.days if req else 1)

    res = mgr.postpone_bill_reminder(bill_id, days=days_to_postpone)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("error", "Failed postponing reminder"))

    bill_dict = res.get("bill", {})
    if bill_dict:
        res["bill"] = _normalize_bill(bill_dict)
    res["status"] = "ok"
    return res


@router.delete("/bills/{bill_id}")
async def delete_bill(bill_id: str):
    mgr = get_finance_manager()
    res = mgr.delete_bill(bill_id)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail="Bill not found")
    res["status"] = "deleted"
    return res


@router.get("/subscriptions")
async def get_subscriptions(status: Optional[str] = None):
    mgr = get_finance_manager()
    subs = mgr.list_subscriptions(status=status)
    commitments = mgr.analytics.get_recurring_commitments_summary()
    normalized = [_normalize_sub(s) for s in subs]
    return {
        "subscriptions": normalized,
        "count": len(normalized),
        "monthly_burn": commitments.get("monthly_subscription_burn", 0.0),
        "status": "ok",
    }


@router.post("/subscriptions")
async def create_subscription(req: SubscriptionCreateRequest):
    mgr = get_finance_manager()
    res = mgr.add_subscription(
        service_name=req.service_name,
        amount=req.amount,
        billing_frequency=req.get_frequency(),
        next_renewal_date=req.next_renewal_date,
        payment_method=req.payment_method,
        notes=req.notes,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed creating subscription"))

    sub_dict = res.get("subscription", {})
    if sub_dict:
        res["subscription"] = _normalize_sub(sub_dict)
    res["status"] = "ok"
    return res


@router.delete("/subscriptions/{sub_id}")
async def delete_subscription(sub_id: str):
    mgr = get_finance_manager()
    res = mgr.delete_subscription(sub_id)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail="Subscription not found")
    res["status"] = "deleted"
    return res


@router.get("/comparison")
@router.get("/analytics/comparison")
async def get_monthly_comparison(
    month1: Optional[str] = Query(default=None),
    month2: Optional[str] = Query(default=None),
    year1: Optional[int] = Query(default=None),
    m1: Optional[int] = Query(default=None, alias="m1"),
    year2: Optional[int] = Query(default=None),
    m2: Optional[int] = Query(default=None, alias="m2"),
):
    mgr = get_finance_manager()

    y1, mo1 = year1, m1
    y2, mo2 = year2, m2

    if month1 and "-" in month1:
        parts1 = month1.strip().split("-")
        y1 = int(parts1[0])
        mo1 = int(parts1[1])

    if month2 and "-" in month2:
        parts2 = month2.strip().split("-")
        y2 = int(parts2[0])
        mo2 = int(parts2[1])

    if not (y1 and mo1 and y2 and mo2):
        now = datetime.datetime.now()
        y1 = y1 or now.year
        mo1 = mo1 or now.month
        y2 = y2 or (now.year if now.month > 1 else now.year - 1)
        mo2 = mo2 or (now.month - 1 if now.month > 1 else 12)

    comparison = mgr.analytics.compare_months(y1, mo1, y2, mo2)
    comparison["diff"] = comparison.get("expense_diff", 0.0)
    comparison["pct_change"] = comparison.get("expense_pct_change", 0.0)
    comparison["category_diffs"] = {
        c["category"]: c["diff"] for c in comparison.get("category_differences", [])
    }
    return comparison
