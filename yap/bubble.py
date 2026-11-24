"""The as-you-speak bubble (macOS): a small floating panel that shows your words
while you hold the dictation key.

It is a *non-activating* panel: it never takes keyboard focus, so the app you're
dictating into keeps its cursor and the final paste lands where it always did.
It also ignores the mouse, follows you across Spaces and full-screen apps, and
sits at the bottom-centre of whichever screen your pointer is on.

Everything here must run on the MAIN thread (AppKit). The menu-bar app marshals
calls through ``AppHelper.callAfter``.
"""

from __future__ import annotations

from typing import Optional

_MAX_WIDTH = 620       # points
_PAD_X, _PAD_Y = 18, 12
_MAX_CHARS = 220       # long takes: show the most recent words, not the start
_BOTTOM_GAP = 96       # distance above the Dock / bottom of the visible area

# AppKit constants spelled out so this module imports cleanly anywhere.
_STYLE_BORDERLESS = 0
_STYLE_NONACTIVATING_PANEL = 1 << 7
_LEVEL_STATUS = 25                              # NSStatusWindowLevel
_BEHAVIOR = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8)
# canJoinAllSpaces | stationary | ignoresCycle | fullScreenAuxiliary
_BACKING_BUFFERED = 2
_MATERIAL_HUD = 13
_BLEND_BEHIND_WINDOW = 0
_STATE_ACTIVE = 1
_WORD_WRAP = 0


def tail_text(text: str, limit: int = _MAX_CHARS) -> str:
    """Keep the most recent words of a long take, cut on a word boundary."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    space = cut.find(" ")
    if 0 <= space < 40:
        cut = cut[space + 1:]
    return "… " + cut


class Bubble:
    def __init__(self):
        from AppKit import (NSColor, NSFont, NSMakeRect, NSPanel, NSTextField,
                            NSVisualEffectView)

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 300, 48),
            _STYLE_BORDERLESS | _STYLE_NONACTIVATING_PANEL,
            _BACKING_BUFFERED, False)
        panel.setLevel_(_LEVEL_STATUS)
        panel.setCollectionBehavior_(_BEHAVIOR)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setReleasedWhenClosed_(False)

        bg = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, 300, 48))
        bg.setMaterial_(_MATERIAL_HUD)
        bg.setBlendingMode_(_BLEND_BEHIND_WINDOW)
        bg.setState_(_STATE_ACTIVE)
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(14.0)
        bg.layer().setMasksToBounds_(True)
        panel.setContentView_(bg)

        label = NSTextField.labelWithString_("")
        label.setFont_(NSFont.systemFontOfSize_(17.0))
        label.setLineBreakMode_(_WORD_WRAP)
        label.setMaximumNumberOfLines_(4)
        label.setPreferredMaxLayoutWidth_(_MAX_WIDTH - 2 * _PAD_X)
        bg.addSubview_(label)

        self._panel, self._bg, self._label = panel, bg, label
        self._hide_token = 0

    # -- public (main thread only) ------------------------------------------
    def listening(self) -> None:
        """Key just went down: show a quiet placeholder until words arrive."""
        self._set("Listening…", muted=True)

    def text(self, words: str) -> None:
        words = tail_text(words)
        if words:
            self._set(words, muted=False)

    def finishing(self) -> None:
        """Key released: dim the preview while the final pass runs."""
        self._hide_token += 1
        self._label.setAlphaValue_(0.6)

    def hide(self, after: float = 0.0) -> None:
        self._hide_token += 1
        token = self._hide_token
        if after <= 0:
            self._panel.orderOut_(None)
            return
        try:
            from PyObjCTools import AppHelper

            AppHelper.callLater(after, lambda: (token == self._hide_token
                                                and self._panel.orderOut_(None)))
        except Exception:
            self._panel.orderOut_(None)

    # -- internals ----------------------------------------------------------
    def _set(self, words: str, muted: bool) -> None:
        from AppKit import NSColor, NSMakeSize

        self._hide_token += 1  # a pending delayed hide must not close this
        self._label.setStringValue_(words)
        self._label.setTextColor_(NSColor.secondaryLabelColor() if muted
                                  else NSColor.labelColor())
        self._label.setAlphaValue_(1.0)
        fit = self._label.sizeThatFits_(NSMakeSize(_MAX_WIDTH - 2 * _PAD_X, 10000))
        w = min(_MAX_WIDTH, max(160.0, fit.width + 2 * _PAD_X))
        h = fit.height + 2 * _PAD_Y
        self._layout(w, h, fit)
        self._panel.orderFrontRegardless()

    def _layout(self, w: float, h: float, fit) -> None:
        from AppKit import NSMakeRect

        vf = self._screen_frame()
        x = vf.origin.x + (vf.size.width - w) / 2.0
        y = vf.origin.y + _BOTTOM_GAP
        self._panel.setFrame_display_(NSMakeRect(x, y, w, h), True)
        self._bg.setFrame_(NSMakeRect(0, 0, w, h))
        self._label.setFrame_(NSMakeRect(_PAD_X, _PAD_Y, w - 2 * _PAD_X, fit.height))

    @staticmethod
    def _screen_frame():
        """Visible frame of the screen under the mouse pointer."""
        from AppKit import NSEvent, NSScreen
        from Foundation import NSPointInRect

        loc = NSEvent.mouseLocation()
        for s in NSScreen.screens():
            if NSPointInRect(loc, s.frame()):
                return s.visibleFrame()
        return NSScreen.mainScreen().visibleFrame()


def create() -> Optional[Bubble]:
    """Build the bubble, or None if AppKit isn't available (never fatal)."""
    try:
        return Bubble()
    except Exception as e:  # pragma: no cover - depends on host
        import sys

        print(f"yap: live preview bubble unavailable ({e})", file=sys.stderr)
        return None
