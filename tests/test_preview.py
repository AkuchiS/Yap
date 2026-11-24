"""Tests for the as-you-speak preview: the recorder's live view, the preview
loop that feeds the bubble, and the bubble's text trimming. No mic, model or
AppKit needed — the engine and recorder are faked."""

import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_tail_text_keeps_recent_words():
    from yap.bubble import tail_text

    assert tail_text("  hello   world ") == "hello world"
    long = " ".join(f"word{i}" for i in range(200))
    out = tail_text(long)
    assert out.startswith("… ") and out.endswith("word199")
    assert len(out) <= 224
    assert " word" in out and not out[2:].startswith("ord")   # cut on a word boundary


def test_recorder_snapshot_and_live_seconds():
    from yap.audio import Recorder

    r = Recorder({"samplerate": 16000})
    assert r.snapshot() is None and r.live_seconds() == 0
    r._live_sr = 16000
    r._live = [np.ones((8000, 1), np.float32), np.zeros((16000, 1), np.float32)]
    assert abs(r.live_seconds() - 1.5) < 1e-6
    full = r.snapshot()
    assert full.shape == (24000,) and full.dtype == np.float32
    tail = r.snapshot(last_seconds=1.0)
    assert tail.shape == (16000,) and float(tail.max()) == 0.0   # only the zeros
    r.reset_live()
    assert r.snapshot() is None


def test_recorder_snapshot_resamples_48k():
    from yap.audio import Recorder

    r = Recorder({"samplerate": 16000})
    r._live_sr = 48000
    r._live = [np.zeros((48000, 1), np.float32)]
    assert r.snapshot().shape == (16000,)


class _FakeRecorder:
    def __init__(self):
        self.secs = 0.0

    def live_seconds(self):
        return self.secs

    def snapshot(self, last_seconds=None):
        return np.zeros(int(min(self.secs, last_seconds or 1e9) * 16000), np.float32)


class _FakeEngine:
    name = "local"

    def __init__(self):
        self.calls = 0

    def transcribe_array(self, audio, sr):
        self.calls += 1
        return f"github words {len(audio) // 16000}"


class _FakeLearner:
    def casing_words(self):
        return ["GitHub"]


def _app(engine=None):
    from yap.app import App

    app = App.__new__(App)
    app.cfg = {"preview": {"enabled": True, "interval": 0.0}, "vocabulary": [],
               "replacements": {}}
    app.engine = engine or _FakeEngine()
    app.recorder = _FakeRecorder()
    app.learner = _FakeLearner()
    app.samplerate = 16000
    app.verbosity = 0
    app._take = 1
    app._recording = True
    app._active_app = None
    shown = []
    app.preview_cb = shown.append
    return app, shown


def test_preview_streams_words_then_stops_on_release():
    app, shown = _app()
    t = threading.Thread(target=app._preview_loop, args=(1,), daemon=True)
    t.start()
    for _ in range(6):                     # audio keeps arriving while the key is held
        app.recorder.secs += 0.5
        time.sleep(0.15)
    app._recording = False                 # key released
    t.join(timeout=2)
    assert not t.is_alive()
    assert shown, "the bubble never got any words"
    assert shown[-1].startswith("GitHub words")   # vocab casing applied to the preview
    n = len(shown)
    app.recorder.secs += 2
    time.sleep(0.2)
    assert len(shown) == n                 # nothing after release


def test_stale_take_never_updates_bubble():
    app, shown = _app()
    app._take = 2                          # a newer recording already started
    app.recorder.secs = 3
    app._preview_loop(1)
    assert shown == []


def test_preview_off_for_cloud_engine_and_when_disabled():
    app, _ = _app()
    assert app._preview_enabled()
    cloud = _FakeEngine()
    cloud.name = "cloud"
    app.engine = cloud
    assert not app._preview_enabled()      # never stream audio to a cloud API
    app.engine = _FakeEngine()
    app.cfg["preview"]["enabled"] = False
    assert not app._preview_enabled()
    app.cfg["preview"]["enabled"] = True
    app.preview_cb = None
    assert not app._preview_enabled()      # no GUI, no preview work


def test_cpu_threads_setting():
    from yap.stt.local_whisper import _cpu_threads

    assert 1 <= _cpu_threads("auto") <= 8
    assert _cpu_threads(None) == _cpu_threads("auto")
    assert _cpu_threads(3) == 3
    assert _cpu_threads("nonsense") == _cpu_threads("auto")


# ---- bubble placement (pure maths; Jay's real 4-display layout) -------------
_SCREENS = [(0, 63, 3440, 1347),          # main ultrawide (primary)
            (-2160, -240, 2160, 3840),    # portrait, left
            (3440, -320, 2160, 3840),     # portrait, right
            (0, 1440, 3440, 1440)]        # ultrawide above


def test_bubble_goes_just_under_the_caret():
    from yap.bubble import place, _GAP

    x, y = place("caret", (800, 700, 2, 20), 400, 60, _SCREENS)
    assert x == 788 and y == 700 - 60 - _GAP


def test_bubble_flips_above_caret_near_screen_bottom():
    from yap.bubble import place, _GAP

    x, y = place("caret", (800, 90, 2, 20), 400, 60, _SCREENS)
    assert y == 90 + 20 + _GAP                # no room below → above the line


def test_bubble_on_other_display_stays_on_that_display():
    from yap.bubble import place

    x, y = place("caret", (-300, 2500, 2, 20), 600, 60, _SCREENS)
    assert -2160 <= x and x + 600 <= 0        # clamped inside the left portrait
    x, y = place("field", (5500, 100, 90, 30), 600, 60, _SCREENS)
    assert 3440 <= x and x + 600 <= 3440 + 2160


def test_tall_field_is_treated_as_a_page_not_an_input():
    from yap.bubble import place

    # Claude reported its whole chat area (input box sits at its bottom edge)
    area = (100, 63, 1600, 1200)
    x, y = place("field", area, 500, 60, _SCREENS)
    assert y > 63 + 300                       # well clear of the bottom input box
    assert x == 100 + (1600 - 500) / 2


def test_short_field_near_screen_bottom_goes_above_it():
    from yap.bubble import place, _GAP

    x, y = place("field", (300, 80, 900, 44), 500, 60, _SCREENS)
    assert y == 80 + 44 + _GAP


def test_no_anchor_falls_back_to_screen_under_mouse():
    from yap.bubble import place, _BOTTOM_GAP

    x, y = place(None, None, 600, 60, _SCREENS, mouse=(1000, 2000))
    assert (x, y) == ((3440 - 600) / 2, 1440 + _BOTTOM_GAP)   # the upper display


def test_window_anchor_avoids_bottom_input():
    from yap.bubble import place

    x, y = place("window", (200, 300, 1000, 800), 400, 60, _SCREENS)
    assert (x, y) == (200 + 300, 300 + 800 * 0.55 - 30)   # not on the bottom input


def test_focus_anchor_never_raises():
    from yap.bubble import focus_anchor

    kind, rect = focus_anchor()          # untrusted test process → graceful
    assert kind in (None, "caret", "field", "window")
