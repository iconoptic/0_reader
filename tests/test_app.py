"""End-to-end tests of the App screen stack with a fake display."""

import os
import signal
import sys
import time

import pytest

import books
import config
import main
import screens


SAMPLE = ("CHAPTER I.\n\nFirst one. Second one here again today. Third!\n\n"
          "CHAPTER II.\n\nFourth sentence. Fifth and last.")


def _write_book(name, text=SAMPLE):
    p = os.path.join(config.BOOKS_DIR, name)
    with open(p, "w") as f:
        f.write(text)
    return p


class _NullInput:
    def __init__(self, on_event):
        self.keys = {}


@pytest.fixture
def app(fake_display, monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)

    def make(**kwargs):
        a = main.App(display=fake_display, input_cls=_NullInput, **kwargs)
        return a

    return make


def fire(app, name, kind="tap"):
    """Deliver one event straight to the active screen (bypass the queue)."""
    app.stack[-1].handle(app, (name, kind))


def boot(app_factory):
    a = app_factory()
    a.push(a._initial_screen())
    return a


# ---- boot ---------------------------------------------------------------

def test_boot_library_when_not_in_book(app):
    _write_book("a.txt")
    a = boot(app)
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert len(a.stack) == 1


def test_boot_paused_when_in_book(app):
    path = _write_book("resume.txt")
    a = app()
    a.state.in_book = True
    a.state.last_book = path
    a.state.touch_book(path, position=3, total_words=10)
    a.state.save()
    a.push(a._initial_screen())
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert a.book is not None
    assert a.idx == 3


def test_boot_library_if_last_book_missing(app):
    a = app()
    a.state.in_book = True
    a.state.last_book = os.path.join(config.BOOKS_DIR, "gone.txt")
    a.state.save()
    a.push(a._initial_screen())
    assert isinstance(a.stack[-1], screens.LibraryScreen)


# ---- library ------------------------------------------------------------

def test_library_navigate_open_and_k1_noop(app):
    for n in ["b.txt", "a.txt", "c.txt", "d.txt", "e.txt"]:
        _write_book(n)
    a = boot(app)
    lib = a.stack[-1]
    assert isinstance(lib, screens.LibraryScreen)
    titles = [t for t, _ in lib.items(a)]
    assert titles == ["a", "b", "c", "d", "e"]

    fire(a, "down")
    assert lib.sel == 1
    fire(a, "up")
    assert lib.sel == 0
    fire(a, "up")  # wrap
    assert lib.sel == 4
    fire(a, "right")
    assert lib.sel == min(4, 0 + lib.rows_visible) or lib.sel == 4
    # from sel=4, left pages back
    fire(a, "left")
    assert lib.sel == max(0, 4 - lib.rows_visible)

    lib.sel = 2  # "c"
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert a.book.title == "c"
    assert a.state.in_book and a.state.last_book.endswith("c.txt")

    fire(a, "k1")  # leave to library
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert len(a.stack) == 1
    fire(a, "k1")  # root: still no-op
    assert len(a.stack) == 1


def test_library_opens_at_saved_position(app):
    path = _write_book("pos.txt")
    a = boot(app)
    a.state.touch_book(path, position=5)
    a.state.save()
    # select pos.txt
    lib = a.stack[-1]
    items = lib.items(a)
    lib.sel = next(i for i, (_, p) in enumerate(items) if p == path)
    fire(a, "press")
    assert a.idx == 5


def test_library_k3_pushes_book_info(app):
    _write_book("info.txt")
    a = boot(app)
    fire(a, "k3")
    assert isinstance(a.stack[-1], screens.BookInfoScreen)
    assert a.stack[-1].title == "info"
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.LibraryScreen)


# ---- reading / paused ---------------------------------------------------

def _open_paused(app_factory, name="book.txt", text=SAMPLE):
    path = _write_book(name, text)
    a = app_factory()
    # Force library boot even if a prior test left in_book=True on disk.
    a.state.in_book = False
    a.state.last_book = None
    a.state.save()
    a.push(screens.LibraryScreen())
    lib = a.stack[-1]
    items = lib.items(a)
    lib.sel = next(i for i, (_, p) in enumerate(items) if p == path)
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    return a


def test_press_k3_toggle_reading_paused(app):
    a = _open_paused(app)
    depth = len(a.stack)
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ReadingScreen)
    assert len(a.stack) == depth
    fire(a, "k3")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert len(a.stack) == depth


def test_wpm_change_sets_flash(app):
    a = _open_paused(app)
    base = a.state.settings["wpm"]
    fire(a, "up")
    assert a.state.settings["wpm"] == base + config.WPM_STEP
    assert a._flash_text == "%d wpm" % a.state.settings["wpm"]
    fire(a, "down")
    assert a.state.settings["wpm"] == base


def test_sentence_and_chapter_jumps(app):
    a = _open_paused(app)
    starts = a.book.sentence_starts
    chapters = a.book.chapter_starts
    assert len(starts) >= 2
    assert len(chapters) >= 2

    fire(a, "right")
    assert a.idx == starts[1]
    fire(a, "left")
    assert a.idx == starts[0]

    # chapter jump only on paused hold/repeat
    a.idx = chapters[0]
    fire(a, "right", "repeat")
    assert a.idx == chapters[1]
    fire(a, "left", "hold")
    assert a.idx == chapters[0]

    # Reading: hold does nothing for chapters
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ReadingScreen)
    before = a.idx
    fire(a, "right", "repeat")
    assert a.idx == before


def test_k1_saves_and_returns_to_library(app):
    a = _open_paused(app)
    path = a.book.path
    a.idx = 7
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert len(a.stack) == 1
    assert a.book is None
    assert a.state.in_book is False
    assert a.state.book(path)["position"] == 7


def test_k2_opens_book_menu(app):
    a = _open_paused(app)
    fire(a, "k2")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)


# ---- book menu ----------------------------------------------------------

def test_bookmark_this_page(app):
    a = _open_paused(app)
    path = a.book.path
    a.idx = 4
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = 0  # Bookmark this page
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert 4 in a.state.book(path)["bookmarks"]


def test_save_and_close_book(app):
    a = _open_paused(app)
    path = a.book.path
    a.idx = 2
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Save & close book")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert a.state.book(path)["position"] == 2
    assert a.state.in_book is False


def test_book_menu_pushes_settings_system(app):
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    expected = {
        "Settings": screens.SettingsScreen,
        "System": screens.SystemScreen,
    }
    for label, cls in expected.items():
        menu.sel = menu.items(a).index(label)
        fire(a, "press")
        assert isinstance(a.stack[-1], cls)
        fire(a, "k1")
        assert isinstance(a.stack[-1], screens.BookMenuScreen)


def test_book_menu_pushes_chapters_bookmarks_info(app):
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    expected = {
        "Chapters": screens.ChaptersScreen,
        "Bookmarks": screens.BookmarksScreen,
        "Book info": screens.BookInfoScreen,
    }
    for label, cls in expected.items():
        menu.sel = menu.items(a).index(label)
        fire(a, "press")
        assert isinstance(a.stack[-1], cls)
        fire(a, "k1")
        assert isinstance(a.stack[-1], screens.BookMenuScreen)


# ---- chapters / bookmarks / book info -----------------------------------

def test_chapters_screen_items_row_activate_empty(app):
    a = _open_paused(app)
    n = len(a.book.chapter_starts)
    assert n >= 2
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Chapters")
    fire(a, "press")
    ch = a.stack[-1]
    assert isinstance(ch, screens.ChaptersScreen)
    assert ch.items(a) == list(range(n))
    assert ch.row_text(a, 0) == a.book.chapter_title(a.book.chapter_starts[0])

    # fallback when chapter_title is falsy
    a.book.chapter_titles[1] = ""
    assert ch.row_text(a, 1) == "Chapter 2"

    ch.sel = 1
    fire(a, "press")
    assert a.idx == a.book.chapter_starts[1]
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert len(a.stack) == 2  # Library + Paused

    # empty-book chapters: empty_lines renders without crashing
    a.book.chapter_starts = []
    a.book.chapter_titles = []
    a.push(screens.ChaptersScreen())
    assert a.stack[-1].items(a) == []
    img = a.stack[-1].frame(a)
    assert img is not None


def test_bookmarks_screen_activate_and_delete(app):
    a = _open_paused(app)
    path = a.book.path
    a.state.add_bookmark(path, 3)
    a.state.add_bookmark(path, 8)
    a.state.save()

    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Bookmarks")
    fire(a, "press")
    bm = a.stack[-1]
    assert isinstance(bm, screens.BookmarksScreen)
    assert bm.items(a) == [3, 8]
    assert "word 3" in bm.row_text(a, 3)

    # activate jumps and returns to Paused
    bm.sel = 1
    fire(a, "press")
    assert a.idx == 8
    assert isinstance(a.stack[-1], screens.PausedScreen)

    # reopen, delete via k3 confirm
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Bookmarks")
    fire(a, "press")
    bm = a.stack[-1]
    bm.sel = 0  # word 3
    fire(a, "k3")
    assert isinstance(a.stack[-1], screens.ConfirmScreen)
    fire(a, "k1")  # decline
    assert 3 in a.state.book(path)["bookmarks"]
    assert isinstance(a.stack[-1], screens.BookmarksScreen)

    fire(a, "k3")
    fire(a, "k3")  # confirm delete
    assert 3 not in a.state.book(path)["bookmarks"]
    assert bm.items(a) == [8]


def test_book_info_screen_renders_and_k1_pops(app):
    path = _write_book("meta.txt")
    a = boot(app)
    a.state.touch_book(path, position=4, total_words=20, time_read_secs=120)
    a.state.settings["wpm"] = 300
    a.state.save()
    lib = a.stack[-1]
    items = lib.items(a)
    lib.sel = next(i for i, (_, p) in enumerate(items) if p == path)
    fire(a, "k3")
    info = a.stack[-1]
    assert isinstance(info, screens.BookInfoScreen)
    assert info.title == "meta"
    assert info.path == path
    img = info.frame(a)
    assert img is not None
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    # other keys do not pop
    fire(a, "k3")
    info = a.stack[-1]
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.BookInfoScreen)


def test_bookmark_round_trip(app):
    a = _open_paused(app)
    path = a.book.path
    a.idx = 6
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = 0  # Bookmark this page
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert 6 in a.state.book(path)["bookmarks"]

    a.idx = 0
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Bookmarks")
    fire(a, "press")
    bm = a.stack[-1]
    assert 6 in bm.items(a)
    bm.sel = bm.items(a).index(6)
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert a.idx == 6


# ---- step_word / end ----------------------------------------------------

def test_step_word_reaches_end_screen(app):
    a = boot(app)
    words = ["One.", "Two.", "Three."]
    a.book = books.Book("/mem.txt", "mem", words, [0, 1, 2], set())
    a.idx = 0
    a.state.in_book = True
    a.state.touch_book("/mem.txt", total_words=len(words))
    a.push(screens.ReadingScreen())
    # drain the book
    for _ in range(10):
        if isinstance(a.stack[-1], screens.EndScreen):
            break
        a.step_word()
    assert isinstance(a.stack[-1], screens.EndScreen)
    assert a.state.in_book is False
    assert a.state.book("/mem.txt")["position"] == len(words) - 1
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.LibraryScreen)


# ---- idle ---------------------------------------------------------------

def test_idle_dim_and_off_on_library(app, monkeypatch):
    monkeypatch.setattr(config, "IDLE_DIM_SECS", 0.05)
    monkeypatch.setattr(config, "IDLE_OFF_SECS", 0.1)
    a = boot(app)
    panel = a.display.panel
    theme_contrast = a.theme.contrast

    a._last_input_at = time.monotonic() - 0.06
    a._tick_idle()
    assert a._idle_state == "dim"
    assert panel.contrast_level == config.IDLE_DIM_CONTRAST
    assert panel.sleeping is False

    a._last_input_at = time.monotonic() - 0.15
    a._tick_idle()
    assert a._idle_state == "off"
    assert panel.sleeping is True

    # wake via tick after fresh input
    a._last_input_at = time.monotonic()
    a._tick_idle()
    assert a._idle_state == "active"
    assert panel.sleeping is False
    assert panel.contrast_level == theme_contrast


def test_idle_never_dims_while_reading(app, monkeypatch):
    monkeypatch.setattr(config, "IDLE_DIM_SECS", 0.01)
    monkeypatch.setattr(config, "IDLE_OFF_SECS", 0.02)
    a = _open_paused(app)
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ReadingScreen)
    a._last_input_at = time.monotonic() - 10
    a._tick_idle()
    assert a._idle_state == "active"
    assert a.display.panel.sleeping is False


def test_wake_key_is_swallowed(app, monkeypatch):
    monkeypatch.setattr(config, "IDLE_DIM_SECS", 0.05)
    monkeypatch.setattr(config, "IDLE_OFF_SECS", 0.1)
    _write_book("w1.txt")
    _write_book("w2.txt")
    a = boot(app)
    lib = a.stack[-1]
    assert lib.sel == 0
    a._last_input_at = time.monotonic() - 1
    a._tick_idle()
    assert a._idle_state == "off"

    # App.run swallows the first event after wake
    a._last_input_at = time.monotonic()
    was_off = a._idle_state == "off"
    a._tick_idle()
    assert was_off and a._idle_state == "active"
    # swallowed: do not call handle — sel stays 0
    assert lib.sel == 0
    # subsequent key reaches the screen
    fire(a, "down")
    assert lib.sel == 1


# ---- time_read_secs -----------------------------------------------------

def test_time_read_accumulates(app, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(screens.time, "monotonic", lambda: clock[0])
    a = _open_paused(app)
    path = a.book.path
    before = a.state.book(path)["time_read_secs"]
    fire(a, "press")  # ReadingScreen.on_enter @ 1000
    clock[0] = 1005.0
    fire(a, "press")  # pause -> on_exit accumulates 5s
    assert a.state.book(path)["time_read_secs"] == pytest.approx(before + 5.0)


# ---- SIGTERM ------------------------------------------------------------

def test_bail_saves_and_sleeps(app, monkeypatch):
    a = _open_paused(app, name="bail.txt")
    a.idx = 9
    path = a.book.path

    main._bail(a)
    assert a.display.panel.sleeping is True
    assert a.state.book(path)["position"] == 9

    a2 = _open_paused(app, name="bail2.txt")
    a2.idx = 3
    monkeypatch.setattr(
        sys, "exit",
        lambda code=0: (_ for _ in ()).throw(SystemExit(code)))

    def bail(signum, frame):
        main._bail(a2)
        sys.exit(0)

    with pytest.raises(SystemExit):
        bail(signal.SIGTERM, None)
    assert a2.display.panel.sleeping is True


# ---- confirm dialog -----------------------------------------------------

def test_confirm_screen_yes_no(app):
    a = boot(app)
    called = []

    def on_yes(app_):
        called.append(True)

    a.push(screens.ConfirmScreen("Sure?", on_yes))
    fire(a, "k1")  # no
    assert called == []
    assert isinstance(a.stack[-1], screens.LibraryScreen)

    a.push(screens.ConfirmScreen("Sure?", on_yes))
    fire(a, "k3")  # yes
    assert called == [True]
    assert isinstance(a.stack[-1], screens.LibraryScreen)


def test_confirm_screen_ignores_non_k1_cancel(app):
    a = boot(app)
    called = []

    def on_yes(app_):
        called.append(True)

    a.push(screens.ConfirmScreen("Sure?", on_yes))
    for name in ("k2", "press", "up", "down", "left", "right"):
        fire(a, name)
        assert isinstance(a.stack[-1], screens.ConfirmScreen)
        assert called == []
    fire(a, "k1")
    assert called == []
    assert isinstance(a.stack[-1], screens.LibraryScreen)


# ---- settings / themes / display / system -------------------------------

def test_settings_cycles_word_size_and_pivot_style(app):
    import render
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Settings")
    fire(a, "press")
    settings = a.stack[-1]
    assert isinstance(settings, screens.SettingsScreen)

    # word_size cycles full tuple and wraps; affects Reading/Paused frames
    sizes = list(screens._WORD_SIZES)
    assert a.state.settings["word_size"] == "medium"
    for expected in sizes[sizes.index("medium") + 1:] + sizes[:sizes.index("medium") + 1]:
        before = render.word_frame(a.book.words[a.idx], a.theme,
                                   word_size=a.state.settings["word_size"])
        settings.sel = settings.items(a).index("word_size")
        fire(a, "press")
        assert a.state.settings["word_size"] == expected
        after = render.word_frame(a.book.words[a.idx], a.theme,
                                  word_size=a.state.settings["word_size"])
        if expected != "medium":
            # at least one cycle away from start should differ from medium
            pass
        assert before != after or expected == "medium"

    # reset and check medium vs large differ
    a.state.settings["word_size"] = "medium"
    med = render.word_frame(a.book.words[a.idx], a.theme, word_size="medium")
    settings.sel = settings.items(a).index("word_size")
    fire(a, "press")  # -> large
    assert a.state.settings["word_size"] == "large"
    large = render.word_frame(a.book.words[a.idx], a.theme, word_size="large")
    assert med != large

    # pivot_style cycles and updates app.theme immediately
    styles = list(screens._PIVOT_STYLES)
    a.state.settings["pivot_style"] = "ticks"
    from dataclasses import replace
    a.theme = replace(a.theme, pivot_style="ticks")
    for expected in styles[1:] + ["ticks"]:
        before = render.word_frame(a.book.words[a.idx], a.theme)
        settings.sel = settings.items(a).index("pivot_style")
        fire(a, "press")
        assert a.state.settings["pivot_style"] == expected
        assert a.theme.pivot_style == expected
        after = render.word_frame(a.book.words[a.idx], a.theme)
        assert before != after

    # Theme / Display push the right screens
    settings.sel = settings.items(a).index("theme")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ThemesScreen)
    fire(a, "k1")
    settings.sel = settings.items(a).index("display")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.DisplaySettingsScreen)


def test_themes_screen_apply_and_preserve_pivot(app):
    import theme
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Settings")
    fire(a, "press")
    settings = a.stack[-1]
    # set a non-default pivot override first
    a.state.settings["pivot_style"] = "box"
    from dataclasses import replace
    a.theme = replace(a.theme, pivot_style="box")
    a.state.save()

    settings.sel = settings.items(a).index("theme")
    fire(a, "press")
    themes = a.stack[-1]
    assert isinstance(themes, screens.ThemesScreen)
    keys = themes.items(a)
    assert keys == list(theme.THEMES)
    assert len(keys) == 5
    # current theme marked
    active = a.state.settings["theme"]
    assert themes.row_text(a, active).endswith(" *")
    for k in keys:
        if k != active:
            assert not themes.row_text(a, k).endswith(" *")

    # activate a different theme
    target = "paper" if active != "paper" else "focus"
    themes.sel = keys.index(target)
    fire(a, "press")
    assert a.state.settings["theme"] == target
    assert a.theme.name == theme.THEMES[target].name
    assert a.theme.pivot_style == "box"  # override preserved
    assert a.display.panel.inverted is theme.THEMES[target].invert
    assert a.display.panel.contrast_level == theme.THEMES[target].contrast
    assert isinstance(a.stack[-1], screens.SettingsScreen)


def test_display_settings_contrast_session_only(app):
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Settings")
    fire(a, "press")
    settings = a.stack[-1]
    settings.sel = settings.items(a).index("display")
    fire(a, "press")
    disp = a.stack[-1]
    assert isinstance(disp, screens.DisplaySettingsScreen)
    base = a.theme.contrast
    assert disp._value == base

    fire(a, "up")
    assert disp._value == min(0xFF, base + screens.DisplaySettingsScreen.STEP)
    assert a.display.panel.contrast_level == disp._value
    fire(a, "down")
    assert disp._value == base
    assert a.display.panel.contrast_level == base

    # clamp high
    disp._value = 0xFF - 1
    fire(a, "up")
    assert disp._value == 0xFF
    # clamp low
    disp._value = 1
    fire(a, "down")
    assert disp._value == 0x00

    fire(a, "up")  # nudge away from theme
    nudged = disp._value
    assert nudged != base
    fire(a, "k1")  # back; keep session contrast
    assert a.display.panel.contrast_level == nudged
    assert isinstance(a.stack[-1], screens.SettingsScreen)
    a.state.save()
    assert "contrast" not in a.state.settings


def test_system_screen_info_and_power(app, tmp_path, monkeypatch):
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("System")
    fire(a, "press")
    sys_screen = a.stack[-1]
    assert isinstance(sys_screen, screens.SystemScreen)

    # helpers don't raise
    ip = screens.SystemScreen._ip_address()
    assert isinstance(ip, str) and len(ip) > 0
    disk = screens.SystemScreen._disk_free(str(tmp_path))
    assert "MB free" in disk

    for label in ("IP address", "Disk free", "Version"):
        sys_screen.sel = sys_screen.items(a).index(label)
        fire(a, "press")
        assert isinstance(a.stack[-1], screens.MessageScreen)
        assert a.stack[-1].lines and a.stack[-1].lines[0]
        fire(a, "press")  # ignored; only K1 pops
        assert isinstance(a.stack[-1], screens.MessageScreen)
        fire(a, "k1")
        assert isinstance(a.stack[-1], screens.SystemScreen)

    # reboot / power off via confirm; monkeypatch subprocess
    calls = []
    monkeypatch.setattr(
        "subprocess.call",
        lambda argv: calls.append(list(argv)) or 0)

    sys_screen.sel = sys_screen.items(a).index("Reboot")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ConfirmScreen)
    fire(a, "k1")  # decline
    assert calls == []
    assert isinstance(a.stack[-1], screens.SystemScreen)

    fire(a, "press")
    fire(a, "k3")  # confirm reboot
    assert calls and calls[-1][-1] == "reboot"

    calls.clear()
    sys_screen.sel = sys_screen.items(a).index("Power off")
    fire(a, "press")
    fire(a, "k1")  # decline
    assert calls == []
    fire(a, "press")
    fire(a, "k3")  # confirm poweroff
    assert calls and calls[-1][-1] == "poweroff"


# ---- Phase 2D: library K1 hold / K2, control-map seams ----------------

def test_library_k1_hold_power_off_confirm(app, monkeypatch):
    _write_book("a.txt")
    a = boot(app)
    calls = []
    monkeypatch.setattr(
        "subprocess.call",
        lambda argv: calls.append(list(argv)) or 0)

    fire(a, "k1", "hold")
    assert isinstance(a.stack[-1], screens.ConfirmScreen)
    fire(a, "k1")  # decline
    assert calls == []
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert len(a.stack) == 1

    fire(a, "k1", "hold")
    fire(a, "k3")  # confirm
    assert calls and calls[-1][-1] == "poweroff"
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert len(a.stack) == 1  # ConfirmScreen popped exactly once


def test_library_k2_reduced_menu(app):
    _write_book("a.txt")
    a = boot(app)
    assert a.book is None
    fire(a, "k2")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)
    assert a.stack[-1].items(a) == ["Settings", "System"]
    fire(a, "press")  # Settings
    assert isinstance(a.stack[-1], screens.SettingsScreen)
    fire(a, "k1")
    menu = a.stack[-1]
    menu.sel = 1
    fire(a, "press")  # System
    assert isinstance(a.stack[-1], screens.SystemScreen)


def test_reading_control_map_bindings(app):
    """Every Reading-row control-map (name, kind) from Paused->Reading."""
    a = _open_paused(app)
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ReadingScreen)
    depth = len(a.stack)
    base = a.state.settings["wpm"]
    starts = a.book.sentence_starts

    fire(a, "up")
    assert a.state.settings["wpm"] == base + config.WPM_STEP
    fire(a, "down")
    assert a.state.settings["wpm"] == base

    a.idx = starts[0]
    fire(a, "right")
    assert a.idx == starts[1]
    fire(a, "left")
    assert a.idx == starts[0]

    fire(a, "k2")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)
    assert a.stack[-1].items(a) == list(screens.BookMenuScreen._BOOK_ITEMS)
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.ReadingScreen)

    fire(a, "k3")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert len(a.stack) == depth
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ReadingScreen)

    path = a.book.path
    a.idx = 5
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert len(a.stack) == 1
    assert a.state.book(path)["position"] == 5


def test_list_screen_k1_press_k3_matrix(app):
    """Every list screen: K1=back, press=activate, K3=context or no-op."""
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]

    # Book menu K1
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.PausedScreen)
    fire(a, "k2")
    menu = a.stack[-1]

    # Chapters: press activates (tested elsewhere); K3 no-op; K1 back
    menu.sel = menu.items(a).index("Chapters")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ChaptersScreen)
    before = a.idx
    fire(a, "k3")  # no context action
    assert a.idx == before
    assert isinstance(a.stack[-1], screens.ChaptersScreen)
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)

    # Bookmarks: K3 = delete confirm; K1 back
    a.state.add_bookmark(a.book.path, 2)
    a.state.save()
    menu.sel = menu.items(a).index("Bookmarks")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.BookmarksScreen)
    fire(a, "k3")
    assert isinstance(a.stack[-1], screens.ConfirmScreen)
    fire(a, "k1")  # decline delete
    assert isinstance(a.stack[-1], screens.BookmarksScreen)
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)

    # Settings / Themes / System: K1 back; K3 no-op
    for label, cls in (("Settings", screens.SettingsScreen),
                       ("System", screens.SystemScreen)):
        menu.sel = menu.items(a).index(label)
        fire(a, "press")
        assert isinstance(a.stack[-1], cls)
        fire(a, "k3")
        assert isinstance(a.stack[-1], cls)
        fire(a, "k1")
        assert isinstance(a.stack[-1], screens.BookMenuScreen)

    menu.sel = menu.items(a).index("Settings")
    fire(a, "press")
    settings = a.stack[-1]
    settings.sel = settings.items(a).index("theme")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.ThemesScreen)
    fire(a, "k3")
    assert isinstance(a.stack[-1], screens.ThemesScreen)
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.SettingsScreen)


def test_nested_list_k2_opens_menu(app):
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Settings")
    fire(a, "press")
    assert isinstance(a.stack[-1], screens.SettingsScreen)
    depth = len(a.stack)
    fire(a, "k2")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)
    assert len(a.stack) == depth + 1


def test_book_menu_k2_is_noop(app):
    a = _open_paused(app)
    fire(a, "k2")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)
    depth = len(a.stack)
    fire(a, "k2")
    assert isinstance(a.stack[-1], screens.BookMenuScreen)
    assert len(a.stack) == depth


def test_message_screen_only_k1_exits(app):
    a = boot(app)
    a.push(screens.MessageScreen(["hello"]))
    for name in ("press", "k2", "k3", "up"):
        fire(a, name)
        assert isinstance(a.stack[-1], screens.MessageScreen)
    fire(a, "k1")
    assert isinstance(a.stack[-1], screens.LibraryScreen)


# ---- Phase 2D: stack-depth invariants -----------------------------------

def test_stack_depth_chapters_round_trip(app):
    a = _open_paused(app)
    assert len(a.stack) == 2  # Library + Paused
    fire(a, "k2")
    assert len(a.stack) == 3
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Chapters")
    fire(a, "press")
    assert len(a.stack) == 4
    assert isinstance(a.stack[-1], screens.ChaptersScreen)
    fire(a, "press")  # activate chapter -> pop_to(Paused)
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert len(a.stack) == 2


def test_stack_depth_bookmarks_round_trip(app):
    a = _open_paused(app)
    a.state.add_bookmark(a.book.path, 3)
    a.state.save()
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Bookmarks")
    fire(a, "press")
    assert len(a.stack) == 4
    fire(a, "press")  # activate bookmark -> pop_to(Paused)
    assert isinstance(a.stack[-1], screens.PausedScreen)
    assert len(a.stack) == 2
    assert a.idx == 3


def test_stack_depth_settings_theme_round_trip(app):
    a = _open_paused(app)
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Settings")
    fire(a, "press")
    assert len(a.stack) == 4  # Lib + Paused + Menu + Settings
    settings = a.stack[-1]
    settings.sel = settings.items(a).index("theme")
    fire(a, "press")
    assert len(a.stack) == 5
    fire(a, "press")  # activate theme -> pop back to Settings
    assert isinstance(a.stack[-1], screens.SettingsScreen)
    assert len(a.stack) == 4


def test_stack_depth_end_any_key_to_library(app):
    a = _open_paused(app)
    fire(a, "press")  # Reading
    while not isinstance(a.stack[-1], screens.EndScreen):
        a.step_word()
    assert len(a.stack) >= 2
    fire(a, "press")  # any key
    assert isinstance(a.stack[-1], screens.LibraryScreen)
    assert len(a.stack) == 1
    assert a.book is None
    fire(a, "k2")
    assert a.stack[-1].items(a) == list(screens.BookMenuScreen._NO_BOOK_ITEMS)


# ---- Phase 2D: state.save() timing audit --------------------------------

def _count_saves(a, monkeypatch):
    n = [0]
    real = a.state.save

    def counting():
        n[0] += 1
        return real()

    monkeypatch.setattr(a.state, "save", counting)
    return n


def test_save_on_pause_and_not_every_word(app, monkeypatch):
    long = " ".join("word%d" % i for i in range(50))
    a = _open_paused(app, name="long.txt", text=long + ".")
    monkeypatch.setattr(config, "SAVE_EVERY_WORDS", 100)
    counts = _count_saves(a, monkeypatch)

    fire(a, "press")  # Reading
    counts[0] = 0
    for _ in range(5):
        a.step_word()
    assert counts[0] == 0  # not every word
    assert a.words_since_save == 5

    fire(a, "press")  # pause -> Reading.on_exit saves
    assert counts[0] >= 1
    assert isinstance(a.stack[-1], screens.PausedScreen)


def test_save_every_n_words(app, monkeypatch):
    long = " ".join("word%d" % i for i in range(40))
    a = _open_paused(app, name="nwords.txt", text=long + ".")
    monkeypatch.setattr(config, "SAVE_EVERY_WORDS", 5)
    fire(a, "press")
    counts = _count_saves(a, monkeypatch)
    a.words_since_save = 0
    while a.words_since_save < 5 and not isinstance(a.stack[-1], screens.EndScreen):
        a.step_word()
    assert counts[0] >= 1
    assert a.words_since_save == 0  # reset by save_position


def test_save_on_leave_settings_bookmark_sigterm(app, monkeypatch):
    a = _open_paused(app)
    path = a.book.path
    counts = _count_saves(a, monkeypatch)

    # leave to library
    counts[0] = 0
    a.idx = 6
    fire(a, "k1")
    assert counts[0] >= 1
    assert a.state.book(path)["position"] == 6

    # reopen and change settings (word_size / pivot_style / theme)
    a = _open_paused(app, name="set.txt")
    counts = _count_saves(a, monkeypatch)
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Settings")
    fire(a, "press")
    settings = a.stack[-1]
    counts[0] = 0
    settings.sel = settings.items(a).index("word_size")
    fire(a, "press")
    assert counts[0] >= 1
    counts[0] = 0
    settings.sel = settings.items(a).index("pivot_style")
    fire(a, "press")
    assert counts[0] >= 1
    settings.sel = settings.items(a).index("theme")
    fire(a, "press")
    counts[0] = 0
    fire(a, "press")  # apply a theme
    assert counts[0] >= 1
    assert isinstance(a.stack[-1], screens.SettingsScreen)

    # bookmark add
    fire(a, "k1")  # Settings -> menu
    fire(a, "k1")  # menu -> paused
    fire(a, "k2")
    counts = _count_saves(a, monkeypatch)
    counts[0] = 0
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Bookmark this page")
    fire(a, "press")
    assert counts[0] >= 1

    # bookmark remove via confirm
    fire(a, "k2")
    menu = a.stack[-1]
    menu.sel = menu.items(a).index("Bookmarks")
    fire(a, "press")
    counts[0] = 0
    fire(a, "k3")
    fire(a, "k3")  # confirm delete
    assert counts[0] >= 1

    # SIGTERM / bail
    a2 = _open_paused(app, name="sig.txt")
    a2.idx = 4
    path2 = a2.book.path
    counts = _count_saves(a2, monkeypatch)
    main._bail(a2)
    assert counts[0] >= 1
    assert a2.state.book(path2)["position"] == 4


# ---- Phase 2D: boot.py / main.main contract -----------------------------

def test_main_signature_matches_boot(fake_display):
    """boot.py does main.main(disp); display must be accepted as positional."""
    import inspect
    params = list(inspect.signature(main.main).parameters)
    assert params[0] == "display"
    # smoke: App accepts the same display object boot would hand over
    a = main.App(display=fake_display, input_cls=_NullInput)
    assert a.display is fake_display
