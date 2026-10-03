"""
Data models and schemas for Victor's Browser Research Agent.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProductConstraints(BaseModel):
    """Hard constraints extracted from the user's research request."""
    brand: Optional[str] = None
    model_name: Optional[str] = None
    model_number_or_sku: Optional[str] = None
    cpu: Optional[str] = None
    ram_gb: Optional[int] = None
    storage_gb: Optional[int] = None
    storage_type: Optional[str] = None  # SSD, HDD, eMMC
    gpu: Optional[str] = None
    display_size: Optional[str] = None
    display_type: Optional[str] = None  # OLED, IPS, etc.
    condition: str = "new"  # new, refurbished, renewed
    region: str = "India"
    currency_symbol: str = "₹"
    preferred_retailers: List[str] = Field(default_factory=list)
    max_budget: Optional[float] = None
    exact_specs_required: bool = True

    def matches_specs(self, candidate_specs: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        Verify if a candidate matches all specified hard constraints.
        Returns (is_match, mismatch_reasons).
        """
        reasons = []

        # 1. RAM check
        if self.ram_gb is not None and "ram_gb" in candidate_specs:
            cand_ram = candidate_specs.get("ram_gb")
            if cand_ram and cand_ram != self.ram_gb:
                reasons.append(f"RAM mismatch: expected {self.ram_gb}GB, found {cand_ram}GB")

        # 2. Storage check
        if self.storage_gb is not None and "storage_gb" in candidate_specs:
            cand_storage = candidate_specs.get("storage_gb")
            if cand_storage and cand_storage != self.storage_gb:
                reasons.append(f"Storage mismatch: expected {self.storage_gb}GB, found {cand_storage}GB")

        # 3. CPU check
        if self.cpu and "cpu" in candidate_specs:
            cand_cpu = str(candidate_specs.get("cpu", "")).lower()
            exp_cpu = self.cpu.lower()
            # If user specified i7 and candidate is i5, reject
            for tier in ("i3", "i5", "i7", "i9", "ryzen 3", "ryzen 5", "ryzen 7", "ryzen 9", "m1", "m2", "m3"):
                if tier in exp_cpu and tier not in cand_cpu:
                    reasons.append(f"CPU mismatch: expected {self.cpu}, found {candidate_specs.get('cpu')}")
                    break

        return (len(reasons) == 0, reasons)


class PriceDetail(BaseModel):
    """Detailed price structure distinguishing listed, selling, effective, and EMI prices."""
    listed_price: Optional[float] = None  # MRP or original price
    selling_price: float = 0.0  # Current unconditional selling price
    effective_price: float = 0.0  # Selling price after applying conditional discounts
    unconditional_price: float = 0.0  # Final price without requiring bank cards or exchange
    currency: str = "INR"
    currency_symbol: str = "₹"
    is_conditional: bool = False
    discount_conditions: List[str] = Field(default_factory=list)
    emi_per_month: Optional[float] = None  # Monthly installment (strictly NOT the total price)
    delivery_charges: Optional[float] = None


class CandidateProduct(BaseModel):
    """A single product candidate discovered and inspected across online sources."""
    candidate_id: str
    product_name: str
    exact_model_or_sku: Optional[str] = None
    retailer: str
    seller: Optional[str] = None
    source_url: str
    price: PriceDetail
    availability: str = "in_stock"  # in_stock, out_of_stock, unknown
    delivery_info: Optional[str] = None
    specs: Dict[str, Any] = Field(default_factory=dict)
    config_match: bool = True
    config_mismatch_reasons: List[str] = Field(default_factory=list)
    verification_status: str = "unverified_snippet"  # verified_page, unverified_snippet, failed
    confidence: float = 0.5
    provenance: str = ""
    timestamp: float = Field(default_factory=time.time)


class ResearchTraceStep(BaseModel):
    """Structured audit trail step for the research execution."""
    iteration: int
    stage: str  # PLAN, SEARCH, EXTRACT, NORMALIZE, COMPARE, VERIFY, GAP_ANALYSIS
    action: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class ResearchState(BaseModel):
    """Active working state of a Browser Research Agent session."""
    objective: str
    category: str = "shopping"  # shopping, comparison, factual
    constraints: ProductConstraints = Field(default_factory=ProductConstraints)
    queries_executed: List[str] = Field(default_factory=list)
    sources_checked: List[str] = Field(default_factory=list)
    candidates: List[CandidateProduct] = Field(default_factory=list)
    verified_candidates: List[CandidateProduct] = Field(default_factory=list)
    rejected_candidates: List[CandidateProduct] = Field(default_factory=list)
    unresolved_questions: List[str] = Field(default_factory=list)
    iteration_count: int = 0
    max_iterations: int = 3
    max_searches: int = 6
    max_pages_inspected: int = 8
    started_at: float = Field(default_factory=time.time)
    timeout_seconds: float = 35.0
    last_action: str = "initialized"
    status: str = "initialized"  # initialized, running, completed, timed_out, failed
    trace: List[ResearchTraceStep] = Field(default_factory=list)

    def is_timed_out(self) -> bool:
        return (time.time() - self.started_at) >= self.timeout_seconds

    def has_exceeded_limits(self) -> bool:
        return (
            self.iteration_count >= self.max_iterations
            or len(self.queries_executed) >= self.max_searches
            or len(self.sources_checked) >= self.max_pages_inspected
            or self.is_timed_out()
        )

    def add_trace(self, stage: str, action: str, details: Optional[Dict[str, Any]] = None):
        step = ResearchTraceStep(
            iteration=self.iteration_count,
            stage=stage,
            action=action,
            details=details or {},
        )
        self.trace.append(step)


class ResearchResult(BaseModel):
    """Final verified outcome produced by the Browser Research Agent."""
    objective: str
    exact_product_name: str
    verified_configuration: Dict[str, Any] = Field(default_factory=dict)
    lowest_verified_unconditional_price: Optional[float] = None
    lowest_verified_effective_price: Optional[float] = None
    lowest_price_retailer: Optional[str] = None
    lowest_price_url: Optional[str] = None
    price_conditions: List[str] = Field(default_factory=list)
    availability: str = "in_stock"
    other_verified_options: List[Dict[str, Any]] = Field(default_factory=list)
    rejected_variants_count: int = 0
    rejection_reasons: List[str] = Field(default_factory=list)
    sources_inspected_count: int = 0
    sources_inspected: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    summary_markdown: str = ""
    duration_seconds: float = 0.0
    trace: List[ResearchTraceStep] = Field(default_factory=list)
