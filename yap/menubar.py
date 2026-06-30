"""macOS menu-bar app — the icon-in-the-menu-bar experience.

Architecture (important): the menu-bar process is a **thin UI only**. The actual
dictation — the global keyboard listener + paste injection — runs in a SEPARATE
`yap run` daemon process that this app spawns and talks to over the control
socket (`yap.ipc`). That separation is deliberate: macOS 26 aborts a process that
touches the Text Input Source API off the main thread, which is exactly what a
keyboard listener does inside an app event loop. By keeping the listener in its
own headless process (which has no app event loop), the menu-bar app can show its
icon and menu without ever risking that crash.

Requires `rumps` (macOS only):  pip install "yap-dictation[macos]"
Launch with:  yap app
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Any, Optional

from . import config, ipc

# Menu-bar state glyphs (used as the title; the brand icon, if available, sits
# beside them). Kept as text so the app needs no asset files to show *something*.
_GLYPH = {"idle": "🎙", "listening": "🔴", "transcribing": "⏳", "starting": "…"}


def _daemon_command() -> list[str]:
    """Command that launches the headless dictation daemon as a child process."""
    if getattr(sys, "frozen", False):       # inside the bundled Yap.app
        return [sys.executable, "run", "--quiet"]
    return [sys.executable, "-m", "yap", "run", "--quiet"]


def _request_permissions() -> None:
    """Ask macOS for the permissions the daemon needs so the app *appears* in
    System Settings → Privacy & Security and can be granted. The daemon (our child,
    same code-signed identity) is covered by the grant given to this app."""
    try:
        try:
            from ApplicationServices import (  # type: ignore
                AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)
        except Exception:
            from HIServices import (  # type: ignore
                AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
    except Exception as e:
        print(f"yap: could not request Accessibility ({e})", file=sys.stderr)
    try:
        import ctypes
        iokit = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDRequestAccess.restype = ctypes.c_bool
        iokit.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
        iokit.IOHIDRequestAccess(1)  # kIOHIDRequestTypeListenEvent (Input Monitoring)
    except Exception as e:
        print(f"yap: could not request Input Monitoring ({e})", file=sys.stderr)


def _show_in_dock() -> None:
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(0)  # Regular: Dock + menu bar
    except Exception as e:
        print(f"yap: could not show Dock icon ({e})", file=sys.stderr)


def _set_dock_icon(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        from AppKit import NSApplication, NSImage
        img = NSImage.alloc().initByReferencingFile_(path)
        if img is not None and img.isValid():
            NSApplication.sharedApplication().setApplicationIconImage_(img)
            return True
    except Exception as e:
        print(f"yap: could not set Dock icon ({e})", file=sys.stderr)
    return False


def run(cfg: dict[str, Any]) -> int:
    if sys.platform != "darwin":
        print("yap app: the menu-bar app is macOS-only for now. Use `yap run` "
              "elsewhere.", file=sys.stderr)
        return 2
    try:
        import rumps
    except Exception:
        print("yap app: needs rumps. Install it:\n"
              "  pip install rumps    (or: pipx inject yap-dictation rumps)",
              file=sys.stderr)
        return 2

    from .hotkey import describe_mode

    _request_permissions()
    icon_path = config.icon_path(cfg)
    mode, combo = cfg["hotkey"]["mode"], cfg["hotkey"]["combo"]
    engine_name = cfg.get("engine", "local")

    class YapBar(rumps.App):
        def __init__(self):
            super().__init__("Yap", title=_GLYPH["starting"], icon=icon_path,
                             template=False, quit_button=None)
            if not (cfg.get("app", {}) or {}).get("menubar_only"):
                _show_in_dock()
            _set_dock_icon(icon_path)
            self._daemon: Optional[subprocess.Popen] = None  # the child we spawned
            self.status_item = rumps.MenuItem("Starting the dictation engine…")
            self.menu = [
                self.status_item,
                rumps.MenuItem(describe_mode(mode, combo)),
                None,
                rumps.MenuItem("Start / stop dictation", callback=self._toggle),
                rumps.MenuItem("Learn from my last correction", callback=self._relearn),
                None,
                rumps.MenuItem("Quit Yap", callback=self._quit),
            ]
            threading.Thread(target=self._boot, daemon=True).start()
            try:
                self._poll = rumps.Timer(self._poll_status, 1.0)
                self._poll.start()
            except Exception:
                pass

        # -- main-thread UI marshalling -------------------------------------
        def _main(self, fn):
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(fn)
            except Exception:
                try:
                    fn()
                except Exception:
                    pass

        # -- daemon lifecycle ------------------------------------------------
        def _boot(self):
            """Reuse a running daemon if one's there; otherwise spawn one."""
            ok, _ = ipc.send("ping")
            if not ok:
                try:
                    logp = os.path.expanduser("~/Library/Logs/yap.log")
                    os.makedirs(os.path.dirname(logp), exist_ok=True)
                    logf = open(logp, "a")
                    self._daemon = subprocess.Popen(_daemon_command(),
                                                    stdout=logf, stderr=logf)
                except Exception as e:
                    self._main(lambda: setattr(self.status_item, "title",
                                               f"couldn't start engine: {e}"))
                    return
            # wait (up to ~90s) for first-run model warmup, then mark ready
            for _ in range(180):
                time.sleep(0.5)
                ok, _ = ipc.send("ping")
                if ok:
                    self._main(lambda: setattr(self.status_item, "title",
                                               "Ready — hold your hotkey to dictate"))
                    return
            self._main(lambda: setattr(self.status_item, "title",
                                       "engine didn't come up — see ~/Library/Logs/yap.log"))

        def _poll_status(self, _timer):
            ok, reply = ipc.send("status")
            state = "starting"
            if ok:
                state = "listening" if reply == "recording" else "idle"
            self._main(lambda: setattr(self, "title", _GLYPH.get(state, _GLYPH["idle"])))

        # -- menu actions (all driven over the control socket) ---------------
        def _toggle(self, _sender):
            ipc.send("toggle")

        def _relearn(self, _sender):
            ok, reply = ipc.send("relearn")
            msg = reply if ok else "couldn't reach the dictation engine"
            self._main(lambda: self._notify(msg))

        def _notify(self, msg):
            self.status_item.title = msg
            try:
                rumps.notification("Yap", "", msg)
            except Exception:
                pass

        def _quit(self, _sender):
            # stop the daemon we started (leave a pre-existing one alone)
            if self._daemon is not None:
                try:
                    self._daemon.terminate()
                except Exception:
                    pass
            import rumps as _r
            _r.quit_application()

    YapBar().run()
    return 0
