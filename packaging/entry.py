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
    # Double-clicked with no args: run the dictation daemon directly.
    #
    # NOT the menu-bar app on macOS: a menu-bar app runs an NSApplication event
    # loop, which forces the keyboard library to touch the Text Input Source API
    # off the main thread — and macOS 26 aborts the process for that. The headless
    # daemon keeps a single listener and TIS-free injection, so it runs cleanly.
    # (`yap app` is still available explicitly for testing the future main-thread
    # menu-bar build.)
    sys.argv.append("run")

raise SystemExit(main())
