"""Speech-to-text engines."""

from __future__ import annotations

from typing import Any

from .base import Engine


def build_engine(cfg: dict[str, Any]) -> Engine:
    """Construct the STT engine selected in config (`engine`: local | cloud)."""
    from ..text import build_prompt

    kind = cfg.get("engine", "local")
    prompt = build_prompt(cfg.get("vocabulary"))
    if kind == "local":
        return _build_local(cfg["local"], prompt)
    if kind == "cloud":
        from .cloud_openai import CloudWhisperEngine

        return CloudWhisperEngine(cfg["cloud"], prompt=prompt)
    raise ValueError(f"unknown engine {kind!r} (expected 'local' or 'cloud')")


def pick_backend(local_cfg: dict[str, Any]) -> str:
    """Which on-device model to run. `local.backend`:
      auto     -> Parakeet on Apple Silicon (GPU, ~7x faster), Whisper elsewhere
      parakeet -> Parakeet everywhere (Apple GPU, else ONNX on the CPU)
      whisper  -> faster-whisper everywhere (the original engine)"""
    from .parakeet import mlx_available, onnx_available

    want = str(local_cfg.get("backend") or "auto").lower()
    if want == "whisper":
        return "whisper"
    if want == "parakeet":
        if mlx_available() or onnx_available():
            return "parakeet"
        import sys

        print("yap: Parakeet isn't installed (pip install 'yap-dictation[parakeet]'); "
              "using Whisper.", file=sys.stderr)
        return "whisper"
    return "parakeet" if mlx_available() else "whisper"


def _build_local(local_cfg: dict[str, Any], prompt):
    if pick_backend(local_cfg) == "parakeet":
        try:
            from .parakeet import ParakeetEngine

            return ParakeetEngine(local_cfg, prompt=prompt)
        except Exception as e:  # never leave the user without dictation
            import sys

            print(f"yap: Parakeet unavailable ({e}); using Whisper.", file=sys.stderr)
    from .local_whisper import LocalWhisperEngine

    return LocalWhisperEngine(local_cfg, prompt=prompt)
