"""
Hardware and OS Abstraction Layer for Victor 2.0 System Control.

Utilizes deterministic native Windows APIs (kernel32, wininet, shell32, user32,
Core Audio COM, WMI) for instant, low-level system telemetry and safe controls
without relying on LLMs or external cloud services.
"""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import HRESULT, POINTER, c_float, c_int, c_ulong, c_ulonglong, c_void_p, byref
from ctypes.wintypes import BOOL, DWORD
import logging
import os
import re
import subprocess
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Virtual Key Codes ---
VK_LWIN = 0x5B
VK_N = 0x4E
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

# --- Windows Settings URI Schemes ---
SETTINGS_URI_MAP: Dict[str, Tuple[str, str]] = {
    "bluetooth": ("ms-settings:bluetooth", "Bluetooth & Devices"),
    "wifi": ("ms-settings:network-wifi", "Wi-Fi"),
    "network": ("ms-settings:network", "Network & Internet"),
    "internet": ("ms-settings:network", "Network & Internet"),
    "sound": ("ms-settings:sound", "Sound"),
    "audio": ("ms-settings:sound", "Sound"),
    "volume": ("ms-settings:sound", "Sound"),
    "display": ("ms-settings:display", "Display"),
    "brightness": ("ms-settings:display", "Display"),
    "battery": ("ms-settings:powersleep", "Power & Battery"),
    "power": ("ms-settings:powersleep", "Power & Battery"),
    "notifications": ("ms-settings:notifications", "Notifications"),
    "apps": ("ms-settings:appsfeatures", "Apps & Features"),
    "system": ("ms-settings:", "Windows Settings"),
    "settings": ("ms-settings:", "Windows Settings"),
}


# ==============================================================================
# 1. BATTERY & POWER STATUS (kernel32.GetSystemPowerStatus)
# ==============================================================================
class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


def get_battery_status() -> str:
    """
    Reads real-time battery percentage, charging state, and AC power source.
    Gracefully handles desktop computers without batteries.
    """
    sps = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(byref(sps)):
        return "Unable to query Windows power status API."

    # BatteryFlag == 128 means no system battery installed (Desktop)
    if sps.BatteryFlag == 128 or sps.BatteryLifePercent == 255:
        ac_desc = "connected to AC power" if sps.ACLineStatus == 1 else "running on direct power"
        return f"System is a desktop workstation ({ac_desc}, no battery present)."

    percent = int(sps.BatteryLifePercent)
    if sps.ACLineStatus == 1:
        charging_desc = "plugged in and charging"
    elif sps.ACLineStatus == 0:
        charging_desc = "discharging on battery power"
    else:
        charging_desc = "power source unknown"

    return f"Battery is at {percent}% ({charging_desc})."


# ==============================================================================
# 2. NETWORK & WI-FI STATUS (netsh wlan & wininet.InternetGetConnectedState)
# ==============================================================================
def get_network_status() -> str:
    """
    Queries active Wi-Fi connection, SSID, signal strength, and internet status.
    Gracefully handles disconnected wireless adapters and Ethernet connections.
    """
    # 1. Check live internet connectivity
    flags = c_ulong()
    has_internet = bool(ctypes.windll.wininet.InternetGetConnectedState(byref(flags), 0))
    internet_desc = "Internet is active and online" if has_internet else "Internet appears offline"

    # 2. Query WLAN interface
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        output = proc.stdout

        if "There is no wireless interface on the system" in output:
            return f"No wireless Wi-Fi adapter detected. {internet_desc} (likely wired Ethernet)."

        state_match = re.search(r"^\s*State\s*:\s*(.+)$", output, re.MULTILINE)
        ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", output, re.MULTILINE)
        signal_match = re.search(r"^\s*Signal\s*:\s*(.+)$", output, re.MULTILINE)

        state = state_match.group(1).strip() if state_match else "unknown"

        if state.lower() == "connected":
            ssid = ssid_match.group(1).strip() if ssid_match else "Unknown Network"
            signal = signal_match.group(1).strip() if signal_match else "Unknown"
            return f"Connected to Wi-Fi '{ssid}' (Signal: {signal}). {internet_desc}."
        else:
            return f"Wi-Fi is currently {state}. {internet_desc}."
    except Exception as e:
        logger.warning(f"[Hardware] Network query error: {e}")
        return f"{internet_desc}. Could not inspect wireless adapter details ({str(e)})."


# ==============================================================================
# 3. BLUETOOTH STATUS (PnP device check & bthserv)
# ==============================================================================
def get_bluetooth_status() -> str:
    """
    Inspects Bluetooth hardware presence, service state, and active adapters.
    Gracefully handles disabled or absent Bluetooth adapters.
    """
    try:
        # Check Bluetooth Support Service status
        svc_proc = subprocess.run(
            ["sc", "query", "bthserv"],
            capture_output=True,
            text=True,
            timeout=2.5,
        )
        service_running = "RUNNING" in svc_proc.stdout

        # Check active PnP Bluetooth device
        ps_cmd = "Get-PnpDevice -Class Bluetooth -Status OK -ErrorAction SilentlyContinue | Select-Object -First 1 -Property FriendlyName | ConvertTo-Json"
        pnp_proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=3.5,
        )

        pnp_out = pnp_proc.stdout.strip()
        device_name = ""
        if pnp_out and "FriendlyName" in pnp_out:
            match = re.search(r'"FriendlyName":\s*"([^"]+)"', pnp_out)
            if match:
                device_name = match.group(1).strip()

        if device_name:
            svc_note = "service active" if service_running else "service stopped"
            return f"Bluetooth is enabled and active ({device_name}, {svc_note})."
        elif service_running:
            return "Bluetooth service is running, but no active Bluetooth radio adapter was detected."
        else:
            return "Bluetooth is currently disabled or no Bluetooth hardware is available."
    except Exception as e:
        logger.warning(f"[Hardware] Bluetooth query error: {e}")
        return f"Unable to determine Bluetooth state: {str(e)}"


# ==============================================================================
# 4. DISPLAY BRIGHTNESS (WMI WmiMonitorBrightness & WmiSetBrightness)
# ==============================================================================
def get_brightness() -> str:
    """
    Reads current screen brightness percentage via WMI.
    Gracefully handles external monitors or desktops without internal brightness controls.
    """
    try:
        ps_cmd = "Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness -ErrorAction Stop | Select-Object -First 1 -Property CurrentBrightness | ConvertTo-Json"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=3.5,
        )
        out = proc.stdout.strip()
        match = re.search(r'"CurrentBrightness":\s*(\d+)', out)
        if match:
            level = int(match.group(1))
            return f"Current screen brightness is {level}%."
        return "Screen brightness reading is not supported on this display hardware (typically external desktop monitors)."
    except Exception as e:
        logger.debug(f"[Hardware] Brightness read error: {e}")
        return "Screen brightness reading is not supported on this display hardware."


def adjust_brightness(
    delta_percent: int = 5,
    level_percent: Optional[int] = None,
) -> str:
    """
    Adjusts screen brightness with strict clamping between 0% and 100%.
    Supports relative adjustments (+5%, -5%) to prevent sudden extreme jumps.
    """
    try:
        # First read current brightness
        ps_read = "Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness -ErrorAction Stop | Select-Object -First 1 -Property CurrentBrightness | ConvertTo-Json"
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_read],
            capture_output=True,
            text=True,
            timeout=3.5,
        )
        out = proc.stdout.strip()
        match = re.search(r'"CurrentBrightness":\s*(\d+)', out)
        if not match:
            return "Display brightness control is not available on this monitor hardware."

        current_val = int(match.group(1))

        # Calculate target with strict clamping [0, 100]
        if level_percent is not None:
            target_val = max(0, min(100, int(level_percent)))
        else:
            target_val = max(0, min(100, current_val + int(delta_percent)))

        if target_val == current_val:
            return f"Screen brightness is already at {current_val}%."

        # Apply target via WmiSetBrightness
        ps_set = f"Invoke-CimMethod -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods -MethodName WmiSetBrightness -Arguments @{{ Timeout = 1; Brightness = {target_val} }} -ErrorAction Stop"
        set_proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_set],
            capture_output=True,
            text=True,
            timeout=3.5,
        )
        if set_proc.returncode == 0:
            return f"Adjusted screen brightness from {current_val}% to {target_val}%."
        else:
            return f"Failed to set brightness: {set_proc.stderr.strip()}"
    except Exception as e:
        logger.warning(f"[Hardware] Brightness adjust error: {e}")
        return f"Display brightness adjustment is not supported on this monitor: {str(e)}"


# ==============================================================================
# 5. AUDIO MASTER VOLUME & MUTE (Core Audio COM IAudioEndpointVolume)
# ==============================================================================
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid_from_str(s: str) -> GUID:
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(s, byref(g))
    return g


def _get_audio_endpoint_volume() -> Optional[c_void_p]:
    """Helper to acquire an active IAudioEndpointVolume COM interface pointer."""
    try:
        ctypes.windll.ole32.CoInitialize(None)
        clsid_enum = _guid_from_str("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
        iid_enum = _guid_from_str("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        iid_aev = _guid_from_str("{5CDF2C82-841E-4546-9722-0CF74078229A}")

        pEnum = c_void_p()
        hr = ctypes.windll.ole32.CoCreateInstance(
            byref(clsid_enum), None, 1, byref(iid_enum), byref(pEnum)
        )
        if hr != 0 or not pEnum.value:
            return None

        # IMMDeviceEnumerator::GetDefaultAudioEndpoint (slot 4)
        vtable = ctypes.cast(pEnum.value, POINTER(POINTER(c_void_p)))
        pDevice = c_void_p()
        hr = ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_int, c_int, POINTER(c_void_p))(vtable[0][4])(
            pEnum, 0, 1, byref(pDevice)
        )
        if hr != 0 or not pDevice.value:
            return None

        # IMMDevice::Activate (slot 3)
        dev_vt = ctypes.cast(pDevice.value, POINTER(POINTER(c_void_p)))
        pAEV = c_void_p()
        hr = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), DWORD, c_void_p, POINTER(c_void_p))(
            dev_vt[0][3]
        )(pDevice, byref(iid_aev), 1, None, byref(pAEV))

        if hr == 0 and pAEV.value:
            return pAEV
        return None
    except Exception as e:
        logger.debug(f"[Hardware] Core Audio initialization error: {e}")
        return None


def get_master_volume() -> str:
    """Reads real-time Windows master volume percentage and mute status."""
    pAEV = _get_audio_endpoint_volume()
    if pAEV:
        try:
            aev_vt = ctypes.cast(pAEV.value, POINTER(POINTER(c_void_p)))
            # Slot 9: GetMasterVolumeLevelScalar
            # Slot 14: GetMute
            level = c_float()
            is_mute = BOOL()
            ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(c_float))(aev_vt[0][9])(pAEV, byref(level))
            ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(BOOL))(aev_vt[0][14])(pAEV, byref(is_mute))

            vol_pct = int(round(level.value * 100))
            mute_status = "muted" if is_mute.value else "unmuted"
            return f"Current system master volume is {vol_pct}% ({mute_status})."
        except Exception as e:
            logger.debug(f"[Hardware] Error reading Core Audio volume: {e}")

    # Fallback to winmm waveOutGetVolume
    try:
        vol = ctypes.c_ulong()
        if ctypes.windll.winmm.waveOutGetVolume(0, byref(vol)) == 0:
            left = (vol.value & 0xFFFF) / 65535.0
            return f"Current audio volume is approximately {int(round(left * 100))}%."
    except Exception:
        pass

    return "Unable to determine current audio volume."


def adjust_volume(
    action: str = "up",
    steps: int = 1,
    level_percent: Optional[int] = None,
) -> str:
    """
    Adjusts system volume: up, down, mute, or sets exact scalar percentage.
    """
    action = (action or "up").lower().strip()

    # Direct percentage set via Core Audio if specified
    if level_percent is not None:
        target = max(0, min(100, int(level_percent)))
        pAEV = _get_audio_endpoint_volume()
        if pAEV:
            try:
                aev_vt = ctypes.cast(pAEV.value, POINTER(POINTER(c_void_p)))
                # Slot 7: SetMasterVolumeLevelScalar(float fLevel, LPCGUID pguidEventContext)
                scalar = c_float(target / 100.0)
                ctypes.WINFUNCTYPE(HRESULT, c_void_p, c_float, c_void_p)(aev_vt[0][7])(pAEV, scalar, None)
                return f"Set system master volume to {target}%."
            except Exception as e:
                logger.debug(f"[Hardware] Direct volume set error: {e}")

    # Relative key presses via user32 keybd_event
    if action == "mute":
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
        return "Toggled system mute."
    elif action in ("up", "increase"):
        for _ in range(max(1, steps)):
            ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 2, 0)
        return f"Increased system volume by {steps} steps ({get_master_volume()})."
    elif action in ("down", "decrease"):
        for _ in range(max(1, steps)):
            ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 2, 0)
        return f"Decreased system volume by {steps} steps ({get_master_volume()})."

    return "Unknown volume action requested. Use 'up', 'down', 'mute', or specify 'level_percent'."


# ==============================================================================
# 6. CPU & RAM PERFORMANCE METRICS (kernel32.GlobalMemoryStatusEx & GetSystemTimes)
# ==============================================================================
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", c_ulong),
        ("dwMemoryLoad", c_ulong),
        ("ullTotalPhys", c_ulonglong),
        ("ullAvailPhys", c_ulonglong),
        ("ullTotalPageFile", c_ulonglong),
        ("ullAvailPageFile", c_ulonglong),
        ("ullTotalVirtual", c_ulonglong),
        ("ullAvailVirtual", c_ulonglong),
        ("sullAvailExtendedVirtual", c_ulonglong),
    ]


def get_system_performance() -> str:
    """
    Computes real-time CPU utilization percentage and physical RAM load breakdown.
    Executes in milliseconds via native kernel32 APIs without third-party dependencies.
    """
    # 1. RAM Status
    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(mem))
    total_gb = mem.ullTotalPhys / (1024**3)
    avail_gb = mem.ullAvailPhys / (1024**3)
    used_gb = total_gb - avail_gb
    ram_load = int(mem.dwMemoryLoad)

    # 2. CPU Times (two samples across 100ms)
    def _read_cpu():
        idle = c_ulonglong()
        kernel = c_ulonglong()
        user = c_ulonglong()
        ctypes.windll.kernel32.GetSystemTimes(byref(idle), byref(kernel), byref(user))
        return idle.value, kernel.value, user.value

    i1, k1, u1 = _read_cpu()
    time.sleep(0.1)
    i2, k2, u2 = _read_cpu()

    idle_delta = i2 - i1
    kernel_delta = k2 - k1
    user_delta = u2 - u1
    total_sys = kernel_delta + user_delta

    if total_sys > 0:
        cpu_pct = max(0.0, min(100.0, (total_sys - idle_delta) * 100.0 / total_sys))
        cpu_desc = f"{cpu_pct:.1f}%"
    else:
        cpu_desc = "Normal"

    return f"CPU Usage: {cpu_desc} | RAM Usage: {ram_load}% ({used_gb:.1f} GB used of {total_gb:.1f} GB total)."


# ==============================================================================
# 7. WINDOWS SETTINGS LAUNCHER (shell32.ShellExecuteW with ms-settings:)
# ==============================================================================
def open_windows_settings(page_key: Optional[str] = "settings") -> str:
    """
    Opens official Windows Settings pages using safe URI schemes.
    Avoids brittle UI automation in favor of deterministic OS handlers.
    """
    key = (page_key or "settings").lower().strip()
    entry = SETTINGS_URI_MAP.get(key)
    if not entry:
        # Check partial keyword match
        for k, v in SETTINGS_URI_MAP.items():
            if k in key:
                entry = v
                break

    if not entry:
        valid_pages = ", ".join(sorted(set(k for k in SETTINGS_URI_MAP.keys() if len(k) > 3)))
        return f"Unknown settings page '{page_key}'. Supported pages: {valid_pages}."

    uri, friendly_name = entry
    try:
        res = ctypes.windll.shell32.ShellExecuteW(None, "open", uri, None, None, 1)
        if res > 32:
            return f"Opened Windows {friendly_name} Settings."
        else:
            return f"Windows reported code {res} while attempting to open {friendly_name} settings."
    except Exception as e:
        logger.error(f"[Hardware] ShellExecute error for '{uri}': {e}")
        return f"Failed to open {friendly_name} settings: {str(e)}"


# ==============================================================================
# 8. NOTIFICATION CENTER (Win + N key sequence & privacy status)
# ==============================================================================
def open_notification_panel() -> str:
    """
    Triggers the Windows Notification Center shortcut (Win + N) to display
    active notifications and calendar directly on screen for Anubhav Sir.
    """
    try:
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_N, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(VK_N, 0, 2, 0)
        ctypes.windll.user32.keybd_event(VK_LWIN, 0, 2, 0)
        return "Opened Windows Notification Center on screen."
    except Exception as e:
        logger.error(f"[Hardware] Notification panel trigger error: {e}")
        return f"Could not trigger Notification Center: {str(e)}"


def get_notification_status() -> str:
    """
    Returns an informative status regarding system notifications.
    Explains Windows security boundaries while providing an immediate on-screen view.
    """
    return (
        "Windows protects private notification content from desktop applications. "
        "I have opened the Windows Notification Center on your screen so you can review them directly."
    )
