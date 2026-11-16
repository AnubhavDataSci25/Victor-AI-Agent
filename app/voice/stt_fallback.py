"""
GPU-Accelerated Speech-to-Text (STT) Fallback Engine for Victor AI Assistant.

Provides local offline speech transcription when Gemini Live audio streaming
is unavailable or delayed. Runs on GPU (CUDA, float16) with strict VRAM safeguards
(requires >= 250 MB free VRAM) and automatically falls back to CPU if GPU is busy.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


class GpuSTTFallback:
    """
    Local Whisper-based STT Fallback engine running on NVIDIA GeForce MX330 (CUDA)
    with seamless automatic CPU fallback.
    """

    def __init__(
        self,
        model_name: str = "openai/whisper-tiny.en",
        prefer_gpu: bool = True,
        vram_safety_margin_mb: float = 250.0,
    ) -> None:
        self.model_name = model_name
        self.prefer_gpu = prefer_gpu
        self.vram_safety_margin_mb = vram_safety_margin_mb

        self._torch = None
        self._model = None
        self._processor = None
        self._device = "cpu"
        self._device_name = "CPU"
        self._is_gpu_active = False
        self._initialized = False

    def _init_model(self) -> bool:
        """Lazily initializes the Whisper processor and model."""
        if self._initialized:
            return self._model is not None

        self._initialized = True
        try:
            import torch
            self._torch = torch

            # Determine target device based on GPU availability and free VRAM
            target_device = "cpu"
            torch_dtype = torch.float32

            if self.prefer_gpu and torch.cuda.is_available():
                total_mem = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
                alloc_mem = torch.cuda.memory_allocated(0) / (1024 * 1024)
                free_mb = total_mem - alloc_mem

                if free_mb >= self.vram_safety_margin_mb:
                    target_device = "cuda:0"
                    torch_dtype = torch.float16
                    self._is_gpu_active = True
                    self._device_name = torch.cuda.get_device_name(0)
                    logger.info(
                        f"[GpuSTTFallback] Initializing Whisper model on {self._device_name} "
                        f"(free VRAM: {free_mb:.1f} MB, dtype: float16)"
                    )
                else:
                    logger.warning(
                        f"[GpuSTTFallback] Free VRAM ({free_mb:.1f} MB) < {self.vram_safety_margin_mb} MB threshold. "
                        "Falling back to CPU."
                    )
                    self._device_name = "CPU (Low VRAM Fallback)"
            else:
                self._device_name = "CPU"

            from transformers import WhisperForConditionalGeneration, WhisperProcessor

            try:
                self._processor = WhisperProcessor.from_pretrained(self.model_name)
                self._model = WhisperForConditionalGeneration.from_pretrained(
                    self.model_name,
                    torch_dtype=torch_dtype,
                ).to(target_device)
                self._model.eval()
                self._device = target_device
                logger.info(f"[GpuSTTFallback] Whisper successfully loaded on {self._device_name}.")
                return True
            except Exception as load_err:
                # If loading on GPU failed, retry on CPU
                if target_device != "cpu":
                    logger.warning(f"[GpuSTTFallback] GPU load failed: {load_err}. Retrying on CPU.")
                    self._device = "cpu"
                    self._is_gpu_active = False
                    self._device_name = "CPU (Fallback)"
                    try:
                        self._model = WhisperForConditionalGeneration.from_pretrained(
                            self.model_name,
                            torch_dtype=torch.float32,
                        ).to("cpu")
                        self._model.eval()
                        return True
                    except Exception:
                        pass
                logger.debug(f"[GpuSTTFallback] Remote/cache model load failed: {load_err}")
                return False

        except Exception as e:
            logger.warning(f"[GpuSTTFallback] Local Whisper model unavailable: {e}. STT fallback inactive.")
            self._model = None
            self._processor = None
            return False

    @property
    def is_gpu_active(self) -> bool:
        return self._is_gpu_active

    @property
    def device_name(self) -> str:
        return self._device_name

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """
        Transcribes raw 16-bit mono PCM audio into text.
        Executes on GPU if active, otherwise falls back gracefully to CPU.
        """
        if not pcm_bytes or len(pcm_bytes) < 320:
            return ""

        if not self._init_model() or self._model is None or self._processor is None:
            return ""

        try:
            audio_data = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            inputs = self._processor(audio_data, sampling_rate=sample_rate, return_tensors="pt")
            input_features = inputs.input_features.to(self._device)
            if self._is_gpu_active and self._torch is not None:
                input_features = input_features.to(dtype=self._torch.float16)

            with self._torch.inference_mode():
                predicted_ids = self._model.generate(input_features, max_new_tokens=128)
                transcription = self._processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]

            return transcription.strip()

        except Exception as e:
            logger.warning(f"[GpuSTTFallback] Transcription error on {self._device_name}: {e}")
            if self._is_gpu_active:
                logger.info("[GpuSTTFallback] Attempting one-time CPU transcription fallback.")
                try:
                    self._device = "cpu"
                    self._is_gpu_active = False
                    self._device_name = "CPU (Fallback)"
                    if self._model is not None and self._torch is not None:
                        self._model = self._model.to("cpu", dtype=self._torch.float32)
                        return self.transcribe(pcm_bytes, sample_rate)
                except Exception as cpu_err:
                    logger.error(f"[GpuSTTFallback] CPU fallback also failed: {cpu_err}")

            return ""


# Singleton instance accessor
_gpu_stt_instance: Optional[GpuSTTFallback] = None

def get_gpu_stt_fallback() -> GpuSTTFallback:
    global _gpu_stt_instance
    if _gpu_stt_instance is None:
        _gpu_stt_instance = GpuSTTFallback()
    return _gpu_stt_instance
