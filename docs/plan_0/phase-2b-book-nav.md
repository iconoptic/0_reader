# Phase 2B — Book navigation screens (Chapters, Bookmarks, Book info)

**Status:** not started. **Depends on:** [`phase-2a-core.md`](phase-2a-core.md)
landed (this phase edits three specific lines in `screens.py`'s
`BookMenuScreen.activate` and `LibraryScreen.context_action`, and adds
three new classes to the end of that same file). **Part of the Phase 2
split** — see [`phase-2-app.md`](phase-2-app.md) and [`README.md`](README.md).

## Scope

Add three screens and wire them in. This phase does **not** touch
`App`, `ListScreen`, `ReadingScreen`, `PausedScreen`, `EndScreen`,
`MessageScreen`, or `ConfirmScreen` — those are Phase 2A's and are
already correct. Everything here is additive.

## Deliverables

In `rapid_reader/screens.py`, append:

```python
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
```

`BookInfoScreen` needs `Screen` imported in `screens.py` already (it is,
via `from contracts import Screen`) — no new import needed there. Add
`import books` if not already present (it is, from Phase 2A).

### `App.pop_to(screen_cls)` helper (add to `main.py`'s `App`)

`ChaptersScreen`/`BookmarksScreen`'s `activate()` needs to land back on
`PausedScreen` regardless of how deep the stack got (Paused ->
BookMenuScreen -> Chapters, three deep) — add this alongside `pop_to_root`:

```python
    def pop_to(self, screen_cls):
        """Pop until the top of the stack is an instance of screen_cls
        (inclusive check on the *next* one down); used by book-navigation
        screens to return to Paused after jumping. Assumes screen_cls is
        somewhere on the stack (true for every current call site)."""
        while len(self.stack) > 1 and not isinstance(self.stack[-1], screen_cls):
            self.pop()
        self.redraw()
```

### Wire into `BookMenuScreen.activate` (edit these three lines only)

```python
        elif item == "Chapters":
            app.push(ChaptersScreen())
        elif item == "Bookmarks":
            app.push(BookmarksScreen())
        elif item == "Book info":
            app.push(BookInfoScreen(app.book.title, app.book.path))
```

(Remove the corresponding three `self._not_yet(app, item)` lines. Leave
"Settings"/"System" as `self._not_yet(...)` — Phase 2C owns those.)

### Wire into `LibraryScreen.context_action`

Phase 2A's `LibraryScreen.context_action` already pushes
`BookInfoScreen(title, path)` (it was written expecting this phase to
add the class) — confirm this is present and correct; no edit needed
there if 2A already did it verbatim. If 2A instead pushed a
`MessageScreen` placeholder for this case, replace that one line the same
way as the `BookMenuScreen` lines above.

## Tests

Add to `tests/test_app.py` (or `test_screens.py`, matching whatever 2A
used):

- `ChaptersScreen`: `items()` matches `len(book.chapter_starts)`;
  `row_text` falls back to `"Chapter N"` for a book with no
  `chapter_titles` entry at that index (shouldn't happen given how
  `books.py` builds them, but the fallback should still be exercised);
  `activate()` sets `app.idx` and returns to `PausedScreen` from at least
  two stack depths (Paused -> BookMenu -> Chapters); empty-book case
  renders without crashing (`empty_lines`).
- `BookmarksScreen`: reflects `state.book(path)["bookmarks"]`
  (add/remove via `state.add_bookmark`/`remove_bookmark` between
  re-renders); `activate()` jumps `app.idx` and returns to Paused;
  `context_action` (`k3`) pushes a `ConfirmScreen`, and confirming (`k3`
  again on that screen) actually calls `state.remove_bookmark` and the
  bookmark is gone from `items()` afterwards; declining (any other key)
  leaves the bookmark in place.
- `BookInfoScreen`: constructed with a title/path, renders via
  `render.info_frame` with the right numbers pulled from
  `state.book(path)`; `k1` pops.
- `BookMenuScreen`: "Chapters"/"Bookmarks"/"Book info" now push the real
  screens (update/replace the Phase 2A placeholder-assertion tests for
  just these three items; leave the "Settings"/"System" placeholder
  assertions as they were — Phase 2C's job).
- Full round trip: from `PausedScreen`, `k2` -> `BookMenuScreen` ->
  "Bookmark this page" -> pop -> `k2` -> "Bookmarks" -> see the new entry
  -> `press` on it -> back on `PausedScreen` with `app.idx` at that word.

## Definition of done

- `python3 -m pytest -q` green.
- `BookMenuScreen`'s "Chapters", "Bookmarks", "Book info" items are fully
  live; "Settings" and "System" are still the Phase 2A placeholder
  (untouched by this phase).
- No changes to `App` other than the added `pop_to` method, and no
  changes to `ReadingScreen`/`PausedScreen`/`EndScreen`/`ListScreen`/
  `MessageScreen`/`ConfirmScreen`.
