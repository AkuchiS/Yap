"""A tiny control socket so an external trigger can drive dictation.

Why this exists: on **Wayland**, the OS deliberately stops applications from
grabbing global hotkeys, so yap's in-process key listener (pynput, X11-only on
Linux) never fires. The portable fix is to let your **compositor** own the key and
have it poke the running daemon: bind a key to `yap toggle` (or `yap ptt
press|release`) and it talks to this socket and starts/stops recording exactly as
the hotkey would. Also handy for scripts, Stream Decks, or any other trigger.

POSIX only (a `AF_UNIX` socket). On Windows the global hotkey works natively, so
the socket is a no-op there and `yap toggle` will say so.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path
from typing import Callable, Tuple

from . import config


def socket_path() -> str:
    """Control-socket path. Prefer $XDG_RUNTIME_DIR (per-user, cleaned on logout)."""
    rt = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(rt) if rt else config.config_dir()
    return str(base / "yap.sock")


def supported() -> bool:
    return hasattr(socket, "AF_UNIX") and sys.platform != "win32"


class Server:
    """Accept one-line commands on the control socket and dispatch to `handler`.

    `handler(cmd: str) -> str` runs on the server thread and returns a reply line.
    A bad command never takes the server down — exceptions become an `err:` reply.
    """

    def __init__(self, handler: Callable[[str], str]):
        self.handler = handler
        self.path = socket_path()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> "Server | None":
        if not supported():
            return None
        try:
            os.unlink(self.path)        # clear a stale socket from a previous run
        except OSError:
            pass
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.bind(self.path)
        except OSError:
            return None                 # another instance already owns it, etc.
        s.listen(8)
        s.settimeout(0.5)               # so the accept loop can notice _stop
        try:
            os.chmod(self.path, 0o600)  # owner-only: no other user can trigger you
        except OSError:
            pass
        self._sock = s
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    data = conn.recv(256).decode("utf-8", "replace").strip()
                    reply = self.handler(data) if data else "err: empty"
                except Exception as e:  # noqa: BLE001 - never crash the daemon
                    reply = f"err: {e}"
                try:
                    conn.sendall((reply + "\n").encode("utf-8"))
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def join(self) -> None:
        """Block until stopped — keeps the process alive when there is no pynput
        listener to join (e.g. a Wayland session)."""
        while not self._stop.is_set():
            self._stop.wait(0.5)


def send(cmd: str, timeout: float = 2.0) -> Tuple[bool, str]:
    """Send one command to the running daemon. Returns (ok, reply-or-reason)."""
    if not supported():
        return False, ("the control socket isn't available on this OS — the global "
                       "hotkey works here, so bind/use that instead.")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(socket_path())
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        return False, "yap isn't running — start it with `yap run` (or `yap app`)."
    try:
        s.sendall((cmd + "\n").encode("utf-8"))
        reply = s.recv(256).decode("utf-8", "replace").strip()
        return True, reply
    except OSError as e:
        return False, f"couldn't talk to yap: {e}"
    finally:
        try:
            s.close()
        except OSError:
            pass
