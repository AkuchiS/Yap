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
_BOTTOM_GAP = 96       # fallback: distance above the bottom of the screen
_GAP = 10              # space between the text cursor / field and the bubble

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


# ---------------------------------------------------------------- placement ---
# Rects are (x, y, w, h) in Cocoa screen coordinates (origin bottom-left of the
# primary display, y up). Kept as plain tuples so the maths is testable anywhere.

def _contains(r, x, y) -> bool:
    return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]


def _screen_for(screens, x, y):
    for vf in screens:
        if _contains(vf, x, y):
            return vf
    return screens[0]


def place(kind: Optional[str], anchor, w: float, h: float, screens, mouse=(0, 0)):
    """Where the bubble's bottom-left corner goes.

    kind/anchor come from the focused app via Accessibility:
      "caret"  -> just under the text cursor (above it if that runs off-screen)
      "field"  -> just under the text box, else above it, else inside its bottom
      "window" -> bottom-centre inside the focused window
      None     -> bottom-centre of the screen under the mouse (old behaviour)
    `screens` = visible frames, primary first. Always clamped on-screen.
    """
    if kind is None or anchor is None:
        vf = _screen_for(screens, *mouse)
        return vf[0] + (vf[2] - w) / 2.0, vf[1] + _BOTTOM_GAP
    ax, ay, aw, ah = anchor
    vf = _screen_for(screens, ax + min(aw, 40) / 2.0, ay + ah / 2.0)
    bottom, top = vf[1], vf[1] + vf[3]
    if kind == "window":
        x, y = ax + (aw - w) / 2.0, ay + 60
    else:
        x = ax - (12 if kind == "caret" else 0)
        y = ay - h - _GAP                       # below
        if y < bottom:
            y = ay + ah + _GAP                  # above
        if y + h > top:
            y = ay + _GAP                       # tall field: inside its bottom edge
    x = min(max(x, vf[0] + 8), vf[0] + vf[2] - w - 8)
    y = min(max(y, bottom + 8), top - h - 8)
    return x, y


def _ax_rect(el, attr_pos="AXPosition", attr_size="AXSize"):
    from ApplicationServices import (AXUIElementCopyAttributeValue, AXValueGetValue,
                                     kAXValueCGPointType, kAXValueCGSizeType)
    e1, pos = AXUIElementCopyAttributeValue(el, attr_pos, None)
    e2, size = AXUIElementCopyAttributeValue(el, attr_size, None)
    if e1 or e2 or pos is None or size is None:
        return None
    ok1, p = AXValueGetValue(pos, kAXValueCGPointType, None)
    ok2, z = AXValueGetValue(size, kAXValueCGSizeType, None)
    if not (ok1 and ok2) or z.width <= 0 or z.height <= 0:
        return None
    return (p.x, p.y, z.width, z.height)


def focus_anchor():
    """Ask the focused app (via Accessibility, which Yap already has for pasting)
    where you're typing. Returns (kind, rect) in Cocoa coordinates, or (None, None).
    Native apps usually report the caret; browsers/Electron often only the field."""
    try:
        from AppKit import NSScreen
        from ApplicationServices import (AXUIElementCopyAttributeValue,
                                         AXUIElementCopyParameterizedAttributeValue,
                                         AXUIElementCreateSystemWide,
                                         AXUIElementSetMessagingTimeout,
                                         AXValueGetValue, kAXValueCGRectType)
        sysw = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(sysw, 0.25)   # never hang on a busy app
        primary_h = NSScreen.screens()[0].frame().size.height

        def flip(r):  # AX: top-left origin, y down -> Cocoa: bottom-left, y up
            return (r[0], primary_h - r[1] - r[3], r[2], r[3])

        err, el = AXUIElementCopyAttributeValue(sysw, "AXFocusedUIElement", None)
        if not err and el is not None:
            err, rng = AXUIElementCopyAttributeValue(el, "AXSelectedTextRange", None)
            if not err and rng is not None:
                err, b = AXUIElementCopyParameterizedAttributeValue(
                    el, "AXBoundsForRange", rng, None)
                if not err and b is not None:
                    ok, r = AXValueGetValue(b, kAXValueCGRectType, None)
                    if ok and r.size.height > 0 and (r.origin.x or r.origin.y):
                        return "caret", flip((r.origin.x, r.origin.y,
                                              max(r.size.width, 1.0), r.size.height))
            field = _ax_rect(el)
            if field:
                return "field", flip(field)
        err, appel = AXUIElementCopyAttributeValue(sysw, "AXFocusedApplication", None)
        if not err and appel is not None:
            err, win = AXUIElementCopyAttributeValue(appel, "AXFocusedWindow", None)
            if not err and win is not None:
                wr = _ax_rect(win)
                if wr:
                    return "window", flip(wr)
    except Exception:
        pass
    return None, None


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
        self._anchor = (None, None)   # where you're typing, fixed for the take
        self._last_kind = "unset"

    # -- public (main thread only) ------------------------------------------
    def listening(self) -> None:
        """Key just went down: find where you're typing, then show a quiet
        placeholder there until words arrive."""
        self._anchor = focus_anchor()
        kind = self._anchor[0] or "screen"
        if kind != self._last_kind:          # log only when the method changes
            import sys
            print(f"yap: bubble placed by {kind}", file=sys.stderr)
            self._last_kind = kind
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
        from AppKit import NSEvent, NSMakeRect, NSScreen

        screens = [(f.origin.x, f.origin.y, f.size.width, f.size.height)
                   for f in (s.visibleFrame() for s in NSScreen.screens())]
        m = NSEvent.mouseLocation()
        x, y = place(self._anchor[0], self._anchor[1], w, h, screens, (m.x, m.y))
        self._panel.setFrame_display_(NSMakeRect(x, y, w, h), True)
        self._bg.setFrame_(NSMakeRect(0, 0, w, h))
        self._label.setFrame_(NSMakeRect(_PAD_X, _PAD_Y, w - 2 * _PAD_X, fit.height))


def create() -> Optional[Bubble]:
    """Build the bubble, or None if AppKit isn't available (never fatal)."""
    try:
        return Bubble()
    except Exception as e:  # pragma: no cover - depends on host
        import sys

        print(f"yap: live preview bubble unavailable ({e})", file=sys.stderr)
        return None
