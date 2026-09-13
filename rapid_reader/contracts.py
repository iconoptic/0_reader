"""Shared interfaces for the screen-stack app. No hardware, no Pillow.

State v2 schema (Phase 1D implements load/save/migration in state.py)::

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

v1 (LCD build) shape for migration reference (from main.py State)::

    {"wpm": int, "positions": {path: idx}, "totals": {path: total},
     "last_book": path|null, "in_book": bool}

Migration folds ``wpm`` into ``settings.wpm``, and zips ``positions``/``totals``
into ``books[path]`` with empty ``bookmarks``/``time_read_secs``/``last_opened``.
Phase 1D owns the migration code; this module only documents the schema.

Control map (Phase 1B / Phase 2)::

    Stable roles: K1 = Back/leave (hold on Library = power), K2 = Menu
    everywhere, K3 = Act (pause/resume, confirm-yes, list context).

    Library (list of ListScreen; subdirs are folder menus):
      up/down     — move selection (repeats)
      left/right  — page by one screenful (repeats)
      press       — open folder submenu or selected book
      K1 hold     — power-off confirm (root BOOKS_DIR only)
      K2 tap      — main menu
      K3 tap      — book info for the highlighted book (books only)
      After 1s with a truncated highlight, the selected row marquees
      left until the end is visible, pauses, then snaps back.

    Reading:
      press or K3 tap — pause
      up/down tap     — wpm ± WPM_STEP (flash briefly in a corner)
      left/right tap  — jump one sentence back/forward
      K1 tap          — save position and return to library
      K2 tap          — open book menu

    Paused:
      same as Reading, plus left/right hold (repeat) — jump one chapter
      back/forward

    Every list screen (chapters, bookmarks, settings, themes, system and
    its Info/Diagnostics/Power submenus, book menu):
      K1    — back one level
      K2    — open menu (no-op when already on the menu)
      press — select/activate highlighted row
      K3    — context action where one exists (e.g. delete bookmark);
              otherwise no-op
      Truncated highlighted rows marquee after 1s (same as Library).

    Stress test (System > Diagnostics > Stress test):
      ready screen (duration picker):
        up/down — move selection      press — start the run
        K1      — back               K2 — open menu
      running (non-interruptible except K1):
        K1 tap  — abort early and go straight to the results screen
        other keys ignored while a run is in progress
      results (scrollable summary; full detail is in the log file under
      config.STRESS_LOG_DIR):
        up/down — scroll             K1 — back      K2 — open menu

    Confirm dialogs:
      K3 tap — yes
      K1 tap — no
      other keys ignored

    Idle (any screen except Reading):
      no input for IDLE_DIM_SECS  → contrast drops to IDLE_DIM_CONTRAST
      no input for IDLE_OFF_SECS  → panel sleeps
      any key press wakes the panel and is swallowed (not passed to the
      active screen's handle)
"""

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

    def poll_timeout(self, app=None):
        """Seconds the main loop may block waiting for input before
        calling ``tick``. Default 1.0 matches idle dim polling. List
        screens override this to speed up while a selected title is
        marquee-scrolling."""
        return 1.0

    def tick(self, app):
        """Called on the main loop's idle timeout when the display is
        not asleep. Default no-op; ListScreen uses this for title
        marquee, OtaScreen for apply progress."""
        pass