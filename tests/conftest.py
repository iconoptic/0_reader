"""Shared test fixtures.

The app modules live in ``rapid_reader/`` and import each other as top-level
modules (``import config``), exactly as they run on the device, so that
directory is put on ``sys.path``. Hardware-only libraries (``spidev``,
``lgpio``, ``gpiozero``) are never imported by the tests; ``oled``,
``display`` and ``buttons`` tolerate their absence.
"""

import os
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rapid_reader"))

import config  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Point book/state paths at a temp dir so tests never touch /var or ~."""
    books_dir = tmp_path / "ebooks"
    books_dir.mkdir()
    state_dir = tmp_path / "state"
    monkeypatch.setattr(config, "BOOKS_DIR", str(books_dir))
    monkeypatch.setattr(config, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(config, "STATE_FILE", str(state_dir / "state.json"))
    yield


@pytest.fixture
def books_dir():
    return config.BOOKS_DIR


class FakeButton:
    """Stand-in for gpiozero.Button: records callbacks, lets tests fire
    them directly. Timing (hold/repeat) is exercised by monkeypatching
    config.HOLD_DELAY / config.REPEAT_SECS down to a few milliseconds and
    using the `wait_for` fixture to await the real threading.Timer -- see
    test_buttons.py for the pattern."""

    def __init__(self):
        self.when_pressed = None
        self.when_released = None

    def tap(self):
        self.when_pressed()
        self.when_released()

    def press(self):
        self.when_pressed()

    def release(self):
        self.when_released()


@pytest.fixture
def fake_button():
    return FakeButton


class FakePanel:
    """Stand-in for oled.SH1106: records every frame pushed to it."""

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.frames = []
        self.raw = []
        self.contrast_level = None
        self.inverted = False
        self.sleeping = False

    def show(self, image):
        assert image.size == (self.width, self.height), image.size
        self.frames.append(image)

    def show_raw(self, buf):
        assert len(buf) == self.width * self.height // 8
        self.raw.append(bytes(buf))

    def contrast(self, value):
        self.contrast_level = value

    def invert(self, on):
        self.inverted = bool(on)

    def sleep(self):
        self.sleeping = True

    def wake(self):
        self.sleeping = False

    @property
    def last(self):
        return self.frames[-1]


@pytest.fixture
def fake_display():
    import display
    return display.Display(FakePanel(config.OLED_W, config.OLED_H))


@pytest.fixture
def wait_for():
    """Poll until predicate() is true (for the tap-window timers)."""

    def _wait(pred, timeout=2.0):
        ev = threading.Event()
        deadline = timeout
        step = 0.01
        while deadline > 0:
            if pred():
                return True
            ev.wait(step)
            deadline -= step
        return pred()

    return _wait
