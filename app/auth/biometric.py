"""
Native Windows Hello Biometric Verifier (UserConsentVerifier).

Provides 2FA biometric verification using native Windows APIs:
Windows.Security.Credentials.UI.UserConsentVerifier.

Security Rules:
- Victor NEVER captures, stores, processes, transmits, or compares fingerprint data.
- Only receives the high-level OS verification result (VERIFIED or error enum).
- Zero external API keys, zero cloud services, zero biometric data storage.
- Non-sensitive logging only (never log biometric templates, PINs, tokens, or private secrets).
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from enum import Enum

from app.logging import get_logger, log_event

logger = get_logger("auth.biometric")


class BiometricAvailability(str, Enum):
    AVAILABLE = "Available"
    DEVICE_NOT_PRESENT = "DeviceNotPresent"
    NOT_CONFIGURED_FOR_USER = "NotConfiguredForUser"
    DISABLED_BY_POLICY = "DisabledByPolicy"
    DEVICE_BUSY = "DeviceBusy"
    UNKNOWN = "Unknown"


class BiometricResult(str, Enum):
    VERIFIED = "Verified"
    DEVICE_NOT_PRESENT = "DeviceNotPresent"
    NOT_CONFIGURED_FOR_USER = "NotConfiguredForUser"
    DISABLED_BY_POLICY = "DisabledByPolicy"
    DEVICE_BUSY = "DeviceBusy"
    RETRIES_EXHAUSTED = "RetriesExhausted"
    CANCELED = "Canceled"
    TIMEOUT = "Timeout"
    ERROR = "Error"


class BaseBiometricVerifier(ABC):
    @abstractmethod
    async def check_availability(self) -> BiometricAvailability:
        """Check if Windows Hello / biometric verification is supported and configured."""
        pass

    @abstractmethod
    async def request_verification(self, prompt: str) -> BiometricResult:
        """Request native Windows Hello biometric verification from the user."""
        pass


class WindowsHelloVerifier(BaseBiometricVerifier):
    """
    Native Windows Hello Verifier using Windows.Security.Credentials.UI.UserConsentVerifier.
    Invokes the native WinRT API via a PowerShell runtime bridge.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def check_availability(self) -> BiometricAvailability:
        """
        Queries UserConsentVerifier.CheckAvailabilityAsync() for biometric availability.
        """
        ps_cmd = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
            "$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { "
            "  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' "
            "}; "
            "$op = [Windows.Security.Credentials.UI.UserConsentVerifier,Windows.Security.Credentials.UI,ContentType=WindowsRuntime]::CheckAvailabilityAsync(); "
            "$task = $asTaskGeneric.MakeGenericMethod([Windows.Security.Credentials.UI.UserConsentVerifierAvailability,Windows.Security.Credentials.UI,ContentType=WindowsRuntime]).Invoke($null, @($op)); "
            "$task.Wait(); "
            "Write-Output ('RESULT:' + $task.Result.ToString())"
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", ps_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            raw = stdout.decode("utf-8", errors="ignore")

            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("RESULT:"):
                    status_str = line.split(":", 1)[1].strip()
                    try:
                        status = BiometricAvailability(status_str)
                        log_event(logger, logging.INFO, "biometric_availability_checked", status=status.value)
                        return status
                    except ValueError:
                        log_event(logger, logging.WARNING, "biometric_availability_unknown_value", raw=status_str)
                        return BiometricAvailability.UNKNOWN

            log_event(logger, logging.WARNING, "biometric_availability_no_result")
            return BiometricAvailability.UNKNOWN

        except asyncio.TimeoutError:
            log_event(logger, logging.ERROR, "biometric_availability_timeout")
            return BiometricAvailability.UNKNOWN
        except Exception as e:
            log_event(logger, logging.ERROR, "biometric_availability_error", error=str(e))
            return BiometricAvailability.UNKNOWN

    async def request_verification(self, prompt: str = "Victor AI Agent Authentication") -> BiometricResult:
        """
        Invokes UserConsentVerifier.RequestVerificationAsync(prompt) and returns BiometricResult.
        """
        # Escape any single quotes in prompt
        escaped_prompt = prompt.replace("'", "''")
        timeout_ms = int(self.timeout_seconds * 1000)

        ps_cmd = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
            "$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { "
            "  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 2 -and $_.IsGenericMethod -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' -and $_.GetParameters()[1].ParameterType.Name -eq 'CancellationToken' "
            "}; "
            f"$cts = New-Object System.Threading.CancellationTokenSource; "
            f"$cts.CancelAfter({timeout_ms}); "
            f"$op = [Windows.Security.Credentials.UI.UserConsentVerifier,Windows.Security.Credentials.UI,ContentType=WindowsRuntime]::RequestVerificationAsync('{escaped_prompt}'); "
            "$task = $asTaskGeneric.MakeGenericMethod([Windows.Security.Credentials.UI.UserConsentVerificationResult,Windows.Security.Credentials.UI,ContentType=WindowsRuntime]).Invoke($null, @($op, $cts.Token)); "
            "try { "
            "  $task.Wait($cts.Token); "
            "  Write-Output ('RESULT:' + $task.Result.ToString()); "
            "} catch [System.OperationCanceledException] { "
            "  Write-Output 'RESULT:Timeout'; "
            "} catch { "
            "  Write-Output 'RESULT:Error'; "
            "}"
        )

        try:
            log_event(logger, logging.INFO, "biometric_verification_requested")
            proc = await asyncio.create_subprocess_exec(
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", ps_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_seconds + 5.0)
            raw = stdout.decode("utf-8", errors="ignore")

            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("RESULT:"):
                    status_str = line.split(":", 1)[1].strip()
                    try:
                        result = BiometricResult(status_str)
                        log_event(logger, logging.INFO, "biometric_verification_completed", result=result.value)
                        return result
                    except ValueError:
                        log_event(logger, logging.WARNING, "biometric_verification_unknown_result", raw=status_str)
                        return BiometricResult.ERROR

            log_event(logger, logging.WARNING, "biometric_verification_no_result")
            return BiometricResult.ERROR

        except asyncio.TimeoutError:
            log_event(logger, logging.WARNING, "biometric_verification_timeout")
            return BiometricResult.TIMEOUT
        except Exception as e:
            log_event(logger, logging.ERROR, "biometric_verification_error", error=str(e))
            return BiometricResult.ERROR
