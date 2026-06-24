"""Shape a source image into a Dock/taskbar icon that suits the OS.

macOS does NOT auto-round app icons — each app ships its own shape — so a full
square image looks out of place next to the system's rounded "squircle" icons.
This reshapes the image per-platform:

  * macOS  : rounded squircle, inset within a transparent canvas so it sits at
             the same visual size as its neighbors (matching Big Sur+ icons).
  * Windows: left square (taskbar icons are square).
  * Linux  : mild rounding (varies by desktop; a gentle radius looks at home).

Needs Pillow. If it's missing, the caller falls back to copying the raw image.
"""

from __future__ import annotations

import sys

_CANVAS = 1024


def iconify(src_path: str, dst_path: str, platform: str | None = None) -> bool:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False  # caller copies the raw file and suggests installing Pillow

    platform = platform or sys.platform
    img = Image.open(src_path).convert("RGBA")

    # center-crop to a square, then scale to the working canvas
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    img = img.resize((_CANVAS, _CANVAS), Image.LANCZOS)

    def rounded(image, size, radius):
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                               radius=radius, fill=255)
        image = image.copy()
        image.putalpha(mask)
        return image

    if platform == "darwin":
        # squircle (~22.37% radius) inset to ~82% of the canvas with transparent
        # margin — the standard macOS look.
        inner = int(_CANVAS * 0.82)
        content = rounded(img.resize((inner, inner), Image.LANCZOS),
                          inner, int(inner * 0.2237))
        icon = Image.new("RGBA", (_CANVAS, _CANVAS), (0, 0, 0, 0))
        off = (_CANVAS - inner) // 2
        icon.paste(content, (off, off), content)
    elif platform.startswith("win") or platform == "cygwin":
        icon = img  # Windows taskbar icons are square
    else:
        icon = rounded(img, _CANVAS, int(_CANVAS * 0.12))  # gentle rounding

    icon.save(dst_path, "PNG")
    return True
