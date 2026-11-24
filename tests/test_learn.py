"""Tests for relearn's correction diffing — the 'learn my last fix' feature.

Run:  python -m pytest tests/test_learn.py   (or: python tests/test_learn.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yap.learn import diff_corrections
from yap.text import apply_replacements


def test_multiword_to_single_phrase_fix():
    # The most common real correction — and the case that used to be dropped.
    fixes, casings = diff_corrections("post grey sequel", "PostgreSQL")
    assert fixes == {"post grey sequel": "PostgreSQL"}
    # ...and it actually rewrites a later transcript:
    assert apply_replacements("i love post grey sequel", fixes) == "i love PostgreSQL"


def test_phrase_fix_with_surrounding_context():
    fixes, _ = diff_corrections("the cube an eddies cluster", "the Kubernetes cluster")
    assert fixes == {"cube an eddies": "Kubernetes"}


def test_casing_only_becomes_a_vocab_entry():
    fixes, casings = diff_corrections("i use anthropic daily", "i use Anthropic daily")
    assert "Anthropic" in casings and fixes == {}


def test_clean_one_to_one_spelling_fix():
    fixes, _ = diff_corrections("send the file to jon", "send the file to John")
    assert fixes == {"jon": "John"}


def test_sentence_sized_rewrite_is_ignored():
    old = "this is a long sentence the user completely rewrote by hand afterwards"
    new = "totally different words here now please"
    fixes, _ = diff_corrections(old, new)
    assert fixes == {}                       # too big to learn as one find/replace


def test_identical_learns_nothing():
    fixes, casings = diff_corrections("nothing changed here", "nothing changed here")
    assert fixes == {} and casings == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")


# ---- auto-vocabulary safety rails ------------------------------------------
import os as _os
import tempfile as _tempfile


def _learner(vocab=()):
    from yap.learn import VocabLearner
    return VocabLearner({"vocabulary": list(vocab),
                         "learning": {"enabled": True, "min_count": 3, "max_words": 80}})


def test_common_word_said_lowercase_is_not_learned():
    _os.environ["YAP_CONFIG_DIR"] = _tempfile.mkdtemp()
    try:
        l = _learner()
        for _ in range(3):
            l.observe("Is there a way to make it More realistic?")
        assert "More" in l.words()            # looked like a name so far
        for _ in range(3):
            l.observe("I want more of that and some more.")
        assert "More" not in l.words()        # you say it lowercase → ordinary word
        assert "More" not in l.casing_words()
    finally:
        _os.environ.pop("YAP_CONFIG_DIR", None)


def test_mishearing_of_your_vocab_is_not_learned():
    _os.environ["YAP_CONFIG_DIR"] = _tempfile.mkdtemp()
    try:
        l = _learner(["AkuchiS", "Jaz"])
        for _ in range(4):
            l.observe("Send it to Akutchess and Jazz today.")
        assert "Akutchess" not in l.words()
        assert "Jazz" not in l.words()
    finally:
        _os.environ.pop("YAP_CONFIG_DIR", None)


def test_only_camelcase_learned_words_force_casing():
    _os.environ["YAP_CONFIG_DIR"] = _tempfile.mkdtemp()
    try:
        l = _learner()
        for _ in range(3):
            l.observe("Push it to GitHub and Hermes now.")
        assert "GitHub" in l.casing_words()
        assert "Hermes" in l.words() and "Hermes" not in l.casing_words()
    finally:
        _os.environ.pop("YAP_CONFIG_DIR", None)


def test_key_release_without_a_started_recording_does_nothing():
    """Key-up after on_start bailed (still transcribing) must not re-run _finish
    on the previous audio — that re-pasted the last sentence."""
    from yap.app import App
    app = App.__new__(App)
    app._recording = False
    started = []
    import threading
    orig = threading.Thread
    threading.Thread = lambda *a, **k: started.append(k) or orig(target=lambda: None)
    try:
        app._stop_event = threading.Event()
        app.on_stop()
    finally:
        threading.Thread = orig
    assert started == []
    assert not app._stop_event.is_set()
