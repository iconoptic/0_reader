# Phase 1B — Input

**Status:** done. **Depends on:** Phase 0 (`config.py`, `contracts.py`).
**Parallel with:** 1A, 1C, 1D, 3.

## Context you need

Read first:
- [`phase-0-contracts.md`](phase-0-contracts.md) — `config.PINS`,
  `config.REPEATING_KEYS`, `config.HOLD_DELAY`, `config.REPEAT_SECS`,
  `config.ROTATE_180`, and the event-tuple contract (`(name, kind)`,
  `kind` in `"tap" | "hold" | "repeat"`).
- `rapid_reader/buttons.py` (current file, being replaced) — study
  `TapButton`'s structure: it wraps a `gpiozero.Button` (or an injected
  fake), uses `threading.Timer` + a lock, and calls a caller-supplied
  callback. Keep that general shape; the timing state machine changes.
- `tests/conftest.py` — the current `FakeButton` fixture (records
  `when_pressed`/`when_held`/`when_released`, exposes `.tap()`/`.hold()`
  helpers) and the `wait_for` fixture (polls a predicate with a timeout,
  used to await real `threading.Timer` firing in tests without sleeping
  the full production duration — tests monkeypatch the timing constants
  down to a few milliseconds first).
- `tests/test_buttons.py` (current file) — current coverage to mirror for
  the new key/input model.

## Why the old model changes

The old HAT had two keys and a tap/double-tap/triple-tap/hold vocabulary
(`TAP_WINDOW`, `HOLD_TIME`). The new HAT has 8 inputs (5-way joystick +
K1/K2/K3) and the control map (see Phase 0) only ever needs **tap**,
**hold** (fires once) and **repeat** (fires repeatedly while held, for
list navigation) — no multi-tap counting. This is a simpler state machine
per key, not a harder one.

## Deliverables

- **New** `rapid_reader/buttons.py` contents (same filename, full rewrite)
  exporting `Key` and `Input`. Delete `TapButton`.
- **Update** `tests/conftest.py`'s `FakeButton` and `fake_button` fixture
  to match the new callback surface (see below).
- **Rewrite** `tests/test_buttons.py` for `Key`/`Input`.

## `rapid_reader/buttons.py` — required contents

### `Key` — one physical input

```python
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
```

Guard against `gpiozero` being unimportable exactly like the old file did
(`try: from gpiozero import Button; except ImportError: Button = None`) so
this module can be imported on a dev box / under test with no GPIO
library installed.

### `Input` — all 8 keys, with rotation

```python
class Input:
    """Owns all 8 Key objects. on_event(name, kind) is called for every
    key's event, already remapped for config.ROTATE_180."""

    def __init__(self, on_event, button_cls=None):
        pins = dict(config.PINS)
        if config.ROTATE_180:
            pins["up"], pins["down"] = pins["down"], pins["up"]
            pins["left"], pins["right"] = pins["right"], pins["left"]
        self.keys = {}
        for name in config.PINS:
            repeats = name in config.REPEATING_KEYS
            button = button_cls() if button_cls else None
            if button is not None:
                # test fakes take no pin; real gpiozero.Button needs one
                pass
            key = Key(name, on_event, repeats,
                      button=Button(pins[name], pull_up=True, bounce_time=0.03)
                      if button is None else button)
            self.keys[name] = key
```

Adjust the exact `button_cls`/`button` plumbing so it matches whatever
`App`/tests actually need to inject (see the `fake_button` fixture below)
— the important, non-negotiable part is: **the rotation swap happens on
`config.PINS`'s values (which physical pin backs which logical name), not
on the event names emitted afterwards.** After construction, `Input`
always emits the same 8 logical names (`"up"`, `"down"`, `"left"`,
`"right"`, `"press"`, `"k1"`, `"k2"`, `"k3"`) regardless of
`config.ROTATE_180` — callers (Phase 2's `App`/screens) never need to
know about rotation at all.

## `tests/conftest.py` changes

Update `FakeButton` to match the new pressed/released-only surface (no
`when_held` is set by `Key`, so the fixture doesn't need to fire it):

```python
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
```

Remove the old synchronous `.hold()` helper (it assumed a
`when_held`-based model that no longer exists) — replace call sites in
`test_buttons.py` with the `press()` / monkeypatched-timing / `wait_for` /
`release()` sequence, e.g.:

```python
def test_key_repeat(fake_button, wait_for, monkeypatch):
    monkeypatch.setattr(config, "HOLD_DELAY", 0.02)
    monkeypatch.setattr(config, "REPEAT_SECS", 0.02)
    events = []
    btn = fake_button()
    key = buttons.Key("up", lambda n, k: events.append((n, k)), repeats=True,
                       button=btn)
    btn.press()
    assert wait_for(lambda: len(events) >= 2)   # at least two "repeat"s
    btn.release()
    assert events[0] == ("up", "repeat")
```

Also decide, and apply consistently, how `Input` accepts injected fake
buttons for the `App`/test fixtures in Phase 2 — a `button_cls` factory
called once per key name is the simplest option consistent with the old
`App(display=None, button_cls=None)` injection pattern; document whatever
you choose in a short docstring on `Input.__init__` so Phase 2 can rely on
it without re-reading this file.

## `tests/test_buttons.py` — required coverage

- Tap: press+release before `HOLD_DELAY` → exactly one `"tap"` event, no
  `"hold"`/`"repeat"`.
- Hold on a non-repeating key (e.g. `"k1"`): press, wait past
  `HOLD_DELAY` (monkeypatched tiny) → exactly one `"hold"` event fires and
  no more, even if held much longer; release afterwards fires nothing
  further.
- Repeat on a repeating key (e.g. `"up"`): press, wait long enough for
  several `REPEAT_SECS` intervals (both monkeypatched tiny) → multiple
  `"repeat"` events, evenly spaced-ish; release stops further events.
- Releasing before `HOLD_DELAY` never fires a leftover `"hold"`/`"repeat"`
  from a stale timer (i.e. `_released` actually cancels the pending
  timer — test by monkeypatching `HOLD_DELAY` to something a bit larger
  than the test's own release timing and asserting no event arrives).
- `Input.__init__` with `config.ROTATE_180 = True` (monkeypatched):
  pressing the *physical* pin that `config.PINS["down"]` names (unrotated)
  results in an `"up"` event, and vice versa; left/right likewise;
  `"press"`/`"k1"`/`"k2"`/`"k3"` are unaffected by rotation.
- Real `gpiozero.Button` construction parameters: pin number,
  `pull_up=True`, `bounce_time=0.03` — same style of check as the old
  `test_buttons.py` had for `TapButton`.

## Definition of done

- `python3 -m pytest -q` green, including the rewritten `test_buttons.py`.
- `rapid_reader/buttons.py` exports `Key` and `Input`; `TapButton` no
  longer exists anywhere in the codebase (grep for it).
- `Input` emits only the 8 canonical event names, unaffected by rotation
  from the caller's perspective.

## Non-goals

- Do not touch `config.py`/`contracts.py` (Phase 0 owns them — if you find
  a genuine gap, e.g. a missing constant, add a short note to this file's
  PR/commit description rather than freelance-editing Phase 0's contract).
- Do not implement `App`, screens, or anything that consumes these events
  beyond the test suite — that is Phase 2.
