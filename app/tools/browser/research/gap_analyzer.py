"""
Gap analyzer for Browser Research Agent.
Determines whether additional research iterations are warranted based on source coverage,
spec confidence, price convergence, and execution limits.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from app.decision.jev_client import JevClient
from app.decision.models import JevQuestion, QuestionType
from app.tools.browser.research.models import ResearchState
from app.tools.browser.research.strategy_planner import SearchStrategyPlanner


class GapAnalyzer:
    """Identifies information gaps in current research and produces adaptive follow-up queries."""

    MAJOR_INDIAN_RETAILERS = ["Amazon India", "Flipkart", "Croma", "Reliance Digital"]

    def __init__(self, jev_client: Optional[JevClient] = None) -> None:
        self.jev = jev_client or JevClient()

    async def analyze(self, state: ResearchState) -> Tuple[bool, List[str], List[str]]:
        """
        Evaluate research state for gaps.
        Returns:
            (should_continue: bool, gap_reasons: List[str], follow_up_queries: List[str])
        """
        # Hard limits check: stop immediately if budget or limits exceeded
        if state.has_exceeded_limits():
            return (False, ["Research limits or timeout reached"], [])

        gap_reasons: List[str] = []
        missing_retailers: List[str] = []
        uncertain_specs: List[str] = []

        # 1. Retailer diversity check
        retailers_checked = {c.retailer for c in state.verified_candidates if c.config_match}
        if len(retailers_checked) < 2:
            gap_reasons.append("Less than 2 independent retailers checked")
            for ret in self.MAJOR_INDIAN_RETAILERS:
                if ret not in retailers_checked:
                    missing_retailers.append(ret)

        # 2. Verification status check
        verified_pages = [c for c in state.verified_candidates if c.verification_status == "verified_page"]
        if not verified_pages:
            gap_reasons.append("No candidates verified directly on product pages (only search snippets)")

        # 3. Spec confidence check
        if state.constraints.ram_gb and not any(c.specs.get("ram_gb") == state.constraints.ram_gb for c in verified_pages):
            uncertain_specs.append(f"{state.constraints.ram_gb}GB RAM")
            gap_reasons.append(f"RAM constraint ({state.constraints.ram_gb}GB) not yet confirmed on product pages")

        if state.constraints.storage_gb and not any(c.specs.get("storage_gb") == state.constraints.storage_gb for c in verified_pages):
            uncertain_specs.append(f"{state.constraints.storage_gb}GB Storage")
            gap_reasons.append(f"Storage constraint ({state.constraints.storage_gb}GB) not yet confirmed on product pages")

        # 4. Price convergence / discrepancy check
        if len(verified_pages) >= 2:
            prices = [c.price.selling_price for c in verified_pages if c.price.selling_price > 0]
            if prices and (max(prices) / min(prices)) > 1.35:
                gap_reasons.append(f"High price variance detected ({min(prices)} vs {max(prices)}); checking additional sources")

        # Optional Jev bounded advisory check if available and ambiguous
        if self.jev.is_available() and gap_reasons and len(verified_pages) >= 1:
            try:
                question = JevQuestion(
                    type=QuestionType.NOUL,
                    instructions="Is the collected product and pricing evidence sufficient to answer the user conclusively without further searches?",
                )
                state_summary = f"Objective: {state.objective}. Verified Candidates: {len(verified_pages)}. Retailers: {list(retailers_checked)}. Gaps: {gap_reasons}"
                resp = await self.jev.decide(state=state_summary, questions={"sufficient": question})
                if resp and "sufficient" in resp.answers:
                    noul_val = resp.answers["sufficient"].noul or 0.0
                    # If Jev is highly confident evidence is sufficient, stop early
                    if noul_val > 0.80:
                        return (False, ["Jev confirmed evidence is sufficient for conclusive answer"], [])
            except Exception:
                pass

        if not gap_reasons:
            return (False, ["Sufficient multi-source evidence gathered; prices converged"], [])

        # Generate targeted gap-filling follow-up queries
        base_product = f"{state.constraints.brand or ''} {state.constraints.model_name or ''} {state.constraints.model_number_or_sku or ''}".strip()
        follow_ups = SearchStrategyPlanner.generate_gap_queries(
            base_product=base_product or state.objective,
            missing_retailers=missing_retailers[:2],
            uncertain_specs=uncertain_specs[:1],
        )

        return (True, gap_reasons, follow_ups)
