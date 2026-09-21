"""
Victor 2.0 Configuration.

Typed, validated configuration loaded from environment variables and
config/default.yaml. Uses pydantic-settings for environment binding
and falls back to YAML for structured defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml
from pydantic import BaseModel, ConfigDict, Field

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "config" / "default.yaml"
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:
    load_dotenv()


def _load_yaml_defaults() -> dict[str, Any]:
    """Load config/default.yaml if it exists and is non-empty."""
    if _CONFIG_FILE.exists():
        with _CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
    return {}


class SecurityConfig(BaseModel):
    """Authentication and session security settings."""
    auth_mode: str = "pin"  # "pin" or "passphrase"
    max_failed_attempts: int = 3
    lockout_seconds: int = 600
    session_timeout_minutes: int = 15
    secrets_path: str = str(_PROJECT_ROOT / "config" / "secrets.yaml")
    biometric_timeout_seconds: float = 60.0


class FilesystemConfig(BaseModel):
    """Filesystem tool sandboxing settings."""
    allowed_roots: list[str] = Field(default_factory=lambda: [str(Path.home())])
    max_read_bytes: int = 1_000_000  # 1 MB


class BrowserConfig(BaseModel):
    """Playwright browser automation settings."""
    headless: bool = False
    default_timeout_ms: int = 10_000


class ComputerConfig(BaseModel):
    """Windows OS automation settings."""
    applications: dict[str, str] = Field(default_factory=lambda: {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "command_prompt": "cmd.exe",
        "task_manager": "taskmgr.exe",
        "control_panel": "control.exe",
        "system_information": "msinfo32.exe",
        "on_screen_keyboard": "osk.exe",
        "vscode": "code",
    })


class MemoryConfig(BaseModel):
    """Memory & Context Manager settings."""
    db_path: str = str(_PROJECT_ROOT / "config" / "memory.db")
    max_recall_results: int = 3
    enabled: bool = True


class CodingConfig(BaseModel):
    """Coding Computer Control & Groq inference settings."""
    groq_api_key: str = Field(default_factory=lambda: os.getenv("GROQ_API") or os.getenv("GROQ_API_KEY") or "")
    groq_model: str = "openai/gpt-oss-20b"
    groq_api_base: str = "https://api.groq.com/openai/v1"
    approved_workspace_roots: list[str] = Field(default_factory=lambda: [
        str(Path.home()),
        "E:\\",
        "C:\\Projects",
        "D:\\Projects",
        "E:\\Projects",
        str(_PROJECT_ROOT),
    ])
    max_fix_iterations: int = 2
    command_timeout_seconds: int = 30
    vscode_path: str = ""


class MultiAgentConfig(BaseModel):
    """Multi-Agent Project Planning & Execution settings."""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    downloads_dir: str | Path = Field(default_factory=lambda: str(Path.home() / "Downloads"))
    gemini_url: str = "https://gemini.google.com"
    chatgpt_url: str = "https://chatgpt.com"
    claude_url: str = "https://claude.ai"
    browser_timeout_seconds: int = 60
    simulate_responses: bool = Field(default_factory=lambda: os.getenv("MULTI_AGENT_SIMULATE", "").lower() in ("true", "1", "yes"))


class VictorConfig(BaseModel):
    """Top-level configuration for Victor 2.0."""
    host: str = "0.0.0.0"
    port: int = 8000
    gemini_model: str = "gemini-3.8-live"

    security: SecurityConfig = Field(default_factory=SecurityConfig)
    filesystem: FilesystemConfig = Field(default_factory=FilesystemConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    computer: ComputerConfig = Field(default_factory=ComputerConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    coding: CodingConfig = Field(default_factory=CodingConfig)
    multi_agent: MultiAgentConfig = Field(default_factory=MultiAgentConfig)


def load_config() -> VictorConfig:
    """Build VictorConfig from YAML defaults + environment overrides."""
    yaml_data = _load_yaml_defaults()

    # Environment overrides take precedence
    env_overrides: dict[str, Any] = {}
    if os.getenv("VICTOR_HOST"):
        env_overrides["host"] = os.getenv("VICTOR_HOST")
    if os.getenv("VICTOR_PORT"):
        env_overrides["port"] = int(os.getenv("VICTOR_PORT"))
    if os.getenv("GEMINI_MODEL"):
        env_overrides["gemini_model"] = os.getenv("GEMINI_MODEL")
    if os.getenv("BROWSER_HEADLESS"):
        headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
        browser_cfg = yaml_data.get("browser", {})
        browser_cfg["headless"] = headless
        yaml_data["browser"] = browser_cfg
    if os.getenv("VICTOR_AUTH_MODE"):
        security_cfg = yaml_data.get("security", {})
        security_cfg["auth_mode"] = os.getenv("VICTOR_AUTH_MODE")
        yaml_data["security"] = security_cfg
    if os.getenv("BIOMETRIC_TIMEOUT_SECONDS"):
        security_cfg = yaml_data.get("security", {})
        try:
            security_cfg["biometric_timeout_seconds"] = float(os.getenv("BIOMETRIC_TIMEOUT_SECONDS"))
            yaml_data["security"] = security_cfg
        except ValueError:
            pass
    if os.getenv("VICTOR_MEMORY_DB"):
        memory_cfg = yaml_data.get("memory", {})
        memory_cfg["db_path"] = os.getenv("VICTOR_MEMORY_DB")
        yaml_data["memory"] = memory_cfg

    # Coding overrides
    coding_cfg = yaml_data.get("coding", {})
    groq_key = os.getenv("GROQ_API") or os.getenv("GROQ_API_KEY")
    if groq_key:
        coding_cfg["groq_api_key"] = groq_key
    if os.getenv("GROQ_CODING_MODEL"):
        coding_cfg["groq_model"] = os.getenv("GROQ_CODING_MODEL")
    if os.getenv("GROQ_API_BASE"):
        coding_cfg["groq_api_base"] = os.getenv("GROQ_API_BASE")
    if os.getenv("VSCODE_PATH"):
        coding_cfg["vscode_path"] = os.getenv("VSCODE_PATH")
    if coding_cfg:
        yaml_data["coding"] = coding_cfg

    # Multi-Agent overrides
    multi_agent_cfg = yaml_data.get("multi_agent", {})
    if os.getenv("MULTI_AGENT_DOWNLOADS_DIR"):
        multi_agent_cfg["downloads_dir"] = os.getenv("MULTI_AGENT_DOWNLOADS_DIR")
    if multi_agent_cfg:
        yaml_data["multi_agent"] = multi_agent_cfg

    merged = {**yaml_data, **env_overrides}
    return VictorConfig(**merged)


