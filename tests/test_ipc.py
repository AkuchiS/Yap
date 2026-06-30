"""Tests for the Wayland control socket + dictation toggle (no audio/engine/GUI).

Run:  python -m pytest tests/test_ipc.py   (or: python tests/test_ipc.py)
"""

import os
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yap import ipc
from yap.hotkey import is_wayland


def _with_env(**kv):
    """Context-manager-ish helper: set env vars, yield, restore."""
    saved = {k: os.environ.get(k) for k in kv}

    def restore():
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old

    for k, v in kv.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return restore


def test_is_wayland_detection():
    restore = _with_env(XDG_SESSION_TYPE="x11", WAYLAND_DISPLAY=None)
    try:
        assert is_wayland() is False
        os.environ["XDG_SESSION_TYPE"] = "wayland"
        assert is_wayland() is True
        os.environ["XDG_SESSION_TYPE"] = "tty"      # no session type, but a wl display
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        assert is_wayland() is True
    finally:
        restore()


def test_ipc_roundtrip_and_no_daemon():
    if not ipc.supported():
        return  # AF_UNIX unavailable (Windows) — the global hotkey works there
    restore = _with_env(XDG_RUNTIME_DIR=tempfile.mkdtemp())
    try:
        seen = []
        srv = ipc.Server(lambda cmd: (seen.append(cmd), f"ok:{cmd}")[1]).start()
        assert srv is not None
        time.sleep(0.05)
        ok, reply = ipc.send("toggle")
        assert ok and reply == "ok:toggle"
        ok, reply = ipc.send("ping")
        assert ok and reply == "ok:ping"
        assert seen == ["toggle", "ping"]
        srv.stop()
        time.sleep(0.05)
        ok, reply = ipc.send("toggle")          # daemon gone now
        assert ok is False and "isn't running" in reply
    finally:
        restore()


def test_ipc_command_dispatch():
    """Drive the real App._ipc_command against a fake `self` (no heavy deps)."""
    try:
        from yap.app import App
    except Exception:
        return  # numpy/sounddevice not installed in this env — skip
    calls = []
    fake = types.SimpleNamespace(
        _recording=False,
        on_start=lambda: calls.append("start"),
        on_stop=lambda: calls.append("stop"),
        on_relearn=lambda: "learned X",
        toggle=lambda: calls.append("toggle"),
    )
    cmd = App._ipc_command.__get__(fake)   # bind the real method onto the fake

    assert cmd("toggle") in ("idle", "recording") and "toggle" in calls
    assert cmd("start") == "recording" and "start" in calls
    assert cmd("stop") == "idle" and "stop" in calls
    assert cmd("relearn") == "ok learned X"
    assert cmd("ping") in ("idle", "recording")
    assert cmd("bogus").startswith("err:")
    assert cmd("") in ("idle", "recording")    # empty == toggle


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
