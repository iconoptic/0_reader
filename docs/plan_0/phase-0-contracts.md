# Phase 0 — Contracts

**Status:** not started. **Depends on:** nothing (must land first). **Repo
baseline:** current `main` — still the Waveshare Zero LCD HAT (A) build.

## Context you need

Rapid Reader is being ported from a three-LCD, two-key HAT to a new
**1.3" SH1106 OLED HAT**: 128x64, **monochrome (1-bit)**, driven over 4-wire
SPI, with a 5-way joystick + 3 buttons for input. The old side-screen
cards go away; the app becomes a small screen-stack e-reader (library, book
menu, chapters, bookmarks, settings, themes, system page) built around the
existing RSVP word-flash core, which is kept.

This phase does **not** touch hardware or rendering. It only rewrites
`rapid_reader/config.py` and adds the shared interfaces/dataclasses that
every later phase imports, so that Phases 1A/1B/1C/1D/2 can be built in
parallel against a fixed contract instead of guessing at each other's
shape.

Read these existing files first (for context on current conventions, not to
preserve their content — most of it is being replaced):
- `rapid_reader/config.py` — current pins/constants; you are rewriting this
  file.
- `rapid_reader/main.py` lines 53-110 — current `State`/`App.__init__` for
  reference on what data the app already tracks (positions, totals,
  last_book, in_book, wpm).
- `CONTROLS.md` and `README.md` — old control scheme, being replaced by the
  one below.

## Hardware facts (do not re-derive; verified against the Waveshare wiki and
the SH1106 datasheet at `datasheets/SH1106.pdf`)

- OLED on **SPI0 CE0**: MOSI = BCM 10, SCLK = BCM 11, CS = BCM 8 (handled by
  the kernel spidev driver, not GPIO), DC = BCM 24, RST = BCM 25.
- No backlight pin — brightness is set purely via the SH1106 contrast
  command (`0x81`).
- Buttons, all **active-low with internal pull-ups**:
  - K1 = BCM 21, K2 = BCM 20, K3 = BCM 16
  - Joystick UP = BCM 6, DOWN = BCM 19, LEFT = BCM 5, RIGHT = BCM 26,
    PRESS = BCM 13
- Panel is monochrome only — no colour, no grayscale. Every later phase's
  "theme" is limited to invert / font / pivot style / word size / contrast,
  never colour.

## Deliverables

### 1. `rapid_reader/config.py` — full rewrite

Replace the whole file. Required contents (exact names — other phases
import these by name):

```python
# --- OLED (SPI0 CE0) ------------------------------------------------
OLED_SPI = (0, 0)          # (bus, device) for spidev.SpiDev().open(*OLED_SPI)
OLED_DC = 24
OLED_RST = 25
OLED_SPEED_HZ = 4_000_000  # SH1106 spec max
OLED_W, OLED_H = 128, 64
OLED_COL_OFFSET = 2        # SH1106 has 132-col RAM, 128 visible columns
GPIO_CHIP = 0

# Single flag flips the panel 180 degrees *and* swaps the joystick's
# up/down/left/right mapping to match, so the physical "up" on the board
# is always logical "up" regardless of mounting orientation.
ROTATE_180 = False

# --- Keys (BCM, active low, pull-ups) -------------------------------
PIN_KEY1, PIN_KEY2, PIN_KEY3 = 21, 20, 16
PIN_JOY_UP, PIN_JOY_DOWN = 6, 19
PIN_JOY_LEFT, PIN_JOY_RIGHT = 5, 26
PIN_JOY_PRESS = 13

# name -> BCM pin; single source of truth for buttons.Input. Names are the
# canonical event names used everywhere else (see event tuple below).
PINS = {
    "up": PIN_JOY_UP, "down": PIN_JOY_DOWN,
    "left": PIN_JOY_LEFT, "right": PIN_JOY_RIGHT, "press": PIN_JOY_PRESS,
    "k1": PIN_KEY1, "k2": PIN_KEY2, "k3": PIN_KEY3,
}
# Keys that auto-repeat while held (list navigation); the rest fire "hold"
# once and do not repeat.
REPEATING_KEYS = ("up", "down", "left", "right")

# --- Input timing (seconds) -----------------------------------------
HOLD_DELAY = 0.5     # how long a key must be held before "hold" (or the
                      # first "repeat") fires
REPEAT_SECS = 0.12   # interval between "repeat" events while still held

# --- Paths (unchanged from the LCD build) ---------------------------
BOOKS_DIR = "/home/reader/ebooks"
STATE_DIR = "/var/lib/rapid-reader"
STATE_FILE = STATE_DIR + "/state.json"
SPLASH_DIR = "/opt/rapid-reader/splash"
HW_RETRY_SECS = 40.0

# --- Reading ---------------------------------------------------------
DEFAULT_WPM = 250
MIN_WPM = 60
MAX_WPM = 900
WPM_STEP = 25
SAVE_EVERY_WORDS = 100
PANEL_REFRESH_SECS = 0.02   # SH1106 full frame ~5ms @ 4MHz; seed low

# --- Idle / burn-in protection ---------------------------------------
IDLE_DIM_SECS = 60      # no input for this long outside READING -> dim
IDLE_OFF_SECS = 300     # no input for this long -> display off (sleep)
IDLE_DIM_CONTRAST = 0x20
IDLE_ACTIVE_CONTRAST = 0xCF

# --- Fonts -------------------------------------------------------------
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF",
             "/usr/share/fonts/dejavu")
# Bundled font faces theme.py maps to font_key: "sans" | "serif" | "mono".
# Sans reuses DejaVu (already required); serif/mono need a package added in
# Phase 3 — see that phase doc for the exact package name/paths.
FONT_FACES = {
    "sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
    "mono": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
}

# --- Settings (state v2 defaults; state.py imports this) --------------
SETTINGS_DEFAULTS = {
    "wpm": DEFAULT_WPM,
    "theme": "night",          # key into theme.THEMES
    "pivot_style": "ticks",    # ticks | underline | box | bold
    "word_size": "medium",     # small | medium | large
}
```

Do not invent additional constants beyond these unless a later phase's doc
explicitly asks you to add one here — keep this file the single source of
truth other phases can rely on without re-checking.

### 2. New file `rapid_reader/contracts.py`

A tiny module (no hardware imports, no Pillow) holding the shared
interfaces so Phase 1C/1D/2 don't have circular-import into each other:

```python
"""Shared interfaces for the screen-stack app. No hardware, no Pillow."""

from dataclasses import dataclass


# ---- input event -------------------------------------------------------
# Every button/joystick callback enqueues one of these. `name` is one of
# config.PINS's keys ("up","down","left","right","press","k1","k2","k3").
# `kind` is "tap" (press+release under HOLD_DELAY), "hold" (held past
# HOLD_DELAY, key not in config.REPEATING_KEYS — fires once), or "repeat"
# (held past HOLD_DELAY, key in config.REPEATING_KEYS — fires every
# REPEAT_SECS until release; no separate "hold" event is sent for these
# keys).
#
# Event = tuple[str, str]   # (name, kind)


# ---- theme --------------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    """One named look. All fields are required; presets live in theme.py."""
    name: str
    invert: bool          # False: normal SH1106 polarity (lit pixels = ink
                           # on a dark field). True: inverted (SH1106 INVERT
                           # command), i.e. mostly-lit field, dark ink.
    font_key: str          # "sans" | "serif" | "mono" -> config.FONT_FACES
    pivot_style: str        # "ticks" | "underline" | "box" | "bold"
    contrast: int           # SH1106 contrast byte, 0x00-0xFF


# ---- screen stack --------------------------------------------------------
class Screen:
    """Base class every screen in the navigation stack subclasses.

    The app (Phase 2) owns a `list[Screen]` stack; the top of the stack is
    active. `push(screen)` / `pop()` on the App drive navigation; a screen
    never manipulates the stack of another screen directly.
    """

    def frame(self, app):
        """Return a Pillow 'L' (8-bit grayscale, values 0 or 255 only)
        image sized config.OLED_W x config.OLED_H. Theme invert/contrast is
        applied later by the driver, not here — screens always draw in the
        same polarity (ink=255, background=0) regardless of the active
        theme's `invert`."""
        raise NotImplementedError

    def handle(self, app, event):
        """event is an (name, kind) tuple, see above. Mutate app/self state
        and call app.request_redraw() (or push/pop) as needed. Do not
        render here."""
        raise NotImplementedError

    def on_enter(self, app):
        """Called once when this screen becomes the top of the stack
        (after a push, or after the screen above it is popped). Optional
        override; default does nothing."""

    def on_exit(self, app):
        """Called once when this screen stops being the top of the stack
        (before a push on top of it, or when it is popped). Optional
        override; default does nothing."""
```

### 3. State v2 schema (contract only — Phase 1D implements `state.py`)

Document this schema as a docstring at the top of `contracts.py` (or a
comment block) so Phase 1D and Phase 2 agree on shape without needing to
read each other's code:

```jsonc
{
  "version": 2,
  "settings": { /* config.SETTINGS_DEFAULTS shape, values overridden by user */ },
  "last_book": "/home/reader/ebooks/foo.epub or null",
  "in_book": false,
  "books": {
    "/home/reader/ebooks/foo.epub": {
      "position": 0,              // word index
      "total_words": 12345,
      "time_read_secs": 0.0,
      "bookmarks": [],            // sorted list of word indices
      "last_opened": 0.0          // unix epoch seconds
    }
  }
}
```

v1 (current) shape for migration reference (from `main.py` `State`):
`{"wpm": int, "positions": {path: idx}, "totals": {path: total},
"last_book": path|null, "in_book": bool}`. Migration folds `wpm` into
`settings.wpm`, and zips `positions`/`totals` into `books[path]` with
empty `bookmarks`/`time_read_secs`/`last_opened`. Phase 1D owns writing the
actual migration code; this phase only needs to leave this schema
documented and stable.

### 4. Final control map (document as a comment/table in `contracts.py` or
a new `docs/plan/control-map.md` — your choice, but it must exist somewhere
both Phase 1B and Phase 2 will find it)

- **Library** (list of `ListScreen`): up/down = move selection (repeats),
  left/right = page by one screenful (repeats), press = open selected book,
  K1 hold = power-off confirm, K2 tap = main menu, K3 tap = book info for
  the highlighted book.
- **Reading**: press or K3 tap = pause, up/down tap = wpm ± `WPM_STEP`
  (flashes briefly in a corner), left/right tap = jump one sentence
  back/forward, K1 tap = save position and return to library, K2 tap =
  open book menu.
- **Paused**: same bindings as Reading, plus left/right **hold** (repeat)
  = jump one chapter back/forward.
- **Every list screen** (chapters, bookmarks, settings, themes, system,
  book menu): K1 = back one level, press = select/activate highlighted
  row, K3 = context action where one exists (delete bookmark, delete
  book) — otherwise K3 is a no-op.
- **Idle** (any screen except Reading): no input for `IDLE_DIM_SECS` →
  contrast drops to `IDLE_DIM_CONTRAST`; no input for `IDLE_OFF_SECS` →
  panel sleeps. Any key press wakes the panel and is swallowed (not passed
  to the active screen's `handle`).

## Definition of done

- `rapid_reader/config.py` matches the spec above exactly (names, values).
- `rapid_reader/contracts.py` exists with `Theme` and `Screen` as specified,
  importable with no third-party dependency (no Pillow, no gpiozero, no
  spidev) — verify with `python3 -c "import contracts"` from inside
  `rapid_reader/`.
- The state v2 schema and control map are written down somewhere in the
  repo (docstring or doc file) that Phases 1D and 2 can cite.
- `python3 -m pytest -q` still passes (this phase does not change any
  existing behaviour that current tests exercise, but importing `config`
  is done by nearly every test module, so a typo here breaks everything —
  double check `python3 -c "import config"` from `rapid_reader/` too).
- Do **not** delete `lcd.py`, `buttons.py`, `display.py`, `render.py`,
  `main.py` in this phase — those are rewritten in Phases 1A/1B/1C/2. This
  phase only adds/replaces `config.py` and adds `contracts.py`.

## Non-goals

- No SPI/GPIO code, no Pillow drawing, no button-timer implementation, no
  screen implementations. Those belong to Phases 1A–1D and 2.
