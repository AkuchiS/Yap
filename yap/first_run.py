"""First-run setup — the window a brand-new user actually sees.

The problem this solves: yap would launch, put an icon in the menu bar, and do
NOTHING until three permissions were granted — with the only hint buried in a
dropdown nobody clicks. If you didn't already know about System Settings ▸
Privacy & Security, yap looked broken.

macOS will not let an app grant itself Accessibility or Input Monitoring (no
installer, entitlement or script can — Apple requires a human to flip the
toggle). So the best possible experience is: say what's needed in plain words,
take them STRAIGHT to the right pane in one click, and show the ticks go green
as they do it. That's what this is.

Runs modal on the main thread (NSAlert), which is where rumps calls us from.
"""
from __future__ import annotations

from . import permissions

_HEADLINE = "yap needs 3 permissions to type what you say"
_EXPLAIN = ("macOS only lets YOU switch these on — yap can't do it for you.\n"
            "Click a button below and it opens the exact settings page; flick the\n"
            "switch next to yap, then come back here.")
_DONE = "You're all set 🎉"
_DONE_BODY = "Hold your hotkey, speak, and the words land wherever you're typing."


def _alert(title, body, buttons):
    """One NSAlert. Returns the index of the button clicked (0-based)."""
    from AppKit import NSAlert, NSAlertFirstButtonReturn, NSApplication
    try:  # a modal that isn't frontmost is a modal nobody sees
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass
    a = NSAlert.alloc().init()
    a.setMessageText_(title)
    a.setInformativeText_(body)
    for b in buttons:
        a.addButtonWithTitle_(b)
    return int(a.runModal()) - int(NSAlertFirstButtonReturn)


def needed() -> bool:
    """Is there anything to set up? (Cheap; safe to call on every launch.)"""
    return not permissions.all_granted()


def run(log=lambda *_a: None) -> bool:
    """Walk the user through every missing permission. Returns True if, by the end,
    everything is granted. Never raises — a broken setup window must not take the
    app down with it."""
    if not permissions._is_mac():
        return False
    try:
        while True:
            state = permissions.status()
            missing = [p for p in state if not p["granted"]]
            if not missing:
                log("first-run: all permissions granted")
                try:
                    _alert(_DONE, _DONE_BODY, ["Great"])
                except Exception:
                    pass
                return True

            buttons = ["Open %s" % p["system_name"] for p in missing] + ["Later"]
            body = "%s\n\n%s" % (permissions.checklist(state), _EXPLAIN)
            idx = _alert(_HEADLINE, body, buttons)

            if idx < 0 or idx >= len(missing):      # "Later" (or a stray return)
                log("first-run: deferred by user")
                return False

            p = missing[idx]
            log("first-run: opening %s" % p["system_name"])
            if p.get("prompts"):
                # The mic is the one macOS will show a real Allow dialog for.
                permissions.request_microphone(log)
                if permissions.CHECKS[p["key"]]():
                    continue                        # granted via the dialog — loop re-ticks it
            permissions.open_pane(p)
    except Exception as e:                          # never kill the menu-bar app
        log("first-run window failed: %s" % e)
        return False
