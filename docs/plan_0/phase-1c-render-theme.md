# Phase 1C — Render / Theme

**Status:** done. **Depends on:** Phase 0 (`config.py`, `contracts.py`).
**Parallel with:** 1A, 1B, 1D, 3.

This is the most detailed prompt of the six Phase-1 docs on purpose: it has
the largest creative surface area (five theme presets, four pivot styles,
many frame types), and a nimble agent should be given pixel-level numbers
rather than asked to invent a look-and-feel. If anything below is
ambiguous, prefer the simplest, most legible interpretation over a
creative one — this is a 128x64 monochrome panel read at arm's length, not
a design showcase.

## Context you need

Read first:
- [`phase-0-contracts.md`](phase-0-contracts.md) — `contracts.Theme`,
  `config.OLED_W`/`OLED_H` (128x64), `config.FONT_DIRS`/`FONT_FACES`,
  `config.SETTINGS_DEFAULTS`.
- `rapid_reader/render.py` (current file, being replaced) — reuse its
  general shape and the parts of it that are pure layout math, unrelated
  to colour or the 240x240 canvas: `_font_dir()`/`_font()` caching,
  `_ellipsize()`, `_wrap()`, `fmt_minutes()`, `fmt_words()`, the
  fit-largest-size-that-fits loop used by `word_frame`/`_fit_chunk_orp`,
  and the ORP-splitting logic (`pre, ch, post = word[:orp], word[orp],
  word[orp+1:]`, using `rsvp.orp_index`).
- `rapid_reader/rsvp.py` — unchanged in this phase; you only call
  `rsvp.orp_index(word)`.
- `tests/test_render.py` (current file) — current coverage style
  (panel-sized/mode checks, pivot alignment, overflow handling) to mirror.

## The one thing that must change vs. the old file: no colour

The old `render.py` used an `ACCENT` RGB colour to mark the pivot letter
and highlighted rows. **The SH1106 is 1-bit monochrome — there is no third
colour.** Every place the old code used colour to communicate something,
the new code must use a graphical/typographic device instead: bold weight,
underline, an inverted (filled) box, or a corner tick mark. This is called
out explicitly because it is the single most likely mistake a fast port of
the old file would make.

## Deliverables

- **New** `rapid_reader/theme.py`.
- **Rewrite** `rapid_reader/render.py` (same filename).
- **Rewrite** `tests/test_render.py`.
- **New** helper needed by `tools/make_splash.py` (Phase 1A): a
  `render.splash()` function (see below) — if Phase 1A already stubbed a
  placeholder, replace it and update the one call site.

## `rapid_reader/theme.py`

```python
"""Theme presets and font resolution. No hardware, drawing only via render.py."""

import os
from PIL import ImageFont

import config
from contracts import Theme

THEMES = {
    "night": Theme("Night", invert=False, font_key="sans",  pivot_style="ticks",     contrast=0xCF),
    "paper": Theme("Paper", invert=True,   font_key="serif", pivot_style="underline", contrast=0xCF),
    "focus": Theme("Focus", invert=False,  font_key="sans",  pivot_style="box",       contrast=0xFF),
    "dim":   Theme("Dim",   invert=False,  font_key="mono",  pivot_style="bold",      contrast=0x40),
    "mono":  Theme("Mono",  invert=False,  font_key="mono",  pivot_style="ticks",     contrast=0xCF),
}
DEFAULT_THEME_KEY = "night"

_fonts = {}

def _face_dir(reg_name):
    for d in config.FONT_DIRS:
        if os.path.exists(os.path.join(d, reg_name)):
            return d
    raise FileNotFoundError("%r not found in %r" % (reg_name, config.FONT_DIRS))

def fonts(theme):
    """Return (regular_path, bold_path) for theme.font_key."""
    reg_name, bold_name = config.FONT_FACES[theme.font_key]
    d = _face_dir(reg_name)
    return os.path.join(d, reg_name), os.path.join(d, bold_name)

def font(theme, size, bold=False):
    """Cached ImageFont.truetype for this theme's face at `size`."""
    reg, bold_path = fonts(theme)
    path = bold_path if bold else reg
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]
```

`"night"` MUST remain `config.SETTINGS_DEFAULTS["theme"]`'s key — do not
rename it without also updating Phase 0's `config.py` (grep for
`"theme"` in `config.py` first if this file is written after Phase 0
lands, to double-check the key names agree).

Note the `"serif"`/`"mono"` font faces referenced by `FONT_FACES` need
actual font files installed — that package addition belongs to Phase 3;
if Phase 3 has not landed yet when you write this, it is fine for
`fonts()` to raise `FileNotFoundError` for those themes until it does —
that failure mode is expected and acceptable for a parallel in-flight
phase, not a bug in this one.

## `rapid_reader/render.py` — canvas and shared helpers

```python
W, H = config.OLED_W, config.OLED_H   # 128, 64
CENTER_Y = H // 2                     # 32

def _canvas():
    """Mode 'L' (8-bit grayscale, only 0/255 ever drawn), background 0
    (dark/off). All frame functions draw ink=255 on bg=0 regardless of the
    active theme -- theme.invert is applied once, later, by the driver
    (Phase 1A's SH1106.invert()) or by App just before oled.pack_pages(),
    NOT per-frame here. Keep that separation: render.py never needs to
    know whether invert is currently on."""
    from PIL import Image, ImageDraw
    img = Image.new("L", (W, H), 0)
    return img, ImageDraw.Draw(img)
```

Keep, port essentially unchanged (just re-point at the new canvas size and
drop the `w=` RGB-side-card-only parameter no longer needed):
`_ellipsize(draw, text, fnt, max_w)`, `_wrap(draw, text, fnt, max_w,
max_lines)`, `_center(draw, text, fnt, y, w=None, x0=0)` (drop the `fill`
argument — always `255`), `fmt_minutes(minutes)`, `fmt_words(n)`.

## Pivot styles — the no-colour replacement for `ACCENT`

Given `(pre, ch, post)` = the word split at its ORP (`rsvp.orp_index`), a
drawn bounding box for `ch` at `(x, y, x2, y2)`, and `theme.pivot_style`:

- **`"ticks"`**: draw `ch` in the **bold** font. Draw two short vertical
  guide lines centred on the pivot character's horizontal centre `cx`:
  from `(CENTER_Y - 16)` to `(CENTER_Y - 10)` above, and
  `(CENTER_Y + 10)` to `(CENTER_Y + 16)` below (scaled down from the old
  240px-tall `_TICK = (44, 58)` proportionally for a 64px-tall panel —
  adjust these two numbers if they visually collide with letters that
  have tall ascenders/descenders at the chosen font size; verify by eye
  once Phase 4 has a real panel, but they must not be adjustable per-theme
  — they are a fixed part of the `"ticks"` style).
- **`"underline"`**: draw `ch` in the **bold** font, plus a single
  horizontal line spanning exactly the pivot character's drawn width,
  2px below its baseline.
- **`"box"`**: draw a filled rectangle covering `ch`'s bounding box
  (regular weight is fine here, the box itself is the signal), then draw
  `ch` **in background colour (0)** on top of that filled rectangle —
  i.e. the pivot character appears as a "cutout", the monochrome
  equivalent of an inverted highlight. Leave a 1px padding around the
  glyph inside the box.
- **`"bold"`**: draw `ch` in the **bold** font. Nothing else — this is
  deliberately the minimal style.

`pre` and `post` are always drawn in the regular font weight, colour 255,
regardless of pivot style.

## `word_frame(word, theme, flash=None)`

Single most important frame — this is what's on screen during actual
reading, the vast majority of the time.

- Word size tiers (`config.SETTINGS_DEFAULTS`'s `word_size`, one of
  `"small"|"medium"|"large"`) each give a tuple of point sizes to try,
  largest first, same fit-or-shrink algorithm as the old file's
  `_WORD_SIZES` loop (try each size, keep the largest where
  `x0 >= 4 and x0 + total_width <= W - 4`, falling back to the old file's
  two-line hyphenation at the smallest size if nothing fits — port
  `_two_line_word` essentially unchanged, just re-centred for `H=64`
  using two lines at `CENTER_Y - 10` / `CENTER_Y + 10` and a smaller
  regular/bold pair, e.g. size 13):

  ```python
  _WORD_SIZE_TIERS = {
      "small":  (18, 15, 13, 11),
      "medium": (22, 19, 16, 13),
      "large":  (28, 24, 20, 16),
  }
  ```

- Horizontal placement: keep a fixed pivot column `PIVOT_X` (pick
  something around 40% of width, e.g. `PIVOT_X = 50`, biased left of
  centre since `post` is usually shorter than `pre` for common English
  ORP placement — verify empirically with the existing word list in
  `tests/test_render.py`'s fixtures and adjust the constant if words
  routinely clip on one side more than the other) exactly like the old
  file's `PIVOT_X = 96` did for the 240-wide panel — same algorithm,
  smaller numbers.
- `flash`: optional short string (e.g. `"275 wpm"`) drawn in a small
  filled-background box in the top-right corner (e.g. `(W-34, 2)` to
  `(W-2, 12)`, text inverted inside it same technique as the `"box"`
  pivot style) when not `None`. This is how the wpm-change indicator from
  the control map ("flashes in a corner") is implemented — `App` (Phase 2)
  decides for how many frames/seconds to keep passing a non-`None` value
  after a wpm change; `render.py` just draws it if given.

## `chunk_frame(words, theme)`

Multi-word fallback for when a frame render+push is slower than the
current word's delay (rare on this hardware per Phase 0's hardware
facts — SPI headroom is large — but keep the mechanism, it's cheap
insurance). Port the old `_fit_chunk_orp`/`chunk_frame` logic essentially
unchanged: same per-word ORP splitting, same "try each size, fall back to
plain ellipsized text" structure, re-fitted to `W=128`. Pivot styling
inside a chunk uses the same rules as `word_frame`.

## `list_frame(header, rows, sel, top, rows_visible=4, footer=None, note=None)`

The single generic primitive Phase 2's `ListScreen` base class uses for
every list-shaped screen (library, chapters, bookmarks, settings, themes,
system, book/main menus):

- Header band: `y=0..11`, bold ~11pt `header` text at `(3, 1)`; optional
  `note` (small ~9pt) right-aligned in the same band, ellipsized to leave
  the header room. Horizontal rule at `y=12`.
- Rows start at `y=14`, each `row_h = 12` px tall, `rows_visible` of them
  shown at once (4 fits `14 + 4*12 = 62 <= 64`). `rows` is a list of
  plain strings already prepared by the caller (screens.py formats
  whatever per-row text — e.g. a bookmark row already includes its word
  offset/percent, this function does not know about books/bookmarks).
- The row at index `sel` (absolute index into `rows`, not
  viewport-relative) is drawn **inverted**: a filled rectangle across the
  full row width, text drawn in colour 0 on top of it — this replaces the
  old accent-coloured highlight bar, no colour needed.
- Scroll indicators: small filled triangles at the top-right / bottom-
  right of the row band when `top > 0` / more rows exist below the
  viewport — port the old file's triangle `d.polygon(...)` calls,
  re-scaled.
- `footer`: optional line of small text at `y=H-9` (e.g. "3 / 12" position
  indicator, or a hint line) — plain text, not inverted.
- Empty state (`rows` is empty): draw 2-3 lines of small plain text passed
  in by the caller (e.g. "No books found." + where to copy them) instead
  of an empty list — mirror the old `menu()` function's empty-library
  message, shortened to fit 128px width.

## `paused_frame(title, words, idx, sentence_start, wpm, progress, theme)`

Context view shown when paused (see the control map in Phase 0 — this
replaces the old three-screen "paused" behaviour with everything on one
128x64 frame, so it necessarily shows less surrounding text than the old
240x240 version did):

- Header band same as `list_frame`'s: bold title (ellipsized) at `(3,1)`,
  `"NN%  NNN wpm"` right-aligned in the same band at small size, rule at
  `y=12`.
- Body: word-wrap **only the current sentence** (from `sentence_start` to
  the next sentence boundary, or to `idx`'s containing sentence — do not
  attempt to also show trailing/future sentences the way the old 240x240
  version did; there is not enough room, and faking "dimmed" text without
  colour is not worth the complexity) starting at `(3, 15)`, line height
  11px, as many lines as fit in `15..H-2` (≈4 lines). The current word
  (`words[idx]`) is drawn **bold and underlined** (again: weight +
  underline stand in for the old accent colour); the rest of the sentence
  is regular weight. If the sentence overflows the available lines,
  ellipsize the last visible line exactly like `_wrap` already does.

## `info_frame(title, ext, position, total_words, wpm, time_read_secs)`

Book-info screen (`K3` from the library, per the control map): a simple
stack of left-aligned lines under a `list_frame`-style header (reuse the
header band exactly), e.g.:

```
<ellipsized title, wrapped to 2 lines if needed>
Format: EPUB
Length: 42.3k words
Progress: 61%  ·  3h 20m left
Time read: 2h 05m
```

Plain text, one line per fact, ~12px line height, starting at `y=14`; no
selection/highlighting (this is a read-only screen, `K1` just pops it).

## `message_frame(lines, hint=None, big=None)`, `confirm_frame(text, yes_hint, no_hint)`, `end_frame(title)`

Port the old `message()`/`confirm_power()`/`the_end()` essentially
unchanged, just centred for `128x64` instead of `240x240`, and dropping
`fill=ACCENT` in favour of `fill=255` everywhere (no colour distinction
between "big" text and normal lines any more — use size alone, exactly
like the old code already did with `bf = _font(_BOLD, 26)` vs. `f =
_font(_BOLD, 18)`, just smaller numbers for this panel, e.g. 16pt "big" /
11pt normal). `confirm_frame` replaces the old hardcoded
`confirm_power()` with a generic version so Phase 2 can also use it for
"delete this bookmark?" / "delete this book?" (the `K3` context actions
from the control map) without adding a new render function per confirm
dialog.

## `splash()`

A single static frame for the boot splash (used once by
`tools/make_splash.py`, Phase 1A): port the spirit of the old
`splash_main()` — "Rapid Reader" with the pivot letter (`orp_index` of
"Rapid") in bold, small tick marks — centred on the 128x64 canvas, no side
panels to also render any more (the old file's `splash_side()` has no
replacement — delete it).

## `tests/test_render.py` — required coverage

Mirror the old file's structure at the new canvas size, in mode `"L"`:
- Every frame function returns a `128x64`, mode `"L"` image using only
  values `0`/`255`.
- `word_frame`: the pivot character sits on the fixed `PIVOT_X` regardless
  of word length (for words that fit at the largest tier size); each of
  the 4 `pivot_style` values produces a visibly different pixel pattern
  around the pivot character (assert on concrete pixel checks — e.g.
  `"ticks"` has lit pixels at the expected tick coordinates and
  `"underline"` does not, and vice versa); an over-long word shrinks
  through the size tiers and eventually hyphenates onto two lines rather
  than clipping at the panel edge (check no lit pixel exists at column 0
  or column 127 for a deliberately huge fake word, mirroring the old
  clip-safety tests).
- `list_frame`: selection row is inverted (its background is mostly `255`
  where other rows are mostly `0`); scroll indicators appear only when
  there is in fact more content above/below the viewport; empty state
  renders without raising.
- `paused_frame`: current word is distinguishable (bold+underline) from
  the rest of the sentence; overflow stays inside the frame (no assertion
  failure from `_wrap`/`_ellipsize` on a very long synthetic sentence).
- `theme.fonts()`/`theme.font()` resolve for at least `"night"`, `"focus"`,
  `"dim"` (the themes using `"sans"`/`"mono"` — safe even before Phase 3
  adds serif/mono packages, since DejaVuSansMono ships with
  `fonts-dejavu-core` already; only `"paper"`'s `"serif"` face may need
  Phase 3's package — skip/xfail that one case with a comment if the font
  file genuinely isn't present in the test environment yet).

## Definition of done

- `python3 -m pytest -q` green.
- `rapid_reader/theme.py` exists with `THEMES`, `DEFAULT_THEME_KEY`,
  `fonts()`, `font()`.
- No RGB colour anywhere in `render.py` — grep for `ACCENT`, `FG`, `DIM`,
  `(255,` style RGB tuples and confirm none remain; every draw call uses a
  single integer `fill=` (0 or 255) or no `fill=` argument at all when
  drawing on an already-correct-value shape.
- `rapid_reader/render.py` no longer references three screens/side cards
  anywhere (grep for `SW`, `SH`, `_side`, `book_card`, `speed_card`,
  `progress_card`, `hints_card`, `splash_side` — none should remain).

## Non-goals

- Do not implement `App`, the screen stack, or state loading — `render.py`
  functions take plain arguments (strings, ints, a `Theme`) and know
  nothing about `books.Book`, `state.py`'s schema, or navigation. That
  wiring is Phase 2's job.
- Do not add a fifth pivot style or additional theme presets beyond the
  five named ones without flagging it — Phase 2's Settings/Themes screens
  will enumerate exactly `theme.THEMES` and exactly the four pivot styles
  named in Phase 0's contract.
