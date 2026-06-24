"""Best-effort detection of the frontmost (focused) application, cross-platform.

Used to give integration hooks context — *which* app you're dictating into — so a
handoff can be smart (e.g. don't pause your assistant if you're dictating into it;
behave differently in Slack vs your editor). Always degrades to None rather than
raising, so it can never break dictation.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional


def frontmost_app() -> Optional[str]:
    try:
        if sys.platform == "darwin":
            return _macos()
        if sys.platform.startswith("win") or sys.platform == "cygwin":
            return _windows()
        return _linux()
    except Exception:
        return None


def _macos() -> Optional[str]:
    # NSWorkspace is the reliable, permission-free way to get the active app.
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is not None:
            name = app.localizedName()
            if name:
                return str(name)
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first process '
             'whose frontmost is true'],
            capture_output=True, text=True, timeout=2)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _windows() -> Optional[str]:
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    # Prefer the owning process's executable name; fall back to the window title.
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        k32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            buf = ctypes.create_unicode_buffer(260)
            size = wt.DWORD(260)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                k32.CloseHandle(h)
                exe = buf.value.rsplit("\\", 1)[-1]
                return exe[:-4] if exe.lower().endswith(".exe") else exe
            k32.CloseHandle(h)
    except Exception:
        pass
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or None


def _linux() -> Optional[str]:
    # X11 only; Wayland generally forbids querying the active window for privacy.
    for cmd in (
        ["xdotool", "getactivewindow", "getwindowclassname"],
        ["xdotool", "getactivewindow", "getwindowname"],
    ):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except FileNotFoundError:
            continue
        except Exception:
            break
    return None
