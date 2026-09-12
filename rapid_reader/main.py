#!/usr/bin/env python3
"""Rapid Reader: RSVP speed reader for a Pi Zero W + SH1106 OLED HAT.

Single 128x64 panel. Navigation is a screen stack (library, reading,
paused, book menu, dialogs). Controls:

  Library:  up/down       move selection (repeats)
            left/right    page (repeats)
            press         open book
            K1 hold       power-off confirm
            K2            menu (Settings / System)
            K3            book info
            K1 tap        no-op at root

  Reading:  press / K3    pause
            up/down       wpm +/- WPM_STEP
            left/right    jump sentence
            K1            save & library
            K2            book menu

  Paused:   same as Reading, plus left/right hold/repeat = jump chapter

Normally started via boot.py (which shows the splash first); running this
file directly also works.
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
import display as oled_display
import render
import rsvp
import screens
import state
import theme


class App:
    def __init__(self, display=None, input_cls=None):
        self.display = display if display is not None else oled_display.open_display()
        self.events = queue.Queue()
        self.input = (input_cls or buttons.Input)(self._on_event)
        self.state = state.State()
        self.theme = theme.THEMES.get(self.state.settings["theme"],
                                       theme.THEMES[theme.DEFAULT_THEME_KEY])
        self.book = None            # books.Book, set when a book is open
        self.idx = 0
        self.stack = []              # list[contracts.Screen]; stack[-1] is active
        self.words_since_save = 0
        self.refresh_secs = config.PANEL_REFRESH_SECS
        self._last_input_at = time.monotonic()
        self._idle_state = "active"  # "active" | "dim" | "off"
        self._flash_text = None
        self._flash_until = 0.0
        self._reading_since = None
        self.display.invert(self.theme.invert)
        self.display.contrast(self.theme.contrast)

    def _on_event(self, name, kind):
        self.events.put((name, kind))

    # ---- navigation ----
    def push(self, screen):
        if self.stack:
            self.stack[-1].on_exit(self)
        self.stack.append(screen)
        screen.on_enter(self)
        self.redraw()

    def pop(self):
        if len(self.stack) <= 1:
            return   # library root: never pop past it
        old = self.stack.pop()
        old.on_exit(self)
        self.stack[-1].on_enter(self)
        self.redraw()

    def pop_to_root(self):
        # Exit every screen above the root without redrawing intermediates
        # (leave_to_library clears self.book before this runs). Always land
        # on LibraryScreen — a book-only stack (e.g. old resume shape) must
        # not redraw Paused/Reading/End with book already None.
        while len(self.stack) > 1:
            old = self.stack.pop()
            old.on_exit(self)
        if not self.stack or not isinstance(self.stack[0], screens.LibraryScreen):
            if self.stack:
                self.stack[0].on_exit(self)
            self.stack[:] = [screens.LibraryScreen()]
        self.stack[-1].on_enter(self)
        self.redraw()

    def pop_to(self, screen_cls):
        """Pop until the top of the stack is an instance of screen_cls
        (inclusive check on the *next* one down); used by book-navigation
        screens to return to Paused after jumping. Assumes screen_cls is
        somewhere on the stack (true for every current call site)."""
        while len(self.stack) > 1 and not isinstance(self.stack[-1], screen_cls):
            self.pop()
        self.redraw()

    def replace_top(self, screen):
        """Swap the active screen without growing the stack -- used only
        for the Reading<->Paused toggle, which is the same open book at
        the same navigation depth, not a new destination."""
        if self.stack:
            self.stack[-1].on_exit(self)
        self.stack[-1] = screen
        screen.on_enter(self)
        self.redraw()

    # ---- rendering ----
    def redraw(self):
        img = self.stack[-1].frame(self)
        self.display.show(img)

    # ---- theme / idle ----
    def apply_theme(self, theme_key):
        self.theme = theme.THEMES[theme_key]
        self.state.settings["theme"] = theme_key
        self.display.invert(self.theme.invert)
        self.display.contrast(self.theme.contrast)
        self.state.save()
        self.redraw()

    def _tick_idle(self):
        idle_for = time.monotonic() - self._last_input_at
        reading = self.stack and isinstance(self.stack[-1], screens.ReadingScreen)
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

    # ---- playback ----
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
            self.idx = chapters[j] if j < len(chapters) else len(self.book.words) - 1
        self.redraw()

    def change_wpm(self, delta):
        self.state.settings["wpm"] = max(
            config.MIN_WPM, min(config.MAX_WPM, self.state.settings["wpm"] + delta))
        self.state.save()
        wpm = self.state.settings["wpm"]
        if (self.book and self.stack
                and isinstance(self.stack[-1], screens.PausedScreen)):
            words_left = max(0, len(self.book.words) - self.idx)
            secs = (words_left / max(1, wpm)) * 60.0
            self._flash_text = "%s left" % render.fmt_duration_hms(secs)
            self._flash_until = time.monotonic() + 2.0
        else:
            self._flash_text = "%d wpm" % wpm
            self._flash_until = time.monotonic() + 1.0

    def _check_ota(self):
        """If an OTA is pending, wake, save, and push the update screen."""
        if not self.stack:
            return False
        if isinstance(self.stack[-1], screens.OtaScreen):
            return False
        if os.path.exists(config.OTA_FAILED):
            # A previous attempt already failed; never auto-retry, even
            # if `pending` is somehow still present (belt-and-braces —
            # see docs/plan_1/phase-0-ota-contracts.md §1).
            return False
        if not os.path.exists(config.OTA_PENDING):
            return False
        if self.book:
            self.save_position()
        else:
            self.state.save()
        self._last_input_at = time.monotonic()
        self._idle_state = "active"
        try:
            self.display.wake()
            self.display.contrast(self.theme.contrast)
        except Exception:
            pass
        self.push(screens.OtaScreen())
        return True

    def _ota_blocking(self):
        """True while an OTA update is in progress and must not be
        interrupted: the run loop swallows input and bypasses idle
        dim/off until the attempt concludes or fails. Once failed, this
        is False and OtaScreen is handled like any other screen — input
        dispatch dismisses it, and idle dim/off applies again (see
        docs/plan_1/phase-0-ota-contracts.md §2)."""
        top = self.stack[-1] if self.stack else None
        return isinstance(top, screens.OtaScreen) and not top._failed

    def save_position(self):
        if self.book:
            self.state.touch_book(self.book.path, position=self.idx)
        self.state.save()
        self.words_since_save = 0

    def open_book(self, path):
        self.book = books.Book.load(path)
        rec = self.state.book(path)
        self.idx = min(rec["position"], max(0, len(self.book.words) - 1))
        self.state.touch_book(path, total_words=len(self.book.words))
        self.state.last_book = path
        self.state.in_book = True
        self.state.save()
        self.push(screens.PausedScreen())

    def leave_to_library(self):
        self.save_position()
        if self.book and self._reading_since is not None:
            self._accumulate_reading_time()
        self.state.in_book = False
        self.state.save()
        self.book = None
        self.pop_to_root()

    def _accumulate_reading_time(self):
        elapsed = time.monotonic() - self._reading_since
        self._reading_since = None
        self.state.touch_book(
            self.book.path,
            time_read_secs=self.state.book(self.book.path)["time_read_secs"] + elapsed)

    def step_word(self):
        words, para_ends = self.book.words, self.book.para_ends
        start = self.idx
        chunk = [words[start]]
        wpm = self.state.settings["wpm"]
        total_delay = rsvp.word_delay(words[start], wpm, start in para_ends)
        end = start
        while total_delay < self.refresh_secs and end + 1 < len(words):
            end += 1
            chunk.append(words[end])
            total_delay += rsvp.word_delay(words[end], wpm, end in para_ends)

        t0 = time.monotonic()
        flash = self._flash_text if time.monotonic() < self._flash_until else None
        word_size = self.state.settings["word_size"]
        img = (render.word_frame(chunk[0], self.theme, flash=flash, word_size=word_size)
               if len(chunk) == 1
               else render.chunk_frame(chunk, self.theme, word_size=word_size))
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
            if self._reading_since is not None:
                self._accumulate_reading_time()
            self.push(screens.EndScreen())
            return
        remaining = total_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    # ---- main loop ----
    def _boot_stack(self):
        """Always start with Library as root; push Paused when resuming."""
        self.push(screens.LibraryScreen())
        library = books.scan_library()
        if (self.state.in_book and self.state.last_book
                and any(p == self.state.last_book for _, p in library)):
            self.book = books.Book.load(self.state.last_book)
            rec = self.state.book(self.state.last_book)
            self.idx = min(rec["position"], max(0, len(self.book.words) - 1))
            self.push(screens.PausedScreen())

    def run(self):
        self._boot_stack()
        while True:
            if self._check_ota():
                continue
            top = self.stack[-1]
            if self._ota_blocking():
                # In progress: swallow input, bypass idle, poll fast.
                # Once failed, fall through to ordinary handling below so
                # the screen can be dismissed and idle dim/off resumes.
                top.tick(self)
                time.sleep(0.15)
                continue
            reading = isinstance(top, screens.ReadingScreen)
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
                continue   # swallow the waking key press, per the control map
            self.stack[-1].handle(self, ev)


def _bail(app):
    """Save and blank the panel. Used by the SIGTERM handler and tests."""
    app.save_position() if app.book else app.state.save()
    try:
        app.display.sleep()
    except Exception:
        pass


def main(display=None):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    app = App(display=display)

    def bail(signum, frame):
        _bail(app)
        sys.exit(0)

    signal.signal(signal.SIGTERM, bail)
    try:
        app.run()
    except Exception:
        traceback.print_exc()
        try:
            app.display.show(render.message_frame(
                ["Error \u2014 restarting"], hint="journalctl -u rapid-reader"))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
