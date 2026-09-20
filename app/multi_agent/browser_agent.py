"""
Browser automation management for multi-agent platforms: Gemini, ChatGPT, and Claude.
Ensures strict tab isolation, response streaming extraction, and download management.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.multi_agent.models import AgentRole
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = get_logger("multi_agent.browser")


class MultiAgentBrowserManager:
    """
    Manages dedicated browser tabs for each AI platform, ensuring zero cross-contamination.
    """

    def __init__(
        self,
        driver: PlaywrightBrowserDriver | None = None,
        downloads_dir: str | Path | None = None,
        simulate_responses: bool = False,
    ) -> None:
        self.driver = driver or PlaywrightBrowserDriver()
        self.downloads_dir = Path(downloads_dir or (Path.home() / "Downloads")).resolve()
        self.simulate_responses = (
            simulate_responses
            or os.getenv("MULTI_AGENT_SIMULATE", "false").lower() == "true"
        )
        # Dedicated mapping of AgentRole to active Playwright Page
        self._agent_pages: dict[AgentRole, Any] = {}

    def get_platform_url(self, role: AgentRole) -> str:
        if role == AgentRole.GEMINI_RESEARCHER:
            return os.getenv("GEMINI_WEB_URL", "https://gemini.google.com")
        elif role == AgentRole.CHATGPT_PROMPT_ENGINEER:
            return os.getenv("CHATGPT_WEB_URL", "https://chatgpt.com")
        elif role == AgentRole.CLAUDE_DEVELOPER:
            return os.getenv("CLAUDE_WEB_URL", "https://claude.ai")
        return "about:blank"

    async def ensure_agent_tab(self, role: AgentRole) -> Any:
        """
        Activates the dedicated tab for the role or spawns a new dedicated tab.
        Never touches tabs belonging to other agents.
        """
        if self.simulate_responses:
            return f"mock_page_{role.value}"

        page = self._agent_pages.get(role)
        if page is not None:
            try:
                if not page.is_closed():
                    await page.bring_to_front()
                    return page
            except Exception:
                pass

        # Open a new isolated tab for this agent
        url = self.get_platform_url(role)
        logger.info(f"Opening dedicated browser tab for {role.value} at {url}")
        new_page = await self.driver.new_page(url)
        self._agent_pages[role] = new_page
        return new_page

    async def detect_challenge(self, role: AgentRole) -> tuple[bool, str]:
        """Checks if the agent tab is paused at a login screen or Cloudflare challenge."""
        if self.simulate_responses:
            return False, ""

        page = self._agent_pages.get(role)
        if not page or page.is_closed():
            return False, ""

        try:
            url = page.url.lower()
            if any(k in url for k in ("accounts.google.com", "login", "auth0", "signin", "challenge")):
                return True, f"{role.value} tab requires user login or authentication verification in browser ({url})."
            title = (await page.title()).lower()
            if any(k in title for k in ("sign in", "log in", "just a moment", "verify you are human")):
                return True, f"{role.value} page is presenting a challenge or login prompt ({title})."
        except Exception as e:
            logger.debug(f"Note during challenge check: {e}")

        return False, ""

    async def send_prompt_and_receive(
        self,
        role: AgentRole,
        prompt: str,
        timeout_seconds: float = 45.0,
    ) -> str:
        """
        Sends the prompt to the dedicated tab and extracts the generated response.
        """
        if self.simulate_responses:
            # Deterministic simulation for tests and offline validation
            await asyncio.sleep(0.1)
            return self._generate_simulated_response(role, prompt)

        page = await self.ensure_agent_tab(role)

        # 1. Check for platform challenge/login
        has_challenge, msg = await self.detect_challenge(role)
        if has_challenge:
            raise RuntimeError(f"Browser interaction halted: {msg} Please complete login in the open Chrome tab.")

        # 2. Input selectors across the 3 platforms
        input_selectors = [
            "rich-textarea",
            "#prompt-textarea",
            "fieldset div[contenteditable='true']",
            "div[contenteditable='true']",
            "textarea",
        ]

        found_input = None
        for sel in input_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=3000)
                if el and await el.is_visible():
                    found_input = sel
                    break
            except Exception:
                continue

        if not found_input:
            # Fallback: paste via keyboard if focused
            try:
                await page.keyboard.type(prompt[:200])
            except Exception as e:
                raise RuntimeError(f"Could not locate chat input for {role.value}: {e}")
        else:
            await page.fill(found_input, prompt)

        # 3. Submit message
        await page.keyboard.press("Enter")
        await asyncio.sleep(2.0)

        # 4. Wait for response completion
        # Heuristic: Monitor response elements until text stabilizes
        start_time = asyncio.get_event_loop().time()
        last_text = ""
        stable_count = 0

        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            await asyncio.sleep(1.5)
            try:
                # Common response containers
                content = await page.evaluate(
                    """() => {
                        const responses = document.querySelectorAll(
                            '.model-response-text, [data-message-author-role="assistant"], .font-claude-message, .markdown'
                        );
                        if (responses.length > 0) {
                            return responses[responses.length - 1].innerText;
                        }
                        return document.body.innerText;
                    }"""
                )
                if content and content == last_text and len(content.strip()) > 50:
                    stable_count += 1
                    if stable_count >= 2:
                        return content
                else:
                    last_text = content or ""
                    stable_count = 0
            except Exception:
                continue

        return last_text if last_text else "Response captured."

    def save_artifact(self, filename: str, content: str) -> Path:
        """Saves artifact deterministically to configured Downloads directory."""
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.downloads_dir / filename
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Saved artifact to {file_path} ({len(content.encode('utf-8'))} bytes)")
        return file_path

    def _generate_simulated_response(self, role: AgentRole, prompt: str) -> str:
        """Deterministic simulation for testing and offline execution."""
        match = re.search(r"PROJECT NAME:\s*([^\n]+)", prompt)
        pname = match.group(1).strip() if match else "PROJECT"

        if role == AgentRole.GEMINI_RESEARCHER:
            return (
                f"# {pname}_IDEA_README.md\n\n"
                f"## 1. Project Concept & Vision\n"
                f"Comprehensive planning documentation for {pname}.\n\n"
                f"## 2. Problem Statement\n"
                f"Addresses core user challenges with end-to-end automation.\n\n"
                f"## 8. Recommended Technology Stack\n"
                f"- Frontend: React / TypeScript\n"
                f"- Backend: FastAPI / Python\n"
                f"- Database: PostgreSQL\n\n"
                f"## 11. Estimated Timeline\n"
                f"4-6 weeks for initial production release."
            )
        elif role == AgentRole.CHATGPT_PROMPT_ENGINEER:
            return (
                f"# {pname}_DEVELOPMENT_SPECIFICATION.md\n\n"
                f"## Master System Instructions\n"
                f"Build {pname} adhering to the approved architecture.\n\n"
                f"### Phase 1: Setup & Scaffolding\n"
                f"Prompt: Initialize FastAPI backend and React frontend.\n\n"
                f"### Phase 2: Core Implementation\n"
                f"Prompt: Implement data models, endpoints, and validation."
            )
        elif role == AgentRole.CLAUDE_DEVELOPER:
            return (
                f"# Claude Development Status: {pname}\n\n"
                f"Scaffolding complete. Project implementation underway in accordance "
                f"with {pname}_DEVELOPMENT_SPECIFICATION.md."
            )
        return "Simulated response."
