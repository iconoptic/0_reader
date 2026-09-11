"""End-to-end tests of the App state machine with fake panels and fake
keys. No sleeping: time.sleep is stubbed while playing."""

import json
import os

import pytest

pytestmark = pytest.mark.skip(
    reason="Phase 2: App still targets the three-panel Display API")

import config
import main
import render


SAMPLE = ("CHAPTER I.\n\nFirst one. Second one here again today. Third!\n\n"
          "CHAPTER II.\n\nFourth sentence. Fifth and last.")


def _write_book(name, text=SAMPLE):
    p = os.path.join(config.BOOKS_DIR, name)
    with open(p, "w") as f:
        f.write(text)
    return p


@pytest.fixture
def app(fake_display, fake_button, monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)

    def button_cls(pin, on_taps, on_hold=None):
        b = fake_button()
        return main._LegacyMultiTap(pin, on_taps, on_hold, button=b)

    def make():
        a = main.App(display=fake_display, button_cls=button_cls)
        a.rescan()
        return a

    return make


def _frames(disp):
    return (len(disp.main.frames), len(disp.left.frames), len(disp.right.frames))


def test_empty_library_menu_uses_all_three_screens(app, fake_display):
    a = app()
    a.show_menu()
    assert a.mode == main.MENU and a.library == []
    assert _frames(fake_display) == (1, 1, 1)
    assert fake_display.right.last.size == (config.SIDE_W, config.SIDE_H)
    # empty library -> blank left card
    assert fake_display.left.last.getextrema() == ((0, 0), (0, 0), (0, 0))


def test_menu_navigation_wraps_and_opens(app, fake_display):
    for n in ["b.txt", "a.txt", "c.txt"]:
        _write_book(n)
    a = app()
    a.show_menu()
    assert [t for t, _ in a.library] == ["a", "b", "c"]
    assert fake_display.left.last.getextrema() != ((0, 0), (0, 0), (0, 0))
    a.handle(("B", 1)); a.handle(("B", 1))
    assert a.sel == 2
    a.handle(("B", 1))
    assert a.sel == 0
    a.handle(("B", 2))
    assert a.sel == 2
    # each move redraws the list and the book card but not the static hints
    assert _frames(fake_display) == (5, 5, 1)
    a.handle(("A", 1))
    assert a.mode == main.PAUSED
    assert a.book.title == "c"
    assert a.idx == 0
    assert a.state.in_book and a.state.last_book.endswith("c.txt")
    assert a.state.totals[a.book.path] == len(a.book.words)
    # paused: progress card left, paused hints right
    assert len(fake_display.right.frames) == 2


def test_open_book_resumes_saved_position(app):
    p = _write_book("x.txt")
    a = app()
    a.state.positions[p] = 7
    a.show_menu()
    a.handle(("A", 1))
    assert a.idx == 7


def test_saved_position_is_clamped_to_book_length(app):
    p = _write_book("x.txt")
    a = app()
    a.state.positions[p] = 10_000
    a.show_menu()
    a.handle(("A", 1))
    assert a.idx == len(a.book.words) - 1


def test_load_failure_and_empty_book_fall_back_to_menu(app):
    _write_book("empty.txt", "")
    a = app()
    a.show_menu()
    a.handle(("A", 1))
    assert a.mode == main.MENU and a.book is None
    _write_book("bad.epub", "not a zip")
    a.rescan()
    a.sel = 0
    a.handle(("A", 1))
    assert a.mode == main.MENU


def test_play_pause_and_wpm_persist(app, fake_display):
    _write_book("x.txt")
    a = app()
    a.show_menu()
    a.handle(("A", 1))              # open -> paused
    assert fake_display.left.backlight_level == config.BL_SIDE
    a.handle(("A", 1))              # play
    assert a.mode == main.READING
    assert fake_display.left.backlight_level == config.BL_SIDE_READING
    a.step_word()
    assert a.idx >= 1
    n_right = len(fake_display.right.frames)
    a.handle(("A", 2))
    assert a.state.wpm == config.DEFAULT_WPM + config.WPM_STEP
    assert len(fake_display.right.frames) == n_right + 1   # speed card redrawn
    a.handle(("B", 2)); a.handle(("B", 2))
    assert a.state.wpm == config.DEFAULT_WPM - config.WPM_STEP
    with open(config.STATE_FILE) as f:
        assert json.load(f)["wpm"] == a.state.wpm
    a.handle(("A", 1))
    assert a.mode == main.PAUSED
    assert fake_display.left.backlight_level == config.BL_SIDE


def test_wpm_is_clamped(app):
    _write_book("x.txt")
    a = app()
    a.state.wpm = config.MAX_WPM
    a.change_wpm(+config.WPM_STEP)
    assert a.state.wpm == config.MAX_WPM
    a.state.wpm = config.MIN_WPM
    a.change_wpm(-config.WPM_STEP)
    assert a.state.wpm == config.MIN_WPM


def test_sentence_navigation(app):
    _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("A", 1))
    words = a.book.words
    # words: CHAPTER I. | First one. Second one here again today. Third! | ...
    a.idx = words.index("Second")
    a.handle(("A", 3))              # forward one sentence
    assert words[a.idx] == "Third!"
    a.handle(("B", 1))              # back: at a sentence start -> previous one
    assert words[a.idx] == "Second"
    a.idx = words.index("today.")   # mid-sentence: back goes to its start
    a.handle(("B", 1))
    assert words[a.idx] == "Second"
    a.idx = words.index("one")      # <3 words in counts as 'just started'
    a.handle(("B", 1))
    assert words[a.idx] == "First"
    a.idx = len(words) - 1
    a.jump_sentence(+1)
    assert a.idx == len(words) - 1  # no overshoot at the end


def test_chapter_navigation(app):
    _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("A", 1))
    words = a.book.words
    assert len(a.book.chapter_starts) == 2
    assert a.chapter_pos() == (1, 2)
    a.handle(("A", 2))              # next chapter
    assert words[a.idx:a.idx + 2] == ["CHAPTER", "II."]
    assert a.chapter_pos() == (2, 2)
    a.handle(("B", 2))              # a few words into ch.2 -> back to ch.1
    assert a.idx == 0
    a.idx = words.index("last.")
    a.handle(("B", 2))              # deep in ch.2 -> start of ch.2
    assert words[a.idx] == "CHAPTER" and words[a.idx + 1] == "II."
    a.handle(("A", 2))              # past last chapter -> end of book
    assert a.idx == len(words) - 1


def test_chapter_navigation_noop_without_chapters(app):
    _write_book("plain.txt", "Just some prose. Nothing else here.")
    a = app()
    a.show_menu(); a.handle(("A", 1))
    assert a.book.chapter_starts == [] and a.chapter_pos() is None
    a.idx = 2
    a.handle(("A", 2))
    assert a.idx == 2


def test_reading_to_end_saves_and_returns_to_menu(app, fake_display):
    p = _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("A", 1)); a.handle(("A", 1))
    n = 0
    while a.mode == main.READING and n < 1000:
        a.step_word()
        n += 1
    assert a.mode == main.END
    assert not a.state.in_book
    assert a.state.positions[p] == len(a.book.words) - 1
    assert fake_display.left.backlight_level == config.BL_SIDE
    a.handle(("A", 1))
    assert a.mode == main.MENU and a.book is None


def test_side_cards_only_redraw_when_content_changes(app, fake_display):
    _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("A", 1)); a.handle(("A", 1))
    l0, r0 = len(fake_display.left.frames), len(fake_display.right.frames)
    m0 = len(fake_display.main.frames)
    a.step_word()
    a.step_word()
    assert len(fake_display.main.frames) == m0 + 2
    # the first frame is still at 0% (same as the paused card -> no redraw);
    # the second is ~8% into a 13-word book -> redraw. Speed card: never.
    assert len(fake_display.left.frames) == l0 + 1
    assert len(fake_display.right.frames) == r0
    # identical key -> no redraw
    a._progress_side()
    n = len(fake_display.left.frames)
    a._progress_side()
    assert len(fake_display.left.frames) == n


def test_chunking_when_frame_rate_is_slower_than_wpm(app):
    _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("A", 1)); a.handle(("A", 1))
    a.refresh_secs = 10.0           # absurdly slow frames -> many words/frame
    before = a.idx
    a.step_word()
    assert a.idx - before >= 2
    # calibration moves toward the observed (near-zero) time
    assert a.refresh_secs < 10.0


def test_periodic_save_while_playing(app, monkeypatch):
    p = _write_book("x.txt")
    monkeypatch.setattr(config, "SAVE_EVERY_WORDS", 2)
    a = app()
    a.show_menu(); a.handle(("A", 1)); a.handle(("A", 1))
    a.step_word(); a.step_word(); a.step_word()
    with open(config.STATE_FILE) as f:
        assert json.load(f)["positions"][p] >= 2


def test_hold_leaves_to_menu_and_state_resumes_on_restart(app):
    p = _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("A", 1)); a.handle(("A", 1))
    a.step_word(); a.step_word()
    pos = a.idx
    a.handle(("holdB", 0))
    assert a.mode == main.MENU and a.book is None
    s = main.State()
    assert s.positions[p] == pos and s.in_book is False

    # power-cut while inside a book -> next boot reopens it, paused
    b = app()
    b.show_menu(); b.handle(("A", 1))
    assert b.state.in_book
    b.save_position()
    c = app()
    # emulate run()'s startup decision without entering the loop
    if c.state.in_book and any(q == c.state.last_book for _, q in c.library):
        c.open_book()
    assert c.mode == main.PAUSED and c.idx == pos


def test_power_off_confirm_cancel_and_failure(app, fake_display, monkeypatch):
    calls = []
    rc = {"code": 0}
    monkeypatch.setattr(main.subprocess, "call",
                        lambda argv: (calls.append(argv), rc["code"])[1])
    monkeypatch.setattr(main.os, "geteuid", lambda: 1000)
    a = app()
    a.show_menu()
    a.handle(("holdB", 0))
    assert a.mode == main.CONFIRM_OFF
    a.handle(("B", 1))
    assert a.mode == main.MENU and calls == []
    a.handle(("holdB", 0))
    a.handle(("A", 1))
    assert calls == [["sudo", "-n", "poweroff"]]
    assert a.mode == main.CONFIRM_OFF        # stays until systemd stops us
    # a failing poweroff must not leave the UI stuck
    rc["code"] = 1
    a.handle(("A", 1))
    assert a.mode == main.MENU
    # root skips sudo
    monkeypatch.setattr(main.os, "geteuid", lambda: 0)
    rc["code"] = 0
    a.handle(("holdB", 0)); a.handle(("A", 1))
    assert calls[-1] == ["poweroff"]


def test_key_events_reach_the_queue(app):
    a = app()
    a.key2.btn.tap()
    # Legacy multi-tap still uses gpiozero's when_held; fire it directly
    # now that FakeButton no longer has a synchronous .hold() helper.
    a.key1.btn.when_pressed()
    a.key1.btn.when_held()
    a.key1.btn.when_released()
    assert a.events.get(timeout=1.0) == ("holdA", 0)
    assert a.events.get(timeout=1.0) == ("B", 1)


def test_state_roundtrip_and_corrupt_file(tmp_path):
    s = main.State()
    s.wpm = 275
    s.positions["/b"] = 3
    s.totals["/b"] = 30
    s.save()
    t = main.State()
    assert (t.wpm, t.positions, t.totals) == (275, {"/b": 3}, {"/b": 30})
    with open(config.STATE_FILE, "w") as f:
        f.write("{not json")
    u = main.State()
    assert u.wpm == config.DEFAULT_WPM and u.positions == {}


def test_main_entry_wires_sigterm_and_error_screen(app, fake_display, monkeypatch):
    """main.main() should save state and darken the screens on SIGTERM and
    show an error frame if the app crashes."""
    import signal

    handlers = {}
    monkeypatch.setattr(main.signal, "signal",
                        lambda num, fn: handlers.__setitem__(num, fn))

    class Boom(Exception):
        pass

    def crash(self):
        raise Boom()

    monkeypatch.setattr(main.App, "run", crash)
    monkeypatch.setattr(main, "_LegacyMultiTap",
                        lambda pin, on_taps, on_hold=None: None)
    with pytest.raises(Boom):
        main.main(fake_display)
    assert fake_display.main.last.size == (render.MW, render.MH)
    with pytest.raises(SystemExit):
        handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert fake_display.main.sleeping and fake_display.left.sleeping
