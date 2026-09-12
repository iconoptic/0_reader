"""Every Screen in the navigation stack. No hardware; calls render.py."""

import time

import books
import config
import render
import theme
from contracts import Screen


class ListScreen(Screen):
    """Shared plumbing for every list-shaped screen: an items() list, a
    selection index, K1=back (pop), K2=menu, press=activate(app, item),
    K3=context action if implemented, up/down move selection (with
    wraparound), left/right page by rows_visible. Subclasses override
    items(), header(), row_text(), activate(), and optionally
    context_action()."""

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
        return ("No items.",)

    def activate(self, app, item):
        pass

    def context_action(self, app, item):
        pass  # no-op by default; screens with a K3 action override this

    def on_enter(self, app):
        self.sel = min(self.sel, max(0, len(self.items(app)) - 1))
        self._scroll_into_view()

    def frame(self, app):
        items = self.items(app)
        rows = [self.row_text(app, it) for it in items]
        return render.list_frame(self.header(app), rows, self.sel, self.top,
                                  rows_visible=self.rows_visible,
                                  empty_lines=self.empty_lines(app))

    def handle(self, app, event):
        name, kind = event
        items = self.items(app)
        if name in ("up", "down") and kind in ("tap", "repeat") and items:
            delta = -1 if name == "up" else 1
            self.sel = (self.sel + delta) % len(items)
            self._scroll_into_view()
            app.redraw()
        elif name in ("left", "right") and kind in ("tap", "repeat") and items:
            delta = -self.rows_visible if name == "left" else self.rows_visible
            self.sel = max(0, min(len(items) - 1, self.sel + delta))
            self._scroll_into_view()
            app.redraw()
        elif name == "press" and kind == "tap" and items:
            self.activate(app, items[self.sel])
        elif name == "k3" and kind == "tap" and items:
            self.context_action(app, items[self.sel])
        elif name == "k2" and kind == "tap":
            app.push(BookMenuScreen())
        elif name == "k1" and kind == "tap":
            app.pop()

    def _scroll_into_view(self):
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.rows_visible:
            self.top = self.sel - self.rows_visible + 1


class LibraryScreen(ListScreen):
    """Root of the stack. K1 tap is a no-op (App.pop() refuses to pop the
    last item). K1 hold = power-off confirm; K2 = menu (Settings/System);
    K3 opens BookInfoScreen for the selected book."""

    def items(self, app):
        return books.sort_by_recency(
            books.scan_library(),
            {p: rec["last_opened"] for p, rec in app.state.books.items()})

    def header(self, app):
        return "LIBRARY"

    def row_text(self, app, item):
        return item[0]  # title

    def empty_lines(self, app):
        return ("No books found.", "Copy .txt/.epub to", config.BOOKS_DIR)

    def activate(self, app, item):
        _, path = item
        app.open_book(path)

    def context_action(self, app, item):
        title, path = item
        app.push(BookInfoScreen(title, path))

    def handle(self, app, event):
        name, kind = event
        if name == "k1" and kind == "hold":
            app.push(ConfirmScreen("Power off?", self._power_off))
            return
        super().handle(app, event)

    @staticmethod
    def _power_off(app):
        app.state.save()
        SystemScreen._run_privileged("poweroff")


class ReadingScreen(Screen):
    """No frame() of its own -- App.run()'s reading branch calls
    app.step_word() directly instead of stack[-1].frame() (see
    App.run()); this frame() only exists so nothing crashes if something
    calls it directly (e.g. a future App.redraw() right after push)."""

    def frame(self, app):
        word_size = app.state.settings["word_size"]
        return render.word_frame(app.book.words[app.idx], app.theme,
                                  word_size=word_size)

    def on_enter(self, app):
        app._reading_since = time.monotonic()

    def on_exit(self, app):
        if app._reading_since is not None:
            app._accumulate_reading_time()
        # Persist position on every leave from Reading (pause, menu, library,
        # end) so a crash while paused does not lose progress since the last
        # SAVE_EVERY_WORDS checkpoint.
        app.save_position()

    def handle(self, app, event):
        name, kind = event
        if name in ("press", "k3") and kind == "tap":
            app.replace_top(PausedScreen())
        elif name == "up" and kind == "tap":
            app.change_wpm(config.WPM_STEP)
        elif name == "down" and kind == "tap":
            app.change_wpm(-config.WPM_STEP)
        elif name == "left" and kind == "tap":
            app.jump_sentence(-1)
        elif name == "right" and kind == "tap":
            app.jump_sentence(+1)
        elif name == "k1" and kind == "tap":
            app.leave_to_library()
        elif name == "k2" and kind == "tap":
            app.push(BookMenuScreen())


class PausedScreen(Screen):
    def frame(self, app):
        flash = (app._flash_text
                 if app._flash_text and time.monotonic() < app._flash_until
                 else None)
        return render.paused_frame(
            app.book.title, app.book.words, app.idx,
            app.sentence_start(app.idx), app.state.settings["wpm"],
            min(1.0, app.idx / max(1, len(app.book.words))), app.theme,
            flash=flash)

    def handle(self, app, event):
        name, kind = event
        if name in ("press", "k3") and kind == "tap":
            app.replace_top(ReadingScreen())
        elif name == "up" and kind == "tap":
            app.change_wpm(config.WPM_STEP)
            app.redraw()
        elif name == "down" and kind == "tap":
            app.change_wpm(-config.WPM_STEP)
            app.redraw()
        elif name == "left" and kind == "tap":
            app.jump_sentence(-1)
        elif name == "right" and kind == "tap":
            app.jump_sentence(+1)
        elif name == "left" and kind in ("hold", "repeat"):
            app.jump_chapter(-1)
        elif name == "right" and kind in ("hold", "repeat"):
            app.jump_chapter(+1)
        elif name == "k1" and kind == "tap":
            app.leave_to_library()
        elif name == "k2" and kind == "tap":
            app.push(BookMenuScreen())


class BookMenuScreen(ListScreen):
    """K2 from Library (no book: Settings/System only) or from
    Reading/Paused/lists (full menu when a book is open). K2 is a no-op
    here so we do not stack duplicate menus."""

    _BOOK_ITEMS = ("Bookmark this page", "Chapters", "Bookmarks", "Book info",
                   "Settings", "System", "Save & close book")
    _NO_BOOK_ITEMS = ("Settings", "System")

    def items(self, app):
        return list(self._BOOK_ITEMS if app.book else self._NO_BOOK_ITEMS)

    def header(self, app):
        return "MENU"

    def handle(self, app, event):
        name, kind = event
        if name == "k2" and kind == "tap":
            return
        super().handle(app, event)

    def activate(self, app, item):
        if item == "Bookmark this page":
            app.state.add_bookmark(app.book.path, app.idx)
            app.state.save()
            app.pop()
        elif item == "Save & close book":
            app.leave_to_library()
        elif item == "Chapters":
            app.push(ChaptersScreen())
        elif item == "Bookmarks":
            app.push(BookmarksScreen())
        elif item == "Book info":
            app.push(BookInfoScreen(app.book.title, app.book.path))
        elif item == "Settings":
            app.push(SettingsScreen())
        elif item == "System":
            app.push(SystemScreen())


class EndScreen(Screen):
    def frame(self, app):
        return render.end_frame(app.book.title)

    def handle(self, app, event):
        # Match leave_to_library(): clear the in-memory book so Library K2
        # shows the reduced Settings/System menu (position already saved).
        # pop_to_root always lands on LibraryScreen even if resume left no
        # library under this End/Reading stack.
        app.book = None
        app.pop_to_root()


class MessageScreen(Screen):
    """Centred text; K1 pops (stable Back role). Reused by System/Settings
    for read-only info and by errors."""

    def __init__(self, lines, hint="k1: back"):
        self.lines = lines
        self.hint = hint

    def frame(self, app):
        return render.message_frame(self.lines, hint=self.hint)

    def handle(self, app, event):
        name, kind = event
        if name == "k1" and kind == "tap":
            app.pop()


class ConfirmScreen(Screen):
    """Generic yes/no dialog. `on_yes(app)` runs after this screen is
    popped on yes. K3 = yes; K1 = no; other keys ignored."""

    def __init__(self, text, on_yes, yes_hint="K3: yes", no_hint="K1: no"):
        self.text = text
        self.on_yes = on_yes
        self.yes_hint = yes_hint
        self.no_hint = no_hint

    def frame(self, app):
        return render.confirm_frame(self.text, self.yes_hint, self.no_hint)

    def handle(self, app, event):
        name, kind = event
        if name == "k3" and kind == "tap":
            app.pop()
            self.on_yes(app)
        elif name == "k1" and kind == "tap":
            app.pop()


class ChaptersScreen(ListScreen):
    def items(self, app):
        return list(range(len(app.book.chapter_starts)))

    def header(self, app):
        return "CHAPTERS"

    def row_text(self, app, item):
        return (app.book.chapter_title(app.book.chapter_starts[item])
                or "Chapter %d" % (item + 1))

    def empty_lines(self, app):
        return ("No chapters detected", "in this book.")

    def activate(self, app, item):
        app.idx = app.book.chapter_starts[item]
        app.pop_to(PausedScreen)


class BookmarksScreen(ListScreen):
    def items(self, app):
        return app.state.book(app.book.path)["bookmarks"]

    def header(self, app):
        return "BOOKMARKS"

    def row_text(self, app, item):
        total = max(1, len(app.book.words))
        return "%d%%  (word %d)" % (int(100 * item / total), item)

    def empty_lines(self, app):
        return ("No bookmarks yet.", "Menu > Bookmark this page")

    def activate(self, app, item):
        app.idx = item
        app.pop_to(PausedScreen)

    def context_action(self, app, item):
        def _do_delete(app):
            app.state.remove_bookmark(app.book.path, item)
            app.state.save()
        app.push(ConfirmScreen("Delete this bookmark?", _do_delete))


class BookInfoScreen(Screen):
    def __init__(self, title, path):
        self.title = title
        self.path = path

    def frame(self, app):
        import os
        rec = app.state.book(self.path)
        ext = os.path.splitext(self.path)[1]
        wpm = app.state.settings["wpm"]
        return render.info_frame(self.title, ext, rec["position"],
                                  rec["total_words"], wpm,
                                  rec["time_read_secs"])

    def handle(self, app, event):
        name, kind = event
        if name == "k1" and kind == "tap":
            app.pop()


_WORD_SIZES = ("small", "medium", "large")
_PIVOT_STYLES = ("ticks", "underline", "box", "bold")


class SettingsScreen(ListScreen):
    _ITEMS = ("word_size", "pivot_style", "theme", "display")
    _LABELS = {"word_size": "Word size", "pivot_style": "Pivot style",
               "theme": "Theme", "display": "Display"}

    def items(self, app):
        return list(self._ITEMS)

    def header(self, app):
        return "SETTINGS"

    def row_text(self, app, item):
        s = app.state.settings
        if item == "word_size":
            return "Word size: %s" % s["word_size"]
        if item == "pivot_style":
            return "Pivot style: %s" % s["pivot_style"]
        if item == "theme":
            return "Theme: %s" % app.theme.name
        return "Display"

    def activate(self, app, item):
        from dataclasses import replace
        s = app.state.settings
        if item == "word_size":
            i = (_WORD_SIZES.index(s["word_size"]) + 1) % len(_WORD_SIZES)
            s["word_size"] = _WORD_SIZES[i]
            app.state.save()
            app.redraw()
        elif item == "pivot_style":
            i = (_PIVOT_STYLES.index(s["pivot_style"]) + 1) % len(_PIVOT_STYLES)
            s["pivot_style"] = _PIVOT_STYLES[i]
            app.theme = replace(app.theme, pivot_style=s["pivot_style"])
            app.state.save()
            app.redraw()
        elif item == "theme":
            app.push(ThemesScreen())
        elif item == "display":
            app.push(DisplaySettingsScreen())


class ThemesScreen(ListScreen):
    def items(self, app):
        return list(theme.THEMES)   # keys: "night","paper","focus","dim","mono"

    def header(self, app):
        return "THEME"

    def row_text(self, app, item):
        mark = " *" if item == app.state.settings["theme"] else ""
        return theme.THEMES[item].name + mark

    def activate(self, app, item):
        from dataclasses import replace
        app.apply_theme(item)
        app.theme = replace(app.theme, pivot_style=app.state.settings["pivot_style"])
        app.pop()


class DisplaySettingsScreen(Screen):
    """Session-only contrast nudge (not persisted -- there is no
    `contrast` key in config.SETTINGS_DEFAULTS/state's schema; adding one
    is out of scope here, see the note in phase-0-contracts.md's schema
    if a later pass wants to persist this). Resets to the active theme's
    contrast on the next theme change or app restart."""

    STEP = 0x10

    def __init__(self):
        self._value = None

    def on_enter(self, app):
        if self._value is None:
            self._value = app.theme.contrast

    def frame(self, app):
        return render.message_frame(
            ["Contrast: %d" % self._value],
            hint="up/down adjust    k1 back")

    def handle(self, app, event):
        name, kind = event
        if name == "up" and kind in ("tap", "repeat"):
            self._value = min(0xFF, self._value + self.STEP)
            app.display.contrast(self._value)
            app.redraw()
        elif name == "down" and kind in ("tap", "repeat"):
            self._value = max(0x00, self._value - self.STEP)
            app.display.contrast(self._value)
            app.redraw()
        elif name == "k1" and kind == "tap":
            # Keep session nudge; not persisted across theme change / restart.
            app.pop()


class SystemScreen(ListScreen):
    _ITEMS = ("IP address", "Disk free", "Version", "Screen test",
              "Reboot", "Power off")

    def items(self, app):
        return list(self._ITEMS)

    def header(self, app):
        return "SYSTEM"

    def activate(self, app, item):
        import config
        if item == "IP address":
            app.push(MessageScreen([self._ip_address()]))
        elif item == "Disk free":
            app.push(MessageScreen([self._disk_free(config.BOOKS_DIR)]))
        elif item == "Version":
            app.push(MessageScreen([getattr(config, "VERSION", "dev")]))
        elif item == "Screen test":
            app.push(ScreenTestScreen())
        elif item == "Reboot":
            app.push(ConfirmScreen("Reboot now?", self._reboot))
        elif item == "Power off":
            app.push(ConfirmScreen("Power off now?", self._power_off))

    @staticmethod
    def _ip_address():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "no network"
        finally:
            s.close()

    @staticmethod
    def _disk_free(path):
        import os
        st = os.statvfs(path)
        free_mb = st.f_bavail * st.f_frsize / (1024 * 1024)
        return "%.0f MB free" % free_mb

    @staticmethod
    def _reboot(app):
        SystemScreen._run_privileged("reboot")

    @staticmethod
    def _power_off(app):
        app.state.save()
        SystemScreen._run_privileged("poweroff")

    @staticmethod
    def _run_privileged(cmd):
        import os
        import subprocess
        argv = [cmd] if os.geteuid() == 0 else ["sudo", "-n", cmd]
        subprocess.call(argv)


class ScreenTestScreen(Screen):
    """Full-screen black/white toggle for spotting stuck OLED pixels."""

    def __init__(self):
        self._ink = True  # True = all pixels on (white)

    def frame(self, app):
        from PIL import Image
        fill = 255 if self._ink else 0
        return Image.new("L", (config.OLED_W, config.OLED_H), fill)

    def handle(self, app, event):
        name, kind = event
        if name == "k1" and kind == "tap":
            app.pop()
        elif name in ("press", "up", "down") and kind == "tap":
            self._ink = not self._ink
            app.redraw()



# Stage names the helper writes to config.OTA_PROGRESS ("<n>/<total>
# <stage>"), mapped to the label shown on the progress screen. See
# docs/plan_1/phase-0-ota-contracts.md §5 — this is the full stage list,
# in order; STAGE_TOTAL must match the helper's own count.
_OTA_STAGE_LABELS = {
    "verifying": "Verifying...",
    "copying": "Copying...",
    "committing": "Installing...",
    "restarting": "Restarting...",
}


def _parse_ota_progress(text):
    """Parse one "<current>/<total> <stage>" line into (fraction, label).
    Returns None on anything unparseable, so a torn read (helper mid
    rewrite) or a stage name we don't recognize falls back to the
    indeterminate label rather than showing a bogus fraction."""
    try:
        counts, stage = text.split(None, 1)
        current, total = counts.split("/", 1)
        current, total = int(current), int(total)
    except (ValueError, AttributeError):
        return None
    label = _OTA_STAGE_LABELS.get(stage.strip())
    if label is None or total <= 0:
        return None
    return max(0.0, min(1.0, current / total)), label


class OtaScreen(Screen):
    """Update UI: non-dismissible while applying, dismissible after a
    genuine failure. `_concluded` means the apply attempt is over
    (success or failure) and `tick` has nothing left to do; `_failed`
    means it specifically failed, which is what gates dismissal, idle
    handling, and the on-disk failure marker (see
    docs/plan_1/phase-0-ota-contracts.md §§1-2).

    Progress is read from config.OTA_PROGRESS, written by the helper as
    it moves through real stages (§5) — never a synthetic animation.
    The helper runs under subprocess.Popen so `tick` returns promptly on
    the main loop's 0.15s OTA cadence instead of blocking it for the
    whole apply; config.OTA_TIMEOUT_SECS bounds how long a wedged helper
    can hold this non-dismissible screen before we kill it and fail.
    """

    _KILL_GRACE_SECS = 5.0

    def __init__(self):
        self._fraction = 0.0
        self._label = "Updating..."
        self._phase = "boot"  # boot -> spawned -> concluded
        self._concluded = False
        self._failed = False
        self._proc = None
        self._spawned_at = None
        self._killed_at = None

    def frame(self, app):
        return render.progress_frame(self._fraction, self._label)

    def handle(self, app, event):
        name, kind = event
        if self._failed and name == "k1" and kind == "tap":
            app.pop_to_root()
            return
        # Otherwise swallow all input: in-progress must not be
        # interrupted, and a concluded-but-not-yet-restarted success has
        # nothing useful for K1/K2/K3 to do before the service restarts.

    def tick(self, app):
        if self._concluded:
            return
        if self._phase == "boot":
            self._spawn(app)
            return
        if time.monotonic() - self._spawned_at >= config.OTA_TIMEOUT_SECS:
            self._escalate(app)
            return
        rc = self._proc.poll()
        if rc is None:
            self._refresh_progress(app)
            return
        if rc == 0:
            # Successful apply restarts the service (SIGTERM). If we are
            # still here, the restart just hasn't landed yet — this is
            # not a failure.
            self._concluded = True
            self._fraction = 1.0
            self._label = "Restarting..."
            app.redraw()
            return
        self._fail(app, "exit %d" % rc)

    def _spawn(self, app):
        import os
        import subprocess
        # Clear `pending` immediately before invoking the helper: a
        # crashed, killed, or never-started helper must not leave the
        # device re-entering this screen on every boot (F1; see
        # docs/plan_1/phase-0-ota-contracts.md §1).
        try:
            os.remove(config.OTA_PENDING)
        except OSError:
            pass
        argv = ([config.OTA_APPLY] if os.geteuid() == 0
                else ["sudo", "-n", config.OTA_APPLY])
        try:
            self._proc = subprocess.Popen(argv)
        except OSError as exc:
            self._fail(app, "spawn error: %s" % exc)
            return
        self._spawned_at = time.monotonic()
        self._phase = "spawned"
        self._refresh_progress(app)

    def _refresh_progress(self, app):
        fraction, label = 0.0, "Updating..."
        try:
            with open(config.OTA_PROGRESS) as f:
                parsed = _parse_ota_progress(f.read())
        except OSError:
            parsed = None
        if parsed is not None:
            fraction, label = parsed
        self._fraction, self._label = fraction, label
        app.redraw()

    def _escalate(self, app):
        """Past config.OTA_TIMEOUT_SECS with the helper still running:
        SIGTERM, give it _KILL_GRACE_SECS to exit, then SIGKILL. Either
        way this attempt ends as a timeout failure — a helper that
        ignores SIGTERM has already gone far enough wrong that letting
        it keep running is not a reasonable third option."""
        if self._killed_at is None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._killed_at = time.monotonic()
            self._label = "Update timed out, stopping..."
            app.redraw()
            return
        if self._proc.poll() is not None:
            self._fail(app, "timeout")
            return
        if time.monotonic() - self._killed_at >= self._KILL_GRACE_SECS:
            try:
                self._proc.kill()
                self._proc.wait()
            except OSError:
                pass
            self._fail(app, "timeout")

    def _fail(self, app, reason):
        """Mark this attempt as genuinely failed: dismissible, subject to
        idle dim/off again, and recorded on disk so a reboot before the
        next host sync does not re-enter this screen."""
        import os
        self._concluded = True
        self._failed = True
        self._fraction = 1.0
        self._label = "Update failed (%s)" % reason
        try:
            os.makedirs(config.OTA_DIR, exist_ok=True)
            with open(config.OTA_FAILED, "w") as f:
                f.write("%s %s\n" % (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    reason))
        except OSError:
            pass
        app.redraw()
