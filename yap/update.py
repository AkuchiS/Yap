"""Check GitHub Releases for a newer yap and let the user know.

No telemetry: this makes one outbound call to the *public* GitHub Releases API,
and only when you run `yap update` or launch the menu-bar app — and then at most
once a day (cached next to your config). Nothing about you is sent.

Applying an update is still a manual download for now: each unsigned build of the
macOS app needs its permissions re-granted, so a genuine one-click in-place
updater waits on Apple Developer signing. The plumbing here (check + "how to
update" + the menu-bar notice) is ready for that day — `apply()` just opens the
download page until a signed build can swap itself in place safely.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Callable, Optional

from . import __version__, config

REPO = "AkuchiS/yap"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
_CACHE_TTL = 86400  # seconds — check the network at most once a day


def _parse_version(v: str) -> tuple:
    """'v0.1.2' -> (0, 1, 2). Trailing non-digits in a part stop that part."""
    out = []
    for chunk in (v or "").strip().lstrip("vV").split(".")[:4]:
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        out.append(int(num) if num else 0)
    return tuple(out) or (0,)


def _is_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


def _fetch_latest(timeout: float = 4.0) -> Optional[dict]:
    """The latest release JSON from GitHub, or None on any failure (offline etc.)."""
    req = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"yap/{__version__}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _cache_path():
    return config.config_dir() / "update_check.json"


def check_for_update(current: Optional[str] = None, *, force: bool = False,
                     fetcher: Optional[Callable[[], Optional[dict]]] = None,
                     ttl: int = _CACHE_TTL) -> Optional[dict]:
    """Return {current, latest, available, url} or None if the check couldn't run.

    Uses a once-a-day cache so launching the app doesn't hammer the network;
    `force=True` ignores the cache (used by `yap update`).
    """
    current = current or __version__
    fetcher = fetcher or _fetch_latest
    cache = _cache_path()
    now = time.time()

    data = None
    if not force and cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if now - float(c.get("checked_at", 0)) < ttl and c.get("latest"):
                data = c
        except Exception:
            data = None

    if data is None:
        rel = fetcher()
        if not rel:
            return None  # offline / rate-limited / failed — caller treats as unknown
        data = {
            "checked_at": now,
            "latest": (rel.get("tag_name") or "").strip().lstrip("vV"),
            "html_url": rel.get("html_url") or RELEASES_PAGE,
        }
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    latest = data.get("latest") or ""
    return {
        "current": current,
        "latest": latest,
        "available": bool(latest) and _is_newer(latest, current),
        "url": data.get("html_url") or RELEASES_PAGE,
    }


def instructions(info: dict) -> str:
    """Human-readable 'a new version is out, here's how to get it'."""
    return (
        f"yap {info['latest']} is available — you have {info['current']}.\n"
        f"  Download:  {info['url']}\n"
        f'  Or update: pipx install --force "yap-dictation[full] @ '
        f'git+https://github.com/{REPO}"'
    )


def apply(info: dict) -> bool:
    """Open the download page for the new version.

    This is the seam for a future one-click updater: once the app is Apple-signed
    (stable identity → permissions survive an update), this can download the new
    build and swap it in place without a re-grant. Until then, opening the page is
    the safe, honest action.
    """
    try:
        import webbrowser
        webbrowser.open(info.get("url") or RELEASES_PAGE)
        return True
    except Exception:
        return False
