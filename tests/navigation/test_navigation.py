"""
Tests for Victor Voice-Controlled Dashboard Navigation.

Tests:
1. NavigationRegistry parsing of simple and complex natural language phrases.
2. DashboardNavigationController execution, state tracking, and history back stack.
3. DashboardNavigateTool execution via ToolGateway.
4. Fast-path deterministic navigation in SessionManager.
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.navigation.models import NavigationAction, NavigationDestination
from app.navigation.registry import NavigationRegistry, get_navigation_registry
from app.navigation.controller import DashboardNavigationController, get_navigation_controller
from app.tools.navigation.dashboard_navigate_tool import DashboardNavigateTool


class TestNavigationRegistry:
    def setup_method(self):
        self.registry = NavigationRegistry()

    def test_all_14_destinations_registered(self):
        destinations = self.registry.list_destinations()
        assert len(destinations) == 14
        expected = {
            "dashboard", "finance", "documents", "computer", "browser",
            "applications", "system", "memory", "screen", "automations",
            "agents", "tools", "labs", "settings"
        }
        assert set(d.id for d in destinations) == expected

    @pytest.mark.parametrize("phrase,expected_dest,expected_tab", [
        ("Victor, open Memory.", "memory", None),
        ("Victor, switch to Document RAG.", "documents", None),
        ("Open Window Control.", "computer", None),
        ("Go to System Information.", "system", None),
        ("Show me my Finance Dashboard.", "finance", None),
        ("Open Email Manager.", "automations", None),
        ("Switch back to Home.", "dashboard", None),
        ("Open Finance Budgets", "finance", "budgets"),
        ("Victor, show my expenses", "finance", None),
        ("Show Document Notes", "documents", "notes"),
        ("Open Browser", "browser", None),
        ("Open Camera feed", "screen", None),
    ])
    def test_phrase_matching(self, phrase, expected_dest, expected_tab):
        intent = self.registry.match_intent_from_text(phrase)
        assert intent is not None
        assert intent.destination == expected_dest
        assert intent.tab == expected_tab

    @pytest.mark.parametrize("phrase", [
        ("Victor, go back."),
        ("Go to the previous tab."),
        ("Back to previous screen."),
        ("Go back."),
    ])
    def test_back_intent_matching(self, phrase):
        intent = self.registry.match_intent_from_text(phrase)
        assert intent is not None
        assert intent.destination == "__BACK__"
        assert intent.action == NavigationAction.BACK

    def test_irrelevant_phrase_returns_none(self):
        assert self.registry.match_intent_from_text("What is the capital of France?") is None
        assert self.registry.match_intent_from_text("Play some jazz music.") is None


class TestNavigationController:
    @pytest.mark.asyncio
    async def test_navigate_and_history_stack(self):
        controller = DashboardNavigationController()
        received_broadcasts = []

        async def mock_listener(payload):
            received_broadcasts.append(payload)

        controller.register_listener(mock_listener)

        # 1. Navigate to Memory
        res1 = await controller.navigate("memory")
        assert res1.success is True
        assert controller.current_destination == "memory"
        assert len(received_broadcasts) == 1
        assert received_broadcasts[-1]["destination"] == "memory"

        # 2. Navigate to Finance -> Budgets
        res2 = await controller.navigate("finance", tab="budgets")
        assert res2.success is True
        assert controller.current_destination == "finance"
        assert controller.current_tab == "budgets"
        assert received_broadcasts[-1]["destination"] == "finance"
        assert received_broadcasts[-1]["tab"] == "budgets"

        # 3. History Back -> Should return to Memory
        res_back = await controller.navigate_back()
        assert res_back.success is True
        assert controller.current_destination == "memory"
        assert received_broadcasts[-1]["destination"] == "memory"

        controller.unregister_listener(mock_listener)

    @pytest.mark.asyncio
    async def test_already_active_destination(self):
        controller = DashboardNavigationController()
        await controller.navigate("documents", tab="library")
        res_same = await controller.navigate("documents", tab="library")
        assert res_same.success is True
        assert res_same.is_already_active is True
        assert "already" in res_same.spoken_feedback.lower()


class TestDashboardNavigateTool:
    @pytest.mark.asyncio
    async def test_tool_execution(self):
        tool = DashboardNavigateTool()
        result = await tool.execute({"destination": "documents", "tab": "qa"})
        assert "Document Intelligence" in result or "document" in result.lower()
