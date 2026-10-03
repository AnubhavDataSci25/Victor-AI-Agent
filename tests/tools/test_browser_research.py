"""
Unit and integration tests for Victor's Browser Research Agent.
Verifies constraint extraction, price normalization, EMI isolation,
hardware variant protection, multi-source comparison, gap analysis, and tool execution.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.browser.research.models import (
    CandidateProduct,
    PriceDetail,
    ProductConstraints,
    ResearchResult,
    ResearchState,
)
from app.tools.browser.research.constraint_extractor import ConstraintExtractor
from app.tools.browser.research.price_extractor import PriceExtractor
from app.tools.browser.research.candidate_comparator import CandidateComparator
from app.tools.browser.research.strategy_planner import SearchStrategyPlanner
from app.tools.browser.research.gap_analyzer import GapAnalyzer
from app.tools.browser.research.page_inspector import PageInspector
from app.tools.browser.research.search_engine import ResearchSearchEngine, SearchHit
from app.tools.browser.research.research_agent import BrowserResearchAgent
from app.tools.browser.research.tool import BrowserResearchTool


# ============================================================================
# 1. Constraint Extractor Tests
# ============================================================================

def test_extract_constraints_laptop_specs():
    objective = "Find the lowest price for ASUS Vivobook 15 with 16GB RAM and 512GB SSD in India"
    constraints = ConstraintExtractor.extract_constraints(objective)

    assert constraints.brand == "ASUS"
    assert "Vivobook" in constraints.model_name
    assert constraints.ram_gb == 16
    assert constraints.storage_gb == 512
    assert constraints.storage_type == "SSD"
    assert constraints.region == "India"


def test_extract_constraints_complex_gaming_laptop():
    objective = "Lowest price for Lenovo Legion 5 Pro RTX 4060 i7 1TB SSD under 120000"
    constraints = ConstraintExtractor.extract_constraints(objective)

    assert constraints.brand == "Lenovo"
    assert "Legion" in constraints.model_name
    assert constraints.gpu == "RTX 4060"
    assert constraints.cpu == "Intel Core i7"
    assert constraints.storage_gb == 1024
    assert constraints.max_budget == 120000.0


def test_extract_constraints_retailer_and_condition():
    objective = "Cheapest refurbished MacBook Air M2 8GB 256GB on Flipkart or Amazon"
    constraints = ConstraintExtractor.extract_constraints(objective)

    assert constraints.brand == "Apple"
    assert constraints.condition == "refurbished"
    assert constraints.ram_gb == 8
    assert constraints.storage_gb == 256
    assert "Flipkart" in constraints.preferred_retailers
    assert "Amazon India" in constraints.preferred_retailers


# ============================================================================
# 2. Price Extractor & EMI Isolation Tests
# ============================================================================

def test_price_extractor_clean_price():
    text = "ASUS Vivobook 15 OLED. Price: ₹62,990. MRP: ₹79,990. Inclusive of all taxes."
    detail = PriceExtractor.parse_price(text)

    assert detail.selling_price == 62990.0
    assert detail.listed_price == 79990.0
    assert detail.unconditional_price == 62990.0
    assert not detail.is_conditional


def test_price_extractor_strict_emi_isolation():
    text = "Great Indian Festival Deal: ₹64,999 (MRP ₹82,990). EMI starts at ₹3,150/month."
    detail = PriceExtractor.parse_price(text)

    assert detail.selling_price == 64999.0
    assert detail.emi_per_month == 3150.0
    # Crucial: EMI of ₹3,150 must NEVER become the product selling price!
    assert detail.unconditional_price == 64999.0
    assert detail.unconditional_price != 3150.0


def test_price_extractor_conditional_bank_and_exchange():
    text = "Price: ₹59,990. Get ₹4,000 Instant Discount with HDFC Bank Card. Exchange bonus up to ₹5,000."
    detail = PriceExtractor.parse_price(text)

    assert detail.selling_price == 59990.0
    assert detail.is_conditional is True
    assert len(detail.discount_conditions) > 0
    assert any("HDFC" in cond for cond in detail.discount_conditions)


def test_price_extractor_out_of_stock_detection():
    text = "This item is currently sold out. We don't know when or if this item will be back in stock."
    status = PriceExtractor.detect_availability(text)
    assert status == "out_of_stock"


# ============================================================================
# 3. Hardware Variant Protection & Comparator Tests
# ============================================================================

def test_variant_protection_rejects_lower_ram():
    constraints = ProductConstraints(
        brand="ASUS",
        model_name="Vivobook 15",
        ram_gb=16,
        storage_gb=512,
    )

    cand_16gb = CandidateProduct(
        candidate_id="c1",
        product_name="ASUS Vivobook 15 (16GB RAM, 512GB SSD)",
        retailer="Amazon India",
        source_url="https://amazon.in/dp/B001",
        price=PriceDetail(selling_price=64990.0, unconditional_price=64990.0),
        specs={"ram_gb": 16, "storage_gb": 512},
        verification_status="verified_page",
    )

    # 8GB variant that is cheaper, but MUST be rejected because user asked for 16GB
    cand_8gb = CandidateProduct(
        candidate_id="c2",
        product_name="ASUS Vivobook 15 (8GB RAM, 512GB SSD)",
        retailer="Flipkart",
        source_url="https://flipkart.com/p/item2",
        price=PriceDetail(selling_price=49990.0, unconditional_price=49990.0),
        specs={"ram_gb": 8, "storage_gb": 512},
        verification_status="verified_page",
    )

    matches, rejected = CandidateComparator.filter_and_match([cand_16gb, cand_8gb], constraints)

    assert len(matches) == 1
    assert matches[0].candidate_id == "c1"
    assert len(rejected) == 1
    assert rejected[0].candidate_id == "c2"
    assert any("RAM mismatch" in r for r in rejected[0].config_mismatch_reasons)


def test_candidate_comparator_find_lowest_unconditional_vs_effective():
    c1 = CandidateProduct(
        candidate_id="c1",
        product_name="Laptop A 16GB",
        retailer="Amazon India",
        source_url="https://amazon.in/1",
        price=PriceDetail(selling_price=65000.0, unconditional_price=65000.0, effective_price=65000.0),
        specs={"ram_gb": 16},
        verification_status="verified_page",
    )
    c2 = CandidateProduct(
        candidate_id="c2",
        product_name="Laptop A 16GB",
        retailer="Flipkart",
        source_url="https://flipkart.com/2",
        price=PriceDetail(
            selling_price=62000.0,
            unconditional_price=62000.0,
            effective_price=59000.0,
            is_conditional=True,
            discount_conditions=["SBI Card ₹3,000 Off"],
        ),
        specs={"ram_gb": 16},
        verification_status="verified_page",
    )
    c3 = CandidateProduct(
        candidate_id="c3",
        product_name="Laptop A 16GB",
        retailer="Croma",
        source_url="https://croma.com/3",
        price=PriceDetail(selling_price=63500.0, unconditional_price=63500.0, effective_price=63500.0),
        specs={"ram_gb": 16},
        verification_status="verified_page",
    )

    lowest_uncond, lowest_eff = CandidateComparator.find_lowest_prices([c1, c2, c3])

    assert lowest_uncond is not None
    assert lowest_uncond.retailer == "Flipkart"
    assert lowest_uncond.price.unconditional_price == 62000.0

    assert lowest_eff is not None
    assert lowest_eff.retailer == "Flipkart"
    assert lowest_eff.price.effective_price == 59000.0


# ============================================================================
# 4. Search Strategy & Gap Analyzer Tests
# ============================================================================

def test_strategy_planner_generates_multi_angle_queries():
    constraints = ProductConstraints(
        brand="ASUS",
        model_name="Vivobook 15",
        ram_gb=16,
        storage_gb=512,
    )
    queries = SearchStrategyPlanner.generate_initial_queries("ASUS Vivobook 15 16GB 512GB", constraints)

    assert len(queries) >= 3
    # Check coverage of direct price, multi-retailer, and buy online terms
    all_q_text = " ".join(queries).lower()
    assert "16gb ram" in all_q_text
    assert "512gb ssd" in all_q_text
    assert "price" in all_q_text or "buy" in all_q_text


@pytest.mark.asyncio
async def test_gap_analyzer_detects_single_retailer_gap():
    state = ResearchState(
        objective="ASUS Zenbook 14 OLED",
        constraints=ProductConstraints(brand="ASUS", model_name="Zenbook 14 OLED"),
    )
    # Only 1 candidate from Amazon
    c1 = CandidateProduct(
        candidate_id="c1",
        product_name="ASUS Zenbook 14 OLED",
        retailer="Amazon India",
        source_url="https://amazon.in/zenbook",
        price=PriceDetail(selling_price=89990.0, unconditional_price=89990.0),
        verification_status="verified_page",
    )
    state.verified_candidates = [c1]

    analyzer = GapAnalyzer()
    should_continue, gaps, follow_ups = await analyzer.analyze(state)

    assert should_continue is True
    assert any("Less than 2 independent retailers checked" in g for g in gaps)
    assert len(follow_ups) > 0
    assert any("Flipkart" in f or "Croma" in f or "Reliance" in f for f in follow_ups)


@pytest.mark.asyncio
async def test_gap_analyzer_stops_when_multi_source_evidence_gathered():
    state = ResearchState(
        objective="ASUS Zenbook 14 OLED",
        constraints=ProductConstraints(brand="ASUS", model_name="Zenbook 14 OLED"),
    )
    c1 = CandidateProduct(
        candidate_id="c1",
        product_name="ASUS Zenbook 14 OLED",
        retailer="Amazon India",
        source_url="https://amazon.in/zenbook",
        price=PriceDetail(selling_price=89990.0, unconditional_price=89990.0),
        verification_status="verified_page",
    )
    c2 = CandidateProduct(
        candidate_id="c2",
        product_name="ASUS Zenbook 14 OLED",
        retailer="Flipkart",
        source_url="https://flipkart.com/zenbook",
        price=PriceDetail(selling_price=88490.0, unconditional_price=88490.0),
        verification_status="verified_page",
    )
    state.verified_candidates = [c1, c2]

    analyzer = GapAnalyzer()
    should_continue, gaps, _ = await analyzer.analyze(state)

    # Both verified pages, prices close, 2 independent retailers
    assert should_continue is False


# ============================================================================
# 5. Full Browser Research Agent Execution (Mocked)
# ============================================================================

@pytest.mark.asyncio
async def test_browser_research_agent_end_to_end():
    mock_search = MagicMock(spec=ResearchSearchEngine)
    mock_search.search = AsyncMock(
        return_value=[
            SearchHit(title="ASUS Vivobook 15 on Flipkart", url="https://flipkart.com/asus-15", snippet="₹61,999 with 16GB RAM 512GB SSD"),
            SearchHit(title="ASUS Vivobook 15 on Amazon India", url="https://amazon.in/asus-15", snippet="₹64,499 with 16GB RAM 512GB SSD"),
            SearchHit(title="ASUS Vivobook 15 on Croma", url="https://croma.com/asus-15", snippet="₹63,990 with 16GB RAM 512GB SSD"),
            SearchHit(title="ASUS Vivobook 15 8GB Variant", url="https://croma.com/asus-8gb", snippet="₹52,990 with 8GB RAM"),
        ]
    )

    mock_inspector = MagicMock(spec=PageInspector)

    async def fake_inspect(url, snippet_title="", snippet_text=""):
        if "flipkart.com/asus-15" in url:
            return CandidateProduct(
                candidate_id="fk1",
                product_name="ASUS Vivobook 15 OLED",
                retailer="Flipkart",
                source_url=url,
                price=PriceDetail(selling_price=61999.0, unconditional_price=61999.0, listed_price=74990.0),
                specs={"ram_gb": 16, "storage_gb": 512},
                verification_status="verified_page",
                availability="in_stock",
            )
        elif "amazon.in/asus-15" in url:
            return CandidateProduct(
                candidate_id="az1",
                product_name="ASUS Vivobook 15 OLED",
                retailer="Amazon India",
                source_url=url,
                price=PriceDetail(selling_price=64499.0, unconditional_price=64499.0, listed_price=74990.0),
                specs={"ram_gb": 16, "storage_gb": 512},
                verification_status="verified_page",
                availability="in_stock",
            )
        elif "croma.com/asus-8gb" in url:
            return CandidateProduct(
                candidate_id="cr_8gb",
                product_name="ASUS Vivobook 15 (8GB)",
                retailer="Croma",
                source_url=url,
                price=PriceDetail(selling_price=52990.0, unconditional_price=52990.0),
                specs={"ram_gb": 8, "storage_gb": 512},
                verification_status="verified_page",
                availability="in_stock",
            )
        return None

    mock_inspector.inspect_url = AsyncMock(side_effect=fake_inspect)

    agent = BrowserResearchAgent(
        search_engine=mock_search,
        page_inspector=mock_inspector,
    )

    result = await agent.research(
        objective="Find the lowest price for ASUS Vivobook 15 with 16GB RAM and 512GB SSD in India"
    )

    assert isinstance(result, ResearchResult)
    assert result.lowest_verified_unconditional_price == 61999.0
    assert result.lowest_price_retailer == "Flipkart"
    assert result.lowest_price_url == "https://flipkart.com/asus-15"
    assert result.rejected_variants_count >= 1
    assert "₹61,999" in result.summary_markdown
    assert "Flipkart" in result.summary_markdown
    assert "Excluded Non-Equivalent Variants" in result.summary_markdown
    assert len(result.trace) > 0


# ============================================================================
# 6. BrowserResearchTool Execution
# ============================================================================

@pytest.mark.asyncio
async def test_browser_research_tool_execution():
    mock_agent = MagicMock(spec=BrowserResearchAgent)
    mock_result = ResearchResult(
        objective="Find price for Laptop",
        exact_product_name="Test Laptop 16GB",
        lowest_verified_unconditional_price=55000.0,
        lowest_price_retailer="Amazon India",
        lowest_price_url="https://amazon.in/laptop",
        summary_markdown="🏆 **Lowest Verified Price Found:** **₹55,000** at Amazon India",
    )
    mock_agent.research = AsyncMock(return_value=mock_result)

    tool = BrowserResearchTool(agent=mock_agent)
    assert tool.name == "browser_research"
    assert tool.timeout_seconds == 45.0
    schema = tool.get_schema()
    assert schema["name"] == "browser_research"
    assert "query" in schema["parameters"]["properties"]

    output = await tool.execute({"query": "Find lowest price for Test Laptop with 16GB RAM"})
    assert "Lowest Verified Price Found" in output
    assert "SYSTEM SECURITY WARNING" in output


# ============================================================================
# 7. Additional Edge Case & Integration Tests
# ============================================================================

def test_variant_protection_storage_and_cpu_mismatch():
    constraints = ProductConstraints(
        brand="Dell",
        model_name="XPS 15",
        cpu="Intel Core i7",
        ram_gb=16,
        storage_gb=1024,
    )

    # Candidate with i5 instead of i7
    c_cpu_mismatch = CandidateProduct(
        candidate_id="c_cpu",
        product_name="Dell XPS 15 (i5, 16GB, 1TB)",
        retailer="Dell Store",
        source_url="https://dell.com/1",
        price=PriceDetail(selling_price=110000.0, unconditional_price=110000.0),
        specs={"cpu": "Intel Core i5", "ram_gb": 16, "storage_gb": 1024},
    )

    # Candidate with 512GB instead of 1TB
    c_storage_mismatch = CandidateProduct(
        candidate_id="c_storage",
        product_name="Dell XPS 15 (i7, 16GB, 512GB)",
        retailer="Amazon India",
        source_url="https://amazon.in/1",
        price=PriceDetail(selling_price=120000.0, unconditional_price=120000.0),
        specs={"cpu": "Intel Core i7", "ram_gb": 16, "storage_gb": 512},
    )

    # Exact match
    c_exact = CandidateProduct(
        candidate_id="c_exact",
        product_name="Dell XPS 15 (i7, 16GB, 1TB)",
        retailer="Flipkart",
        source_url="https://flipkart.com/1",
        price=PriceDetail(selling_price=135000.0, unconditional_price=135000.0),
        specs={"cpu": "Intel Core i7", "ram_gb": 16, "storage_gb": 1024},
    )

    matches, rejected = CandidateComparator.filter_and_match(
        [c_cpu_mismatch, c_storage_mismatch, c_exact],
        constraints,
    )

    assert len(matches) == 1
    assert matches[0].candidate_id == "c_exact"
    assert len(rejected) == 2
    rejection_reasons = [r for c in rejected for r in c.config_mismatch_reasons]
    assert any("CPU mismatch" in r for r in rejection_reasons)
    assert any("Storage mismatch" in r for r in rejection_reasons)


def test_system_integration_registry_and_gateway():
    from app.tools.tool_setup import build_tool_registry
    from app.gateway.tool_gateway import ToolGateway

    registry = build_tool_registry()
    tool = registry.get("browser_research")
    assert tool is not None
    assert tool.name == "browser_research"

    gateway = ToolGateway(registry=registry)
    timeout = gateway.get_tool_timeout("browser_research")
    assert timeout == 45.0


@pytest.mark.asyncio
async def test_decision_engine_routes_price_discovery():
    from app.decision.engine import DecisionEngine

    engine = DecisionEngine()
    decision = await engine.route_intent("Find me the lowest price for ASUS Vivobook 15")
    assert decision.intent == "browser_research"
    assert "browser_research" in decision.candidate_tools


@pytest.mark.asyncio
async def test_browser_research_agent_unreachable_page_resilience():
    mock_search = MagicMock(spec=ResearchSearchEngine)
    mock_search.search = AsyncMock(
        return_value=[
            SearchHit(title="Blocked Site", url="https://blocked.example.com/item", snippet="snippet"),
            SearchHit(title="Working Retailer", url="https://croma.com/working", snippet="₹45,000 16GB"),
        ]
    )

    mock_inspector = MagicMock(spec=PageInspector)

    async def flaky_inspect(url, snippet_title="", snippet_text=""):
        if "blocked" in url:
            raise ConnectionError("Connection refused by target host")
        return CandidateProduct(
            candidate_id="croma_valid",
            product_name="Budget Laptop 16GB",
            retailer="Croma",
            source_url=url,
            price=PriceDetail(selling_price=45000.0, unconditional_price=45000.0),
            specs={"ram_gb": 16},
            verification_status="verified_page",
        )

    mock_inspector.inspect_url = AsyncMock(side_effect=flaky_inspect)

    agent = BrowserResearchAgent(
        search_engine=mock_search,
        page_inspector=mock_inspector,
    )

    # Must complete gracefully without crashing when pages fail
    result = await agent.research(objective="Laptop 16GB RAM lowest price")
    assert result.lowest_verified_unconditional_price == 45000.0
    assert result.lowest_price_retailer == "Croma"
