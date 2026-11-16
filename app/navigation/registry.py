"""
Victor Dashboard Navigation — Centralized Navigation Registry.

Maintains the authoritative catalog of all registered dashboard destinations,
subtabs, aliases, and natural-language matching rules.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from app.navigation.models import NavigationAction, NavigationDestination, NavigationIntent


class NavigationRegistry:
    """Centralized catalog of all Victor desktop dashboard destinations."""

    def __init__(self) -> None:
        self._destinations: Dict[str, NavigationDestination] = {}
        self._alias_map: Dict[str, Tuple[str, Optional[str]]] = {}  # alias -> (dest_id, tab_id)
        self._register_default_destinations()
        self._build_alias_index()

    def _register_default_destinations(self) -> None:
        """Registers the 14 actual dashboard destinations discovered from Victor's frontend."""

        # 1. Main 3D Holographic Command Center / Home
        self.register(NavigationDestination(
            id="dashboard",
            title="Command Center",
            description="Main 3D Holographic Quantum Particle Orb Command Center, System Greeting, HUD Telemetry, and Quick Actions.",
            view_type="main_view",
            aliases=[
                "dashboard", "home", "main", "main screen", "command center", "orb",
                "quantum orb", "start screen", "home screen", "homepage", "switch back to home",
                "return to home", "go to home", "open home", "back to home", "back to dashboard",
                "home dashboard", "main dashboard", "orb screen"
            ]
        ))

        # 2. Personal Finance, Expense & Bill Management
        self.register(NavigationDestination(
            id="finance",
            title="Finance & Bills",
            description="Interactive personal finance dashboard, expense tracking, income, categories, budgets, bills, analytics, and subscriptions.",
            view_type="dedicated_view",
            subtabs={
                "overview": "Finance Overview",
                "transactions": "Transactions",
                "categories": "Categories",
                "budgets": "Budgets",
                "bills": "Bills & Dues",
                "analytics": "Analytics & Diff",
                "subscriptions": "Subscriptions",
            },
            aliases=[
                "finance", "finances", "finance dashboard", "expense dashboard", "expenses",
                "bill management", "bills and dues", "my finance", "personal finance",
                "money tracker", "spending dashboard", "financial dashboard", "finance center"
            ]
        ))

        # 3. Document Intelligence & Conversational RAG
        self.register(NavigationDestination(
            id="documents",
            title="Document Intelligence & RAG",
            description="Conversational Retrieval-Augmented Generation, document library, spreadsheet intelligence, cross-document comparison, study notes.",
            view_type="dedicated_view",
            subtabs={
                "library": "Document Library",
                "qa": "Conversational RAG (Q&A)",
                "excel": "Spreadsheet Intelligence",
                "compare": "Compare Documents",
                "notes": "Study Notes & Summary",
            },
            aliases=[
                "document rag", "document intelligence", "documents", "document library",
                "rag workspace", "rag agent", "doc intelligence", "document dashboard",
                "rag", "docs", "document center", "document manager", "rag dashboard"
            ]
        ))

        # 4. Computer Control
        self.register(NavigationDestination(
            id="computer",
            title="Computer Control",
            description="Desktop window management, screenshots, master audio volume, display brightness, OS controls.",
            view_type="drawer_module",
            aliases=[
                "computer control", "computer", "window control", "desktop control",
                "desktop controls", "window management", "system controls", "windows control",
                "control computer", "pc control", "window manager"
            ]
        ))

        # 5. Web & Browser Automation
        self.register(NavigationDestination(
            id="browser",
            title="Web & Browser",
            description="Playwright web browser automation, YouTube, AI assistants (Gemini, ChatGPT, Claude), tech news.",
            view_type="drawer_module",
            aliases=[
                "browser", "web browser", "web and browser", "web automation", "internet",
                "browser automation", "web control", "web manager"
            ]
        ))

        # 6. Applications & Google Services
        self.register(NavigationDestination(
            id="applications",
            title="Applications",
            description="Desktop app launcher, Google Keep notes, Google Calendar scheduling, Google Meet.",
            view_type="drawer_module",
            aliases=[
                "applications", "apps", "app manager", "google services", "google apps",
                "google calendar", "google keep", "google meet", "desktop apps", "applications manager"
            ]
        ))

        # 7. System Monitor & Telemetry
        self.register(NavigationDestination(
            id="system",
            title="System Monitor",
            description="Real-time CPU, RAM, battery, network / Wi-Fi, Bluetooth, and paired Android phone telemetry.",
            view_type="drawer_module",
            aliases=[
                "system", "system monitor", "system information", "system info",
                "system status", "telemetry", "hardware monitor", "system performance",
                "pc status", "system stats", "computer specs"
            ]
        ))

        # 8. Memory & Context
        self.register(NavigationDestination(
            id="memory",
            title="Memory & Context",
            description="Long-term persistent user facts, personal preferences, reminders, dated tasks, and context manager.",
            view_type="drawer_module",
            aliases=[
                "memory", "memories", "memory manager", "memory dashboard", "context",
                "memory and context", "show my memories", "reminders", "tasks and reminders",
                "memory center", "user memory"
            ]
        ))

        # 9. Screen & Visual Intelligence
        self.register(NavigationDestination(
            id="screen",
            title="Screen Analyzer",
            description="Visual screen analysis, live camera feed, QR/barcode scanning, visual OCR text copy.",
            view_type="drawer_module",
            aliases=[
                "screen", "screen analyzer", "screen intelligence", "visual intelligence",
                "camera analyzer", "screen analysis", "ocr", "screen reader",
                "camera", "camera feed", "camera module"
            ]
        ))

        # 10. Automations & Phone Companion
        self.register(NavigationDestination(
            id="automations",
            title="Automations",
            description="Phone notifications, companion dialer, Gmail / Email Manager, music playback engine.",
            view_type="drawer_module",
            aliases=[
                "automations", "automation", "phone companion", "phone integration",
                "email manager", "emails", "gmail", "phone notifications", "android companion",
                "phone companion app", "phone manager", "companion"
            ]
        ))

        # 11. Multi-Agent Workflows
        self.register(NavigationDestination(
            id="agents",
            title="Agents (Multi-Agent)",
            description="Multi-agent project research, autonomous software engineering pipelines, architecture specs, artifacts.",
            view_type="drawer_module",
            aliases=[
                "agents", "multi agent", "multi agents", "multi-agent workflows",
                "agent team", "project pipeline", "agent workflows", "swarm", "agents pipeline"
            ]
        ))

        # 12. Registered Capabilities (104 Tools Catalog)
        self.register(NavigationDestination(
            id="tools",
            title="Tools Catalog",
            description="Catalog of registered system, API, browser, computer, and automation tools.",
            view_type="drawer_module",
            aliases=[
                "tools", "tool catalog", "capabilities", "registered tools", "toolbox",
                "tool capabilities", "skills", "tools list"
            ]
        ))

        # 13. Victor Labs (Experimental)
        self.register(NavigationDestination(
            id="labs",
            title="Victor Labs",
            description="Continuous visual scene monitoring, Android YouTube casting, companion pairing.",
            view_type="drawer_module",
            aliases=[
                "labs", "victor labs", "experimental", "experiments", "lab", "experimental features"
            ]
        ))

        # 14. Settings & Security
        self.register(NavigationDestination(
            id="settings",
            title="Settings & Security",
            description="Android companion pairing, terminal lock, voice microphone toggle, Windows system settings.",
            view_type="drawer_module",
            aliases=[
                "settings", "security", "settings and security", "preferences", "config",
                "configuration", "pair phone", "system settings", "app settings"
            ]
        ))

    def _build_alias_index(self) -> None:
        """Indexes aliases and subtab keywords for fast deterministic matching."""
        self._alias_map.clear()

        # Navigation History / Back aliases
        back_aliases = [
            "back", "go back", "previous", "previous tab", "previous page",
            "previous screen", "go to previous", "previous section", "return to previous",
            "go to the previous tab", "switch to previous tab"
        ]
        for a in back_aliases:
            self._alias_map[a.lower()] = ("__BACK__", None)

        # Home aliases
        home_aliases = [
            "home", "dashboard", "main", "main screen", "command center", "return to home",
            "switch back to home", "go to home", "open home", "back to home"
        ]
        for a in home_aliases:
            self._alias_map[a.lower()] = ("dashboard", None)

        for dest_id, dest in self._destinations.items():
            self._alias_map[dest_id.lower()] = (dest_id, None)
            self._alias_map[dest.title.lower()] = (dest_id, None)
            for alias in dest.aliases:
                self._alias_map[alias.lower()] = (dest_id, None)

            # Subtab aliases
            for tab_id, tab_title in dest.subtabs.items():
                self._alias_map[f"{dest_id} {tab_id}".lower()] = (dest_id, tab_id)
                self._alias_map[f"{dest_id} {tab_title}".lower()] = (dest_id, tab_id)
                self._alias_map[f"{tab_title} in {dest_id}".lower()] = (dest_id, tab_id)
                self._alias_map[f"{tab_title} in {dest.title}".lower()] = (dest_id, tab_id)
                self._alias_map[tab_title.lower()] = (dest_id, tab_id)
                self._alias_map[tab_id.lower()] = (dest_id, tab_id)

        # Custom high-frequency conversational aliases
        subtab_custom = {
            # Finance subtabs
            "my transactions": ("finance", "transactions"),
            "transaction history": ("finance", "transactions"),
            "spending log": ("finance", "transactions"),
            "expense list": ("finance", "transactions"),
            "my bills": ("finance", "bills"),
            "upcoming bills": ("finance", "bills"),
            "pending bills": ("finance", "bills"),
            "bill dues": ("finance", "bills"),
            "my budgets": ("finance", "budgets"),
            "budget status": ("finance", "budgets"),
            "monthly budget": ("finance", "budgets"),
            "financial analytics": ("finance", "analytics"),
            "cash flow analysis": ("finance", "analytics"),
            "burn rate": ("finance", "analytics"),
            "spending categories": ("finance", "categories"),
            "category breakdown": ("finance", "categories"),
            "my subscriptions": ("finance", "subscriptions"),
            "recurring subscriptions": ("finance", "subscriptions"),
            "active subscriptions": ("finance", "subscriptions"),

            # Document RAG subtabs
            "document library": ("documents", "library"),
            "indexed documents": ("documents", "library"),
            "document qa": ("documents", "qa"),
            "conversational rag": ("documents", "qa"),
            "spreadsheet intelligence": ("documents", "excel"),
            "excel intelligence": ("documents", "excel"),
            "excel sheets": ("documents", "excel"),
            "compare documents": ("documents", "compare"),
            "document comparison": ("documents", "compare"),
            "study notes": ("documents", "notes"),
            "revision notes": ("documents", "notes"),
            "document summary": ("documents", "notes"),
        }
        for k, v in subtab_custom.items():
            self._alias_map[k] = v

    def register(self, destination: NavigationDestination) -> None:
        """Registers a new destination."""
        self._destinations[destination.id] = destination

    def get_destination(self, dest_id: str) -> Optional[NavigationDestination]:
        """Returns destination metadata by ID."""
        return self._destinations.get(dest_id)

    def list_destinations(self) -> List[NavigationDestination]:
        """Returns all registered destinations."""
        return list(self._destinations.values())

    def match_intent_from_text(self, text: str) -> Optional[NavigationIntent]:
        """
        Deterministically parses natural-language user text into a NavigationIntent.
        Handles phrases such as:
          - "Victor, open Memory."
          - "Victor, switch to Document RAG."
          - "Open Window Control."
          - "Go to System Information."
          - "Show me my Finance Dashboard."
          - "Open Email Manager."
          - "Switch back to Home."
          - "Go to the previous tab."
        Returns NavigationIntent if matched, otherwise None.
        """
        if not text:
            return None

        # Clean noise words & wake word
        clean = text.lower().strip()
        clean = re.sub(r'^(?:victor|hey victor|hi victor|ok victor|please|can you|could you)\s*[,:]*\s*', '', clean)
        clean = clean.strip().rstrip('.!?')

        # Check for history navigation ("previous tab", "go back", "back")
        back_patterns = [
            r'^(?:go\s+)?back$',
            r'^(?:go\s+to\s+|return\s+to\s+|switch\s+to\s+|back\s+to\s+)?(?:the\s+)?previous(?:\s+tab|\s+page|\s+screen|\s+section)?$',
            r'^previous\s+tab$',
            r'^previous\s+page$',
            r'^previous\s+screen$',
        ]
        for pat in back_patterns:
            if re.match(pat, clean):
                return NavigationIntent(
                    intent="dashboard_navigation",
                    destination="__BACK__",
                    action=NavigationAction.BACK,
                    source="voice_or_text"
                )

        # Check for home navigation
        home_patterns = [
            r'^(?:switch\s+back\s+to\s+|return\s+to\s+|go\s+to\s+|open\s+|back\s+to\s+)?home(?:\s+screen|\s+page|\s+dashboard)?$',
            r'^(?:switch\s+back\s+to\s+|return\s+to\s+|go\s+to\s+|open\s+|back\s+to\s+)?dashboard$',
            r'^command\s+center$',
            r'^orb$',
        ]
        for pat in home_patterns:
            if re.match(pat, clean):
                return NavigationIntent(
                    intent="dashboard_navigation",
                    destination="dashboard",
                    action=NavigationAction.HOME,
                    source="voice_or_text"
                )

        # Check common navigation verb prefixes
        verb_prefix_pattern = r'^(?:open|switch\s+to|go\s+to|show(?:\s+me)?(?:\s+my)?|display|view|take\s+me\s+to|navigate\s+to|jump\s+to)\s+'
        match = re.match(verb_prefix_pattern, clean)
        target_phrase = re.sub(verb_prefix_pattern, '', clean).strip() if match else clean

        # Strip trailing words like 'dashboard', 'tab', 'page', 'section', 'view'
        cleaned_target = re.sub(r'\s+(?:dashboard|tab|page|section|view|screen|manager|window)$', '', target_phrase).strip()

        # 1. Exact alias match on target phrase
        if target_phrase in self._alias_map:
            dest_id, tab_id = self._alias_map[target_phrase]
            return NavigationIntent(
                intent="dashboard_navigation",
                destination=dest_id,
                tab=tab_id,
                action=NavigationAction.OPEN,
                source="voice_or_text"
            )

        # 2. Match cleaned target (without trailing "dashboard", "tab", etc.)
        if cleaned_target in self._alias_map:
            dest_id, tab_id = self._alias_map[cleaned_target]
            return NavigationIntent(
                intent="dashboard_navigation",
                destination=dest_id,
                tab=tab_id,
                action=NavigationAction.OPEN,
                source="voice_or_text"
            )

        # 3. Full cleaned phrase match in alias map
        if clean in self._alias_map:
            dest_id, tab_id = self._alias_map[clean]
            return NavigationIntent(
                intent="dashboard_navigation",
                destination=dest_id,
                tab=tab_id,
                action=NavigationAction.OPEN,
                source="voice_or_text"
            )

        # 4. Keyword fuzzy scan across registered aliases
        for alias, (dest_id, tab_id) in self._alias_map.items():
            if len(alias) >= 4 and (alias in clean or alias in target_phrase):
                return NavigationIntent(
                    intent="dashboard_navigation",
                    destination=dest_id,
                    tab=tab_id,
                    action=NavigationAction.OPEN,
                    source="voice_or_text"
                )

        return None


# Global singleton instance
_GLOBAL_REGISTRY: Optional[NavigationRegistry] = None


def get_navigation_registry() -> NavigationRegistry:
    """Returns the singleton NavigationRegistry."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = NavigationRegistry()
    return _GLOBAL_REGISTRY
