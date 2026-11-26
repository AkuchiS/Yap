"""Local, offline STT using NVIDIA Parakeet (TDT 0.6B).

Two backends, picked for the machine:
  * "mlx"  - Apple Silicon GPU via parakeet-mlx. About 7x faster than Whisper
             small on an M-series Mac (22 s of speech: 0.24 s vs 1.8 s).
  * "onnx" - any OS (Windows, Linux, Intel Mac) via onnx-asr + ONNX Runtime on
             the CPU. Roughly Whisper-speed there, so it's opt-in, not the default.

Runs entirely on your machine. No audio ever leaves the device. Parakeet has
no prompt, so vocabulary steering happens afterwards (replacements + casing),
not inside the model as with Whisper's initial_prompt.
"""

from __future__ import annotations

import platform
import sys
import threading
from typing import Any, Optional

import numpy as np

MLX_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
ONNX_MODEL = "nemo-parakeet-tdt-0.6b-v3"


def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def mlx_available() -> bool:
    """True when the fast Apple-GPU backend can run here (without importing it)."""
    if not apple_silicon():
        return False
    import importlib.util

    return (importlib.util.find_spec("parakeet_mlx") is not None
            and importlib.util.find_spec("mlx") is not None)


def onnx_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("onnx_asr") is not None


class ParakeetEngine:
    # "local" on purpose: everything that treats the on-device engine specially
    # (live preview, tray switch) keeps working. `backend` says which one.
    name = "local"

    def __init__(self, cfg: dict[str, Any], prompt: Optional[str] = None,
                 backend: str = "auto"):
        self.cfg = cfg
        self.prompt = prompt  # kept for interface parity; Parakeet can't use it
        if backend == "auto":
            backend = "mlx" if mlx_available() else "onnx"
        self.backend = backend
        self.active_model = MLX_MODEL if backend == "mlx" else ONNX_MODEL
        self.active_device = "gpu" if backend == "mlx" else "cpu"
        self._model = None
        # One decode at a time: MLX shares one GPU stream, and at ~0.1-0.3 s a
        # pass, waiting for a preview to finish costs less than racing it.
        self._lock = threading.Lock()

    def resolved_model(self) -> str:
        return f"parakeet-tdt-0.6b-v3 ({self.backend})"

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if self.backend == "mlx":
            from parakeet_mlx import from_pretrained

            self._model = from_pretrained(self.cfg.get("parakeet_model") or MLX_MODEL)
        else:
            import onnx_asr

            self._model = onnx_asr.load_model(self.cfg.get("parakeet_model") or ONNX_MODEL,
                                              quantization="int8")
        return self._model

    def warmup(self) -> None:
        with self._lock:
            model = self._ensure_model()
            # The GPU compiles kernels for the first few input sizes it sees; run
            # short, medium and long dummy clips now so the first real dictations
            # aren't 2-4x slower than the rest (measured 1.1 s -> 0.3 s for 22 s).
            noise = np.random.default_rng(0).normal(0, 1e-3, 16000 * 20).astype(np.float32)
            for secs in (1, 4, 10, 20):
                self._run(model, noise[:16000 * secs])

    def _run(self, model, audio: "np.ndarray") -> str:
        if audio.size < 1600:   # under 0.1 s: nothing to hear
            return ""
        if self.backend == "mlx":
            import mlx.core as mx
            from parakeet_mlx.audio import get_logmel

            mel = get_logmel(mx.array(audio), model.preprocessor_config)
            return model.generate(mel)[0].text.strip()
        return str(model.recognize(audio, sample_rate=16000)).strip()

    def _decode(self, audio: "np.ndarray") -> str:
        with self._lock:
            return self._run(self._ensure_model(), audio)

    def transcribe_array(self, samples: "np.ndarray", samplerate: int) -> str:
        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samplerate != 16000:
            from .local_whisper import _resample_to_16k

            audio = _resample_to_16k(audio, samplerate)
        return self._decode(audio)

    def transcribe_file(self, wav_path: str) -> str:
        import wave

        with wave.open(wav_path, "rb") as w:
            sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if width != 2:
            raise ValueError("expected a 16-bit WAV")
        audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            audio = audio.reshape(-1, ch).mean(axis=1)
        return self.transcribe_array(audio, sr)
