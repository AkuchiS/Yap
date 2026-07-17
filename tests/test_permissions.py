"""First-run permissions: the checklist, the plain-English wording, and the
one-tap deep links to System Settings.

The PyObjC calls only work on a Mac, but everything that decides WHAT we ask for,
in what order, and WHERE each button sends you is Quartz-free — so we can prove
off a Mac that a new user gets the right three prompts pointing at the right panes.
That's the whole point: yap looked broken to anyone who didn't already know about
System Settings ▸ Privacy & Security.

Run:  python -m pytest tests/test_permissions.py  (or: python tests/test_permissions.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yap import first_run, permissions

IS_MAC = sys.platform == "darwin"


def test_asks_for_exactly_the_three_grants_yap_needs():
    keys = [p["key"] for p in permissions.PERMISSIONS]
    assert keys == ["microphone", "input_monitoring", "accessibility"], keys


def test_microphone_is_asked_first_because_it_is_the_only_one_that_prompts():
    # macOS shows a real Allow dialog for the mic; the other two the user must
    # toggle by hand. Leading with the easy win is deliberate.
    assert permissions.PERMISSIONS[0]["key"] == "microphone"
    assert permissions.PERMISSIONS[0]["prompts"] is True
    assert all(p["prompts"] is False for p in permissions.PERMISSIONS[1:])


def test_every_permission_deep_links_to_a_real_settings_pane():
    for p in permissions.PERMISSIONS:
        pane = p["pane"]
        assert pane.startswith("x-apple.systempreferences:com.apple.preference.security?Privacy_"), pane
    # each pane must be distinct — sending two grants to the same page is the bug
    panes = [p["pane"] for p in permissions.PERMISSIONS]
    assert len(set(panes)) == len(panes), panes


def test_panes_point_at_the_right_apple_anchors():
    by = {p["key"]: p["pane"] for p in permissions.PERMISSIONS}
    assert by["microphone"].endswith("Privacy_Microphone")
    assert by["input_monitoring"].endswith("Privacy_ListenEvent")   # Apple's name for Input Monitoring
    assert by["accessibility"].endswith("Privacy_Accessibility")


def test_wording_is_plain_english_but_still_names_the_apple_setting():
    for p in permissions.PERMISSIONS:
        assert p["label"] and p["why"] and p["system_name"]
        # the label is what a person thinks; system_name is what they'll see in Settings
        assert p["label"] != p["system_name"] or p["key"] == "microphone"
    labels = [p["label"] for p in permissions.PERMISSIONS]
    assert "See your hotkey" in labels and "Type at your cursor" in labels


def test_checks_exist_for_every_permission():
    assert set(permissions.CHECKS) == {p["key"] for p in permissions.PERMISSIONS}
    for fn in permissions.CHECKS.values():
        assert callable(fn)


def test_status_reports_every_permission_and_never_raises():
    st = permissions.status()
    assert len(st) == len(permissions.PERMISSIONS)
    assert [s["key"] for s in st] == [p["key"] for p in permissions.PERMISSIONS]
    for s in st:
        assert isinstance(s["granted"], bool)


def test_checklist_shows_every_permission_with_a_tickbox():
    text = permissions.checklist()
    for p in permissions.PERMISSIONS:
        assert p["label"] in text
        assert p["system_name"] in text          # so they can match it in Settings
    assert ("▢" in text) or ("✅" in text)


def test_checklist_ticks_what_is_granted():
    fake = [dict(p, granted=(p["key"] == "microphone")) for p in permissions.PERMISSIONS]
    text = permissions.checklist(fake)
    lines = [l for l in text.split("\n") if l.strip().startswith(("✅", "▢"))]
    assert lines[0].startswith("✅"), lines      # microphone granted
    assert lines[1].startswith("▢"), lines       # the rest still to do


def test_open_pane_accepts_a_permission_or_a_url_and_never_raises():
    # off a Mac these are no-ops that must return False rather than explode
    if not IS_MAC:
        assert permissions.open_pane(permissions.PERMISSIONS[0]) is False
        assert permissions.open_pane("") is False


def test_checks_are_safe_off_mac():
    if not IS_MAC:
        assert permissions.accessibility_ok() is False
        assert permissions.input_monitoring_ok() is False
        assert permissions.microphone_ok() is False
        assert permissions.all_granted() is False
        assert len(permissions.missing()) == 3


def test_first_run_is_needed_when_something_is_missing():
    if not IS_MAC:
        assert first_run.needed() is True


def test_first_run_never_raises_and_reports_failure_off_mac():
    # A broken setup window must never take the menu-bar app down with it.
    assert first_run.run(lambda *_a: None) is False


def test_request_microphone_is_safe_off_mac():
    if not IS_MAC:
        permissions.request_microphone(lambda *_a: None)   # must not raise


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("all passed")
