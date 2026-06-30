"""Frozen-app entry point.

Double-click (no args) runs the dictation daemon; any args run the normal CLI,
so the same binary serves both Yap.app and `yap <subcommand>`.
"""

import sys

# Multiprocessing helpers (ctranslate2/onnxruntime semaphore + resource trackers)
# re-launch this frozen executable. Intercept their two relaunch forms BEFORE we
# touch argv or import the app — otherwise they hit the CLI parser and crash with
# "invalid choice: 'from multiprocessing...'", destabilizing the whole app.
if len(sys.argv) >= 3 and sys.argv[1] == "-c":
    exec(sys.argv[2])
    raise SystemExit(0)

import multiprocessing

multiprocessing.freeze_support()  # handles the --multiprocessing-fork relaunch

from yap.cli import main

if len(sys.argv) == 1:
    # Double-clicked with no args → the menu-bar app on macOS (icon + menu),
    # the run daemon elsewhere. The menu-bar app is now crash-safe on macOS 26:
    # it's a thin UI that spawns a SEPARATE headless `yap run` daemon for the
    # keyboard work, so the UI process never touches the Text Input Source API
    # that aborts when used off the main thread (see yap/menubar.py).
    sys.argv.append("app" if sys.platform == "darwin" else "run")

raise SystemExit(main())
