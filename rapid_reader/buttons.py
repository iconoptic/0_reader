"""8-key input: tap / hold / repeat for the SH1106 OLED HAT."""

import threading

try:
    from gpiozero import Button
except ImportError:  # tests / dev box without GPIO
    Button = None

import config


class Key:
    """One physical button/joystick direction.

    on_event(name, kind) is called with kind="tap" on a quick
    press-and-release (released before config.HOLD_DELAY elapses);
    kind="hold" once, config.HOLD_DELAY after press, if `repeats` is
    False and the key is still held; kind="repeat" every
    config.REPEAT_SECS starting config.HOLD_DELAY after press, for as
    long as the key stays held, if `repeats` is True. Only one of
    tap/hold/repeat-events fires per press-release cycle's press phase;
    tap is mutually exclusive with hold/repeat.

    `button` may be any object exposing settable `when_pressed` /
    `when_released` attributes (a gpiozero.Button by default, or a test
    fake); `Key` never touches gpiozero's own hold_time/when_held
    machinery -- it drives its own threading.Timer so the "first hold"
    delay and the "repeat interval" can be different values.
    """

    def __init__(self, name, on_event, repeats, button=None):
        self.name = name
        self.on_event = on_event
        self.repeats = repeats
        self._timer = None
        self._fired = False   # True once this press has emitted hold/repeat
        self._lock = threading.Lock()
        if button is None:
            button = Button(config.PINS[name], pull_up=True, bounce_time=0.03)
        self.btn = button
        self.btn.when_pressed = self._pressed
        self.btn.when_released = self._released

    def _pressed(self):
        with self._lock:
            self._fired = False
            self._timer = threading.Timer(config.HOLD_DELAY, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self):
        with self._lock:
            self._fired = True
            repeats = self.repeats
        self.on_event(self.name, "repeat" if repeats else "hold")
        if repeats:
            with self._lock:
                self._timer = threading.Timer(config.REPEAT_SECS, self._fire)
                self._timer.daemon = True
                self._timer.start()

    def _released(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            fired = self._fired
            self._fired = False
        if not fired:
            self.on_event(self.name, "tap")


class Input:
    """Owns all 8 Key objects. on_event(name, kind) is called for every
    key's event, already remapped for config.ROTATE_180.

    button_cls, if given, is a zero-arg factory called once per key to
    build an injectable stand-in for gpiozero.Button (same pattern as
    App(display=None, button_cls=None)). When omitted, each Key builds a
    real gpiozero.Button on the (possibly rotation-swapped) BCM pin.
    """

    def __init__(self, on_event, button_cls=None):
        pins = dict(config.PINS)
        if config.ROTATE_180:
            pins["up"], pins["down"] = pins["down"], pins["up"]
            pins["left"], pins["right"] = pins["right"], pins["left"]
        self.keys = {}
        for name in config.PINS:
            repeats = name in config.REPEATING_KEYS
            if button_cls is not None:
                button = button_cls()
            else:
                button = Button(pins[name], pull_up=True, bounce_time=0.03)
            self.keys[name] = Key(name, on_event, repeats, button=button)
