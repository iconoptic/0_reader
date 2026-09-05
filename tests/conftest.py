"""Shared test fixtures.

The app modules live in ``rapid_reader/`` and import each other as top-level
modules (``import config``), exactly as they run on the device, so that
directory is put on ``sys.path``. Hardware-only modules (``epd``, the real
``gpiozero``/``spidev``) are never imported by the tests; ``main`` and
``buttons`` tolerate their absence.
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
    """Stand-in for gpiozero.Button: records callbacks, lets tests fire them."""

    def __init__(self):
        self.when_pressed = None
        self.when_held = None
        self.when_released = None

    def tap(self):
        self.when_pressed()
        self.when_released()

    def hold(self):
        self.when_pressed()
        self.when_held()
        self.when_released()


@pytest.fixture
def fake_button():
    return FakeButton


class FakeEPD:
    """Records every frame the app pushes, tagged full/partial."""

    def __init__(self):
        self.frames = []
        self.sleeping = False

    def display_full(self, image):
        self.frames.append(("full", image))

    def display_partial(self, image):
        self.frames.append(("partial", image))

    def sleep(self):
        self.sleeping = True

    @property
    def last(self):
        return self.frames[-1][1]


@pytest.fixture
def fake_epd():
    return FakeEPD()


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
