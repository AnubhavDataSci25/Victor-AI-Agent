"""
Search strategy planner for Browser Research Agent.
Formulates multi-angle, retailer-targeted, and gap-filling search queries.
"""

from __future__ import annotations

from typing import List
from app.tools.browser.research.models import ProductConstraints


class SearchStrategyPlanner:
    """Generates prioritized, multi-query search strategies for comprehensive web research."""

    @classmethod
    def generate_initial_queries(cls, raw_query: str, constraints: ProductConstraints) -> List[str]:
        """Produce prioritized search query formulations across discovery and direct channels."""
        queries: List[str] = []

        # Construct specific model string
        brand = constraints.brand or ""
        model = constraints.model_name or ""
        sku = constraints.model_number_or_sku or ""
        
        # Build specification tags
        specs = []
        if constraints.ram_gb:
            specs.append(f"{constraints.ram_gb}GB RAM")
        if constraints.storage_gb:
            if constraints.storage_gb >= 1024:
                specs.append(f"{constraints.storage_gb // 1024}TB SSD")
            else:
                specs.append(f"{constraints.storage_gb}GB SSD")
        if constraints.cpu:
            specs.append(constraints.cpu)
        if constraints.display_type:
            specs.append(constraints.display_type)

        spec_str = " ".join(specs)
        base_name = f"{brand} {model}".strip() or raw_query

        # Strategy 1: Exact model + specs + price
        if sku and spec_str:
            queries.append(f'"{brand} {sku}" {spec_str} price India')
        elif base_name and spec_str:
            queries.append(f'"{base_name}" {spec_str} price in India')

        # Strategy 2: Model + best price / buy online
        queries.append(f"{base_name} {spec_str} lowest price buy online India".strip())

        # Strategy 3: Direct retailer search targets
        if constraints.preferred_retailers:
            for ret in constraints.preferred_retailers:
                queries.append(f"{base_name} {spec_str} on {ret} India".strip())
        else:
            # Broad retailer coverage query
            queries.append(f"{base_name} {spec_str} Amazon Flipkart Croma".strip())

        # Strategy 4: Manufacturer / official store specifications
        if brand and (model or sku):
            queries.append(f"{brand} {sku or model} official store India specifications".strip())

        # Strategy 5: Fallback to raw query if nothing synthesized
        if not queries:
            queries.append(raw_query)

        # Deduplicate and return top 4 initial queries
        unique_queries = []
        for q in queries:
            cleaned = " ".join(q.split())
            if cleaned and cleaned not in unique_queries:
                unique_queries.append(cleaned)

        return unique_queries[:4]

    @classmethod
    def generate_gap_queries(
        cls,
        base_product: str,
        missing_retailers: List[str],
        uncertain_specs: List[str],
    ) -> List[str]:
        """Generate targeted follow-up queries to resolve identified research gaps."""
        gap_queries: List[str] = []

        # Target missing retailers directly
        for ret in missing_retailers:
            gap_queries.append(f"{base_product} price {ret} India")

        # Resolve spec uncertainties
        for spec in uncertain_specs:
            gap_queries.append(f"{base_product} official {spec} specifications")

        return gap_queries[:3]
