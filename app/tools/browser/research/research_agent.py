"""
Browser Research Agent for Victor AI Assistant.
Orchestrates goal-oriented, multi-source web research with constraint verification,
spec-matching, gap analysis, and adaptive stopping.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.tools.browser.playwright_driver import PlaywrightBrowserDriver
from app.tools.browser.research.candidate_comparator import CandidateComparator
from app.tools.browser.research.constraint_extractor import ConstraintExtractor
from app.tools.browser.research.gap_analyzer import GapAnalyzer
from app.tools.browser.research.models import (
    CandidateProduct,
    ProductConstraints,
    ResearchResult,
    ResearchState,
)
from app.tools.browser.research.page_inspector import PageInspector
from app.tools.browser.research.search_engine import ResearchSearchEngine, SearchHit
from app.tools.browser.research.strategy_planner import SearchStrategyPlanner

logger = logging.getLogger(__name__)


class BrowserResearchAgent:
    """
    High-performance, iterative web research agent.
    Executes: PLAN -> SEARCH -> EXTRACT -> NORMALIZE -> COMPARE -> VERIFY -> GAP ANALYSIS -> FOLLOW-UP -> STOP
    """

    def __init__(
        self,
        driver: Optional[PlaywrightBrowserDriver] = None,
        search_engine: Optional[ResearchSearchEngine] = None,
        page_inspector: Optional[PageInspector] = None,
        gap_analyzer: Optional[GapAnalyzer] = None,
    ) -> None:
        self.driver = driver or PlaywrightBrowserDriver()
        self.search_engine = search_engine or ResearchSearchEngine(driver=self.driver)
        self.page_inspector = page_inspector or PageInspector(driver=self.driver)
        self.gap_analyzer = gap_analyzer or GapAnalyzer()

    async def research(
        self,
        objective: str,
        category: str = "shopping",
        max_budget: Optional[float] = None,
        deep_mode: bool = False,
    ) -> ResearchResult:
        """
        Execute iterative, goal-oriented research on the specified objective.
        """
        start_time = time.time()
        logger.info(f"[BrowserResearchAgent] Initiating research for: '{objective}' (deep_mode={deep_mode})")

        # 1. Initialize constraints and research state
        constraints = ConstraintExtractor.extract_constraints(objective)
        if max_budget is not None and max_budget > 0:
            constraints.max_budget = max_budget

        timeout_sec = 45.0 if deep_mode else 35.0
        max_iter = 4 if deep_mode else 3
        max_searches = 8 if deep_mode else 6
        max_pages = 10 if deep_mode else 8

        state = ResearchState(
            objective=objective,
            category=category,
            constraints=constraints,
            max_iterations=max_iter,
            max_searches=max_searches,
            max_pages_inspected=max_pages,
            timeout_seconds=timeout_sec,
            started_at=start_time,
            status="running",
        )

        # 2. Stage: PLAN
        state.add_trace(
            stage="PLAN",
            action="extract_constraints_and_formulate_strategy",
            details={
                "extracted_constraints": constraints.model_dump(exclude_none=True),
                "budget": constraints.max_budget,
            },
        )

        pending_queries = SearchStrategyPlanner.generate_initial_queries(objective, constraints)
        state.add_trace(
            stage="PLAN",
            action="initial_queries_generated",
            details={"queries": pending_queries},
        )

        seen_search_queries = set()
        inspected_urls = set()

        # 3. Iterative Research Loop
        while not state.has_exceeded_limits():
            state.iteration_count += 1
            logger.info(
                f"[BrowserResearchAgent] Starting Iteration {state.iteration_count}/{state.max_iterations} "
                f"({len(state.verified_candidates)} verified candidates, {len(pending_queries)} queries in queue)"
            )

            # A. Select batch of search queries
            batch_queries: List[str] = []
            while pending_queries and len(batch_queries) < 2 and len(state.queries_executed) < state.max_searches:
                q = pending_queries.pop(0)
                if q not in seen_search_queries:
                    seen_search_queries.add(q)
                    batch_queries.append(q)

            if not batch_queries and not pending_queries:
                # No more searches queued; run gap analysis or terminate
                logger.info("[BrowserResearchAgent] No more search queries in queue.")
                break

            # B. Stage: SEARCH (Concurrent execution)
            state.add_trace(
                stage="SEARCH",
                action="executing_search_batch",
                details={"queries": batch_queries, "iteration": state.iteration_count},
            )
            state.queries_executed.extend(batch_queries)

            search_tasks = [self.search_engine.search(q, limit=4) for q in batch_queries]
            search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)

            discovered_hits: List[SearchHit] = []
            for res in search_results_list:
                if isinstance(res, list):
                    discovered_hits.extend(res)
                elif isinstance(res, Exception):
                    logger.debug(f"[BrowserResearchAgent] Search query failed: {res}")

            # Deduplicate discovered hits by URL
            unique_hits: List[SearchHit] = []
            for hit in discovered_hits:
                if hit.url not in inspected_urls and hit.url not in {h.url for h in unique_hits}:
                    unique_hits.append(hit)

            state.add_trace(
                stage="SEARCH",
                action="search_results_discovered",
                details={"unique_hits_count": len(unique_hits), "sample_urls": [h.url for h in unique_hits[:3]]},
            )

            # C. Stage: EXTRACT & VERIFY (Concurrent page inspection)
            # Pick up to 4 high-relevance pages per iteration
            pages_to_inspect = unique_hits[:4]
            if pages_to_inspect:
                state.add_trace(
                    stage="EXTRACT",
                    action="inspecting_pages_concurrently",
                    details={"urls": [h.url for h in pages_to_inspect]},
                )

                inspect_tasks = [
                    self.page_inspector.inspect_url(
                        url=hit.url,
                        snippet_title=hit.title,
                        snippet_text=hit.snippet,
                    )
                    for hit in pages_to_inspect
                ]
                inspected_candidates = await asyncio.gather(*inspect_tasks, return_exceptions=True)

                for hit, cand in zip(pages_to_inspect, inspected_candidates):
                    inspected_urls.add(hit.url)
                    if hit.url not in state.sources_checked:
                        state.sources_checked.append(hit.url)

                    if isinstance(cand, CandidateProduct):
                        state.candidates.append(cand)
                    elif isinstance(cand, Exception):
                        logger.debug(f"[BrowserResearchAgent] Error inspecting {hit.url}: {cand}")

            # D. Stage: NORMALIZE & COMPARE
            matches, rejected = CandidateComparator.filter_and_match(state.candidates, state.constraints)
            state.verified_candidates = CandidateComparator.rank_candidates(matches)
            state.rejected_candidates = rejected

            state.add_trace(
                stage="COMPARE",
                action="candidates_partitioned",
                details={
                    "verified_matches_count": len(state.verified_candidates),
                    "rejected_mismatches_count": len(state.rejected_candidates),
                    "top_match_price": state.verified_candidates[0].price.selling_price if state.verified_candidates else None,
                },
            )

            # E. Stage: GAP ANALYSIS & ADAPTIVE STOPPING
            should_continue, gap_reasons, follow_ups = await self.gap_analyzer.analyze(state)
            state.add_trace(
                stage="GAP_ANALYSIS",
                action="evaluated_coverage_and_convergence",
                details={
                    "should_continue": should_continue,
                    "gap_reasons": gap_reasons,
                    "follow_up_queries": follow_ups,
                },
            )

            if not should_continue:
                logger.info(f"[BrowserResearchAgent] Adaptive stopping triggered: {gap_reasons}")
                break

            # Add follow-up queries to queue for next iteration
            for fq in follow_ups:
                if fq not in seen_search_queries and fq not in pending_queries:
                    pending_queries.append(fq)

            if state.is_timed_out():
                logger.info("[BrowserResearchAgent] Reached maximum allowed research timeout.")
                break

        # 4. Final Verification and Synthesis
        duration = round(time.time() - start_time, 2)
        state.status = "completed"
        lowest_unconditional, lowest_effective = CandidateComparator.find_lowest_prices(state.verified_candidates)

        summary_md = self._generate_markdown_summary(
            state=state,
            lowest_unconditional=lowest_unconditional,
            lowest_effective=lowest_effective,
            duration=duration,
        )

        result = ResearchResult(
            objective=objective,
            exact_product_name=(
                lowest_unconditional.product_name
                if lowest_unconditional
                else f"{constraints.brand or ''} {constraints.model_name or ''}".strip() or objective
            ),
            verified_configuration=lowest_unconditional.specs if lowest_unconditional else constraints.model_dump(exclude_none=True),
            lowest_verified_unconditional_price=lowest_unconditional.price.unconditional_price if lowest_unconditional else None,
            lowest_verified_effective_price=lowest_effective.price.effective_price if lowest_effective else None,
            lowest_price_retailer=lowest_unconditional.retailer if lowest_unconditional else None,
            lowest_price_url=lowest_unconditional.source_url if lowest_unconditional else None,
            price_conditions=lowest_effective.price.discount_conditions if lowest_effective else [],
            availability=lowest_unconditional.availability if lowest_unconditional else "unknown",
            other_verified_options=[
                {
                    "retailer": c.retailer,
                    "unconditional_price": c.price.unconditional_price,
                    "effective_price": c.price.effective_price,
                    "availability": c.availability,
                    "url": c.source_url,
                    "verification": c.verification_status,
                }
                for c in state.verified_candidates[1:5]
            ],
            rejected_variants_count=len(state.rejected_candidates),
            rejection_reasons=[
                f"{c.product_name[:40]} ({c.retailer}): {', '.join(c.config_mismatch_reasons)}"
                for c in state.rejected_candidates[:5]
            ],
            sources_inspected_count=len(state.sources_checked),
            sources_inspected=state.sources_checked[:8],
            confidence=0.95 if (lowest_unconditional and lowest_unconditional.verification_status == "verified_page") else 0.70,
            summary_markdown=summary_md,
            duration_seconds=duration,
            trace=state.trace,
        )

        logger.info(
            f"[BrowserResearchAgent] Research finished in {duration}s. "
            f"Lowest verified unconditional price: ₹{result.lowest_verified_unconditional_price} "
            f"at {result.lowest_price_retailer}"
        )
        return result

    def _generate_markdown_summary(
        self,
        state: ResearchState,
        lowest_unconditional: Optional[CandidateProduct],
        lowest_effective: Optional[CandidateProduct],
        duration: float,
    ) -> str:
        """Format a clear, concise, evidence-grounded markdown report for Victor."""
        c = state.constraints
        lines: List[str] = []

        # Product Title
        product_display = f"{c.brand or ''} {c.model_name or ''} {c.model_number_or_sku or ''}".strip()
        if not product_display:
            product_display = state.objective

        lines.append(f"### 🔍 Browser Research Report: {product_display}\n")

        # Configuration Verified
        spec_parts = []
        if c.ram_gb:
            spec_parts.append(f"**RAM:** {c.ram_gb}GB")
        if c.storage_gb:
            spec_parts.append(f"**Storage:** {c.storage_gb if c.storage_gb < 1024 else c.storage_gb // 1024}{'GB' if c.storage_gb < 1024 else 'TB'}")
        if c.cpu:
            spec_parts.append(f"**CPU:** {c.cpu}")
        if c.gpu:
            spec_parts.append(f"**GPU:** {c.gpu}")
        if c.display_type or c.display_size:
            spec_parts.append(f"**Display:** {c.display_size or ''} {c.display_type or ''}".strip())

        if spec_parts:
            lines.append(f"**Target Configuration:** {', '.join(spec_parts)}")

        if not lowest_unconditional and not state.verified_candidates:
            lines.append("\n⚠️ **No exact matching verified products found.**")
            lines.append("I searched across multiple sources, but could not confirm an in-stock offer meeting all exact specifications.")
            if state.rejected_candidates:
                lines.append("\n**Excluded Variants:**")
                for r in state.rejected_candidates[:3]:
                    lines.append(f"- *{r.product_name}* at {r.retailer}: {'; '.join(r.config_mismatch_reasons)}")
            lines.append(f"\n*Researched {len(state.sources_checked)} sources in {duration}s.*")
            return "\n".join(lines)

        # Primary Result: Lowest Verified Unconditional Price
        p = lowest_unconditional.price
        lines.append(f"\n🏆 **Lowest Verified Price Found:** **₹{p.unconditional_price:,.0f}**")
        lines.append(f"- **Retailer:** {lowest_unconditional.retailer}")
        lines.append(f"- **Stock Availability:** {'✅ In Stock' if lowest_unconditional.availability == 'in_stock' else '⚠️ ' + lowest_unconditional.availability.replace('_', ' ').capitalize()}")
        lines.append(f"- **Source:** [{lowest_unconditional.retailer} Product Page]({lowest_unconditional.source_url})")

        if p.listed_price and p.listed_price > p.unconditional_price:
            savings = p.listed_price - p.unconditional_price
            lines.append(f"- **MRP / List Price:** ₹{p.listed_price:,.0f} (Savings: ₹{savings:,.0f})")

        # Effective Price with Conditional Discounts
        if lowest_effective and lowest_effective.price.is_conditional and lowest_effective.price.effective_price < p.unconditional_price:
            ep = lowest_effective.price
            lines.append(f"\n💡 **Lowest Effective Price (Conditional):** **₹{ep.effective_price:,.0f}** at {lowest_effective.retailer}")
            if ep.discount_conditions:
                cond_str = ", ".join(ep.discount_conditions)
                lines.append(f"  *(Requires: {cond_str})*")

        # Other Verified Retailer Options
        other_matches = [cand for cand in state.verified_candidates if cand.source_url != lowest_unconditional.source_url]
        if other_matches:
            lines.append("\n**Other Verified Retailers Checked:**")
            for om in other_matches[:4]:
                verified_tag = " [Direct Page]" if om.verification_status == "verified_page" else " [Search Snippet]"
                avail_tag = " (In Stock)" if om.availability == "in_stock" else f" ({om.availability.replace('_', ' ')})"
                lines.append(f"- **{om.retailer}:** ₹{om.price.unconditional_price:,.0f}{avail_tag}{verified_tag} - [Link]({om.source_url})")

        # Variant Protection / Exclusions
        if state.rejected_candidates:
            diff_specs = [c for c in state.rejected_candidates if any("mismatch" in r for r in c.config_mismatch_reasons)]
            if diff_specs:
                lines.append("\n🛡️ **Excluded Non-Equivalent Variants:**")
                for rej in diff_specs[:3]:
                    reasons_str = "; ".join(rej.config_mismatch_reasons)
                    lines.append(f"- Excluded {rej.retailer} variant (*₹{rej.price.selling_price:,.0f}*): {reasons_str}")

        # Research Meta & Verification Note
        unique_retailers = {cand.retailer for cand in state.verified_candidates}
        lines.append(
            f"\n*Verified across {len(unique_retailers)} retailers ({len(state.sources_checked)} URLs inspected, "
            f"{len(state.queries_executed)} queries) in {duration}s.*"
        )

        return "\n".join(lines)
