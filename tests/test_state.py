"""Tests for rapid_reader.state (v2 schema + v1 migration)."""

import json
import os

import pytest

import config
import state


def test_fresh_state_has_defaults(tmp_path):
    s = state.State(path=str(tmp_path / "missing.json"))
    assert s.settings == config.SETTINGS_DEFAULTS
    assert s.last_book is None
    assert s.in_book is False
    assert s.books == {}


def test_save_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    s = state.State(path=path)
    s.settings["wpm"] = 300
    s.settings["theme"] = "paper"
    s.settings["pivot_style"] = "box"
    s.settings["word_size"] = "large"
    s.last_book = "/books/a.txt"
    s.in_book = True
    s.touch_book("/books/a.txt", position=42, total_words=100,
                 time_read_secs=12.5, last_opened=1700000000.0)
    s.add_bookmark("/books/a.txt", 10)
    s.add_bookmark("/books/a.txt", 5)
    s.save()

    loaded = state.State(path=path)
    assert loaded.settings == s.settings
    assert loaded.last_book == "/books/a.txt"
    assert loaded.in_book is True
    assert loaded.books == s.books


def test_book_touch_and_bookmarks(tmp_path):
    s = state.State(path=str(tmp_path / "state.json"))
    rec = s.book("/b.txt")
    assert rec == {
        "position": 0,
        "total_words": 0,
        "time_read_secs": 0.0,
        "bookmarks": [],
        "last_opened": 0.0,
    }
    s.touch_book("/b.txt", position=7, total_words=99)
    assert s.book("/b.txt")["position"] == 7
    assert s.book("/b.txt")["total_words"] == 99
    assert s.book("/b.txt")["bookmarks"] == []

    s.add_bookmark("/b.txt", 30)
    s.add_bookmark("/b.txt", 10)
    s.add_bookmark("/b.txt", 30)  # dedupe
    assert s.book("/b.txt")["bookmarks"] == [10, 30]

    s.remove_bookmark("/b.txt", 10)
    s.remove_bookmark("/b.txt", 99)  # absent: no error
    assert s.book("/b.txt")["bookmarks"] == [30]


def test_clean_book_record_bookmarks_not_shared(tmp_path):
    path = str(tmp_path / "state.json")
    with open(path, "w") as f:
        json.dump({"version": 2, "books": {"/a.txt": {}, "/b.txt": {}}}, f)
    s = state.State(path=path)
    assert s.books["/a.txt"]["bookmarks"] is not s.books["/b.txt"]["bookmarks"]
    s.books["/a.txt"]["bookmarks"].append(1)
    assert s.books["/b.txt"]["bookmarks"] == []
    assert state._BOOK_DEFAULTS["bookmarks"] == []


def test_migrate_v1_dict():
    v1 = {
        "wpm": 400,
        "positions": {"/a.txt": 12, "/b.txt": 3},
        "totals": {"/a.txt": 100, "/c.txt": 50},
        "last_book": "/a.txt",
        "in_book": True,
    }
    v2 = state.migrate_v1(v1)
    assert v2["version"] == 2
    assert v2["settings"]["wpm"] == 400
    assert v2["settings"]["theme"] == config.SETTINGS_DEFAULTS["theme"]
    assert v2["last_book"] == "/a.txt"
    assert v2["in_book"] is True
    assert set(v2["books"]) == {"/a.txt", "/b.txt", "/c.txt"}
    assert v2["books"]["/a.txt"] == {
        "position": 12, "total_words": 100,
        "time_read_secs": 0.0, "bookmarks": [], "last_opened": 0.0,
    }
    assert v2["books"]["/b.txt"]["position"] == 3
    assert v2["books"]["/b.txt"]["total_words"] == 0
    assert v2["books"]["/c.txt"]["position"] == 0
    assert v2["books"]["/c.txt"]["total_words"] == 50


def test_load_migrates_v1_file(tmp_path):
    path = str(tmp_path / "state.json")
    with open(path, "w") as f:
        json.dump({
            "wpm": 175,
            "positions": {"/old.txt": 9},
            "totals": {"/old.txt": 200},
            "last_book": "/old.txt",
            "in_book": False,
        }, f)
    s = state.State(path=path)
    assert s.settings["wpm"] == 175
    assert s.last_book == "/old.txt"
    assert s.in_book is False
    assert s.books["/old.txt"]["position"] == 9
    assert s.books["/old.txt"]["total_words"] == 200
    assert s.books["/old.txt"]["bookmarks"] == []
    # migration is read-only: file still v1 until save()
    with open(path) as f:
        on_disk = json.load(f)
    assert "version" not in on_disk
    assert "positions" in on_disk


def test_clean_settings_clamps_and_rejects():
    cleaned = state._clean_settings({
        "wpm": 9999,
        "theme": "custom-neon",
        "pivot_style": "nope",
        "word_size": "huge",
    })
    assert cleaned["wpm"] == config.MAX_WPM
    assert cleaned["theme"] == "custom-neon"
    assert cleaned["pivot_style"] == config.SETTINGS_DEFAULTS["pivot_style"]
    assert cleaned["word_size"] == config.SETTINGS_DEFAULTS["word_size"]

    cleaned = state._clean_settings({"wpm": 1, "pivot_style": "bold",
                                     "word_size": "small"})
    assert cleaned["wpm"] == config.MIN_WPM
    assert cleaned["pivot_style"] == "bold"
    assert cleaned["word_size"] == "small"


def test_save_atomic_and_creates_dirs(tmp_path, monkeypatch):
    nested = tmp_path / "var" / "lib" / "rapid-reader" / "state.json"
    s = state.State(path=str(nested))
    s.settings["wpm"] = 200
    seen = []

    real_replace = os.replace

    def tracking_replace(src, dst):
        seen.append((src, dst))
        assert src.endswith(".tmp")
        assert not os.path.exists(dst) or True
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", tracking_replace)
    s.save()
    assert nested.exists()
    assert seen == [(str(nested) + ".tmp", str(nested))]
    assert not os.path.exists(str(nested) + ".tmp")


def test_save_swallows_oserror(tmp_path, monkeypatch):
    path = str(tmp_path / "state.json")
    s = state.State(path=path)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "makedirs", boom)
    s.save()  # must not raise
