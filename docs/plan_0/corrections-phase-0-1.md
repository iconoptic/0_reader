# Corrections — Phase 0 / 1A / 1B / 1C / 1D review

**Status of the review:** Phases 0, 1A, 1B, 1C and 1D have all landed in
the repo (`rapid_reader/config.py`, `contracts.py`, `oled.py`, `display.py`,
`buttons.py`, `theme.py`, `render.py`, `state.py`, plus the `rsvp.py` /
`books.py` additions, and their tests). `python3 -m pytest -q` is green:
**121 passed, 19 skipped** — the 19 skips are all in `tests/test_app.py`,
explicitly marked `"Phase 2: App still targets the three-panel Display
API"`; that file is untouched on purpose and is Phase 2's job, not a
regression.

**Overall verdict: no blocking bugs.** The implementations match their
phase docs closely, in some places going beyond the spec in ways worth
keeping (see "Good deviations worth knowing about" below, since Phase 2
must build against the *actual* signatures, not the originally-guessed
ones). There are three small, non-blocking issues below — none of them
affect current test results, but two are worth a quick fix before Phase 2
starts depending on this code, and the third is a cleanup item to assign
explicitly to Phase 2 rather than leave as a dangling comment.

This doc is itself a nimble-sized task: apply the two code fixes below,
confirm the full suite is still green, done.

## Fix 1 — `state.py`: `_clean_book_record` can alias the shared default `bookmarks` list

`rapid_reader/state.py`, `_BOOK_DEFAULTS` is a module-level dict whose
`"bookmarks"` value is a single list object `[]`. `_clean_book_record`
does `out = dict(_BOOK_DEFAULTS)` (a shallow copy — `out["bookmarks"] is
_BOOK_DEFAULTS["bookmarks"]` until reassigned) and only reassigns
`out["bookmarks"]` when the raw record's `"bookmarks"` field is a valid
list:

```python
def _clean_book_record(raw):
    out = dict(_BOOK_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    ...
    marks = raw.get("bookmarks")
    if isinstance(marks, list):
        cleaned = sorted({int(m) for m in marks if isinstance(m, (int, float))})
        out["bookmarks"] = cleaned
    return out
```

If two different book paths in the same state file both lack a valid
`"bookmarks"` field, both records end up sharing the exact same list
object (and that object is `_BOOK_DEFAULTS["bookmarks"]` itself). Every
current caller (`add_bookmark`/`remove_bookmark`/`touch_book`) happens to
always *reassign* `rec["bookmarks"]` rather than mutate it in place, so
this is currently harmless — but it is a footgun for Phase 2, which is
free to read `app.state.book(path)["bookmarks"]` directly (per
`phase-2-app.md`'s `BookmarksScreen` row). A future in-place mutation
(e.g. `.append(...)`) on one book's list would silently corrupt every
other book's bookmarks and the shared default itself.

**Fix:** always give each record its own list, both here and (for
consistency/defence-in-depth, even though it already does this correctly)
in `State.book()`:

```python
def _clean_book_record(raw):
    out = dict(_BOOK_DEFAULTS)
    out["bookmarks"] = []
    if not isinstance(raw, dict):
        return out
    ...
```

(Keep the existing `if isinstance(marks, list): out["bookmarks"] =
cleaned` branch below it unchanged — it will just be overwriting the
fresh `[]` instead of the shared one when a valid list is present.)

Add a regression test to `tests/test_state.py` asserting no aliasing,
e.g.:

```python
def test_clean_book_record_bookmarks_not_shared(tmp_path):
    path = str(tmp_path / "state.json")
    with open(path, "w") as f:
        json.dump({"version": 2, "books": {"/a.txt": {}, "/b.txt": {}}}, f)
    s = state.State(path=path)
    assert s.books["/a.txt"]["bookmarks"] is not s.books["/b.txt"]["bookmarks"]
    s.books["/a.txt"]["bookmarks"].append(1)
    assert s.books["/b.txt"]["bookmarks"] == []
    assert state._BOOK_DEFAULTS["bookmarks"] == []
```

## Fix 2 — `render.py`: `chunk_frame` ignores `word_size`

`word_frame(word, theme, flash=None, word_size=None)` (the actual,
already-implemented signature — see below) picks its glyph-size tier from
`word_size`, defaulting to `config.SETTINGS_DEFAULTS["word_size"]`. The
chunked fallback path (`chunk_frame` / its helper `_fit_chunk_orp`) does
not take a `word_size` parameter at all — it always tries
`_WORD_SIZE_TIERS["medium"]`. This means a user who sets `word_size` to
`"small"` or `"large"` will see chunk frames (used when wpm outpaces the
frame rate) rendered at the wrong size relative to normal word frames.
Low-severity, but Phase 2 will call both functions with the same theme
and should not have to work around a size-mismatch that is not documented
anywhere.

**Fix:** thread `word_size` through, mirroring `word_frame`:

```python
def _fit_chunk_orp(d, words, theme, word_size=None):
    sizes = _WORD_SIZE_TIERS.get(word_size, _WORD_SIZE_TIERS["medium"])
    ...

def chunk_frame(words, theme, word_size=None):
    img, d = _canvas()
    fitted = _fit_chunk_orp(d, words, theme, word_size)
    ...
    sizes = _WORD_SIZE_TIERS.get(word_size, _WORD_SIZE_TIERS["medium"])
    ...
```

(Both call sites inside `chunk_frame` that currently read
`_WORD_SIZE_TIERS["medium"]` directly need the same `.get(word_size,
_WORD_SIZE_TIERS["medium"])` swap.) Add one assertion to the existing
`test_chunk_frame_keeps_orp_when_it_fits_else_plain` (or a new small test)
that `chunk_frame(["a", "b"], theme, word_size="large")` differs from the
default-size result.

## Fix 3 (not a code change here — a Phase 2 checklist item)

`config.py` still carries a block of old LCD-HAT constants (`MAIN`,
`LEFT`, `RIGHT`, `MAIN_W/H`, `SIDE_W/H`, `*_ROTATE_180`, `SWAP_SIDES`,
`BACKLIGHT_PWM_HZ`, `BL_*`, `TAP_WINDOW`, `HOLD_TIME`), explicitly
commented `# --- Temporary: LCD HAT (remove in Phases 1A / 1B / 2) ---`.
This is a deliberate, correctly-flagged compromise (not a bug) — it keeps
the current `rapid_reader/main.py` and `tests/test_app.py` importable
until Phase 2 replaces them; deleting it now would break the tree for no
benefit. Confirmed the only remaining references are in `main.py`,
`tests/test_app.py`, and `tools/build_card.sh` (Phase 3's file) — nothing
in the already-landed Phase 0/1A/1B/1C/1D code touches it.

**Action:** this is now an explicit deliverable of
[`phase-2d-integration.md`](phase-2d-integration.md) (see its Definition
of done) rather than a dangling comment — Phase 2 must delete this block
from `config.py` once `main.py`/`test_app.py` no longer need it.

## Good deviations worth knowing about (not bugs — use these, not the originally-guessed ones)

The implementations closed a couple of gaps the phase docs left open, in
sensible ways. Phase 2 (and its split, `phase-2a`.."phase-2d") must code
against the **actual** shapes below:

- `render.word_frame(word, theme, flash=None, word_size=None)` — the
  `word_size` parameter (not in the original `phase-1c-render-theme.md`
  text) is how the caller selects the small/medium/large tier; pass
  `app.state.settings["word_size"]`.
- Every frame function ends by running the whole image through
  `_finalize()`, which thresholds antialiased text edges back to strict
  0/255 — this is what makes `_only_01(img)`-style assertions hold; you
  do not need to (and should not) do your own thresholding on frames
  coming out of `render.py`.
- `display.Display` methods: `show(image)`, `contrast(value)`,
  `invert(on)`, `splash(path=None) -> bool`, `sleep()`, `wake()`.
  `display.open_display(retry_secs=None, log=print) -> Display` already
  applies `config.IDLE_ACTIVE_CONTRAST` as a boot-time default — Phase 2
  does not need to set an initial contrast itself, only react to theme
  changes afterwards.
- `buttons.Input(on_event, button_cls=None)` exposes `.keys: dict[str,
  Key]`; `Key(name, on_event, repeats, button=None)`.
- `state.State(path=None)`: `.settings`, `.last_book`, `.in_book`,
  `.books` (dict keyed by path); `.book(path) -> dict` (creates on first
  access, with its own fresh `bookmarks` list — see Fix 1),
  `.touch_book(path, **fields)`, `.add_bookmark(path, idx)`,
  `.remove_bookmark(path, idx)`, `.save()`.
- `theme.THEMES: dict[str, Theme]`, `theme.DEFAULT_THEME_KEY`,
  `theme.font(theme, size, bold=False)` (cached), `theme.fonts(theme) ->
  (regular_path, bold_path)`.
- `books.Book.load(path)`, `.chapter_title(idx) -> str | None`,
  `.chapter_starts`, `.chapter_titles`, `.sentence_starts`, `.para_ends`,
  `books.scan_library(directory=None)`, `books.sort_by_recency(library,
  last_opened)`.
- `rsvp.word_delay(word, wpm, is_para_end=False, weights=None)`,
  `rsvp.orp_index(word)`, `rsvp.core_span(word)`.
- DejaVu Serif and DejaVu Sans Mono are already present alongside DejaVu
  Sans on a standard `ttf-dejavu`/`fonts-dejavu-core` install (confirmed
  on this dev box) — `theme.THEMES["paper"]`/`["dim"]`/`["mono"]` resolve
  fonts without any package install; `test_theme_paper_serif_or_xfail` in
  `tests/test_render.py` xfails gracefully only on a system that is
  missing the face, so Phase 3 likely has nothing to add here — confirm
  during Phase 3, don't assume a package is required.

## Definition of done

- Fix 1 and Fix 2 applied exactly as above (or an equivalent fix — the
  requirement is "no shared mutable default" and "`chunk_frame` honours
  `word_size` the same way `word_frame` does").
- The two new/extended tests pass.
- `python3 -m pytest -q` still reports `121+ passed` (two more once the
  new assertions land) with the same 19 intentional `test_app.py` skips —
  no other file changes.
