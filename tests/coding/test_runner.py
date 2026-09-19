"""
Tests for ControlledTerminalRunner, timeout handling, and safety enforcement.
"""

from pathlib import Path
import pytest

from app.coding.runner import (
    ControlledTerminalRunner,
    CommandSecurityError,
    CommandConfirmationRequired,
)
from app.tools.permissions import PermissionEngine, PermissionLevel


@pytest.mark.asyncio
async def test_run_safe_command(tmp_path: Path):
    runner = ControlledTerminalRunner(tmp_path)
    result = await runner.run_command("python --version")
    assert result.success
    assert result.exit_code == 0
    assert "Python" in result.stdout or "Python" in result.stderr


@pytest.mark.asyncio
async def test_block_dangerous_command(tmp_path: Path):
    runner = ControlledTerminalRunner(tmp_path)
    with pytest.raises(CommandSecurityError):
        await runner.run_command("rm -rf /")

    with pytest.raises(CommandSecurityError):
        await runner.run_command("del /f /s /q c:\\")


@pytest.mark.asyncio
async def test_package_install_requires_confirmation(tmp_path: Path):
    runner = ControlledTerminalRunner(tmp_path)

    # Without confirmation -> raises CommandConfirmationRequired
    with pytest.raises(CommandConfirmationRequired):
        await runner.run_command("pip install requests", user_confirmed=False)

    # Note: We don't actually run pip install in test to avoid installing,
    # but the classification check confirms it requires confirmation.
    assert runner.classify_command("pip install requests") == PermissionLevel.MEDIUM
    assert runner.classify_command("npm install lodash") == PermissionLevel.MEDIUM


@pytest.mark.asyncio
async def test_command_timeout(tmp_path: Path):
    runner = ControlledTerminalRunner(tmp_path, timeout_seconds=1.0)
    # Run python command that sleeps longer than timeout
    res = await runner.run_command("python -c \"import time; time.sleep(3)\"", timeout_override=0.5)
    assert not res.success
    assert res.error_type == "timeout"
    assert "timed out" in res.stderr
