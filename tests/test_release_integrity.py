"""Release-facing invariants that prevent packaging and documentation drift."""

import io
import os
import re
import ssl
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT))

from yap import __version__


def test_package_versions_match():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match, "pyproject.toml has no project version"
    assert match.group(1) == __version__


def test_public_links_point_to_the_real_repository():
    for relative in ("pyproject.toml", "yap/update.py", "yap/cleanup.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "github.com/yap-dictation/yap" not in text, relative
        assert "AkuchiS" in text, relative


def test_macos_download_and_guidance_match_the_shipped_app():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "macOS-download_.zip" in readme
    assert "macOS-download_.dmg" not in readme
    assert "on macOS 26 use `yap autostart`, **not**" not in readme
    assert "signed `Yap.app` download is the recommended route" in readme


def test_menu_bar_app_checks_for_updates():
    source = (ROOT / "yap/menubar.py").read_text(encoding="utf-8")
    assert "check_for_update" in source
    assert "Update available:" in source


def test_release_check_supplies_an_ssl_context():
    """The frozen macOS app must use its bundled CA file for GitHub HTTPS."""
    from yap import update

    seen = {}
    original = update.urllib.request.urlopen

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(_request, *, timeout, context):
        seen.update(timeout=timeout, context=context)
        return Response(b'{"tag_name":"v9.9.9"}')

    update.urllib.request.urlopen = fake_urlopen
    try:
        result = update._fetch_latest(timeout=1.25)
    finally:
        update.urllib.request.urlopen = original

    assert result["tag_name"] == "v9.9.9"
    assert seen["timeout"] == 1.25
    assert isinstance(seen["context"], ssl.SSLContext)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
