"""
GPU-Accelerated Voice Activity Detector (VAD) for Victor AI Assistant.

Leverages PyTorch CUDA acceleration for high-speed spectral and energy analysis
of incoming microphone audio frames with zero-downtime CPU fallback.
Designed specifically with strict VRAM safeguards for 2GB GPUs (NVIDIA GeForce MX330).
"""

from __future__ import annotations

import logging
import math
import struct
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class GpuVoiceActivityDetector:
    """
    Intelligent Voice Activity Detector that executes harmonic & energy analysis
    on the GPU via CUDA when available, with immediate seamless CPU fallback.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        min_rms: float = 0.010,
        energy_multiplier: float = 2.4,
        prefer_gpu: bool = True,
    ) -> None:
        self.sample_rate = sample_rate
        self.min_rms = min_rms
        self.energy_multiplier = energy_multiplier
        self.prefer_gpu = prefer_gpu

        self._torch = None
        self._device = None
        self._device_name = "CPU"
        self._is_gpu_active = False
        self._vocal_mask = None
        self._cached_freq_len = 0
        self._consecutive_gpu_errors = 0

        self._init_backend()

    def _init_backend(self) -> None:
        """Initializes PyTorch backend on CUDA if available and requested."""
        try:
            import torch
            self._torch = torch
            if self.prefer_gpu and torch.cuda.is_available():
                # Check free VRAM safety margin (require at least 100 MB free)
                total_mem = torch.cuda.get_device_properties(0).total_memory
                allocated_mem = torch.cuda.memory_allocated(0)
                free_bytes = total_mem - allocated_mem
                if free_bytes > 100 * 1024 * 1024:
                    self._device = torch.device("cuda:0")
                    self._device_name = torch.cuda.get_device_name(0)
                    self._is_gpu_active = True
                    logger.info(f"[GpuVAD] Successfully initialized on GPU: {self._device_name}")
                    return
                else:
                    logger.warning("[GpuVAD] Low VRAM detected (<100MB). Falling back to CPU.")

            self._device = torch.device("cpu")
            self._device_name = "CPU (PyTorch)"
            self._is_gpu_active = False
            logger.info("[GpuVAD] Initialized on CPU backend.")
        except Exception as e:
            logger.warning(f"[GpuVAD] PyTorch unavailable: {e}. Using pure NumPy/CPU fallback.")
            self._torch = None
            self._device = None
            self._device_name = "CPU (NumPy)"
            self._is_gpu_active = False

    @property
    def is_gpu_active(self) -> bool:
        return self._is_gpu_active

    @property
    def device_name(self) -> str:
        return self._device_name

    def calculate_metrics(self, pcm_chunk: bytes) -> Tuple[float, float]:
        """
        Calculates normalized RMS amplitude [0.0, 1.0] and vocal spectral ratio [0.0, 1.0].
        Executes on GPU if active, otherwise falls back seamlessly to CPU.
        """
        if not pcm_chunk:
            return 0.0, 0.0

        if self._is_gpu_active and self._torch is not None:
            try:
                np_arr = np.frombuffer(pcm_chunk, dtype=np.int16).copy()
                tensor = self._torch.from_numpy(np_arr).to(self._device, dtype=self._torch.float32) / 32768.0
                
                # RMS on GPU
                rms = float(self._torch.sqrt(self._torch.mean(tensor ** 2)).item())

                # Spectral energy in vocal band (85Hz - 3400Hz) vs total
                n_samples = len(tensor)
                if n_samples >= 64:
                    fft_mag = self._torch.abs(self._torch.fft.rfft(tensor))
                    if self._vocal_mask is None or self._cached_freq_len != n_samples:
                        freqs = self._torch.fft.rfftfreq(n_samples, 1.0 / self.sample_rate).to(self._device)
                        self._vocal_mask = (freqs >= 85) & (freqs <= 3400)
                        self._cached_freq_len = n_samples

                    vocal_energy = float(self._torch.sum(fft_mag[self._vocal_mask] ** 2).item())
                    total_energy = float(self._torch.sum(fft_mag ** 2).item()) + 1e-9
                    vocal_ratio = max(0.0, min(1.0, vocal_energy / total_energy))
                else:
                    vocal_ratio = 1.0

                self._consecutive_gpu_errors = 0
                return rms, vocal_ratio

            except Exception as e:
                self._consecutive_gpu_errors += 1
                logger.warning(f"[GpuVAD] GPU processing error: {e}. Temporarily falling back to CPU.")
                if self._consecutive_gpu_errors >= 3:
                    logger.error("[GpuVAD] Repeated GPU errors. Switching device to CPU.")
                    self._is_gpu_active = False
                    self._device = self._torch.device("cpu") if self._torch else None
                    self._device_name = "CPU (Fallback)"

        # CPU Fallback
        try:
            audio_array = np.frombuffer(pcm_chunk, dtype=np.int16)
            if audio_array.size == 0:
                return 0.0, 0.0
            normalized = audio_array.astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(normalized * normalized)))
            return rms, 1.0
        except Exception:
            num_samples = len(pcm_chunk) // 2
            if num_samples == 0:
                return 0.0, 0.0
            samples = struct.unpack(f"<{num_samples}h", pcm_chunk[:num_samples * 2])
            sum_sq = sum((s / 32768.0) ** 2 for s in samples)
            rms = math.sqrt(sum_sq / num_samples)
            return rms, 1.0

    def is_speech(self, pcm_chunk: bytes, noise_floor: float) -> Tuple[bool, float, float]:
        """
        Determines whether the given audio chunk constitutes human speech.
        Returns: (is_speech_bool, rms_float, vocal_ratio_float)
        """
        rms, vocal_ratio = self.calculate_metrics(pcm_chunk)
        threshold = max(self.min_rms, noise_floor * self.energy_multiplier)

        # Harmonic speech verification: energy >= threshold AND vocal band ratio >= 0.25
        speech_detected = (rms >= threshold) and (vocal_ratio >= 0.25)
        return speech_detected, rms, vocal_ratio


# Singleton instance accessor
_gpu_vad_instance: Optional[GpuVoiceActivityDetector] = None

def get_gpu_vad() -> GpuVoiceActivityDetector:
    global _gpu_vad_instance
    if _gpu_vad_instance is None:
        _gpu_vad_instance = GpuVoiceActivityDetector()
    return _gpu_vad_instance
