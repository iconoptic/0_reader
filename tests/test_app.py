"""End-to-end tests of the App state machine with a fake panel and fake
buttons. No sleeping: time.sleep is stubbed while playing."""

import json
import os

import pytest

import config
import main


SAMPLE = ("CHAPTER I.\n\nFirst one. Second one here again today. Third!\n\n"
          "CHAPTER II.\n\nFourth sentence. Fifth and last.")


def _write_book(name, text=SAMPLE):
    p = os.path.join(config.BOOKS_DIR, name)
    with open(p, "w") as f:
        f.write(text)
    return p


@pytest.fixture
def app(fake_epd, fake_button, monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    holders = {}

    def button_cls(pin, on_taps, on_hold=None):
        b = fake_button()
        tb = main.buttons.TapButton(pin, on_taps, on_hold, button=b)
        holders[pin] = tb
        return tb

    def make():
        a = main.App(display=fake_epd, button_cls=button_cls)
        a.rescan()
        return a

    return make


def _drain(a):
    while not a.events.empty():
        a.handle(a.events.get())


def test_boot_frame_and_empty_library(app, fake_epd):
    a = app()
    assert fake_epd.frames[0][0] == "full"
    a.show_menu()
    assert a.mode == main.MENU
    assert a.library == []


def test_menu_navigation_wraps_and_opens(app):
    for n in ["b.txt", "a.txt", "c.txt"]:
        _write_book(n)
    a = app()
    a.show_menu()
    assert [t for t, _ in a.library] == ["a", "b", "c"]
    a.handle(("5", 1)); a.handle(("5", 1))
    assert a.sel == 2
    a.handle(("5", 1))
    assert a.sel == 0
    a.handle(("5", 2))
    assert a.sel == 2
    a.handle(("6", 1))
    assert a.mode == main.PAUSED
    assert a.book.title == "c"
    assert a.idx == 0
    assert a.state.in_book and a.state.last_book.endswith("c.txt")


def test_open_book_resumes_saved_position(app):
    p = _write_book("x.txt")
    a = app()
    a.state.positions[p] = 7
    a.show_menu()
    a.handle(("6", 1))
    assert a.idx == 7


def test_saved_position_is_clamped_to_book_length(app):
    p = _write_book("x.txt")
    a = app()
    a.state.positions[p] = 10_000
    a.show_menu()
    a.handle(("6", 1))
    assert a.idx == len(a.book.words) - 1


def test_load_failure_and_empty_book_fall_back_to_menu(app, monkeypatch):
    _write_book("empty.txt", "")
    a = app()
    a.show_menu()
    a.handle(("6", 1))
    assert a.mode == main.MENU
    _write_book("bad.epub", "not a zip")
    a.rescan()
    a.sel = 0
    a.handle(("6", 1))
    assert a.mode == main.MENU


def test_play_pause_and_wpm_persist(app):
    _write_book("x.txt")
    a = app()
    a.show_menu()
    a.handle(("6", 1))              # open -> paused
    a.handle(("6", 1))              # play
    assert a.mode == main.READING
    a.step_word()
    assert a.idx >= 1
    a.handle(("6", 2))
    assert a.state.wpm == config.DEFAULT_WPM + config.WPM_STEP
    a.handle(("5", 2)); a.handle(("5", 2))
    assert a.state.wpm == config.DEFAULT_WPM - config.WPM_STEP
    with open(config.STATE_FILE) as f:
        assert json.load(f)["wpm"] == a.state.wpm
    a.handle(("6", 1))
    assert a.mode == main.PAUSED


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
    a.show_menu(); a.handle(("6", 1))
    words = a.book.words
    # words: CHAPTER I. | First one. Second one here again today. Third! | ...
    a.idx = words.index("Second")
    a.handle(("6", 3))              # forward one sentence
    assert words[a.idx] == "Third!"
    a.handle(("5", 1))              # back: at a sentence start -> previous one
    assert words[a.idx] == "Second"
    a.idx = words.index("today.")   # mid-sentence: back goes to its start
    a.handle(("5", 1))
    assert words[a.idx] == "Second"
    a.idx = words.index("one")      # <3 words in counts as 'just started'
    a.handle(("5", 1))
    assert words[a.idx] == "First"
    a.idx = len(words) - 1
    a.jump_sentence(+1)
    assert a.idx == len(words) - 1  # no overshoot at the end


def test_chapter_navigation(app):
    _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("6", 1))
    words = a.book.words
    assert len(a.book.chapter_starts) == 2
    a.handle(("6", 2))              # next chapter
    assert words[a.idx:a.idx + 2] == ["CHAPTER", "II."]
    a.handle(("5", 2))              # a few words into ch.2 -> back to ch.1
    assert a.idx == 0
    a.idx = words.index("last.")
    a.handle(("5", 2))              # deep in ch.2 -> start of ch.2
    assert words[a.idx] == "CHAPTER" and words[a.idx + 1] == "II."
    a.handle(("6", 2))              # past last chapter -> end of book
    assert a.idx == len(words) - 1


def test_chapter_navigation_noop_without_chapters(app):
    _write_book("plain.txt", "Just some prose. Nothing else here.")
    a = app()
    a.show_menu(); a.handle(("6", 1))
    assert a.book.chapter_starts == []
    a.idx = 2
    a.handle(("6", 2))
    assert a.idx == 2


def test_reading_to_end_saves_and_returns_to_menu(app, fake_epd):
    p = _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("6", 1)); a.handle(("6", 1))
    n = 0
    while a.mode == main.READING and n < 1000:
        a.step_word()
        n += 1
    assert a.mode == main.END
    assert not a.state.in_book
    assert a.state.positions[p] == len(a.book.words) - 1
    assert fake_epd.frames[-1][0] == "full"
    a.handle(("6", 1))
    assert a.mode == main.MENU and a.book is None


def test_chunking_when_panel_is_slower_than_wpm(app, fake_epd):
    _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("6", 1)); a.handle(("6", 1))
    a.refresh_secs = 10.0           # absurdly slow panel -> many words/frame
    before = a.idx
    a.step_word()
    assert a.idx - before >= 2
    # calibration moves toward the observed (near-zero) time
    assert a.refresh_secs < 10.0


def test_periodic_save_while_playing(app, monkeypatch):
    p = _write_book("x.txt")
    monkeypatch.setattr(config, "SAVE_EVERY_WORDS", 2)
    a = app()
    a.show_menu(); a.handle(("6", 1)); a.handle(("6", 1))
    a.step_word(); a.step_word(); a.step_word()
    with open(config.STATE_FILE) as f:
        assert json.load(f)["positions"][p] >= 2


def test_hold_leaves_to_menu_and_state_resumes_on_restart(app):
    p = _write_book("x.txt")
    a = app()
    a.show_menu(); a.handle(("6", 1)); a.handle(("6", 1))
    a.step_word(); a.step_word()
    pos = a.idx
    a.handle(("hold5", 0))
    assert a.mode == main.MENU and a.book is None
    s = main.State()
    assert s.positions[p] == pos and s.in_book is False

    # power-cut while inside a book -> next boot reopens it, paused
    b = app()
    b.show_menu(); b.handle(("6", 1))
    assert b.state.in_book
    b.save_position()
    c = app()
    c.run_once = True
    # emulate run()'s startup decision without entering the loop
    if c.state.in_book and any(q == c.state.last_book for _, q in c.library):
        c.open_book()
    assert c.mode == main.PAUSED and c.idx == pos


def test_power_off_confirm_and_cancel(app, fake_epd, monkeypatch):
    calls = []
    monkeypatch.setattr(main.subprocess, "call", lambda argv: calls.append(argv))
    monkeypatch.setattr(main.os, "geteuid", lambda: 1000)
    a = app()
    a.show_menu()
    a.handle(("hold5", 0))
    assert a.mode == main.CONFIRM_OFF
    a.handle(("5", 1))
    assert a.mode == main.MENU and calls == []
    a.handle(("hold5", 0))
    a.handle(("6", 1))
    assert calls == [["sudo", "-n", "poweroff"]]
    assert fake_epd.sleeping


def test_button_events_reach_the_queue(app):
    a = app()
    a.btn5.btn.tap()
    a.btn6.btn.hold()
    assert a.events.get(timeout=1.0) == ("hold6", 0)
    assert a.events.get(timeout=1.0) == ("5", 1)


def test_state_roundtrip_and_corrupt_file(tmp_path):
    s = main.State()
    s.wpm = 275
    s.positions["/b"] = 3
    s.save()
    t = main.State()
    assert (t.wpm, t.positions) == (275, {"/b": 3})
    with open(config.STATE_FILE, "w") as f:
        f.write("{not json")
    u = main.State()
    assert u.wpm == config.DEFAULT_WPM and u.positions == {}
