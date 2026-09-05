#!/usr/bin/env python3
"""Rapid Reader: RSVP speed reader for a Pi Zero W + Waveshare Zero LCD HAT (A).

Three screens: the centre 240x240 panel carries the content (words while
reading, the library, the paused sentence); the two portrait 80x160 side
panels carry peripheral cards -- progress on the left, speed or key hints
on the right -- that only redraw when their content changes.

Controls (K1 is the upper key, K2 the lower one):

  Library:  K2 tap        move down
            K2 double     move up
            K1 tap        open book (resumes where you left off)
            K1 double     rescan library
            K2 hold       power-off prompt

  Reading:  K1 tap        pause
            K2 tap        back one sentence
            K2 double     slower (-25 wpm)
            K1 double     faster (+25 wpm)
            K1 triple     forward one sentence
            K2 hold       save & back to library

  Paused:   K1 tap        play
            K2 tap        back one sentence
            K2 double     previous chapter (if detected)
            K1 double     next chapter (if detected)
            K1 triple     forward one sentence
            K2 hold       save & back to library

Normally started via boot.py (which shows the splash first); running this
file directly also works.
"""

import bisect
import json
import os
import queue
import signal
import subprocess
import sys
import time
import traceback

import books
import buttons
import config
import render
import rsvp
from display import open_display

MENU, READING, PAUSED, CONFIRM_OFF, END = range(5)


class State:
    def __init__(self):
        self.wpm = config.DEFAULT_WPM
        self.positions = {}
        self.totals = {}
        self.last_book = None
        self.in_book = False
        try:
            with open(config.STATE_FILE) as f:
                data = json.load(f)
            self.wpm = int(data.get("wpm", self.wpm))
            self.positions = dict(data.get("positions", {}))
            self.totals = dict(data.get("totals", {}))
            self.last_book = data.get("last_book")
            self.in_book = bool(data.get("in_book", False))
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(config.STATE_DIR, exist_ok=True)
            tmp = config.STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"wpm": self.wpm, "positions": self.positions,
                           "totals": self.totals,
                           "last_book": self.last_book,
                           "in_book": self.in_book}, f)
            os.replace(tmp, config.STATE_FILE)
        except OSError:
            traceback.print_exc()


class App:
    def __init__(self, display=None, button_cls=None):
        # display/button_cls are injectable so the app logic can run under
        # test (or on a dev box) without SPI/GPIO hardware
        self.display = display if display is not None else open_display()
        button_cls = button_cls or buttons.TapButton
        self.events = queue.Queue()
        self.state = State()
        self.mode = MENU
        self.library = []
        self.sel = 0
        self.top = 0
        self.book = None
        self.idx = 0
        self.words_since_save = 0
        self.refresh_secs = config.PANEL_REFRESH_SECS
        self._side_keys = {}
        self._sides_dim = None
        self.key1 = button_cls(config.PIN_KEY1,
                               lambda n: self.events.put(("A", n)),
                               lambda: self.events.put(("holdA", 0)))
        self.key2 = button_cls(config.PIN_KEY2,
                               lambda n: self.events.put(("B", n)),
                               lambda: self.events.put(("holdB", 0)))

    # ---- helpers ----------------------------------------------------

    def progress(self):
        if not self.book or not self.book.words:
            return 0.0
        return min(1.0, self.idx / len(self.book.words))

    def chapter_pos(self):
        """(current chapter number, chapter count) or None if undetected."""
        chapters = self.book.chapter_starts if self.book else []
        if not chapters:
            return None
        return (bisect.bisect_right(chapters, self.idx), len(chapters))

    def _side(self, which, key, make):
        """Redraw a side card only when its content key changed."""
        if self._side_keys.get(which) != key:
            self._side_keys[which] = key
            self.display.show(**{which: make()})

    def _set_mode(self, mode):
        self.mode = mode
        dim = mode == READING
        if dim != self._sides_dim:
            self._sides_dim = dim
            self.display.backlight(
                sides=config.BL_SIDE_READING if dim else config.BL_SIDE)

    def _progress_side(self):
        words = len(self.book.words)
        remaining = words - self.idx
        wpm = self.state.wpm
        chapter = self.chapter_pos()
        key = ("progress", int(self.progress() * 100), int(remaining / wpm),
               chapter)
        self._side("left", key, lambda: render.progress_card(
            self.progress(), remaining, wpm, chapter))

    def show_menu(self, note=None):
        self._set_mode(MENU)
        titles = [t for t, _ in self.library]
        if self.sel >= len(titles):
            self.sel = max(0, len(titles) - 1)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + render.MENU_ROWS:
            self.top = self.sel - render.MENU_ROWS + 1
        self.display.show(main=render.menu(titles, self.sel, self.top, note))
        if titles:
            title, path = self.library[self.sel]
            ext = os.path.splitext(path)[1]
            pos = self.state.positions.get(path)
            total = self.state.totals.get(path)
            self._side("left", ("book", path, pos, total, self.state.wpm),
                       lambda: render.book_card(title, ext, pos, total,
                                                self.state.wpm))
        else:
            self._side("left", ("blank",), render.blank_side)
        self._side("right", ("hints", "menu"), lambda: render.hints("menu"))

    def rescan(self):
        self.library = books.scan_library()
        if self.state.last_book:
            for i, (_, p) in enumerate(self.library):
                if p == self.state.last_book:
                    self.sel = i
                    break

    def open_book(self):
        if not self.library:
            return
        title, path = self.library[self.sel]
        self.display.show(main=render.message([title], big="Loading\u2026"))
        try:
            self.book = books.Book.load(path)
        except Exception:
            traceback.print_exc()
            self.show_menu(note="load failed")
            return
        if not self.book.words:
            self.book = None
            self.show_menu(note="empty book")
            return
        self.idx = min(self.state.positions.get(path, 0),
                       len(self.book.words) - 1)
        self.state.totals[path] = len(self.book.words)
        self.state.last_book = path
        self.state.in_book = True
        self.show_paused()

    def save_position(self):
        if self.book:
            self.state.positions[self.book.path] = self.idx
        self.state.save()
        self.words_since_save = 0

    def sentence_start(self, idx):
        starts = self.book.sentence_starts
        i = bisect.bisect_right(starts, idx) - 1
        return starts[max(0, i)]

    def jump_sentence(self, direction):
        starts = self.book.sentence_starts
        cur = self.sentence_start(self.idx)
        if direction < 0:
            # if we just started this sentence, go to the previous one
            if self.idx - cur < 3:
                i = bisect.bisect_left(starts, cur) - 1
                cur = starts[max(0, i)]
            self.idx = cur
        else:
            i = bisect.bisect_right(starts, self.idx)
            self.idx = starts[i] if i < len(starts) else len(self.book.words) - 1

    def change_wpm(self, delta):
        self.state.wpm = max(config.MIN_WPM,
                             min(config.MAX_WPM, self.state.wpm + delta))
        self.state.save()
        if self.mode == READING:
            self._side("right", ("speed", self.state.wpm),
                       lambda: render.speed_card(self.state.wpm))

    def jump_chapter(self, direction):
        chapters = self.book.chapter_starts
        if not chapters:
            return
        i = bisect.bisect_right(chapters, self.idx) - 1
        if direction < 0:
            # if we're only a few words into this chapter, go to the one before it
            if i >= 0 and self.idx - chapters[i] < 5:
                i -= 1
            self.idx = chapters[i] if i >= 0 else 0
        else:
            j = bisect.bisect_right(chapters, self.idx)
            self.idx = (chapters[j] if j < len(chapters)
                        else len(self.book.words) - 1)

    def show_paused(self):
        self._set_mode(PAUSED)
        self.display.show(main=render.paused(
            self.book.title, self.book.words, self.idx,
            self.sentence_start(self.idx), self.state.wpm, self.progress()))
        self._progress_side()
        self._side("right", ("hints", "paused"), lambda: render.hints("paused"))
        self.save_position()

    def start_reading(self):
        self._set_mode(READING)
        self._side("right", ("speed", self.state.wpm),
                   lambda: render.speed_card(self.state.wpm))

    def leave_to_menu(self):
        self.state.in_book = False
        self.save_position()
        self.book = None
        self.rescan()
        self.show_menu()

    def show_end(self):
        self._set_mode(END)
        self.display.show(main=render.the_end(self.book.title))
        self._progress_side()
        self._side("right", ("hints", "end"), lambda: render.hints("end"))

    def power_off(self):
        self.display.show(main=render.message(["Powering off\u2026"],
                                              hint="safe to unplug when dark"),
                          left=render.blank_side(), right=render.blank_side())
        self._side_keys.clear()
        self.state.save()
        argv = ["poweroff"] if os.geteuid() == 0 else ["sudo", "-n", "poweroff"]
        rc = subprocess.call(argv)
        if rc != 0:
            self.show_menu(note="power-off failed")

    # ---- playback ---------------------------------------------------

    def step_word(self):
        words, para_ends = self.book.words, self.book.para_ends
        start = self.idx
        chunk = [words[start]]
        total_delay = rsvp.word_delay(words[start], self.state.wpm,
                                      start in para_ends)
        end = start
        # pull in more words if a frame takes longer than one word's slot,
        # so the average pace still matches the requested wpm
        while total_delay < self.refresh_secs and end + 1 < len(words):
            end += 1
            chunk.append(words[end])
            total_delay += rsvp.word_delay(words[end], self.state.wpm,
                                           end in para_ends)

        t0 = time.monotonic()
        img = (render.word_frame(chunk[0]) if len(chunk) == 1
               else render.chunk_frame(chunk))
        self.display.show(main=img)
        self._progress_side()
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
            self.show_end()
            return
        remaining = total_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    # ---- event handling ----------------------------------------------

    def handle(self, ev):
        kind, n = ev
        if self.mode == MENU:
            if kind == "B" and n == 1 and self.library:
                self.sel = (self.sel + 1) % len(self.library)
                self.show_menu()
            elif kind == "B" and n >= 2 and self.library:
                self.sel = (self.sel - 1) % len(self.library)
                self.show_menu()
            elif kind == "A" and n == 1:
                self.open_book()
            elif kind == "A" and n >= 2:
                self.rescan()
                self.show_menu(note="rescanned")
            elif kind == "holdB":
                self._set_mode(CONFIRM_OFF)
                self.display.show(main=render.confirm_power())
                self._side("left", ("blank",), render.blank_side)
                self._side("right", ("hints", "confirm"),
                           lambda: render.hints("confirm"))

        elif self.mode == CONFIRM_OFF:
            if kind == "A":
                self.power_off()
            else:
                self.show_menu()

        elif self.mode == READING:
            if kind == "A" and n == 1:
                self.show_paused()
            elif kind == "A" and n == 2:
                self.change_wpm(config.WPM_STEP)
            elif kind == "A" and n >= 3:
                self.jump_sentence(+1)
            elif kind == "B" and n == 1:
                self.jump_sentence(-1)
            elif kind == "B" and n == 2:
                self.change_wpm(-config.WPM_STEP)
            elif kind == "holdB":
                self.leave_to_menu()

        elif self.mode == PAUSED:
            if kind == "A" and n == 1:
                self.start_reading()
            elif kind == "A" and n == 2:
                self.jump_chapter(+1)
                self.show_paused()
            elif kind == "A" and n >= 3:
                self.jump_sentence(+1)
                self.show_paused()
            elif kind == "B" and n == 1:
                self.jump_sentence(-1)
                self.show_paused()
            elif kind == "B" and n == 2:
                self.jump_chapter(-1)
                self.show_paused()
            elif kind == "holdB":
                self.leave_to_menu()

        elif self.mode == END:
            self.leave_to_menu()

    # ---- main loop ----------------------------------------------------

    def run(self):
        self.rescan()
        # resume exactly where the reader was powered off, paused
        if (self.state.in_book and self.state.last_book
                and any(p == self.state.last_book for _, p in self.library)):
            self.open_book()
        else:
            self.show_menu()
        while True:
            if self.mode == READING:
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    self.step_word()
                    continue
                self.handle(ev)
            else:
                ev = self.events.get()
                self.handle(ev)


def main(display=None):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    if display is None:
        display = open_display()
    app = App(display=display)

    def bail(signum, frame):
        app.save_position() if app.book else app.state.save()
        try:
            display.sleep()      # screens go dark as the system shuts down
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, bail)
    try:
        app.run()
    except Exception:
        traceback.print_exc()
        try:
            display.show(main=render.message(
                ["Error \u2014 restarting", "journalctl -u rapid-reader"]))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
