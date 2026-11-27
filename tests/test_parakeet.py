"""Engine choice per platform: Parakeet on Apple Silicon, Whisper elsewhere,
and a safe fall-back whenever Parakeet can't run. No model is loaded here."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yap.stt.parakeet as pk
from yap.stt import pick_backend


def _fake(monkeypatch, mlx, onnx):
    monkeypatch.setattr(pk, "mlx_available", lambda: mlx)
    monkeypatch.setattr(pk, "onnx_available", lambda: onnx)


def test_auto_uses_parakeet_only_where_it_is_fast(monkeypatch):
    _fake(monkeypatch, mlx=True, onnx=False)            # Apple Silicon Mac
    assert pick_backend({"backend": "auto"}) == "parakeet"
    _fake(monkeypatch, mlx=False, onnx=True)            # Windows/Linux with ONNX
    assert pick_backend({"backend": "auto"}) == "whisper"
    _fake(monkeypatch, mlx=False, onnx=False)           # plain install
    assert pick_backend({}) == "whisper"


def test_forced_choices(monkeypatch):
    _fake(monkeypatch, mlx=False, onnx=True)
    assert pick_backend({"backend": "parakeet"}) == "parakeet"   # opt-in on Linux/Win
    _fake(monkeypatch, mlx=True, onnx=False)
    assert pick_backend({"backend": "whisper"}) == "whisper"     # opt-out on a Mac
    _fake(monkeypatch, mlx=False, onnx=False)
    assert pick_backend({"backend": "parakeet"}) == "whisper"    # not installed


def test_backend_auto_resolves_per_machine(monkeypatch):
    _fake(monkeypatch, mlx=True, onnx=True)
    e = pk.ParakeetEngine({})
    assert e.backend == "mlx" and e.name == "local"     # preview still allowed
    _fake(monkeypatch, mlx=False, onnx=True)
    assert pk.ParakeetEngine({}).backend == "onnx"


def test_mlx_never_claimed_off_apple_silicon(monkeypatch):
    monkeypatch.setattr(pk, "apple_silicon", lambda: False)
    assert pk.mlx_available() is False


def test_gpu_cache_is_capped_and_freed(monkeypatch):
    """Regression: MLX's buffer cache grew to 45 GB because every dictation is
    a different length. The engine must cap it and clear it after each pass."""
    assert pk._CACHE_LIMIT <= 1024 ** 3
    _fake(monkeypatch, mlx=True, onnx=False)
    e = pk.ParakeetEngine({})
    freed = []
    monkeypatch.setattr(e, "_ensure_model", lambda: object())
    monkeypatch.setattr(e, "_run", lambda m, a: "hi")
    monkeypatch.setattr(e, "_free", lambda: freed.append(1))
    import numpy as np
    assert e.transcribe_array(np.zeros(16000, np.float32), 16000) == "hi"
    assert freed == [1]
