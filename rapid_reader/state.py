"""Persistent app state (v2 schema) with v1 migration."""

import json
import os
import traceback

import config

SCHEMA_VERSION = 2

_PIVOT_STYLES = ("ticks", "underline", "box", "bold")
_WORD_SIZES = ("small", "medium", "large")

_BOOK_DEFAULTS = {
    "position": 0,
    "total_words": 0,
    "time_read_secs": 0.0,
    "bookmarks": [],
    "last_opened": 0.0,
}


def _clean_settings(raw):
    out = dict(config.SETTINGS_DEFAULTS)
    wpm = raw.get("wpm")
    if isinstance(wpm, (int, float)):
        out["wpm"] = max(config.MIN_WPM, min(config.MAX_WPM, int(wpm)))
    theme = raw.get("theme")
    if isinstance(theme, str):
        out["theme"] = theme
    pivot = raw.get("pivot_style")
    if pivot in _PIVOT_STYLES:
        out["pivot_style"] = pivot
    size = raw.get("word_size")
    if size in _WORD_SIZES:
        out["word_size"] = size
    return out


def _clean_book_record(raw):
    out = dict(_BOOK_DEFAULTS)
    out["bookmarks"] = []
    if not isinstance(raw, dict):
        return out
    pos = raw.get("position")
    if isinstance(pos, (int, float)):
        out["position"] = max(0, int(pos))
    total = raw.get("total_words")
    if isinstance(total, (int, float)):
        out["total_words"] = max(0, int(total))
    secs = raw.get("time_read_secs")
    if isinstance(secs, (int, float)):
        out["time_read_secs"] = float(secs)
    opened = raw.get("last_opened")
    if isinstance(opened, (int, float)):
        out["last_opened"] = float(opened)
    marks = raw.get("bookmarks")
    if isinstance(marks, list):
        cleaned = sorted({int(m) for m in marks if isinstance(m, (int, float))})
        out["bookmarks"] = cleaned
    return out


def migrate_v1(data):
    positions = data.get("positions", {})
    totals = data.get("totals", {})
    books = {}
    for path in set(positions) | set(totals):
        books[path] = {
            "position": positions.get(path, 0),
            "total_words": totals.get(path, 0),
            "time_read_secs": 0.0,
            "bookmarks": [],
            "last_opened": 0.0,
        }
    return {
        "version": 2,
        "settings": {**config.SETTINGS_DEFAULTS,
                     "wpm": data.get("wpm", config.DEFAULT_WPM)},
        "last_book": data.get("last_book"),
        "in_book": bool(data.get("in_book", False)),
        "books": books,
    }


class State:
    def __init__(self, path=None):
        self.path = path or config.STATE_FILE
        self.settings = dict(config.SETTINGS_DEFAULTS)
        self.last_book = None
        self.in_book = False
        self.books = {}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if data.get("version", 1) < 2:
            data = migrate_v1(data)
        self.settings = _clean_settings(data.get("settings", {}))
        self.last_book = data.get("last_book")
        self.in_book = bool(data.get("in_book", False))
        self.books = {p: _clean_book_record(r)
                      for p, r in data.get("books", {}).items()}

    def save(self):
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            payload = {
                "version": SCHEMA_VERSION,
                "settings": self.settings,
                "last_book": self.last_book,
                "in_book": self.in_book,
                "books": self.books,
            }
            with open(tmp, "w") as f:
                json.dump(payload, f)
            os.replace(tmp, self.path)
        except OSError:
            traceback.print_exc()

    def book(self, path):
        if path not in self.books:
            self.books[path] = dict(_BOOK_DEFAULTS)
            self.books[path]["bookmarks"] = []
        return self.books[path]

    def touch_book(self, path, **fields):
        rec = self.book(path)
        for key, value in fields.items():
            if key == "bookmarks":
                rec["bookmarks"] = sorted({int(m) for m in value})
            elif key in _BOOK_DEFAULTS:
                rec[key] = value

    def add_bookmark(self, path, idx):
        rec = self.book(path)
        marks = set(rec["bookmarks"])
        marks.add(int(idx))
        rec["bookmarks"] = sorted(marks)

    def remove_bookmark(self, path, idx):
        rec = self.book(path)
        idx = int(idx)
        if idx in rec["bookmarks"]:
            rec["bookmarks"] = [m for m in rec["bookmarks"] if m != idx]
