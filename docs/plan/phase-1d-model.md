# Phase 1D — Model

**Status:** not started. **Depends on:** Phase 0 (`config.py`, `contracts.py`).
**Parallel with:** 1A, 1B, 1C, 3.

## Context you need

Read first:
- [`phase-0-contracts.md`](phase-0-contracts.md) — the state v2 schema and
  `config.SETTINGS_DEFAULTS`, `config.MIN_WPM`/`MAX_WPM`/`STATE_FILE`/
  `STATE_DIR`.
- `rapid_reader/main.py` lines 53-84 — the current `State` class (v1
  schema) you are replacing with a standalone `state.py` module.
- `rapid_reader/rsvp.py` — current `word_delay()`, being extended with a
  new optional parameter, not restructured.
- `rapid_reader/books.py` — current `Book`/`_tokenize`/`scan_library`;
  being extended, not restructured. Pay particular attention to
  `_tokenize`'s chapter-heading detection (`_looks_like_chapter_heading`,
  `_CHAPTER_MARK`) since you are adding a parallel `chapter_titles` list
  alongside the existing `chapter_starts`.
- `tests/test_books.py`, `tests/test_rsvp.py` — current coverage to
  extend.
- `CONTROLS.md`'s old state file description and `README.md`'s "Device
  layout" section, for the v1 shape you're migrating away from.

## Deliverables

- **New** `rapid_reader/state.py` (there is currently no such file — the
  old `State` class lived inside `main.py`; it moves out and gains the v2
  schema).
- **Extend** `rapid_reader/rsvp.py`: `word_delay()` gains a `weights=`
  parameter.
- **Extend** `rapid_reader/books.py`: chapter titles + a pure recency-sort
  helper.
- **New** `tests/test_state.py`.
- **Extend** `tests/test_rsvp.py`, `tests/test_books.py`.

Do **not** remove `main.py`'s current `State` class yet — Phase 2 is what
actually deletes it and switches `App` over to `state.State`. Leaving it
in place (even though it becomes dead code once Phase 2 lands) means this
phase's tests don't depend on Phase 2 having landed first, and vice versa.

## `rapid_reader/state.py`

### Schema (must match Phase 0's contract exactly)

```python
SCHEMA_VERSION = 2

# on-disk shape:
# {
#   "version": 2,
#   "settings": {...config.SETTINGS_DEFAULTS shape...},
#   "last_book": "<path>" | null,
#   "in_book": bool,
#   "books": {
#     "<path>": {
#       "position": int,           # word index
#       "total_words": int,
#       "time_read_secs": float,
#       "bookmarks": [int, ...],   # sorted word indices
#       "last_opened": float,      # unix epoch seconds
#     }, ...
#   }
# }
```

### Validation (self-contained — do not import `theme.py` from here; that
would couple this phase to Phase 1C's naming while both are in flight.
Hardcode the allowed sets, which are part of Phase 0's frozen contract):

```python
_PIVOT_STYLES = ("ticks", "underline", "box", "bold")
_WORD_SIZES = ("small", "medium", "large")

def _clean_settings(raw):
    out = dict(config.SETTINGS_DEFAULTS)
    wpm = raw.get("wpm")
    if isinstance(wpm, (int, float)):
        out["wpm"] = max(config.MIN_WPM, min(config.MAX_WPM, int(wpm)))
    theme = raw.get("theme")
    if isinstance(theme, str):
        out["theme"] = theme   # existence in theme.THEMES is checked by
                                # the caller (Phase 2), not here -- this
                                # module must not import theme.py
    pivot = raw.get("pivot_style")
    if pivot in _PIVOT_STYLES:
        out["pivot_style"] = pivot
    size = raw.get("word_size")
    if size in _WORD_SIZES:
        out["word_size"] = size
    return out
```

### `State` class

```python
class State:
    def __init__(self, path=None):
        self.path = path or config.STATE_FILE
        self.settings = dict(config.SETTINGS_DEFAULTS)
        self.last_book = None
        self.in_book = False
        self.books = {}          # path -> book-record dict, v2 shape
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
        """Atomic write: tmp file + os.replace, same pattern as the old
        main.py State.save(); swallow OSError with traceback.print_exc(),
        do not raise (the app must keep running if the disk is briefly
        unwritable)."""

    def book(self, path):
        """Return this path's record, creating a fresh default one
        (position=0, total_words=0, time_read_secs=0.0, bookmarks=[],
        last_opened=0.0) in self.books if it doesn't exist yet. Does not
        write to disk -- caller still calls save()."""

    def touch_book(self, path, **fields):
        """Update only the given fields (e.g. position=, total_words=,
        time_read_secs=, last_opened=) on book(path); merges, does not
        replace bookmarks unless explicitly passed."""

    def add_bookmark(self, path, idx):
        """Insert idx into book(path)'s bookmarks, keeping it sorted and
        de-duplicated."""

    def remove_bookmark(self, path, idx):
        """Remove idx from book(path)'s bookmarks if present; no error if
        absent."""
```

### `migrate_v1(data)`

Old (v1) on-disk shape, from the current `main.py` `State`:
`{"wpm": int, "positions": {path: idx}, "totals": {path: total},
"last_book": path|None, "in_book": bool}` (no `"version"` key at all —
that absence, or `version < 2`, is what triggers migration).

```python
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
        "settings": {**config.SETTINGS_DEFAULTS, "wpm": data.get("wpm", config.DEFAULT_WPM)},
        "last_book": data.get("last_book"),
        "in_book": bool(data.get("in_book", False)),
        "books": books,
    }
```

Migration must be **read-only on the old file** — `State.save()` always
writes the v2 shape; the original v1 file is never mutated in place
(overwritten only via the normal tmp+rename `save()` path, and only once
the app actually saves for some other reason). Don't add a separate
"migrate and immediately re-save" step; loading is enough.

## `rapid_reader/rsvp.py` — `word_delay` weights

```python
DEFAULT_WEIGHTS = {"long": 0.4, "clause": 0.7, "sentence": 1.5, "para": 1.0}

def word_delay(word, wpm, is_para_end=False, weights=None):
    """Seconds to show a word. `weights` (optional) overrides any subset
    of DEFAULT_WEIGHTS's keys; unspecified keys keep their default."""
    w = DEFAULT_WEIGHTS if weights is None else {**DEFAULT_WEIGHTS, **weights}
    base = 60.0 / wpm
    d = base
    start, end = core_span(word)
    if end - start >= 9:
        d += base * w["long"]
    tail = word[end:] if end < len(word) else ""
    if any(c in tail for c in ".!?"):
        d += base * w["sentence"]
    elif any(c in tail for c in ",;:\u2014"):
        d += base * w["clause"]
    if is_para_end:
        d += base * w["para"]
    return d
```

This must be **behaviourally identical to the current function when
called without `weights`** — the numeric constants above are exactly the
current hardcoded ones (`0.4`, `0.7`, `1.5`, `1.0`); this is a pure
refactor for future extensibility (Phase 2 does not need to add a "pacing"
setting to use this — that's optional future work, not required now), not
a behaviour change. Add a regression test asserting
`word_delay(w, wpm, is_para_end)` (no `weights` arg) returns the same
value before and after this change for a handful of representative words.

## `rapid_reader/books.py` — chapter titles + recency sort

### Chapter titles

`_tokenize` currently returns `(words, sentence_starts, para_ends,
chapter_starts)`. Extend it to also return `chapter_titles`, a list
parallel to `chapter_starts` (same length, same order) holding the
heading text as a plain string (the detected heading paragraph's tokens
joined with a single space, e.g. `"Chapter 12"`, `"XIV"`, or `"I. A
SCANDAL IN BOHEMIA"`). Capture this at the same point `chapter_starts`'s
entry is appended (i.e. right where `is_chapter` is `True` in the current
loop over `toks`) — join whatever `toks` list is used for that heading
paragraph, **before** the `_CHAPTER_MARK` sentinel is stripped out. Update
`Book.__init__`/`Book.load` to accept and store `chapter_titles` as a new
attribute (default `()` like `chapter_starts` already defaults).

Add a method:

```python
def chapter_title(self, idx):
    """Title of the chapter containing word index `idx`, or None if this
    book has no detected chapters. Same bisect logic App.chapter_pos()
    already uses in main.py to find which chapter idx falls in -- reuse
    that exact approach (bisect_right on self.chapter_starts)."""
    if not self.chapter_starts:
        return None
    i = bisect.bisect_right(self.chapter_starts, idx) - 1
    if i < 0:
        return None
    return self.chapter_titles[i]
```

(`import bisect` at the top of `books.py` if not already present.)

### Recency sort — pure function, no `State` import

```python
def sort_by_recency(library, last_opened):
    """library: list of (title, path), as returned by scan_library().
    last_opened: {path: epoch_seconds, ...} -- caller passes
    {p: r["last_opened"] for p, r in state.books.items()} or similar; this
    function does not import state.py, keeping books.py free of that
    dependency. Returns a new list: books with a last_opened timestamp
    first (most recent first), then never-opened books after them sorted
    by title (case-insensitive), matching scan_library()'s existing sort
    for that group."""
    def key(item):
        title, path = item
        t = last_opened.get(path)
        return (0, -t) if t else (1, title.lower())
    return sorted(library, key=key)
```

`scan_library()` itself is unchanged (still returns title-sorted, still
the default library order) — `sort_by_recency` is an explicit opt-in the
Settings/Library screen (Phase 2) can call when the user picks "recently
read" ordering.

## Tests

### `tests/test_state.py` (new)

- Fresh `State` (no file on disk) has `config.SETTINGS_DEFAULTS`,
  `last_book=None`, `in_book=False`, `books={}`.
- `save()` then a new `State(path=...)` round-trips settings/last_book/
  in_book/books exactly.
- `book(path)` creates a default record on first access; `touch_book`
  updates only the given fields; `add_bookmark`/`remove_bookmark` keep
  the list sorted/deduplicated and are idempotent.
- `migrate_v1`: feed a v1-shaped dict (as `main.py`'s old `State.save()`
  would have written), assert the v2 result has the right `books` entries
  built from `positions`/`totals`, `settings.wpm` carried over, and
  `version == 2`. Also test loading a v1 file end-to-end through
  `State.__init__` (write v1 JSON to `tmp_path`, construct `State`, check
  the resulting in-memory shape) — do not just unit-test `migrate_v1` in
  isolation.
- `_clean_settings` rejects out-of-range `wpm` (clamped to
  `MIN_WPM`/`MAX_WPM`) and invalid `pivot_style`/`word_size` values
  (falls back to `config.SETTINGS_DEFAULTS`'s value), and passes through
  valid ones including an arbitrary `theme` string (validity of the theme
  key itself is explicitly **not** this module's job — see above).
- `save()` is atomic (write to `path + ".tmp"`, `os.replace`) and does not
  raise if the containing directory doesn't exist yet — mirror the old
  `main.py` `State.save()`'s `os.makedirs(..., exist_ok=True)` /
  `except OSError: traceback.print_exc()` behaviour.

### `tests/test_rsvp.py` (extend)

- `word_delay(word, wpm, is_para_end)` without `weights` matches the
  previous hardcoded-constant behaviour for representative cases (short
  word, long word ≥9 core chars, word ending in `.`/`,`, paragraph end).
- `weights={"sentence": 0.0}` (etc., one override) changes only that
  component of the delay, leaving the others at their defaults.

### `tests/test_books.py` (extend)

- A synthetic plain-text book with a couple of `"Chapter N"` headings:
  `chapter_titles` has the same length as `chapter_starts` and the right
  text at each index; `Book.chapter_title(idx)` returns the right title
  for indices before/at/after each heading, and `None` for a book with no
  detected chapters.
- A synthetic EPUB with `<h1>`/`<h2>` headings: same checks, confirming
  the heading text captured is the tag's text content, not including the
  `_CHAPTER_MARK` sentinel.
- `sort_by_recency`: a library of a few `(title, path)` pairs, some with
  `last_opened` entries (most-recent-first among those) and some without
  (title-sorted, placed after all timestamped ones).

## Definition of done

- `python3 -m pytest -q` green, including new `test_state.py` and the
  extensions to `test_rsvp.py`/`test_books.py`.
- `rapid_reader/state.py` importable standalone with no Pillow/gpiozero/
  spidev/lgpio dependency (`python3 -c "import state"` from
  `rapid_reader/`, on a machine with none of those installed, must work).
- `main.py`'s current `State` class is left untouched (still present,
  still used by the current `App` — Phase 2 removes it).

## Non-goals

- Do not wire `state.State` into `main.py`/`App` — that's Phase 2.
- Do not add a UI for editing settings — that's Phase 2's Settings screen.
- Do not import `theme.py` from `state.py` (see validation note above).
