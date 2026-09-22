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

        # 2. Input selectors tailored by platform and waiting for SPA hydration
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        role_selectors = {
            AgentRole.GEMINI_RESEARCHER: [
                "rich-textarea .ql-editor",
                "rich-textarea [contenteditable='true']",
                "rich-textarea p",
                "div[contenteditable='true']",
            ],
            AgentRole.CHATGPT_PROMPT_ENGINEER: [
                "#prompt-textarea",
                "div#prompt-textarea",
                "div.ProseMirror[contenteditable='true']",
                "textarea[name='prompt-textarea']",
                "textarea.wcDTda_fallbackTextarea",
                "div[contenteditable='true']",
            ],
            AgentRole.CLAUDE_DEVELOPER: [
                "fieldset div[contenteditable='true']",
                "div.tiptap.ProseMirror",
                "div.ProseMirror[contenteditable='true']",
                "div[contenteditable='true']",
                "textarea",
            ],
        }
        input_selectors = role_selectors.get(role, ["div[contenteditable='true']", "textarea"])

        found_input = None
        input_el = None
        # Poll for hydrated input up to 12 seconds
        poll_start = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - poll_start) < 12.0:
            for sel in input_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        found_input = sel
                        input_el = el
                        break
                except Exception:
                    continue
            if input_el:
                break
            await asyncio.sleep(0.5)

        if not input_el:
            raise RuntimeError(f"Could not locate chat input for {role.value} within 12s on {page.url}")

        tag_name = ""
        is_editable = False
        try:
            tag_name = await input_el.evaluate("el => el.tagName.toLowerCase()")
            is_editable = await input_el.evaluate("el => el.isContentEditable")
        except Exception:
            pass

        if tag_name in ("textarea", "input") and not is_editable:
            try:
                await input_el.fill(prompt)
            except Exception:
                await input_el.click()
                await page.keyboard.insert_text(prompt)
        else:
            # Contenteditable (ProseMirror / Quill / TipTap)
            await input_el.scroll_into_view_if_needed()
            await input_el.click()
            await asyncio.sleep(0.3)
            try:
                await page.keyboard.insert_text(prompt)
            except Exception as e:
                logger.debug(f"keyboard.insert_text failed: {e}")

            # Verify editor populated
            editor_len = await page.evaluate(
                """(el) => (el.innerText || el.textContent || el.value || '').trim().length""",
                input_el,
            )
            if editor_len < 10:
                logger.info(f"Using JS execCommand fallback to insert prompt for {role.value}...")
                await page.evaluate(
                    """([el, text]) => {
                        el.focus();
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertText', false, text);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }""",
                    [input_el, prompt],
                )

        # 3. Submit message
        await asyncio.sleep(0.8)
        send_btn_selectors = [
            "button[data-testid='send-button']",
            "button[aria-label*='Send' i]",
            "button[aria-label*='Submit' i]",
            "button.send-button",
            "fieldset button:has(svg)",
            "button:has(svg path[d*='M2.01 21L23 12'])",
        ]
        submitted = False
        for btn_sel in send_btn_selectors:
            try:
                btn = await page.query_selector(btn_sel)
                if btn and await btn.is_visible() and not (await btn.is_disabled()):
                    await btn.click()
                    submitted = True
                    logger.info(f"Clicked send button: {btn_sel}")
                    break
            except Exception:
                continue

        if not submitted:
            await page.keyboard.press("Enter")
            logger.info("Submitted via Enter keypress")

        # 4. Wait for response completion
        # Heuristic: Monitor response elements until text stabilizes
        start_time = asyncio.get_event_loop().time()
        last_text = ""
        stable_count = 0

        # Wait at least 3.0 seconds for generation to start before polling stabilization
        await asyncio.sleep(3.0)

        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            await asyncio.sleep(1.5)
            try:
                # Common response containers
                content = await page.evaluate(
                    """() => {
                        const responses = document.querySelectorAll(
                            '[data-message-author-role="assistant"], .model-response-text, .font-claude-message, message-content, article, .markdown'
                        );
                        if (responses.length > 0) {
                            return responses[responses.length - 1].innerText || "";
                        }
                        return "";
                    }"""
                )
                content = (content or "").strip()
                if content and content == last_text and len(content) > 50:
                    stable_count += 1
                    if stable_count >= 2:
                        return content
                else:
                    if content:
                        last_text = content
                    stable_count = 0
            except Exception:
                continue

        if last_text and len(last_text) > 50 and last_text != "Response captured.":
            return last_text
        raise RuntimeError(f"No valid response generated by {role.value} within {timeout_seconds}s timeout.")

    async def generate_direct_llm_fallback(self, role: AgentRole, prompt: str) -> str:
        """
        Direct LLM fallback using Google GenAI SDK when browser automation
        encounters login hurdles, Cloudflare bot detection, or UI selector drifts.
        Ensures the user's multi-agent workflow never breaks.
        """
        if self.simulate_responses:
            return self._generate_simulated_response(role, prompt)

        try:
            from google import genai
            api_key = os.getenv("GEMINI_API_KEY")
            client = genai.Client(api_key=api_key) if api_key else genai.Client()
            model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
            logger.info(f"Invoking direct Gemini LLM fallback ({model}) for {role.value}...")

            role_system_notes = {
                AgentRole.GEMINI_RESEARCHER: "You are the Gemini Research & Planning Agent. Provide deep, structured research and architecture in markdown format.",
                AgentRole.CHATGPT_PROMPT_ENGINEER: "You are the ChatGPT Prompt Engineering Agent. Transform research into detailed modular specifications and prompts in markdown format.",
                AgentRole.CLAUDE_DEVELOPER: "You are the Claude Development Agent. Generate concrete code architecture and execution plans in markdown format.",
            }
            enriched_prompt = f"{role_system_notes.get(role, '')}\n\n{prompt}"

            response = await client.aio.models.generate_content(
                model=model,
                contents=enriched_prompt,
            )
            text = response.text or ""
            if text.strip():
                return text.strip()
            raise ValueError("Empty response from GenAI client")
        except Exception as exc:
            logger.error(f"Direct LLM fallback error: {exc}")
            raise

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
