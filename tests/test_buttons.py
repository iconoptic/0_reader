import threading

import pytest

import buttons
import config


@pytest.fixture(autouse=True)
def _fast_windows(monkeypatch):
    monkeypatch.setattr(config, "TAP_WINDOW", 0.05)
    monkeypatch.setattr(config, "HOLD_TIME", 0.1)


class _Recorder:
    def __init__(self):
        self.taps = []
        self.holds = 0
        self.got = threading.Event()

    def on_taps(self, n):
        self.taps.append(n)
        self.got.set()

    def on_hold(self):
        self.holds += 1


def _make(fake_button):
    rec = _Recorder()
    btn = fake_button()
    tb = buttons.TapButton(5, rec.on_taps, rec.on_hold, button=btn)
    return rec, btn, tb


def test_single_tap(fake_button):
    rec, btn, _ = _make(fake_button)
    btn.tap()
    assert rec.got.wait(1.0)
    assert rec.taps == [1]
    assert rec.holds == 0


def test_double_and_triple_tap_counted_within_window(fake_button):
    rec, btn, _ = _make(fake_button)
    btn.tap(); btn.tap()
    assert rec.got.wait(1.0)
    assert rec.taps == [2]
    rec.got.clear()
    btn.tap(); btn.tap(); btn.tap()
    assert rec.got.wait(1.0)
    assert rec.taps == [2, 3]


def test_taps_outside_window_are_separate(fake_button, wait_for):
    rec, btn, _ = _make(fake_button)
    btn.tap()
    assert rec.got.wait(1.0)
    btn.tap()
    assert wait_for(lambda: len(rec.taps) == 2)
    assert rec.taps == [1, 1]


def test_hold_fires_once_and_suppresses_tap(fake_button, wait_for):
    rec, btn, _ = _make(fake_button)
    btn.hold()
    assert rec.holds == 1
    # give the tap window a chance to (wrongly) fire
    assert not wait_for(lambda: rec.taps, timeout=0.2)
    assert rec.taps == []


def test_hold_after_partial_taps_discards_them(fake_button, wait_for):
    rec, btn, _ = _make(fake_button)
    # press #1 released, then press #2 held: the pending tap count is dropped
    btn.tap()
    btn.hold()
    assert rec.holds == 1
    assert not wait_for(lambda: rec.taps, timeout=0.2)


def test_uses_gpiozero_button_when_none_injected(monkeypatch):
    created = {}

    class Btn:
        def __init__(self, pin, **kw):
            created["pin"] = pin
            created["kw"] = kw

    monkeypatch.setattr(buttons, "Button", Btn)
    tb = buttons.TapButton(17, lambda n: None)
    assert created["pin"] == 17
    assert created["kw"]["pull_up"] is True
    assert created["kw"]["hold_time"] == config.HOLD_TIME
    assert tb.btn.when_released == tb._released
