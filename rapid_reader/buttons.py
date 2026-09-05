"""Multi-tap + hold detection for the HAT's two keys (K1/K2)."""

import threading

try:
    from gpiozero import Button
except ImportError:  # tests / dev box without GPIO
    Button = None

import config


class TapButton:
    """Counts taps within a short window; distinguishes press-and-hold.

    on_taps(n) is called with the tap count (1, 2, 3...).
    on_hold() is called once when the button is held HOLD_TIME seconds.
    `button` may be any object exposing when_pressed/when_held/when_released
    callback slots (a gpiozero.Button by default).
    """

    def __init__(self, pin, on_taps, on_hold=None, button=None):
        self.on_taps = on_taps
        self.on_hold = on_hold
        self._count = 0
        self._timer = None
        self._held = False
        self._lock = threading.Lock()
        if button is None:
            button = Button(pin, pull_up=True, bounce_time=0.03,
                            hold_time=config.HOLD_TIME)
        self.btn = button
        self.btn.when_pressed = self._pressed
        self.btn.when_held = self._on_held
        self.btn.when_released = self._released

    def _pressed(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _on_held(self):
        with self._lock:
            self._held = True
            self._count = 0
        if self.on_hold:
            self.on_hold()

    def _released(self):
        fire_later = False
        with self._lock:
            if self._held:
                self._held = False
                return
            self._count += 1
            self._timer = threading.Timer(config.TAP_WINDOW, self._finalize)
            self._timer.daemon = True
            fire_later = True
        if fire_later:
            self._timer.start()

    def _finalize(self):
        with self._lock:
            n = self._count
            self._count = 0
            self._timer = None
        if n and self.on_taps:
            self.on_taps(n)
