"""Frozen-app entry point.

Double-click (no args) launches the menu-bar app; any args run the normal CLI,
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
    # macOS has the menu-bar app; elsewhere fall back to the run daemon so a
    # double-clicked yap.exe / binary actually starts dictating.
    sys.argv.append("app" if sys.platform == "darwin" else "run")

raise SystemExit(main())
