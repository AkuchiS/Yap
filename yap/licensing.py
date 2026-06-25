"""Install timestamp + grandfather codes.

Records when yap first landed on this machine — once, locally, no telemetry and
no phone-home — so that if a paid tier ever launches, people who installed
*before* the cutoff date can be grandfathered onto the free version. The record
is a small JSON file next to the config; `yap license` shows it and emits a
portable grandfather code.

Trust model: the install timestamp is self-reported (it lives on the user's
machine, like everything else in yap — we never call home), which is fine for an
honest freemium grandfather. To make a code *verifiable by the seller* later,
set a secret in the ``YAP_LICENSE_SECRET`` env var when generating/checking
codes: the code is then HMAC-signed and ``verify_code`` can confirm it's genuine.
With no secret the code is still emitted, marked ``unsigned``. Stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__, config

CODE_PREFIX = "YAP1"
SECRET_ENV = "YAP_LICENSE_SECRET"


def _install_path() -> Path:
    return config.config_dir() / "install.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def install_record() -> dict[str, Any]:
    """Return the install record, creating it on first call (idempotent).

    The ``installed_at`` stamp is written exactly once — the first time yap runs
    on this machine — and never touched again, so it's a stable early-adopter mark.
    """
    path = _install_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # corrupt → re-stamp below
    rec = {
        "installed_at": _now_iso(),
        "version": __version__,
        "id": uuid.uuid4().hex,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # best-effort; never block usage on a stamp write
    return rec


def stamp_install() -> None:
    """Best-effort: ensure the install record exists. Safe to call on every run."""
    try:
        install_record()
    except Exception:
        pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()[:16]


def grandfather_code(record: dict[str, Any] | None = None,
                     secret: str | None = None) -> str:
    """A portable code asserting which day this install dates from.

    Format: ``YAP1.<payload>.<sig>`` — payload is url-safe-base64 JSON
    ``{"d": "YYYY-MM-DD", "id": "<8 hex>", "v": "<version>"}`` and sig is an
    HMAC-SHA256 tag (16 hex) when a secret is available, else ``"unsigned"``.
    """
    rec = record or install_record()
    secret = secret if secret is not None else os.environ.get(SECRET_ENV)
    payload = {
        "d": (rec.get("installed_at") or "")[:10],
        "id": (rec.get("id") or "")[:8],
        "v": rec.get("version") or "",
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _sign(body, secret) if secret else "unsigned"
    return f"{CODE_PREFIX}.{body}.{sig}"


def verify_code(code: str, secret: str) -> dict[str, Any]:
    """Validate a grandfather code against the signing secret (seller side).

    Returns ``{"valid": bool, "payload": {...}|None, "reason": str}``.
    """
    try:
        prefix, body, sig = code.strip().split(".")
    except ValueError:
        return {"valid": False, "payload": None, "reason": "malformed code"}
    if prefix != CODE_PREFIX:
        return {"valid": False, "payload": None, "reason": "unknown prefix"}
    if not hmac.compare_digest(_sign(body, secret), sig):
        return {"valid": False, "payload": None, "reason": "bad signature"}
    try:
        payload = json.loads(_unb64(body).decode())
    except (ValueError, json.JSONDecodeError):
        return {"valid": False, "payload": None, "reason": "bad payload"}
    return {"valid": True, "payload": payload, "reason": "ok"}


def is_grandfathered(cutoff: str, record: dict[str, Any] | None = None) -> bool:
    """True if this install predates ``cutoff`` (YYYY-MM-DD) — i.e. an early
    adopter who keeps the free version if a price launches on/after that date."""
    rec = record or install_record()
    day = (rec.get("installed_at") or "")[:10]
    return bool(day) and day < cutoff


def summary() -> str:
    rec = install_record()
    code = grandfather_code(rec)
    lines = [
        f"installed:  {(rec.get('installed_at') or '?')[:10]}  (version {rec.get('version', '?')})",
        f"install id: {rec.get('id', '?')}",
        f"grandfather code: {code}",
    ]
    if code.endswith(".unsigned"):
        lines.append("  (unsigned — set YAP_LICENSE_SECRET when generating to make it verifiable)")
    lines.append("Keep this code: if yap ever adds a paid tier, installs from before "
                 "the cutoff date stay free.")
    return "\n".join(lines)
