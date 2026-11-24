#!/usr/bin/env bash
# Build a self-contained yap.app on macOS (PyInstaller).
# The app bundles its own Python + Whisper stack, so macOS shows "yap" (with
# your icon) in permission dialogs — not "Python".
#
# Usage:
#   ./packaging/build_macos.sh [path/to/icon.png]
#   YAP_BUILD_PY=python3.12 ./packaging/build_macos.sh     # pin the freeze Python
#   YAP_MENUBAR_ONLY=1 ./packaging/build_macos.sh          # hide the Dock icon
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 1. Pick a Python with current PyObjC wheels. macOS's Xcode Python 3.9 can
#    select an old PyObjC source build that fails with recent Xcode.
PY="${YAP_BUILD_PY:-}"
if [ -z "$PY" ]; then
  for c in python3.12 "$HOME/.local/bin/python3.12" python3.11 python3.13; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi
[ -n "$PY" ] || { echo "Python 3.11–3.13 needed to build. Install Python 3.12 or set YAP_BUILD_PY." >&2; exit 1; }
"$PY" -c 'import sys; raise SystemExit(not ((3, 11) <= sys.version_info[:2] < (3, 14)))' || {
  echo "YAP_BUILD_PY must be Python 3.11–3.13 for the macOS build." >&2; exit 1;
}
echo "==> freezing with $("$PY" --version) ($PY)"

# 2. Clean, isolated build venv.
VENV="$ROOT/.build-venv"
rm -rf "$VENV"; "$PY" -m venv "$VENV"; . "$VENV/bin/activate"
pip install -U pip wheel >/dev/null
echo "==> installing yap + build tools (this pulls the Whisper stack)…"
pip install ".[full]" pyinstaller pillow pyobjc-framework-ApplicationServices >/dev/null

# 3. Turn your icon into a multi-resolution .icns (shaped to the macOS squircle).
#    Default to the icon committed in the repo so builds are self-contained;
#    fall back to ~/Downloads or the config dir; or pass a path as arg 1.
ICON_SRC="${1:-}"
PRESHAPED=""
if [ -z "$ICON_SRC" ]; then
  # Prefer the pre-rounded, transparent-corner icon committed in the repo: it's
  # already the macOS squircle, so the result is correct even if Pillow/iconify
  # isn't usable in the build env (which is what shipped a square icon before).
  if [ -f "$ROOT/packaging/yap-icon-macos.png" ]; then
    ICON_SRC="$ROOT/packaging/yap-icon-macos.png"; PRESHAPED=1
  else
    for c in "$ROOT/packaging/yap-icon.png" "$HOME/Downloads/yap-icon.png" \
             "$HOME/Library/Application Support/yap/icon.png"; do
      [ -f "$c" ] && { ICON_SRC="$c"; break; }
    done
  fi
fi
if [ -f "$ICON_SRC" ]; then
  WORK="$(mktemp -d)"; ROUNDED="$WORK/rounded.png"
  if [ -n "$PRESHAPED" ]; then
    SRC="$ICON_SRC"   # already a transparent squircle — use as-is (sips keeps alpha)
  # Otherwise round to the squircle (transparent corners + inset) so it sits like
  # a native icon, not a hard square. Needs Pillow in the build venv.
  elif ICON_SRC="$ICON_SRC" ROUNDED="$ROUNDED" python - <<'PY'
import os, sys
try:
    from yap.icons import iconify
    sys.exit(0 if iconify(os.environ["ICON_SRC"], os.environ["ROUNDED"], "darwin") else 1)
except Exception as e:
    print("   (icon rounding skipped: %s)" % e); sys.exit(1)
PY
  then SRC="$ROUNDED"; else SRC="$ICON_SRC"; fi
  ISET="$WORK/yap.iconset"; mkdir -p "$ISET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$SRC" --out "$ISET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$SRC" --out "$ISET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ISET" -o "$WORK/yap.icns"
  export YAP_ICNS="$WORK/yap.icns"
  echo "==> icon: $YAP_ICNS (squircle)"
else
  echo "==> no icon at '$ICON_SRC' (pass one: ./packaging/build_macos.sh path/to/icon.png); building without"
fi

# 4. Freeze into dist without touching an installed, signed copy.
rm -rf build dist
echo "==> running PyInstaller…"
pyinstaller packaging/yap.spec --noconfirm

# 5. Sign the local candidate with the microphone entitlement. A public release
#    needs the Developer ID + notarization steps in .github/workflows/release.yml.
codesign --force --deep --options runtime \
  --entitlements packaging/entitlements.plist --sign - dist/Yap.app
codesign --verify --deep --strict dist/Yap.app
deactivate || true
echo
echo "✓ built $ROOT/dist/Yap.app (ad-hoc signed local candidate)"
echo "The installed app was left intact. Use the signed, notarized release workflow"
echo "before replacing /Applications/Yap.app or distributing a download."
