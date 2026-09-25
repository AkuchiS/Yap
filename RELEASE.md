# Releasing yap

Cutting a release builds standalone apps for **macOS, Windows, and Linux** and
attaches them to a GitHub Release — so anyone can **download → unzip → run**, no
Python, no building.

## One-time setup

1. **Confirm the CI workflow is active.** The canonical workflow is already at
   `.github/workflows/release.yml`. Tagged releases are blocked unless the macOS
   app is Developer-ID signed, notarized, stapled, and accepted by Gatekeeper.

2. **Make the repo public** — Settings → General → Change visibility. Actions is
   free on public repos (it burns limited minutes on private ones).

3. *(Optional)* **Enable GitHub Sponsors** at https://github.com/sponsors so the
   Support button goes live (configured in `.github/FUNDING.yml`).

## Cut a release

```bash
# bump the version first (pyproject.toml + yap/__init__.py), then:
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions builds all three and publishes a Release at
`github.com/AkuchiS/yap/releases` with:

| File | What the user does |
|---|---|
| `Yap-macOS.zip` | unzip → drag `Yap.app` to Applications → open normally. Grant Mic + Accessibility + Input Monitoring, then quit and reopen once. |
| `yap-Windows.zip` | unzip → double-click `yap.exe` → hold **Right Ctrl**, talk. No permissions needed. |
| `yap-Linux.tar.gz` | extract → run `yap/yap` (needs `libportaudio2`). |

You can also run the workflow without tagging: **Actions → Build apps → Run
workflow** (produces the three zips as downloadable artifacts, no Release).

## Manual / no-CI fallback

Build locally for the OS you're on:
```bash
./packaging/build_macos.sh         # → /Applications/Yap.app
./packaging/build_linux.sh         # → dist/yap/
powershell -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1   # → dist\yap\yap.exe
```
