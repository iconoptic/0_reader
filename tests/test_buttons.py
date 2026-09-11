"""Key / Input: tap, hold, repeat, and ROTATE_180 pin remap."""

import pytest

import buttons
import config


@pytest.fixture(autouse=True)
def _fast_timing(monkeypatch):
    monkeypatch.setattr(config, "HOLD_DELAY", 0.02)
    monkeypatch.setattr(config, "REPEAT_SECS", 0.02)


def test_key_tap(fake_button):
    events = []
    btn = fake_button()
    buttons.Key("k1", lambda n, k: events.append((n, k)), repeats=False,
                button=btn)
    btn.tap()
    assert events == [("k1", "tap")]


def test_key_hold_once(fake_button, wait_for, monkeypatch):
    monkeypatch.setattr(config, "HOLD_DELAY", 0.02)
    events = []
    btn = fake_button()
    buttons.Key("k1", lambda n, k: events.append((n, k)), repeats=False,
                button=btn)
    btn.press()
    assert wait_for(lambda: len(events) >= 1)
    assert wait_for(lambda: len(events) == 1, timeout=0.15)  # no extras
    assert events == [("k1", "hold")]
    btn.release()
    assert events == [("k1", "hold")]


def test_key_repeat(fake_button, wait_for, monkeypatch):
    monkeypatch.setattr(config, "HOLD_DELAY", 0.02)
    monkeypatch.setattr(config, "REPEAT_SECS", 0.02)
    events = []
    btn = fake_button()
    buttons.Key("up", lambda n, k: events.append((n, k)), repeats=True,
                button=btn)
    btn.press()
    assert wait_for(lambda: len(events) >= 2)
    btn.release()
    assert events[0] == ("up", "repeat")
    assert all(e == ("up", "repeat") for e in events)
    n = len(events)
    assert not wait_for(lambda: len(events) > n, timeout=0.1)


def test_release_cancels_pending_hold(fake_button, wait_for, monkeypatch):
    monkeypatch.setattr(config, "HOLD_DELAY", 0.15)
    events = []
    btn = fake_button()
    buttons.Key("k2", lambda n, k: events.append((n, k)), repeats=False,
                button=btn)
    btn.press()
    btn.release()
    assert events == [("k2", "tap")]
    assert not wait_for(lambda: ("k2", "hold") in events, timeout=0.25)
    assert events == [("k2", "tap")]


def test_key_uses_gpiozero_button_when_none_injected(monkeypatch):
    created = {}

    class Btn:
        def __init__(self, pin, **kw):
            created["pin"] = pin
            created["kw"] = kw
            self.when_pressed = None
            self.when_released = None

    monkeypatch.setattr(buttons, "Button", Btn)
    key = buttons.Key("up", lambda n, k: None, repeats=True)
    assert created["pin"] == config.PINS["up"]
    assert created["kw"]["pull_up"] is True
    assert created["kw"]["bounce_time"] == 0.03
    assert "hold_time" not in created["kw"]
    assert key.btn.when_pressed == key._pressed
    assert key.btn.when_released == key._released


def test_input_rotate_180_swaps_joy_pins(monkeypatch):
    """Rotation remaps which physical pin backs each logical name."""
    monkeypatch.setattr(config, "ROTATE_180", True)
    # Capture unrotated pin numbers before Input builds its local map.
    unrotated = dict(config.PINS)
    created = {}

    class Btn:
        def __init__(self, pin, **kw):
            self.pin = pin
            self.when_pressed = None
            self.when_released = None
            created[pin] = self

    monkeypatch.setattr(buttons, "Button", Btn)
    events = []
    inp = buttons.Input(lambda n, k: events.append((n, k)))

    assert inp.keys["up"].btn.pin == unrotated["down"]
    assert inp.keys["down"].btn.pin == unrotated["up"]
    assert inp.keys["left"].btn.pin == unrotated["right"]
    assert inp.keys["right"].btn.pin == unrotated["left"]
    for name in ("press", "k1", "k2", "k3"):
        assert inp.keys[name].btn.pin == unrotated[name]

    # Pressing the physical down pin (now wired to logical "up") emits "up".
    created[unrotated["down"]].when_pressed()
    created[unrotated["down"]].when_released()
    assert events == [("up", "tap")]
    events.clear()
    created[unrotated["up"]].when_pressed()
    created[unrotated["up"]].when_released()
    assert events == [("down", "tap")]
    events.clear()
    created[unrotated["right"]].when_pressed()
    created[unrotated["right"]].when_released()
    assert events == [("left", "tap")]
    events.clear()
    created[unrotated["left"]].when_pressed()
    created[unrotated["left"]].when_released()
    assert events == [("right", "tap")]
    events.clear()
    created[unrotated["k1"]].when_pressed()
    created[unrotated["k1"]].when_released()
    assert events == [("k1", "tap")]


def test_input_button_cls_factory(fake_button):
    events = []
    inp = buttons.Input(lambda n, k: events.append((n, k)),
                        button_cls=fake_button)
    assert set(inp.keys) == set(config.PINS)
    assert inp.keys["up"].repeats is True
    assert inp.keys["k1"].repeats is False
    inp.keys["k3"].btn.tap()
    assert events == [("k3", "tap")]


def test_input_gpiozero_params(monkeypatch):
    created = []

    class Btn:
        def __init__(self, pin, **kw):
            created.append((pin, kw))
            self.when_pressed = None
            self.when_released = None

    monkeypatch.setattr(config, "ROTATE_180", False)
    monkeypatch.setattr(buttons, "Button", Btn)
    buttons.Input(lambda n, k: None)
    assert len(created) == len(config.PINS)
    pins_seen = {pin for pin, _ in created}
    assert pins_seen == set(config.PINS.values())
    for _, kw in created:
        assert kw["pull_up"] is True
        assert kw["bounce_time"] == 0.03
