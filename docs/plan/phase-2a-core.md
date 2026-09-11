# Phase 2A — App core + Library/Reading/Paused/End screens

**Status:** not started. **Depends on:** Phase 0 and all of Phase 1
(1A/1B/1C/1D) landed — confirmed green, see
[`corrections-phase-0-1.md`](corrections-phase-0-1.md). **Part of the
Phase 2 split** — see [`phase-2-app.md`](phase-2-app.md) (design
background) and [`README.md`](README.md). **Run this one first** — 2B/2C
both edit code this phase creates.

> **Note on this file's history:** an earlier version of this doc was
> corrupted in storage (only a "Tests"/"Definition of done" tail
> survived). This is a full rewrite, reconstructed from what
> [`phase-2b-book-nav.md`](phase-2b-book-nav.md),
> [`phase-2c-settings-system.md`](phase-2c-settings-system.md) and
> [`phase-2d-integration.md`](phase-2d-integration.md) already assume
> about this phase's output (they were written against it and are
> internally consistent with each other), cross-checked against the
> actual landed Phase 0/1 code rather than the original guessed
> signatures. Where this differs from [`phase-2-app.md`](phase-2-app.md)'s
> sketch, this file wins — see "Corrections vs. the original sketch"
> below.

## Context you need

Read first:
- [`phase-0-contracts.md`](phase-0-contracts.md) — the control map.
- `rapid_reader/contracts.py` — `Screen`, `Theme` (read the actual file;
  it also carries the full schema/control-map docstring now).
- `rapid_reader/state.py` — `State(path=None)`: `.settings`, `.last_book`,
  `.in_book`, `.books`; `.book(path) -> dict`, `.touch_book(path,
  **fields)`, `.add_bookmark(path, idx)`, `.remove_bookmark(path, idx)`,
  `.save()`.
- `rapid_reader/theme.py` — `THEMES: dict[str, Theme]`, `DEFAULT_THEME_KEY`.
- `rapid_reader/display.py` — `Display.show(image)`, `.contrast(value)`,
  `.invert(on)`, `.splash(path=None) -> bool`, `.sleep()`, `.wake()`;
  `open_display(retry_secs=None, log=print) -> Display` (already applies
  `config.IDLE_ACTIVE_CONTRAST` at boot).
- `rapid_reader/buttons.py` — `Input(on_event, button_cls=None)` (exposes
  `.keys: dict[str, Key]`); event tuples `(name, kind)`.
- `rapid_reader/render.py` — read every function signature directly
  (`word_frame`, `chunk_frame`, `list_frame`, `paused_frame`,
  `info_frame`, `message_frame`, `confirm_frame`, `end_frame`, `splash`)
  — **use the actual signatures in the file, not this doc's prose**, in
  case render.py changes again after this is written.
- `rapid_reader/books.py` — `Book.load(path)`, `.words`,
  `.sentence_starts`, `.para_ends`, `.chapter_starts`,
  `scan_library(directory=None)`.
- `rapid_reader/rsvp.py` — `word_delay(word, wpm, is_para_end=False,
  weights=None)`.
- `rapid_reader/main.py` (current file, being replaced) — port
  `jump_sentence`/`jump_chapter`/`step_word`'s pacing math essentially
  unchanged; everything else in it is LCD-HAT-era and is replaced.
- `tests/conftest.py` — `fake_display` (single `FakePanel`, sized
  `config.OLED_W x config.OLED_H`), `fake_button`/`FakeButton` (a
  zero-arg-constructible stand-in — matches `Input`'s `button_cls`
  contract exactly: `button_cls()` is called once per key), `wait_for`.
- `tests/test_app.py` (current file, entirely `pytest.mark.skip`ped) —
  rewrite it; its current body is LCD-HAT-era reference material only.

## Corrections vs. the original sketch in `phase-2-app.md`

1. **No image-mode conversion needed in `App`.** The original sketch had
   `App.redraw()` do `img.convert("1") if img.mode != "1" else img`
   before calling `display.show()`. The landed `oled.SH1106.show()`
   already accepts mode `"L"` (and thresholds it) directly — `render.py`
   only ever produces `"L"` images. `App`/screens just pass `render.py`'s
   output straight to `self.display.show(...)`.
2. **One `BookMenuScreen`, not separate `MainMenuScreen`/`BookMenuScreen`
   classes**, resolved this way: `BookMenuScreen.items(app)` returns a
   reduced 2-item list (`"Settings"`, `"System"`) when `app.book is
   None` (reached from the Library, per the control map's "K2 tap = main
   menu"), and the full 7-item list when a book is open (reached from
   Reading/Paused, per the control map's "K2 tap = open book menu").
   This is why [`phase-2c-settings-system.md`](phase-2c-settings-system.md)'s
   instruction to "edit `BookMenuScreen.activate`'s Settings/System
   lines" is correct and complete as written — those two lines are
   reachable from both entry points, this phase does not introduce a
   second class 2C would also need to touch.
3. **`App.leave_to_library()` reuses `pop_to_root()`'s natural
   `on_exit`** to stop the reading-time accumulator, instead of a
   separate explicit call — see the ordering note in its listing below;
   getting this ordering backwards (clearing `app.book` before popping)
   is the one subtle bug to watch for when implementing this.

## Deliverables

- **New** `rapid_reader/screens.py`.
- **Rewrite** `rapid_reader/main.py`.
- **Rewrite** `tests/test_app.py` (remove the `pytest.mark.skip`, replace
  the body).

## `rapid_reader/screens.py`

```python
"""Every Screen in the navigation stack. No hardware; calls render.py."""

import os
import subprocess

import books
import config
import render
from contracts import Screen


class ListScreen(Screen):
    """Shared plumbing for every list-shaped screen."""

    rows_visible = 4

    def __init__(self):
        self.sel = 0
        self.top = 0

    def items(self, app):
        raise NotImplementedError

    def header(self, app):
        raise NotImplementedError

    def row_text(self, app, item):
        return str(item)

    def empty_lines(self, app):
        return ("Nothing here.",)

    def activate(self, app, item):
        pass

    def context_action(self, app, item):
        pass

    def frame(self, app):
        items = self.items(app)
        rows = [self.row_text(app, it) for it in items]
        return render.list_frame(self.header(app), rows, self.sel, self.top,
                                  rows_visible=self.rows_visible,
                                  empty_lines=self.empty_lines(app))

    def _handle_nav(self, app, event):
        """up/down/left/right/press/k3 against self.items(app).
        Returns True if it consumed the event; False lets the caller's
        own k1/k2 handling (or the default k1=back below) run instead."""
        name, kind = event
        items = self.items(app)
        if not items:
            return False
        if name in ("up", "down") and kind in ("tap", "repeat"):
            delta = -1 if name == "up" else 1
            self.sel = (self.sel + delta) % len(items)
            self._scroll_into_view()
            app.redraw()
            return True
        if name in ("left", "right") and kind in ("tap", "repeat"):
            delta = -self.rows_visible if name == "left" else self.rows_visible
            self.sel = max(0, min(len(items) - 1, self.sel + delta))
            self._scroll_into_view()
            app.redraw()
            return True
        if name == "press" and kind == "tap":
            self.activate(app, items[self.sel])
            return True
        if name == "k3" and kind == "tap":
            self.context_action(app, items[self.sel])
            return True
        return False

    def handle(self, app, event):
        if self._handle_nav(app, event):
            return
        name, kind = event
        if name == "k1" and kind == "tap":
            app.pop()

    def _scroll_into_view(self):
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.rows_visible:
            self.top = self.sel - self.rows_visible + 1


class LibraryScreen(ListScreen):
    """Root of the stack. Never popped past."""

    def items(self, app):
        return books.scan_library()

    def header(self, app):
        return "LIBRARY"

    def row_text(self, app, item):
        return item[0]   # (title, path)

    def empty_lines(self, app):
        return ("No books found.", "Copy .txt/.epub to", config.BOOKS_DIR)

    def activate(self, app, item):
        title, path = item
        app.open_book(path)

    def context_action(self, app, item):
        # Phase 2B replaces this with app.push(BookInfoScreen(*item)).
        app.push(MessageScreen(["Book info: not yet available"]))

    def handle(self, app, event):
        if self._handle_nav(app, event):
            return
        name, kind = event
        if name == "k1" and kind == "hold":
            app.push(ConfirmScreen("Power off?", self._power_off))
        elif name == "k2" and kind == "tap":
            app.push(BookMenuScreen())
        # k1 tap: intentionally a no-op -- this is the stack root.

    @staticmethod
    def _power_off(app):
        app.state.save()
        argv = (["poweroff"] if os.geteuid() == 0
                else ["sudo", "-n", "poweroff"])
        subprocess.call(argv)


class BookMenuScreen(ListScreen):
    """K2 from the Library (app.book is None: reduced menu) or from
    Reading/Paused (app.book is set: full menu)."""

    _BOOK_ITEMS = ("Chapters", "Bookmarks", "Book info", "Settings",
                   "System", "Bookmark this page", "Save & close book")
    _NO_BOOK_ITEMS = ("Settings", "System")

    def items(self, app):
        return list(self._BOOK_ITEMS if app.book else self._NO_BOOK_ITEMS)

    def header(self, app):
        return "MENU"

    def activate(self, app, item):
        # Phase 2B wires "Chapters"/"Bookmarks"/"Book info" (edit those
        # three elif bodies). Phase 2C wires "Settings"/"System" (edit
        # those two elif bodies). Leave every _not_yet(...) call as the
        # placeholder until the corresponding phase lands.
        if item == "Chapters":
            self._not_yet(app, item)
        elif item == "Bookmarks":
            self._not_yet(app, item)
        elif item == "Book info":
            self._not_yet(app, item)
        elif item == "Settings":
            self._not_yet(app, item)
        elif item == "System":
            self._not_yet(app, item)
        elif item == "Bookmark this page":
            app.state.add_bookmark(app.book.path, app.idx)
            app.state.save()
            app.pop()
        elif item == "Save & close book":
            app.leave_to_library()

    @staticmethod
    def _not_yet(app, item):
        app.push(MessageScreen(["%s: not yet available" % item]))


class ReadingScreen(Screen):
    """Active playback. App.run() bypasses frame() for this screen and
    calls App.step_word() directly on every loop iteration where no
    event is pending -- see App.run() below. frame() still exists so a
    manual app.redraw() (e.g. right after on_enter) has something to
    show."""

    def frame(self, app):
        return render.word_frame(app.book.words[app.idx], app.theme,
                                  flash=app.current_flash(),
                                  word_size=app.state.settings["word_size"])

    def handle(self, app, event):
        name, kind = event
        if name == "press" and kind == "tap":
            app.replace_top(PausedScreen())
        elif name == "k3" and kind == "tap":
            app.replace_top(PausedScreen())
        elif name in ("up", "down") and kind in ("tap", "repeat"):
            app.change_wpm(config.WPM_STEP if name == "up" else -config.WPM_STEP)
        elif name == "left" and kind == "tap":
            app.jump_sentence(-1)
        elif name == "right" and kind == "tap":
            app.jump_sentence(+1)
        elif name == "k1" and kind == "tap":
            app.leave_to_library()
        elif name == "k2" and kind == "tap":
            app.push(BookMenuScreen())

    def on_enter(self, app):
        app._start_reading_timer()

    def on_exit(self, app):
        app._stop_reading_timer()


class PausedScreen(Screen):
    def frame(self, app):
        return render.paused_frame(
            app.book.title, app.book.words, app.idx,
            app.sentence_start(app.idx), app.state.settings["wpm"],
            app.progress(), app.theme)

    def handle(self, app, event):
        name, kind = event
        if name == "press" and kind == "tap":
            app.replace_top(ReadingScreen())
        elif name == "k3" and kind == "tap":
            app.replace_top(ReadingScreen())
        elif name in ("up", "down") and kind in ("tap", "repeat"):
            app.change_wpm(config.WPM_STEP if name == "up" else -config.WPM_STEP)
        elif name == "left" and kind == "tap":
            app.jump_sentence(-1)
        elif name == "right" and kind == "tap":
            app.jump_sentence(+1)
        elif name == "left" and kind == "repeat":
            app.jump_chapter(-1)
        elif name == "right" and kind == "repeat":
            app.jump_chapter(+1)
        elif name == "k1" and kind == "tap":
            app.leave_to_library()
        elif name == "k2" and kind == "tap":
            app.push(BookMenuScreen())


class EndScreen(Screen):
    def frame(self, app):
        return render.end_frame(app.book.title)

    def handle(self, app, event):
        name, kind = event
        if kind == "tap":
            app.pop_to_root()


class MessageScreen(Screen):
    """Generic one-off notice; any tap pops it."""

    def __init__(self, lines, hint="any key: back"):
        self.lines = lines
        self.hint = hint

    def frame(self, app):
        return render.message_frame(self.lines, hint=self.hint)

    def handle(self, app, event):
        name, kind = event
        if kind == "tap":
            app.pop()


class ConfirmScreen(Screen):
    """Generic yes/no dialog. on_yes(app) is called (and this screen
    popped first) only on k3; any other tap just pops (declines)."""

    def __init__(self, prompt, on_yes):
        self.prompt = prompt
        self.on_yes = on_yes

    def frame(self, app):
        return render.confirm_frame(self.prompt, "k3: yes", "other: back")

    def handle(self, app, event):
        name, kind = event
        if kind != "tap":
            return
        app.pop()
        if name == "k3":
            self.on_yes(app)
```

`import subprocess`/`os` at the top are used only by
`LibraryScreen._power_off`; Phase 2C's `SystemScreen` (a separate class,
added later in this same file by that phase) duplicates a very similar
`_run_privileged` helper for "Reboot"/"Power off" from the System screen
— that small duplication across the two entry points (library power-off
vs. system-screen power-off) is intentional and fine, not something to
unify across phases.

## `rapid_reader/main.py`

```python
#!/usr/bin/env python3
"""Rapid Reader: RSVP speed reader for a Pi Zero W + SH1106 OLED HAT.

See CONTROLS.md for the full control map. Normally started via boot.py
(which shows the splash first); running this file directly also works.
"""

import bisect
import os
import queue
import signal
import sys
import time
import traceback

import books
import buttons
import config
import render
import rsvp
import state
import theme
from display import open_display
from screens import (BookMenuScreen, EndScreen, LibraryScreen,
                      PausedScreen, ReadingScreen)


class App:
    def __init__(self, display=None, button_cls=None):
        self.display = display if display is not None else open_display()
        self.events = queue.Queue()
        self.input = buttons.Input(self._on_event, button_cls=button_cls)
        self.state = state.State()
        self.theme = theme.THEMES.get(self.state.settings["theme"],
                                       theme.THEMES[theme.DEFAULT_THEME_KEY])
        self.book = None
        self.idx = 0
        self.stack = []
        self.words_since_save = 0
        self.refresh_secs = config.PANEL_REFRESH_SECS
        self._last_input_at = time.monotonic()
        self._idle_state = "active"
        self._flash_text = None
        self._flash_until = 0.0
        self._reading_since = None
        self.display.invert(self.theme.invert)
        self.display.contrast(self.theme.contrast)

    def _on_event(self, name, kind):
        self.events.put((name, kind))

    # ---- navigation ---------------------------------------------------
    def push(self, screen):
        if self.stack:
            self.stack[-1].on_exit(self)
        self.stack.append(screen)
        screen.on_enter(self)
        self.redraw()

    def pop(self):
        old = self.stack.pop()
        old.on_exit(self)
        self.stack[-1].on_enter(self)
        self.redraw()

    def replace_top(self, screen):
        if self.stack:
            self.stack[-1].on_exit(self)
        self.stack[-1] = screen
        screen.on_enter(self)
        self.redraw()

    def pop_to_root(self):
        while len(self.stack) > 1:
            self.pop()

    def redraw(self):
        if self.stack:
            self.display.show(self.stack[-1].frame(self))

    # ---- theme / settings ----------------------------------------------
    def apply_theme(self, theme_key):
        self.theme = theme.THEMES[theme_key]
        self.state.settings["theme"] = theme_key
        self.display.invert(self.theme.invert)
        self.display.contrast(self.theme.contrast)
        self.state.save()
        self.redraw()

    def change_wpm(self, delta):
        wpm = max(config.MIN_WPM, min(config.MAX_WPM,
                                       self.state.settings["wpm"] + delta))
        self.state.settings["wpm"] = wpm
        self.state.save()
        self._flash_text = "%d wpm" % wpm
        self._flash_until = time.monotonic() + 1.0
        self.redraw()

    def current_flash(self):
        return self._flash_text if time.monotonic() < self._flash_until else None

    # ---- book navigation (ported from the old App, hardware-agnostic) --
    def progress(self):
        if not self.book or not self.book.words:
            return 0.0
        return min(1.0, self.idx / len(self.book.words))

    def sentence_start(self, idx):
        starts = self.book.sentence_starts
        i = bisect.bisect_right(starts, idx) - 1
        return starts[max(0, i)]

    def jump_sentence(self, direction):
        starts = self.book.sentence_starts
        cur = self.sentence_start(self.idx)
        if direction < 0:
            if self.idx - cur < 3:
                i = bisect.bisect_left(starts, cur) - 1
                cur = starts[max(0, i)]
            self.idx = cur
        else:
            i = bisect.bisect_right(starts, self.idx)
            self.idx = starts[i] if i < len(starts) else len(self.book.words) - 1
        self.redraw()

    def jump_chapter(self, direction):
        chapters = self.book.chapter_starts
        if not chapters:
            return
        i = bisect.bisect_right(chapters, self.idx) - 1
        if direction < 0:
            if i >= 0 and self.idx - chapters[i] < 5:
                i -= 1
            self.idx = chapters[i] if i >= 0 else 0
        else:
            j = bisect.bisect_right(chapters, self.idx)
            self.idx = (chapters[j] if j < len(chapters)
                        else len(self.book.words) - 1)
        self.redraw()

    def open_book(self, path):
        self.book = books.Book.load(path)
        rec = self.state.book(path)
        self.idx = min(rec["position"], max(0, len(self.book.words) - 1))
        self.state.touch_book(path, total_words=len(self.book.words),
                               last_opened=time.time())
        self.state.last_book = path
        self.state.in_book = True
        self.state.save()
        self.push(PausedScreen())

    def save_position(self):
        if self.book:
            self.state.touch_book(self.book.path, position=self.idx,
                                   total_words=len(self.book.words))
        self.words_since_save = 0
        self.state.save()

    def leave_to_library(self):
        # Order matters: save + pop (which fires ReadingScreen.on_exit /
        # _stop_reading_timer, needing self.book) BEFORE clearing it.
        self.save_position()
        self.pop_to_root()
        self.state.in_book = False
        self.book = None
        self.state.save()

    # ---- reading-time accumulation --------------------------------------
    def _start_reading_timer(self):
        self._reading_since = time.monotonic()

    def _stop_reading_timer(self):
        if self._reading_since is not None and self.book:
            elapsed = time.monotonic() - self._reading_since
            rec = self.state.book(self.book.path)
            self.state.touch_book(self.book.path,
                                   time_read_secs=rec["time_read_secs"] + elapsed)
        self._reading_since = None

    # ---- playback (ported from the old App.step_word) -------------------
    def step_word(self):
        words, para_ends = self.book.words, self.book.para_ends
        wpm = self.state.settings["wpm"]
        start = self.idx
        chunk = [words[start]]
        total_delay = rsvp.word_delay(words[start], wpm, start in para_ends)
        end = start
        while total_delay < self.refresh_secs and end + 1 < len(words):
            end += 1
            chunk.append(words[end])
            total_delay += rsvp.word_delay(words[end], wpm, end in para_ends)

        t0 = time.monotonic()
        word_size = self.state.settings["word_size"]
        flash = self.current_flash()
        img = (render.word_frame(chunk[0], self.theme, flash, word_size)
               if len(chunk) == 1
               else render.chunk_frame(chunk, self.theme, word_size))
        self.display.show(img)
        elapsed = time.monotonic() - t0
        self.refresh_secs = 0.8 * self.refresh_secs + 0.2 * elapsed

        self.idx = end + 1
        self.words_since_save += len(chunk)
        if self.words_since_save >= config.SAVE_EVERY_WORDS:
            self.save_position()
        if self.idx >= len(words):
            self.idx = len(words) - 1
            self.state.in_book = False
            self.save_position()
            self.push(EndScreen())   # fires ReadingScreen.on_exit -> stops timer
            return
        remaining = total_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    # ---- idle / burn-in protection ---------------------------------------
    def _tick_idle(self):
        idle_for = time.monotonic() - self._last_input_at
        reading = bool(self.stack) and isinstance(self.stack[-1], ReadingScreen)
        if reading:
            target = "active"
        elif idle_for >= config.IDLE_OFF_SECS:
            target = "off"
        elif idle_for >= config.IDLE_DIM_SECS:
            target = "dim"
        else:
            target = "active"
        if target != self._idle_state:
            self._idle_state = target
            if target == "off":
                self.display.sleep()
            elif target == "dim":
                self.display.wake()
                self.display.contrast(config.IDLE_DIM_CONTRAST)
            else:
                self.display.wake()
                self.display.contrast(self.theme.contrast)

    # ---- main loop --------------------------------------------------------
    def _initial_screen(self):
        if (self.state.in_book and self.state.last_book
                and any(p == self.state.last_book for _, p in books.scan_library())):
            self.book = books.Book.load(self.state.last_book)
            rec = self.state.book(self.book.path)
            self.idx = min(rec["position"], max(0, len(self.book.words) - 1))
            return PausedScreen()
        return LibraryScreen()

    def run(self):
        self.push(self._initial_screen())
        while True:
            reading = isinstance(self.stack[-1], ReadingScreen)
            if reading:
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    self.step_word()
                    continue
            else:
                try:
                    ev = self.events.get(timeout=1.0)
                except queue.Empty:
                    self._tick_idle()
                    continue
            self._last_input_at = time.monotonic()
            was_off = self._idle_state == "off"
            self._tick_idle()
            if was_off:
                continue   # swallow the waking key press
            self.stack[-1].handle(self, ev)


def main(display=None):
    if display is None:
        display = open_display()
    app = App(display=display)

    def bail(signum, frame):
        app.save_position()
        try:
            display.sleep()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, bail)
    try:
        app.run()
    except Exception:
        traceback.print_exc()
        try:
            display.show(render.message_frame(
                ["Error \u2014 restarting", "journalctl -u rapid-reader"]))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
```

Note `bail()` calls `app.save_position()` unconditionally (not
`app.save_position() if app.book else app.state.save()` like the old
file) — `save_position()` itself already only touches `self.book`'s
record when `self.book` is set, and always calls `self.state.save()`
either way, so the ternary is redundant now.

## `tests/test_app.py` — required coverage

Remove the file's current `pytestmark = pytest.mark.skip(...)` line and
its LCD-HAT-era body. Add a `fire(app, name, kind="tap")` helper:

```python
def fire(app, name, kind="tap"):
    app._on_event(name, kind)
    ev = app.events.get_nowait()
    app._last_input_at = __import__("time").monotonic()
    app._tick_idle()
    app.stack[-1].handle(app, ev)
```

(This bypasses `buttons.Input`/`Key`'s real timer machinery entirely —
that machinery already has its own tests in `tests/test_buttons.py`;
these tests are about screen/App logic given an event, not about how the
event got generated. For the two tests that specifically need repeated
"repeat" events or the idle-state machine's timing, drive `app._tick_idle()`
and/or call `fire` multiple times with monkeypatched `config.IDLE_*`
constants instead of trying to wait on real timers.)

Build a small in-memory book directly for most tests (`books.Book(path,
title, words, sentence_starts, para_ends, chapter_starts=...,
chapter_titles=...)`) rather than writing a real file through
`books.scan_library()`, except for the handful of tests that are
specifically about the library listing itself.

Required cases:
- Boot resumes into `PausedScreen` when `state.in_book` was true and the
  book is still in the (real, file-backed for this one case) library;
  boots into `LibraryScreen` otherwise.
- `k1` (tap) from `LibraryScreen` is a no-op (`len(app.stack) == 1`
  unchanged); `k1` **hold** pushes `ConfirmScreen`, confirming (`k3`)
  calls the privileged power-off path (monkeypatch `subprocess.call` to
  a recorder — never actually power off in a test), declining does not.
- `k2` tap from `LibraryScreen` (no book open) pushes `BookMenuScreen`
  with exactly `["Settings", "System"]` as its items; both currently
  push a `MessageScreen` saying "not yet available" (2A's placeholder
  state — 2C will change what they push, not add this test file's
  coverage of them existing as placeholders).
- Opening a book (`press` on a library row) lands on `PausedScreen` with
  `app.idx` seeded from `state.book(path)["position"]`.
- Every `ReadingScreen`/`PausedScreen` control-map binding from Phase 0:
  press/k3 toggles Reading<->Paused (`isinstance(app.stack[-1], ...)`,
  and `len(app.stack)` unchanged — this is `replace_top`, not push/pop);
  up/down (`tap` and `repeat`) change `state.settings["wpm"]` by
  `WPM_STEP`, clamped to `MIN_WPM`/`MAX_WPM`; left/right tap jumps a
  sentence in `ReadingScreen` and `PausedScreen`; left/right **repeat**
  jumps a chapter **only** in `PausedScreen` (assert it does nothing in
  `ReadingScreen`); `k1` tap from either saves and returns to
  `LibraryScreen` with `len(app.stack) == 1`; `k2` tap from either pushes
  `BookMenuScreen` with the **full** 7-item list (`app.book` is set here).
- `BookMenuScreen`'s "Bookmark this page" (`state.add_bookmark` called
  with the right path/idx, then pops) and "Save & close book"
  (equivalent to `k1` from Paused) work for real in this phase; the other
  five items each push a `MessageScreen` (update these assertions in
  place, don't leave them skipped, when 2B/2C land — but that's those
  phases' job, not this one's).
- `app.step_word()` walking through a short in-memory book reaches
  `EndScreen` when it runs out of words, with `state.in_book` now
  `False` and the position saved; any key from `EndScreen` returns to
  `LibraryScreen` with `len(app.stack) == 1`.
- Idle: monkeypatch `config.IDLE_DIM_SECS`/`IDLE_OFF_SECS` tiny; assert
  `display.contrast`/`display.sleep` fire at the right thresholds while
  sitting on `LibraryScreen`/`PausedScreen`, and never while on
  `ReadingScreen` (drive this via repeated `app._tick_idle()` calls with
  `app._last_input_at` backdated, not real sleeping).
- The key press that wakes an "off" display is swallowed: after forcing
  `app._idle_state = "off"`, `fire(...)` on any key does not also reach
  the active screen's `handle` (assert no navigation/state change beyond
  waking).
- `time_read_secs` accumulates between `ReadingScreen.on_enter` and
  `on_exit`/leave/end — monkeypatch `time.monotonic` to a small
  incrementing fake, or just assert it strictly increased.
- SIGTERM: call `main.App`'s `bail` directly (extract it in the test by
  constructing `App` and re-deriving the same closure, or refactor
  `bail`'s body into a tiny module-level `_bail(app, display)` helper if
  that is cleaner to test — either is fine) with `sys.exit` monkeypatched
  to a recorder rather than actually exiting the test process; assert
  `state.save()` happened and `display.sleep()` was called.

## Definition of done

- `python3 -m pytest -q` green; `test_app.py` has real (not skipped)
  coverage for everything above.
- A person can run `App(display=fake_display, button_cls=FakeButton)`
  and, via `fire(...)`, walk: library -> open a book -> read it -> pause
  -> resume -> jump sentences/chapters -> change speed -> finish it ->
  land back in the library -> open the book menu and see the five
  placeholder items say "not yet available" while "Bookmark this page"
  and "Save & close book" actually work.
- No other phase's file (`config.py`, `contracts.py`, `oled.py`,
  `buttons.py`, `theme.py`, `render.py`, `state.py`, `rsvp.py`,
  `books.py`) is modified by this phase.

## Non-goals

- Do not add `ChaptersScreen`/`BookmarksScreen`/`BookInfoScreen`
  (Phase 2B) or `SettingsScreen`/`ThemesScreen`/`DisplaySettingsScreen`/
  `SystemScreen` (Phase 2C) — leave every corresponding `BookMenuScreen`
  branch as `self._not_yet(app, item)`.
- Do not remove `config.py`'s temporary LCD-HAT constant block — that is
  Phase 2D's job, once nothing else references it.
