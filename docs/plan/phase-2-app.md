# Phase 2 — App (integration)

**Status:** not started. **Depends on:** all of Phase 1 (1A/1B/1C/1D) and
Phase 0. **Recommendation:** run this on a stronger/more capable model,
not the nimble tier used for Phase 1 — see the note in
[`docs/plan/README.md`](README.md) and "On sub-tasking this nimbly" below
before deciding how to execute it.

## Why this phase is different from the other five

Phases 0/1A/1B/1C/1D are each a self-contained, mechanically-specifiable
unit against a fixed contract. Phase 2 is the opposite: it is the one
place where every contract gets used **at once** — 14 screens, a
navigation stack, idle/dim/off/wake power management, state persistence
timing, and the playback loop all interacting in the same event loop. A
small/fast model working through this under context pressure is exactly
the profile that tends to silently drop a control-map binding, forget to
call `state.save()` at one of the right moments, or leak a stack push
without a matching pop. Use a more capable agent for the integration
pass, and have it run the full test suite (including a manual `fire()`
walk of every screen, see below) before calling this phase done.

## Context you need

Read first, in this order:
- [`phase-0-contracts.md`](phase-0-contracts.md) — `contracts.Screen`,
  the state v2 schema, the full control map.
- [`phase-1a-driver.md`](phase-1a-driver.md), specifically the
  `Display` facade shape (`show`, `contrast`, `invert`, `sleep`, `wake`).
- [`phase-1b-input.md`](phase-1b-input.md), specifically `Input`'s
  constructor and the event tuples it emits.
- [`phase-1c-render-theme.md`](phase-1c-render-theme.md), specifically
  every frame function's signature (`word_frame`, `chunk_frame`,
  `list_frame`, `paused_frame`, `info_frame`, `message_frame`,
  `confirm_frame`, `end_frame`) and `theme.THEMES`.
- [`phase-1d-model.md`](phase-1d-model.md), specifically `state.State`'s
  full API and `books.Book`/`books.sort_by_recency`.
- `rapid_reader/main.py` (current file, being replaced) — study
  `App.step_word()`'s pacing/measurement logic (lines ~288-323, port this
  essentially unchanged, it is hardware-agnostic), `jump_sentence`/
  `jump_chapter` (port unchanged, they only touch `books.Book` data), and
  `run()`'s event-loop structure (`events.get_nowait()` while actively
  reading, blocking `events.get()` otherwise — this phase changes the
  "otherwise" branch to a **timeout**, not a pure block, so idle timers
  can be checked — see below).
- `tests/test_app.py` (current file) — current end-to-end testing style
  using `fake_display`/`fake_button` and a `fire()`-style helper; mirror
  this style for the new stack-based app.

## Deliverables

- **New** `rapid_reader/screens.py`.
- **Rewrite** `rapid_reader/main.py`.
- **Delete** the old `main.py` `State` class (superseded by
  `rapid_reader/state.py` from Phase 1D) and `render.py`'s old
  three-screen call sites (already gone if Phase 1C landed first).
- **Rewrite** `tests/test_app.py`; **new** `tests/test_screens.py` (or
  keep it all in `test_app.py` if that reads better — your call, but the
  coverage below must exist somewhere).
- **Update** `tests/conftest.py`'s `fake_display` fixture: one
  `FakePanel(config.OLED_W, config.OLED_H)` instead of three.

## Architecture

### `App` (in `main.py`)

```python
class App:
    def __init__(self, display=None, input_cls=None):
        self.display = display if display is not None else oled_display.open_display()
        self.events = queue.Queue()
        self.input = (input_cls or buttons.Input)(self._on_event)
        self.state = state.State()
        self.theme = theme.THEMES.get(self.state.settings["theme"], theme.THEMES[theme.DEFAULT_THEME_KEY])
        self.book = None       # books.Book, set when a book is open
        self.idx = 0
        self.stack = []        # list[contracts.Screen]; stack[-1] is active
        self.words_since_save = 0
        self.refresh_secs = config.PANEL_REFRESH_SECS
        self._last_input_at = time.monotonic()
        self._idle_state = "active"   # "active" | "dim" | "off"

    def _on_event(self, name, kind):
        self.events.put((name, kind))

    # ---- navigation ----
    def push(self, screen):
        if self.stack:
            self.stack[-1].on_exit(self)
        self.stack.append(screen)
        screen.on_enter(self)
        self.redraw()

    def pop(self):
        old = self.stack.pop()
        old.on_exit(self)
        self.stack[-1].on_enter(self)
        self.redraw()

    def replace_top(self, screen):
        """Swap the active screen without growing the stack -- used only
        for the Reading<->Paused toggle, which is the same open book at
        the same navigation depth, not a new destination."""
        if self.stack:
            self.stack[-1].on_exit(self)
        self.stack[-1] = screen
        screen.on_enter(self)
        self.redraw()

    # ---- rendering ----
    def redraw(self):
        img = self.stack[-1].frame(self)
        self.display.show(img.convert("1") if img.mode != "1" else img)

    # ---- theme / idle ----
    def apply_theme(self, theme_key):
        self.theme = theme.THEMES[theme_key]
        self.state.settings["theme"] = theme_key
        self.display.invert(self.theme.invert)
        self.display.contrast(self.theme.contrast)
        self.state.save()
        self.redraw()

    def _tick_idle(self):
        idle_for = time.monotonic() - self._last_input_at
        reading = self.stack and isinstance(self.stack[-1], ReadingScreen)
        if reading:
            target = "active"
        elif idle_for >= config.IDLE_OFF_SECS:
            target = "off"
        elif idle_for >= config.IDLE_DIM_SECS:
            target = "dim"
        else:
            target = "active"
        if target != self._idle_state:
            self._idle_state = target
            if target == "off":
                self.display.sleep()
            elif target == "dim":
                self.display.wake(); self.display.contrast(config.IDLE_DIM_CONTRAST)
            else:
                self.display.wake(); self.display.contrast(self.theme.contrast)

    # ---- playback (ported near-unchanged from the old App.step_word) ----
    def step_word(self):
        ...  # see "Porting step_word" below

    # ---- main loop ----
    def run(self):
        self.push(self._initial_screen())
        while True:
            reading = isinstance(self.stack[-1], ReadingScreen)
            if reading:
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    self.step_word()
                    continue
            else:
                try:
                    ev = self.events.get(timeout=1.0)
                except queue.Empty:
                    self._tick_idle()
                    continue
            self._last_input_at = time.monotonic()
            was_off = self._idle_state == "off"
            self._tick_idle()
            if was_off:
                continue   # swallow the waking key press, per the control map
            self.stack[-1].handle(self, ev)
```

`_initial_screen()`: resume paused exactly where the old `App.run()` did
(if `state.in_book` and `state.last_book` is still in the scanned
library, load it and push a `PausedScreen`), else push a fresh
`LibraryScreen`. The library screen is always `self.stack[0]` and is never
popped past — `LibraryScreen.handle`'s `K1`/back case should be a no-op
(or ignored) precisely because it is the root of the stack; don't special
-case this in `App.pop()` itself, just don't call `pop()` from the root
screen's own `handle()`.

### Porting `step_word`

Copy the old `App.step_word()` (main.py lines ~288-323) essentially
unchanged: it already only touches `books.Book`, `rsvp.word_delay`,
`render.word_frame`/`chunk_frame`, `self.display.show`, and
`self.idx`/`self.refresh_secs`/`self.words_since_save` — none of that is
hardware- or screen-count-specific. The only changes needed:
- `render.word_frame(chunk[0], self.theme)` / `render.chunk_frame(chunk,
  self.theme)` — pass the active theme now that `render.py` needs it for
  pivot styling (Phase 1C).
- No side-card `_progress_side()` call — there is no side screen any
  more; progress is only visible on the `PausedScreen`/`BookInfo` screens
  now.
- End-of-book: instead of `self.show_end()`, call
  `self.state.touch_book(self.book.path, position=self.idx,
  total_words=len(self.book.words))`, `self.state.save()`, then
  `self.push(EndScreen())` (or `replace_top`, since Reading is being left
  — use `push` here, matching the control map's "End: any key returns to
  library", i.e. popping back through Reading to Library on the next
  key, which only works cleanly with `push` + a subsequent `pop()`+`pop()`
  or a dedicated `EndScreen.handle` that calls `app.stack[:] =
  [app.stack[0]]` to jump straight back to the library root — pick
  whichever you implement consistently, but test it explicitly, this is
  exactly the kind of stack-bookkeeping edge case call out in the
  intro above).
- wpm-change "flash" (control map: "flashes in a corner"): keep a
  `self._flash_until = time.monotonic() + 1.0` and `self._flash_text`
  set on `change_wpm()`; `step_word()` passes `flash=self._flash_text if
  time.monotonic() < self._flash_until else None` into `word_frame`.

### `screens.py`

```python
"""Every Screen in the navigation stack. No hardware; calls render.py."""

from contracts import Screen


class ListScreen(Screen):
    """Shared plumbing for every list-shaped screen: an items() list, a
    selection index, K1=back (pop), press=activate(app, item), K3=context
    action if implemented, up/down move selection (with wraparound),
    left/right page by rows_visible. Subclasses override items(),
    header(), activate(), and optionally context_action()."""

    rows_visible = 4

    def __init__(self):
        self.sel = 0
        self.top = 0

    def items(self, app):
        raise NotImplementedError

    def header(self, app):
        raise NotImplementedError

    def row_text(self, app, item):
        return str(item)

    def activate(self, app, item):
        pass

    def context_action(self, app, item):
        pass  # no-op by default; screens with a K3 action override this

    def frame(self, app):
        items = self.items(app)
        rows = [self.row_text(app, it) for it in items]
        return render.list_frame(self.header(app), rows, self.sel, self.top,
                                  rows_visible=self.rows_visible)

    def handle(self, app, event):
        name, kind = event
        items = self.items(app)
        if name in ("up", "down") and kind in ("tap", "repeat") and items:
            delta = -1 if name == "up" else 1
            self.sel = (self.sel + delta) % len(items)
            self._scroll_into_view()
            app.redraw()
        elif name in ("left", "right") and kind in ("tap", "repeat") and items:
            delta = -self.rows_visible if name == "left" else self.rows_visible
            self.sel = max(0, min(len(items) - 1, self.sel + delta))
            self._scroll_into_view()
            app.redraw()
        elif name == "press" and kind == "tap" and items:
            self.activate(app, items[self.sel])
        elif name == "k3" and kind == "tap" and items:
            self.context_action(app, items[self.sel])
        elif name == "k1" and kind == "tap":
            app.pop()

    def _scroll_into_view(self):
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + self.rows_visible:
            self.top = self.sel - self.rows_visible + 1
```

Then, one small subclass per list screen. The table below is the full
screen list from the plan; each row is everything a subclass needs beyond
`ListScreen`'s defaults (or, for the four non-list screens, its own
`frame`/`handle`):

| Screen | items() | activate() | context_action() (K3) | Notes |
|---|---|---|---|---|
| `LibraryScreen` | `books.scan_library()`, optionally `books.sort_by_recency` per a library-sort setting | load the book (`books.Book.load`), seed `app.idx` from `app.state.book(path)["position"]`, `app.push(PausedScreen())` | push `BookInfoScreen` for the highlighted title | root of the stack; `k1` (back) is a no-op here — don't call `super().handle()`'s pop for `k1` on this one screen, override `handle` to special-case it, or simply never pop past index 0 in `App.pop()` (pick one, document which) |
| `MainMenuScreen` | fixed list: `["Chapters", "Bookmarks", "Book info", "Settings", "System", "Save & close book"]` | dispatch to the matching screen/action | — | reached via `K2` from Reading/Paused per the control map |
| `ReadingScreen` | n/a (not list-based) | — | — | `frame()` calls `render.word_frame`/`chunk_frame` via `App.step_word`'s own render call, not through this screen's `frame()` at all — `App.run()`'s reading branch bypasses `self.stack[-1].frame()` and calls `step_word()` directly instead (see the main loop above); `handle()` still routes non-playback events (press/K3=pause via `app.replace_top(PausedScreen())`, up/down=`app.change_wpm`, left/right=`app.jump_sentence`, k1=save+`app.pop()` back to Library, k2=push `MainMenuScreen`) |
| `PausedScreen` | n/a | — | — | `frame()` = `render.paused_frame(...)`; `handle()`: press/k3=`app.replace_top(ReadingScreen())`, up/down=`app.change_wpm`, left/right=`app.jump_sentence`, left/right **hold**=`app.jump_chapter`, k1=save+pop to library, k2=push `MainMenuScreen` |
| `BookMenuScreen` | fixed list, same shape as `MainMenuScreen` minus "Save & close book" (already accessible via k1 from Reading/Paused directly) | dispatch | — | reached via `K2` from Reading, per control map's original "K2 book menu"; confirm this is the same destination as `MainMenuScreen` or keep them distinct per the plan's naming — either is acceptable as long as every entry point in the control map lands somewhere sensible |
| `ChaptersScreen` | `[app.book.chapter_title(s) or "Chapter %d" % i for i, s in enumerate(app.book.chapter_starts)]` | `app.idx = app.book.chapter_starts[sel]`; pop back to `PausedScreen` | — | empty-state message when `chapter_starts` is empty |
| `BookmarksScreen` | sorted `app.state.book(app.book.path)["bookmarks"]`, rendered as e.g. `"%d%%"` of the book | jump `app.idx` there, pop to `PausedScreen` | `app.state.remove_bookmark(...)`; confirm via `ConfirmScreen` first | also needs an "add bookmark at current position" action, exposed from `PausedScreen`'s `MainMenuScreen`/`BookMenuScreen` entry, not from this list |
| `BookInfoScreen` | n/a | — | — | `frame()` = `render.info_frame(...)`; `handle()`: k1=pop only |
| `SettingsScreen` | fixed list: `["Word size", "Pivot style", "Theme", "Display", "Library sort"]` | push the matching sub-screen (`ThemesScreen` for "Theme", a small cycling list for "Word size"/"Pivot style"/"Library sort", `DisplaySettingsScreen` for "Display") | — | |
| `DisplaySettingsScreen` | fixed list: `["Contrast"]` (idle dim/off timings are `config.py` constants, not user-editable in 1.0 — keep this screen minimal) | adjust `app.theme`'s contrast override / `app.display.contrast(...)` | — | |
| `ThemesScreen` | `list(theme.THEMES)` | `app.apply_theme(key)`, pop | — | |
| `SystemScreen` | fixed list: `["IP address", "Disk free", "Version", "Reboot", "Power off"]` | show the value (push a `MessageScreen`) or perform the action (subprocess `reboot`/`poweroff`, same privilege-escalation pattern as the old `App.power_off()`) | — | reading IP/disk-free is a couple of lines of `subprocess`/`os.statvfs` — keep it simple, no new dependency |
| `ConfirmScreen` | n/a | — | — | generic yes/no dialog (`render.confirm_frame`), constructed with a prompt string + a callback for "yes"; used for power-off, reboot, delete-bookmark, delete-book |
| `EndScreen` | n/a | — | — | `render.end_frame(app.book.title)`; any key jumps back to the library root (see the stack-bookkeeping note above) |

`MessageScreen` (a trivial one-off wrapper around `render.message_frame`,
popped by any key) is useful glue for `SystemScreen`'s read-only items —
add it even though it isn't in the table above.

## Wiring `state.State` in fully

- Load `state.State()` once in `App.__init__`; every settings change
  (`apply_theme`, word size, pivot style) mutates `self.state.settings`
  and calls `self.state.save()` immediately (small, infrequent writes —
  no need to batch).
- `change_wpm()` (ported from the old `App`) updates
  `self.state.settings["wpm"]` and saves, same as before.
- Reading progress: call `self.state.touch_book(self.book.path,
  position=self.idx)` every `config.SAVE_EVERY_WORDS` words (port the old
  `words_since_save` counter) and on every pause/leave/SIGTERM, exactly
  like the old `save_position()` did — just targeting `state.State`'s v2
  API (`touch_book`) instead of the old flat `positions`/`totals` dicts.
- `time_read_secs`: accumulate wall-clock time spent in `ReadingScreen`
  between play and pause/leave (a `self._reading_since = time.monotonic()`
  set in `ReadingScreen.on_enter`, added to the book record's
  `time_read_secs` in `on_exit` — this is new behaviour the old app didn't
  have, needed for `BookInfoScreen`'s "time read" stat from Phase 1C).

## `main()` / SIGTERM / boot

Port the old `main(display=None)` function's shape (open display if not
given, construct `App`, install a `SIGTERM` handler that saves state and
puts the display to sleep, run `app.run()`, catch/report unexpected
exceptions to the screen via `render.message_frame` and re-raise so
systemd restarts it) — same structure, updated for the single-display,
theme-aware calls.

## On sub-tasking this nimbly

If you do want to break this phase down for smaller/faster agents instead
of one capable agent doing the whole thing, the least-risky split is:

1. **2B first**: `App` skeleton (stack, event loop, idle/theme/SIGTERM,
   `step_word`) wired against a single trivial placeholder `Screen` (e.g.
   just `LibraryScreen` with a stub `items()`), fully tested for
   navigation/idle/persistence mechanics with that one screen.
2. **2A second**: the other 13 screens, added one at a time against the
   now-stable `App`, each screen's own small `test_screens.py` case using
   the same `fire()`-style harness. This keeps each individual PR small
   and reviewable even though the whole phase is not.

Do not attempt to parallelize 2A and 2B — screens genuinely need the
`App` methods they call (`push`/`pop`/`replace_top`/`change_wpm`/
`jump_sentence`/`jump_chapter`/`apply_theme`) to exist first.

## Tests

Mirror the old `test_app.py`'s end-to-end style: a `fire(app, name,
kind)` helper that feeds one event tuple through `App._on_event` then
drains the queue (or, for `ReadingScreen`, calls `step_word()` directly a
controlled number of times) using `fake_display`/`fake_button`-equivalent
fixtures. Required coverage:
- Boot resumes into `PausedScreen` when `state.in_book` was true and the
  book still exists in the library; boots into `LibraryScreen` otherwise.
- Every control-map binding from Phase 0 fires the right transition —
  walk the whole map screen by screen, not just a couple of happy paths.
- `k1` from the library root is a no-op (stack never underflows).
- Idle: monkeypatch `IDLE_DIM_SECS`/`IDLE_OFF_SECS` tiny, assert
  `display.contrast`/`display.sleep` are called at the right thresholds
  while sitting on a non-Reading screen, and never while on
  `ReadingScreen`; the key press that wakes an "off" display is swallowed
  (does not also reach the active screen's `handle`).
- `state.save()` happens at the documented moments (every
  `SAVE_EVERY_WORDS`, on pause, on leave-to-library, on settings change,
  on SIGTERM) — assert via a counting fake or by inspecting the state
  file's mtime/content between steps.
- End-of-book reaches `EndScreen` and any key from there lands back on
  the library root with the stack fully unwound (`len(app.stack) == 1`).
- Chapter/bookmark/theme/pivot-style/word-size changes round-trip through
  `state.State` correctly (persisted, and reflected in `app.theme`/
  `app.book`/`render` calls on the next frame).
- SIGTERM handler saves state and sleeps the display without raising.

## Definition of done

- `python3 -m pytest -q` green.
- Every control-map entry from Phase 0 has been exercised by a test, not
  just implemented in `handle()`.
- `main.py` no longer defines its own `State` class; it imports
  `rapid_reader.state` (or, matching the existing flat-module layout,
  `import state`).
- `rapid_reader/main.py` and `rapid_reader/screens.py` together are the
  only files importing `contracts.Screen`/`contracts.Theme` and treating
  them as base classes — no other module reaches into the stack directly.

## Non-goals

- Do not change `config.py`/`contracts.py`/`oled.py`/`buttons.py`/
  `theme.py`/`render.py`/`state.py`/`rsvp.py`/`books.py`'s public
  interfaces to make this phase easier — if one of them is genuinely
  missing something, that is a signal Phase 0's contract had a gap, not
  license to freelance-change an already-landed phase's file. Flag it
  instead (a short note in this phase's commit/PR description) and make
  the minimal compatible addition.
