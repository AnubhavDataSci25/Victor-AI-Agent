"""
Unit tests for Victor 2.0 System Information & Quick System Control module.

Verifies deterministic native Windows telemetry and safe system controls
(battery, network, bluetooth, brightness, volume, CPU/RAM, notifications, settings)
and their integration with ToolRegistry and PermissionEngine.
"""

import ctypes
from unittest.mock import MagicMock, patch
import pytest

from app.tools.permissions import PermissionLevel
from app.tools.system import (
    SystemAdjustBrightnessTool,
    SystemAdjustVolumeTool,
    SystemGetBatteryTool,
    SystemGetBluetoothTool,
    SystemGetBrightnessTool,
    SystemGetInfoTool,
    SystemGetNetworkTool,
    SystemGetNotificationsTool,
    SystemGetPerformanceTool,
    SystemGetTimeTool,
    SystemGetVolumeTool,
    SystemOpenNotificationPanelTool,
    SystemOpenSettingsTool,
)
from app.tools.system.hardware import (
    adjust_brightness,
    adjust_volume,
    get_battery_status,
    get_bluetooth_status,
    get_brightness,
    get_master_volume,
    get_network_status,
    get_notification_status,
    get_system_performance,
    open_notification_panel,
    open_windows_settings,
    SYSTEM_POWER_STATUS,
)
from app.tools.tool_setup import build_tool_registry


# ==============================================================================
# 1. BATTERY TELEMETRY TESTS
# ==============================================================================
def test_battery_status_laptop_charging():
    with patch("ctypes.windll.kernel32.GetSystemPowerStatus") as mock_power:
        def fake_power(sps_ptr):
            sps_ptr._obj.ACLineStatus = 1
            sps_ptr._obj.BatteryFlag = 1
            sps_ptr._obj.BatteryLifePercent = 85
            return 1

        mock_power.side_effect = fake_power
        status = get_battery_status()
        assert "85%" in status
        assert "plugged in and charging" in status


def test_battery_status_laptop_discharging():
    with patch("ctypes.windll.kernel32.GetSystemPowerStatus") as mock_power:
        def fake_power(sps_ptr):
            sps_ptr._obj.ACLineStatus = 0
            sps_ptr._obj.BatteryFlag = 0
            sps_ptr._obj.BatteryLifePercent = 42
            return 1

        mock_power.side_effect = fake_power
        status = get_battery_status()
        assert "42%" in status
        assert "discharging on battery power" in status


def test_battery_status_desktop_no_battery():
    with patch("ctypes.windll.kernel32.GetSystemPowerStatus") as mock_power:
        def fake_power(sps_ptr):
            sps_ptr._obj.ACLineStatus = 1
            sps_ptr._obj.BatteryFlag = 128  # No system battery
            sps_ptr._obj.BatteryLifePercent = 255
            return 1

        mock_power.side_effect = fake_power
        status = get_battery_status()
        assert "desktop workstation" in status
        assert "no battery present" in status


def test_battery_status_real_call():
    """Verify the real native kernel32 API does not throw an exception."""
    status = get_battery_status()
    assert isinstance(status, str)
    assert len(status) > 0


# ==============================================================================
# 2. NETWORK & WI-FI TESTS
# ==============================================================================
def test_network_status_connected_wifi():
    mock_netsh_out = (
        "There is 1 interface on the system:\n"
        "    Name                   : Wi-Fi\n"
        "    State                  : connected\n"
        "    SSID                   : Office_5G\n"
        "    Signal                 : 95%\n"
    )
    with patch("ctypes.windll.wininet.InternetGetConnectedState", return_value=1), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_netsh_out, returncode=0)
        status = get_network_status()
        assert "Office_5G" in status
        assert "95%" in status
        assert "Internet is active and online" in status


def test_network_status_disconnected_wifi():
    mock_netsh_out = (
        "There is 1 interface on the system:\n"
        "    Name                   : Wi-Fi\n"
        "    State                  : disconnected\n"
    )
    with patch("ctypes.windll.wininet.InternetGetConnectedState", return_value=0), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_netsh_out, returncode=0)
        status = get_network_status()
        assert "Wi-Fi is currently disconnected" in status
        assert "Internet appears offline" in status


def test_network_status_ethernet_only():
    mock_netsh_out = "There is no wireless interface on the system.\n"
    with patch("ctypes.windll.wininet.InternetGetConnectedState", return_value=1), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mock_netsh_out, returncode=0)
        status = get_network_status()
        assert "No wireless Wi-Fi adapter detected" in status
        assert "Internet is active and online" in status


def test_network_status_real_call():
    status = get_network_status()
    assert isinstance(status, str)
    assert len(status) > 0


# ==============================================================================
# 3. BLUETOOTH STATUS TESTS
# ==============================================================================
def test_bluetooth_active_device():
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            if cmd[0] == "sc":
                return MagicMock(stdout="STATE: 4 RUNNING", returncode=0)
            else:
                return MagicMock(stdout='{"FriendlyName": "Intel Wireless Bluetooth"}', returncode=0)

        mock_run.side_effect = side_effect
        status = get_bluetooth_status()
        assert "Bluetooth is enabled and active" in status
        assert "Intel Wireless Bluetooth" in status


def test_bluetooth_disabled_service():
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            if cmd[0] == "sc":
                return MagicMock(stdout="STATE: 1 STOPPED", returncode=0)
            else:
                return MagicMock(stdout="", returncode=0)

        mock_run.side_effect = side_effect
        status = get_bluetooth_status()
        assert "Bluetooth is currently disabled" in status


def test_bluetooth_real_call():
    status = get_bluetooth_status()
    assert isinstance(status, str)
    assert len(status) > 0


# ==============================================================================
# 4. DISPLAY BRIGHTNESS TESTS & CLAMPING
# ==============================================================================
def test_get_brightness_supported():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout='{"CurrentBrightness": 60}', returncode=0)
        status = get_brightness()
        assert "60%" in status


def test_get_brightness_unsupported_hardware():
    with patch("subprocess.run", side_effect=Exception("WMI not supported")):
        status = get_brightness()
        assert "not supported on this display hardware" in status


def test_adjust_brightness_relative_clamped_upper():
    """Adjusting +20 when at 90 should clamp target to 100%."""
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "Get-CimInstance" in cmd_str:
                return MagicMock(stdout='{"CurrentBrightness": 90}', returncode=0)
            elif "Invoke-CimMethod" in cmd_str:
                # Verify Brightness = 100
                assert "Brightness = 100" in cmd_str
                return MagicMock(stdout="", returncode=0)
            return MagicMock(stdout="", returncode=0)

        mock_run.side_effect = side_effect
        result = adjust_brightness(delta_percent=20)
        assert "Adjusted screen brightness from 90% to 100%" in result


def test_adjust_brightness_relative_clamped_lower():
    """Adjusting -20 when at 10 should clamp target to 0%."""
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "Get-CimInstance" in cmd_str:
                return MagicMock(stdout='{"CurrentBrightness": 10}', returncode=0)
            elif "Invoke-CimMethod" in cmd_str:
                assert "Brightness = 0" in cmd_str
                return MagicMock(stdout="", returncode=0)
            return MagicMock(stdout="", returncode=0)

        mock_run.side_effect = side_effect
        result = adjust_brightness(delta_percent=-20)
        assert "Adjusted screen brightness from 10% to 0%" in result


def test_adjust_brightness_exact_level():
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "Get-CimInstance" in cmd_str:
                return MagicMock(stdout='{"CurrentBrightness": 30}', returncode=0)
            elif "Invoke-CimMethod" in cmd_str:
                assert "Brightness = 75" in cmd_str
                return MagicMock(stdout="", returncode=0)
            return MagicMock(stdout="", returncode=0)

        mock_run.side_effect = side_effect
        result = adjust_brightness(level_percent=75)
        assert "Adjusted screen brightness from 30% to 75%" in result


def test_adjust_brightness_already_at_level():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout='{"CurrentBrightness": 50}', returncode=0)
        result = adjust_brightness(level_percent=50)
        assert "already at 50%" in result


# ==============================================================================
# 5. AUDIO MASTER VOLUME TESTS
# ==============================================================================
def test_adjust_volume_mute():
    with patch("ctypes.windll.user32.keybd_event") as mock_kb:
        result = adjust_volume(action="mute")
        assert "Toggled system mute" in result
        assert mock_kb.call_count >= 2


def test_adjust_volume_up_down():
    with patch("ctypes.windll.user32.keybd_event") as mock_kb, \
         patch("app.tools.system.hardware.get_master_volume", return_value="Current master volume is 50%"):
        res_up = adjust_volume(action="up", steps=2)
        assert "Increased system volume by 2 steps" in res_up

        res_down = adjust_volume(action="down", steps=3)
        assert "Decreased system volume by 3 steps" in res_down


def test_get_master_volume_real_call():
    status = get_master_volume()
    assert isinstance(status, str)
    assert len(status) > 0


# ==============================================================================
# 6. PERFORMANCE TELEMETRY TESTS
# ==============================================================================
def test_get_system_performance():
    perf = get_system_performance()
    assert "CPU Usage:" in perf
    assert "RAM Usage:" in perf
    assert "GB used of" in perf
    assert "GB total" in perf


# ==============================================================================
# 7. WINDOWS SETTINGS LAUNCHER TESTS
# ==============================================================================
def test_open_windows_settings_whitelist():
    with patch("ctypes.windll.shell32.ShellExecuteW", return_value=42) as mock_shell:
        res_bt = open_windows_settings("bluetooth")
        assert "Opened Windows Bluetooth & Devices Settings" in res_bt
        mock_shell.assert_called_with(None, "open", "ms-settings:bluetooth", None, None, 1)

        res_wifi = open_windows_settings("wifi")
        assert "Opened Windows Wi-Fi Settings" in res_wifi
        mock_shell.assert_called_with(None, "open", "ms-settings:network-wifi", None, None, 1)

        res_sound = open_windows_settings("sound")
        assert "Opened Windows Sound Settings" in res_sound
        mock_shell.assert_called_with(None, "open", "ms-settings:sound", None, None, 1)


def test_open_windows_settings_unknown_page():
    res = open_windows_settings("invalid_secret_page")
    assert "Unknown settings page" in res
    assert "Supported pages:" in res


# ==============================================================================
# 8. NOTIFICATIONS CENTER TESTS
# ==============================================================================
def test_notification_panel_trigger():
    with patch("ctypes.windll.user32.keybd_event") as mock_kb:
        res = open_notification_panel()
        assert "Opened Windows Notification Center" in res
        assert mock_kb.call_count >= 4


def test_notification_status_explanation():
    status = get_notification_status()
    assert "Windows protects private notification content" in status
    assert "Notification Center" in status


# ==============================================================================
# 9. ASYNC TOOL WRAPPER & PERMISSION TESTS
# ==============================================================================
@pytest.mark.asyncio
async def test_all_system_tools_permission_safe():
    tools = [
        SystemGetBatteryTool(),
        SystemGetNetworkTool(),
        SystemGetBluetoothTool(),
        SystemGetBrightnessTool(),
        SystemAdjustBrightnessTool(),
        SystemGetVolumeTool(),
        SystemAdjustVolumeTool(),
        SystemGetPerformanceTool(),
        SystemGetNotificationsTool(),
        SystemOpenNotificationPanelTool(),
        SystemOpenSettingsTool(),
        SystemGetTimeTool(),
        SystemGetInfoTool(),
    ]
    for tool in tools:
        assert tool.permission_level == PermissionLevel.SAFE
        schema = tool.get_schema()
        assert "name" in schema
        assert "description" in schema
        assert "parameters" in schema


@pytest.mark.asyncio
async def test_tool_execute_battery():
    tool = SystemGetBatteryTool()
    with patch("app.tools.system.tool.get_battery_status", return_value="Battery is at 80% (charging)."):
        res = await tool.execute({})
        assert "Battery is at 80%" in res


@pytest.mark.asyncio
async def test_tool_execute_brightness_adjust():
    tool = SystemAdjustBrightnessTool()
    with patch("app.tools.system.tool.adjust_brightness", return_value="Adjusted screen brightness from 40% to 45%."):
        res = await tool.execute({"delta_percent": 5})
        assert "Adjusted screen brightness from 40% to 45%" in res


@pytest.mark.asyncio
async def test_tool_execute_settings():
    tool = SystemOpenSettingsTool()
    with patch("app.tools.system.tool.open_windows_settings", return_value="Opened Windows Sound Settings."):
        res = await tool.execute({"page": "sound"})
        assert "Opened Windows Sound Settings" in res


# ==============================================================================
# 10. TOOL REGISTRY INTEGRATION
# ==============================================================================
def test_tool_registry_contains_all_system_tools():
    registry = build_tool_registry()
    expected_tools = [
        "system_get_time",
        "system_get_info",
        "system_get_battery",
        "system_get_network",
        "system_get_bluetooth",
        "system_get_brightness",
        "system_adjust_brightness",
        "system_get_volume",
        "system_adjust_volume",
        "system_get_performance",
        "system_get_notifications",
        "system_open_notification_panel",
        "system_open_settings",
        "system_lock_windows",
        "lock_victor",
    ]
    for tool_name in expected_tools:
        tool = registry.get_tool(tool_name)
        assert tool is not None, f"Tool '{tool_name}' was not registered in ToolRegistry"
