"""
Candidate comparator and normalizer for Browser Research Agent.
Enforces configuration equivalence, distinguishes pricing nuances, and ranks verified options.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from app.tools.browser.research.models import CandidateProduct, ProductConstraints


class CandidateComparator:
    """Filters, normalizes, and compares candidate products based on strict constraint matching."""

    @classmethod
    def filter_and_match(
        cls,
        candidates: List[CandidateProduct],
        constraints: ProductConstraints,
    ) -> Tuple[List[CandidateProduct], List[CandidateProduct]]:
        """
        Partition candidates into (verified_matches, rejected_mismatches).
        Ensures different configurations (e.g. 8GB vs 16GB) are never declared as equivalent.
        """
        matches: List[CandidateProduct] = []
        rejected: List[CandidateProduct] = []

        seen_urls = set()

        for cand in candidates:
            # Deduplicate by URL
            if cand.source_url in seen_urls:
                continue
            seen_urls.add(cand.source_url)

            # Check price validity (filter out zero or bogus prices)
            if cand.price.selling_price <= 0:
                cand.config_match = False
                cand.config_mismatch_reasons.append("No valid product selling price detected")
                rejected.append(cand)
                continue

            # Verify specs against user's hard constraints
            is_match, reasons = constraints.matches_specs(cand.specs)
            if not is_match:
                cand.config_match = False
                cand.config_mismatch_reasons.extend(reasons)
                rejected.append(cand)
            else:
                cand.config_match = True
                matches.append(cand)

        return (matches, rejected)

    @classmethod
    def rank_candidates(cls, candidates: List[CandidateProduct]) -> List[CandidateProduct]:
        """
        Rank candidates giving highest priority to:
        1. Verified product pages over unverified snippets
        2. In-stock availability over out-of-stock
        3. Lowest unconditional selling price
        """
        def sort_key(c: CandidateProduct):
            # Verified status weight
            status_weight = 0 if c.verification_status == "verified_page" else 1
            # Availability weight
            avail_weight = 0 if c.availability == "in_stock" else 1
            # Price weight
            price_val = c.price.unconditional_price if c.price.unconditional_price > 0 else c.price.effective_price
            return (status_weight, avail_weight, price_val)

        return sorted(candidates, key=sort_key)

    @classmethod
    def find_lowest_prices(
        cls, candidates: List[CandidateProduct]
    ) -> Tuple[Optional[CandidateProduct], Optional[CandidateProduct]]:
        """
        Finds:
        (lowest_unconditional_candidate, lowest_effective_candidate).
        Only considers verified in-stock candidates matching configuration.
        """
        verified_in_stock = [
            c for c in candidates
            if c.config_match and c.price.selling_price > 0 and c.availability != "out_of_stock"
        ]

        if not verified_in_stock:
            # Fall back to any verified match if none confirmed in-stock
            verified_in_stock = [c for c in candidates if c.config_match and c.price.selling_price > 0]

        if not verified_in_stock:
            return (None, None)

        # Lowest unconditional price (clean price without requiring bank cards or exchange)
        lowest_unconditional = min(verified_in_stock, key=lambda c: c.price.unconditional_price)

        # Lowest effective price (with applicable bank card/exchange discounts)
        lowest_effective = min(verified_in_stock, key=lambda c: c.price.effective_price)

        return (lowest_unconditional, lowest_effective)
