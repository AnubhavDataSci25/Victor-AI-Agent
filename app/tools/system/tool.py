"""
System Information and Quick System Control Tools for Victor 2.0.

Provides deterministic native Windows telemetry and safe system controls
(battery, network, bluetooth, brightness, volume, CPU/RAM, notifications, settings)
without external cloud dependencies or LLM-based API control.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import platform
from typing import Any, Dict

from app.tools.base import BaseTool
from app.tools.computer.windows_driver import WindowsComputerDriver
from app.tools.permissions import PermissionLevel
from app.tools.system.hardware import (
    adjust_brightness,
    adjust_volume,
    get_battery_status,
    get_bluetooth_status,
    get_brightness,
    get_master_volume,
    get_notification_status,
    get_network_status,
    get_system_performance,
    open_notification_panel,
    open_windows_settings,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. TIME & BASIC OS INFO
# ==============================================================================
class SystemGetTimeTool(BaseTool):
    name = "system_get_time"
    description = "Gets the current system time and date."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        now = datetime.datetime.now()
        return now.strftime("Current System Time: %A, %B %d, %Y at %I:%M:%S %p")


class SystemGetInfoTool(BaseTool):
    name = "system_get_info"
    description = "Retrieves basic system information (OS, version, architecture)."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        try:
            os_name = platform.system()
            release = platform.release()
            arch = platform.machine()
            return f"System Info: {os_name} {release} ({arch})"
        except Exception as e:
            return f"Error retrieving system info: {str(e)}"


# ==============================================================================
# 2. BATTERY & POWER
# ==============================================================================
class SystemGetBatteryTool(BaseTool):
    name = "system_get_battery"
    description = "Retrieves real-time Windows battery percentage, charging state, and AC power status. Safe and read-only."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await asyncio.to_thread(get_battery_status)


# ==============================================================================
# 3. NETWORK & WI-FI
# ==============================================================================
class SystemGetNetworkTool(BaseTool):
    name = "system_get_network"
    description = "Queries active Wi-Fi connection, network SSID, signal strength, and live internet connectivity status."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await asyncio.to_thread(get_network_status)


# ==============================================================================
# 4. BLUETOOTH
# ==============================================================================
class SystemGetBluetoothTool(BaseTool):
    name = "system_get_bluetooth"
    description = "Checks whether Bluetooth is enabled and detects active Bluetooth radio hardware and device connectivity."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await asyncio.to_thread(get_bluetooth_status)


# ==============================================================================
# 5. DISPLAY BRIGHTNESS
# ==============================================================================
class SystemGetBrightnessTool(BaseTool):
    name = "system_get_brightness"
    description = "Retrieves current display brightness percentage on supported internal monitors via WMI."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await asyncio.to_thread(get_brightness)


class SystemAdjustBrightnessTool(BaseTool):
    name = "system_adjust_brightness"
    description = (
        "Adjusts display brightness with clamping [0-100%]. Accepts relative 'delta_percent' "
        "(e.g., +5 or -5, default is +5) or an exact target 'level_percent'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "delta_percent": {
                "type": "integer",
                "description": "Relative percentage to increase (+) or decrease (-) brightness (e.g., 5, -5, 10).",
            },
            "level_percent": {
                "type": "integer",
                "description": "Optional exact target brightness percentage (0 to 100).",
            },
        },
    }

    async def execute(self, args: dict) -> str:
        delta = args.get("delta_percent", 5)
        level = args.get("level_percent")
        try:
            delta = int(delta) if delta is not None else 5
        except (ValueError, TypeError):
            delta = 5
        try:
            level = int(level) if level is not None else None
        except (ValueError, TypeError):
            level = None
        return await asyncio.to_thread(adjust_brightness, delta_percent=delta, level_percent=level)


# ==============================================================================
# 6. AUDIO VOLUME & MUTE
# ==============================================================================
class SystemGetVolumeTool(BaseTool):
    name = "system_get_volume"
    description = "Reads current Windows master audio volume percentage and mute status."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await asyncio.to_thread(get_master_volume)


class SystemAdjustVolumeTool(BaseTool):
    name = "system_adjust_volume"
    description = (
        "Adjusts Windows master volume (mute, up, down, or exact target level_percent). "
        "Provide 'steps' for up/down increments."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["mute", "up", "down"],
                "description": "Volume action to perform.",
            },
            "steps": {
                "type": "integer",
                "description": "Number of volume increments/decrements (default 1).",
                "default": 1,
            },
            "level_percent": {
                "type": "integer",
                "description": "Optional exact master audio volume percentage (0 to 100).",
            },
        },
    }

    async def execute(self, args: dict) -> str:
        action = args.get("action", "up")
        try:
            steps = int(args.get("steps", 1))
        except (ValueError, TypeError):
            steps = 1
        level = args.get("level_percent")
        try:
            level = int(level) if level is not None else None
        except (ValueError, TypeError):
            level = None
        return await asyncio.to_thread(
            adjust_volume, action=action, steps=steps, level_percent=level
        )


# Backward-compatibility alias
SystemVolumeTool = SystemAdjustVolumeTool


# ==============================================================================
# 7. CPU & RAM PERFORMANCE
# ==============================================================================
class SystemGetPerformanceTool(BaseTool):
    name = "system_get_performance"
    description = "Retrieves real-time system performance telemetry: CPU utilization percentage and physical RAM usage breakdown."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await asyncio.to_thread(get_system_performance)


# ==============================================================================
# 8. NOTIFICATIONS
# ==============================================================================
class SystemGetNotificationsTool(BaseTool):
    name = "system_get_notifications"
    description = (
        "Explains Windows system notification privacy boundaries and immediately triggers "
        "the native Windows Notification Center panel on screen for the user."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        # Trigger notification panel and return informative status
        await asyncio.to_thread(open_notification_panel)
        return get_notification_status()


class SystemOpenNotificationPanelTool(BaseTool):
    name = "system_open_notification_panel"
    description = "Opens the native Windows Notification Center panel on screen (Win + N)."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await asyncio.to_thread(open_notification_panel)


# ==============================================================================
# 9. WINDOWS SETTINGS
# ==============================================================================
class SystemOpenSettingsTool(BaseTool):
    name = "system_open_settings"
    description = (
        "Opens Windows Settings pages using official ms-settings URI schemes. "
        "Supported pages: 'bluetooth', 'wifi', 'network', 'sound', 'display', 'brightness', "
        "'battery', 'power', 'notifications', 'apps', 'settings'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "page": {
                "type": "string",
                "description": (
                    "Settings page to open: 'bluetooth', 'wifi', 'network', 'sound', "
                    "'display', 'brightness', 'battery', 'power', 'notifications', or 'settings'."
                ),
            }
        },
        "required": ["page"],
    }

    async def execute(self, args: dict) -> str:
        page = args.get("page", "settings")
        return await asyncio.to_thread(open_windows_settings, page)


# ==============================================================================
# 10. SYSTEM & VICTOR LOCKS
# ==============================================================================
class SystemLockWindowsTool(BaseTool):
    name = "system_lock_windows"
    description = "Locks the Windows operating system workstation securely. Note: This locks Windows itself, not Victor."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return WindowsComputerDriver.lock_windows()


class SystemLockVictorTool(BaseTool):
    name = "lock_victor"
    description = "Locks the Victor agent session securely. Call this when the user explicitly asks to 'lock yourself', 'shut down', or 'lock the session'. This terminates the AI connection."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return "Initiating session lock protocol."