#!/usr/bin/env python3
"""Rapid Reader: RSVP speed reader for Pi Zero W + Adafruit 2.13" e-ink bonnet.

Controls (buttons 5 and 6 on the bonnet):

  Library:  5 tap        move down
            5 double     move up
            6 tap        open book (resumes where you left off)
            6 double     rescan library
            5 hold       power-off prompt

  Reading:  6 tap        play / pause
            5 tap        back one sentence
            5 double     slower (-25 wpm)
            6 double     faster (+25 wpm)
            6 triple     forward one sentence
            5 hold       save & back to library

  Paused:   6 tap        play
            5 tap        back one sentence
            5 double     previous chapter (if detected)
            6 double     next chapter (if detected)
            6 triple     forward one sentence
            5 hold       save & back to library
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

try:
    from epd import EPD
except ImportError:  # no spidev/gpiozero on this machine (tests, dev box)
    EPD = None

MENU, READING, PAUSED, CONFIRM_OFF, END = range(5)


class State:
    def __init__(self):
        self.wpm = config.DEFAULT_WPM
        self.positions = {}
        self.last_book = None
        self.in_book = False
        try:
            with open(config.STATE_FILE) as f:
                data = json.load(f)
            self.wpm = int(data.get("wpm", self.wpm))
            self.positions = dict(data.get("positions", {}))
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
                           "last_book": self.last_book,
                           "in_book": self.in_book}, f)
            os.replace(tmp, config.STATE_FILE)
        except OSError:
            traceback.print_exc()


class App:
    def __init__(self, display=None, button_cls=None):
        # display/button_cls are injectable so the app logic can run under
        # test (or on a dev box) without SPI/GPIO hardware
        self.epd = display if display is not None else EPD()
        button_cls = button_cls or buttons.TapButton
        # visible as soon as hardware init succeeds, in case anything below
        # this crash-loops (e.g. group membership not applied yet on first boot)
        self.epd.display_full(render.message(["Rapid Reader", "booting\u2026"]))
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
        self.btn5 = button_cls(config.PIN_BTN_5,
                               lambda n: self.events.put(("5", n)),
                               lambda: self.events.put(("hold5", 0)))
        self.btn6 = button_cls(config.PIN_BTN_6,
                               lambda n: self.events.put(("6", n)),
                               lambda: self.events.put(("hold6", 0)))

    # ---- helpers ----------------------------------------------------

    def progress(self):
        if not self.book or not self.book.words:
            return 0.0
        return min(1.0, self.idx / len(self.book.words))

    def show_menu(self, note=None, full=True):
        self.mode = MENU
        titles = [t for t, _ in self.library]
        if self.sel >= len(titles):
            self.sel = max(0, len(titles) - 1)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + render.MENU_ROWS:
            self.top = self.sel - render.MENU_ROWS + 1
        img = render.menu(titles, self.sel, self.top, note)
        (self.epd.display_full if full else self.epd.display_partial)(img)

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
        self.epd.display_full(render.message(["Loading\u2026", title[:24]]))
        try:
            self.book = books.Book.load(path)
        except Exception:
            traceback.print_exc()
            self.show_menu(note="load failed")
            return
        if not self.book.words:
            self.show_menu(note="empty book")
            return
        self.idx = min(self.state.positions.get(path, 0),
                       len(self.book.words) - 1)
        self.state.last_book = path
        self.state.in_book = True
        self.show_paused(full=True)

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

    def show_paused(self, full=False):
        self.mode = PAUSED
        img = render.paused(self.book.title, self.book.words, self.idx,
                            self.sentence_start(self.idx), self.state.wpm,
                            self.progress())
        (self.epd.display_full if full else self.epd.display_partial)(img)
        self.save_position()

    def leave_to_menu(self):
        self.state.in_book = False
        self.save_position()
        self.book = None
        self.rescan()
        self.show_menu()

    # ---- playback ---------------------------------------------------

    def step_word(self):
        words, para_ends = self.book.words, self.book.para_ends
        start = self.idx
        chunk = [words[start]]
        total_delay = rsvp.word_delay(words[start], self.state.wpm,
                                      start in para_ends)
        end = start
        # pull in more words if the panel can't refresh fast enough to keep
        # up with the requested wpm, so the average pace still matches it
        while total_delay < self.refresh_secs and end + 1 < len(words):
            end += 1
            chunk.append(words[end])
            total_delay += rsvp.word_delay(words[end], self.state.wpm,
                                           end in para_ends)

        t0 = time.monotonic()
        img = (render.word_frame(chunk[0], self.state.wpm, self.progress())
              if len(chunk) == 1 else
              render.chunk_frame(chunk, self.state.wpm, self.progress()))
        self.epd.display_partial(img)
        elapsed = time.monotonic() - t0
        self.refresh_secs = 0.8 * self.refresh_secs + 0.2 * elapsed

        self.idx = end + 1
        self.words_since_save += len(chunk)
        if self.words_since_save >= config.SAVE_EVERY_WORDS:
            self.save_position()
        if self.idx >= len(words):
            self.mode = END
            self.idx = len(words) - 1
            self.state.in_book = False
            self.save_position()
            self.epd.display_full(render.the_end(self.book.title))
            return
        remaining = total_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    # ---- event handling ----------------------------------------------

    def handle(self, ev):
        kind, n = ev
        if self.mode == MENU:
            if kind == "5" and n == 1 and self.library:
                self.sel = (self.sel + 1) % len(self.library)
                self.show_menu(full=False)
            elif kind == "5" and n >= 2 and self.library:
                self.sel = (self.sel - 1) % len(self.library)
                self.show_menu(full=False)
            elif kind == "6" and n == 1:
                self.open_book()
            elif kind == "6" and n >= 2:
                self.rescan()
                self.show_menu(note="rescanned")
            elif kind == "hold5":
                self.mode = CONFIRM_OFF
                self.epd.display_full(render.confirm_power())

        elif self.mode == CONFIRM_OFF:
            if kind == "6":
                self.epd.display_full(
                    render.message(["Powered off", "Safe to unplug"]))
                self.state.save()
                self.epd.sleep()
                if os.geteuid() == 0:
                    subprocess.call(["poweroff"])
                else:
                    subprocess.call(["sudo", "-n", "poweroff"])
            else:
                self.show_menu()

        elif self.mode == READING:
            if kind == "6" and n == 1:
                self.show_paused(full=True)
            elif kind == "6" and n == 2:
                self.change_wpm(config.WPM_STEP)
            elif kind == "6" and n >= 3:
                self.jump_sentence(+1)
            elif kind == "5" and n == 1:
                self.jump_sentence(-1)
            elif kind == "5" and n == 2:
                self.change_wpm(-config.WPM_STEP)
            elif kind == "hold5":
                self.leave_to_menu()

        elif self.mode == PAUSED:
            if kind == "6" and n == 1:
                self.mode = READING
            elif kind == "6" and n == 2:
                self.jump_chapter(+1)
                self.show_paused()
            elif kind == "6" and n >= 3:
                self.jump_sentence(+1)
                self.show_paused()
            elif kind == "5" and n == 1:
                self.jump_sentence(-1)
                self.show_paused()
            elif kind == "5" and n == 2:
                self.jump_chapter(-1)
                self.show_paused()
            elif kind == "hold5":
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


def main():
    os.makedirs(config.STATE_DIR, exist_ok=True)
    app = App()

    def bail(signum, frame):
        app.save_position() if app.book else app.state.save()
        sys.exit(0)

    signal.signal(signal.SIGTERM, bail)
    try:
        app.run()
    except Exception:
        traceback.print_exc()
        try:
            app.epd.display_full(render.message(
                ["Error \u2014 restarting", "see: journalctl -u rapid-reader"]))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
