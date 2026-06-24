#!/usr/bin/env bash
# Completely remove Yap from a Mac (or Linux): login agent, app bundles, the
# pipx install, config, logs, and reset its permission grants. Safe to re-run.
# Does NOT touch your Python install or the Whisper model cache (see notes).
set -u

echo "==> stopping the login agent that respawns Yap…"
launchctl unload "$HOME/Library/LaunchAgents/com.yap.dictation.plist" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.yap.dictation" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.yap.dictation.plist"

echo "==> killing any running Yap instances…"
pkill -f "Applications/[Yy]ap.app" 2>/dev/null || true
pkill -f "yap.cli" 2>/dev/null || true
pkill -f "[ -]m yap" 2>/dev/null || true

echo "==> removing app bundles + build output…"
rm -rf "$HOME/Applications/yap.app" "$HOME/Applications/Yap.app"
rm -rf "$HOME/Downloads/yap/dist" "$HOME/Downloads/yap/build" "$HOME/Downloads/yap/.build-venv"

echo "==> uninstalling the pipx package / CLI…"
pipx uninstall yap-dictation 2>/dev/null || true
rm -rf "$HOME/.local/pipx/venvs/yap-dictation" "$HOME/.local/bin/yap"

echo "==> removing config + logs…"
rm -rf "$HOME/Library/Application Support/yap" "$HOME/.config/yap"
rm -f "$HOME/Library/Logs/yap-app.log"

if [ "$(uname -s)" = "Darwin" ]; then
  echo "==> resetting Yap's permission grants…"
  for svc in Microphone Accessibility ListenEvent PostEvent; do
    tccutil reset "$svc" com.yap.dictation 2>/dev/null || true
  done
fi

echo
echo "✓ Yap removed."
echo "Notes:"
echo "  • Whisper models cache (~/.cache/huggingface) was kept — delete it to"
echo "    reclaim space:  rm -rf ~/.cache/huggingface"
echo "  • Any leftover 'Python 3' rows in System Settings → Privacy & Security"
echo "    can now be removed with the − button (orphans from the old wrapper)."
echo "  • The build Python (python@3.12) was left alone; the next build needs it."
