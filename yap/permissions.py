"""macOS permission state + one-tap deep links to the exact System Settings pane.

Why this exists: macOS will NOT let an app grant itself Accessibility or Input
Monitoring — a human must flip those toggles. Nothing can bypass that. So the best
we can do is tell the user, in plain words, exactly what's missing and take them
*straight* to the right pane with one click, then watch the toggles go green.

Everything here is import-safe off macOS (the checks just report False), so the
labels/panes/ordering are unit-testable on any box.
"""
from __future__ import annotations

import sys

# The three grants yap needs, in the order we ask for them. Deliberately phrased the
# way a person thinks about it ("see your hotkey"), with Apple's official name kept
# as `system_name` so the user can match it to what they see in System Settings.
PERMISSIONS = [
    {
        "key": "microphone",
        "label": "Hear you",
        "system_name": "Microphone",
        "why": "so yap can hear what you say",
        "pane": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        "prompts": True,   # macOS shows a real Allow dialog for this one
    },
    {
        "key": "input_monitoring",
        "label": "See your hotkey",
        "system_name": "Input Monitoring",
        "why": "so yap knows when you're holding the key down",
        "pane": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
        "prompts": False,  # no dialog — the user MUST toggle it themselves
    },
    {
        "key": "accessibility",
        "label": "Type at your cursor",
        "system_name": "Accessibility",
        "why": "so your words land in whatever app you're using",
        "pane": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "prompts": False,
    },
]

_KEYS = [p["key"] for p in PERMISSIONS]


def _is_mac() -> bool:
    return sys.platform == "darwin"


def accessibility_ok() -> bool:
    """Trusted for Accessibility (typing at the cursor). Never prompts."""
    if not _is_mac():
        return False
    try:
        try:
            from ApplicationServices import AXIsProcessTrusted  # type: ignore
        except Exception:
            from HIServices import AXIsProcessTrusted  # type: ignore
        return bool(AXIsProcessTrusted())
    except Exception:
        return False


def input_monitoring_ok() -> bool:
    """Input Monitoring (seeing the hotkey). IOHIDCheckAccess is the read-only check:
    0 == kIOHIDAccessTypeGranted. IOHIDRequestAccess would prompt; we don't here."""
    if not _is_mac():
        return False
    try:
        import ctypes
        iokit = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDCheckAccess.restype = ctypes.c_int
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        return iokit.IOHIDCheckAccess(1) == 0  # 1 = kIOHIDRequestTypeListenEvent
    except Exception:
        return False


def microphone_ok() -> bool:
    """Microphone. 3 == AVAuthorizationStatusAuthorized."""
    if not _is_mac():
        return False
    try:
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio  # type: ignore
        except Exception:
            from AVFoundation import AVCaptureDevice  # type: ignore
            AVMediaTypeAudio = "soun"
        return AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) == 3
    except Exception:
        return False


CHECKS = {
    "microphone": microphone_ok,
    "input_monitoring": input_monitoring_ok,
    "accessibility": accessibility_ok,
}


def status() -> list[dict]:
    """Every permission, in ask-order, with a live `granted` flag. Never raises."""
    out = []
    for p in PERMISSIONS:
        item = dict(p)
        try:
            item["granted"] = bool(CHECKS[p["key"]]())
        except Exception:
            item["granted"] = False
        out.append(item)
    return out


def missing() -> list[dict]:
    """Only what still needs granting (ask-order)."""
    return [p for p in status() if not p["granted"]]


def all_granted() -> bool:
    return not missing()


def checklist(state: list[dict] | None = None) -> str:
    """The human-readable checklist shown in the setup window."""
    state = state if state is not None else status()
    lines = []
    for p in state:
        tick = "✅" if p["granted"] else "▢"
        lines.append("%s  %s — %s\n      (System Settings ▸ Privacy & Security ▸ %s)"
                     % (tick, p["label"], p["why"], p["system_name"]))
    return "\n".join(lines)


def open_pane(perm: dict | str) -> bool:
    """Jump straight to the exact System Settings pane for this permission."""
    url = perm if isinstance(perm, str) else perm.get("pane", "")
    if not url or not _is_mac():
        return False
    try:
        from AppKit import NSURL, NSWorkspace
        return bool(NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url)))
    except Exception:
        try:  # last resort — `open` handles the same URL scheme
            import subprocess
            return subprocess.call(["open", url]) == 0
        except Exception:
            return False


def request_microphone(log=lambda *_a: None) -> None:
    """The mic is the ONE grant macOS will prompt for. Fire it so the Allow dialog
    appears (must be called with the run loop up and the app frontmost)."""
    if not _is_mac():
        return
    try:
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio  # type: ignore
        except Exception:
            from AVFoundation import AVCaptureDevice  # type: ignore
            AVMediaTypeAudio = "soun"
        if AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) == 0:
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVMediaTypeAudio, lambda granted: log("mic granted=%s" % bool(granted)))
    except Exception as e:
        log("mic request failed: %s" % e)
