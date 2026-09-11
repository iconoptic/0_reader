# Phase 2C — Settings, Themes, Display, System screens

**Status:** not started. **Depends on:** [`phase-2a-core.md`](phase-2a-core.md)
landed. Independent of [`phase-2b-book-nav.md`](phase-2b-book-nav.md) —
both edit `screens.py`'s `BookMenuScreen.activate`, but disjoint lines
("Settings"/"System" here vs. "Chapters"/"Bookmarks"/"Book info" there),
so these two can be done in either order, just not truly in parallel
against the same uncommitted file (merge one, then the other). **Part of
the Phase 2 split** — see [`phase-2-app.md`](phase-2-app.md) and
[`README.md`](README.md).

## Scope

Add `SettingsScreen`, `ThemesScreen`, `DisplaySettingsScreen`,
`SystemScreen` to `rapid_reader/screens.py`, and wire `BookMenuScreen`'s
"Settings"/"System" placeholder lines to them. This phase does not touch
`App`'s core loop, `ReadingScreen`, `PausedScreen`, `EndScreen`,
`ListScreen`, `MessageScreen`, or `ConfirmScreen`.

## Deliverables

Append to `rapid_reader/screens.py`:

```python
_WORD_SIZES = ("small", "medium", "large")
_PIVOT_STYLES = ("ticks", "underline", "box", "bold")


class SettingsScreen(ListScreen):
    _ITEMS = ("word_size", "pivot_style", "theme", "display")
    _LABELS = {"word_size": "Word size", "pivot_style": "Pivot style",
               "theme": "Theme", "display": "Display"}

    def items(self, app):
        return list(self._ITEMS)

    def header(self, app):
        return "SETTINGS"

    def row_text(self, app, item):
        s = app.state.settings
        if item == "word_size":
            return "Word size: %s" % s["word_size"]
        if item == "pivot_style":
            return "Pivot style: %s" % s["pivot_style"]
        if item == "theme":
            return "Theme: %s" % app.theme.name
        return "Display"

    def activate(self, app, item):
        s = app.state.settings
        if item == "word_size":
            i = (_WORD_SIZES.index(s["word_size"]) + 1) % len(_WORD_SIZES)
            s["word_size"] = _WORD_SIZES[i]
            app.state.save()
            app.redraw()
        elif item == "pivot_style":
            i = (_PIVOT_STYLES.index(s["pivot_style"]) + 1) % len(_PIVOT_STYLES)
            s["pivot_style"] = _PIVOT_STYLES[i]
            app.state.save()
            app.redraw()
        elif item == "theme":
            app.push(ThemesScreen())
        elif item == "display":
            app.push(DisplaySettingsScreen())
```

`pivot_style` is a setting on `state.settings`, but the *active* theme
(`app.theme`, a `contracts.Theme` instance) is what `render.py` actually
reads for `pivot_style`/`font_key`/`invert`/`contrast` — cycling
`state.settings["pivot_style"]` here only changes what gets *saved and
offered as the default for the next theme pick*; it does **not** retroactively
change `app.theme.pivot_style` for the currently-active theme, because
`Theme` is a frozen dataclass and the five presets in `theme.THEMES` each
hard-code their own `pivot_style`. If you want this setting to actually
change the *look* immediately, apply it as a per-session override
instead of trying to mutate the frozen theme:

```python
    def activate(self, app, item):
        ...
        elif item == "pivot_style":
            from dataclasses import replace
            i = (_PIVOT_STYLES.index(s["pivot_style"]) + 1) % len(_PIVOT_STYLES)
            s["pivot_style"] = _PIVOT_STYLES[i]
            app.theme = replace(app.theme, pivot_style=s["pivot_style"])
            app.state.save()
            app.redraw()
```

Use the `dataclasses.replace` form (apply the same pattern to
`word_size` is unnecessary since `word_size` is not a `Theme` field — it
is read straight from `app.state.settings["word_size"]` by `step_word`/
`ReadingScreen.frame`/`PausedScreen.frame` already, so cycling it in
`SettingsScreen` takes effect on the very next `redraw()`/`step_word()`
with no extra plumbing). Apply the `replace()` override to `app.theme`
whenever `apply_theme()` also runs (i.e. `ThemesScreen.activate`, below,
should call `app.apply_theme(key)` and then immediately re-apply the
user's `pivot_style` override the same way, so switching themes doesn't
silently discard a pivot-style choice made before the switch).

```python
class ThemesScreen(ListScreen):
    def items(self, app):
        return list(theme.THEMES)   # keys: "night","paper","focus","dim","mono"

    def header(self, app):
        return "THEME"

    def row_text(self, app, item):
        mark = " *" if item == app.state.settings["theme"] else ""
        return theme.THEMES[item].name + mark

    def activate(self, app, item):
        from dataclasses import replace
        app.apply_theme(item)
        app.theme = replace(app.theme, pivot_style=app.state.settings["pivot_style"])
        app.pop()


class DisplaySettingsScreen(Screen):
    """Session-only contrast nudge (not persisted -- there is no
    `contrast` key in config.SETTINGS_DEFAULTS/state's schema; adding one
    is out of scope here, see the note in phase-0-contracts.md's schema
    if a later pass wants to persist this). Resets to the active theme's
    contrast on the next theme change or app restart."""

    STEP = 0x10

    def __init__(self):
        self._value = None

    def on_enter(self, app):
        if self._value is None:
            self._value = app.theme.contrast

    def frame(self, app):
        return render.message_frame(
            ["Contrast: %d" % self._value],
            hint="up/down adjust    k1 back")

    def handle(self, app, event):
        name, kind = event
        if name == "up" and kind in ("tap", "repeat"):
            self._value = min(0xFF, self._value + self.STEP)
            app.display.contrast(self._value)
            app.redraw()
        elif name == "down" and kind in ("tap", "repeat"):
            self._value = max(0x00, self._value - self.STEP)
            app.display.contrast(self._value)
            app.redraw()
        elif name == "k1" and kind == "tap":
            app.display.contrast(app.theme.contrast)  # revert, not persisted
            app.pop()


class SystemScreen(ListScreen):
    _ITEMS = ("IP address", "Disk free", "Version", "Reboot", "Power off")

    def items(self, app):
        return list(self._ITEMS)

    def header(self, app):
        return "SYSTEM"

    def activate(self, app, item):
        import config
        if item == "IP address":
            app.push(MessageScreen([self._ip_address()]))
        elif item == "Disk free":
            app.push(MessageScreen([self._disk_free(config.BOOKS_DIR)]))
        elif item == "Version":
            app.push(MessageScreen([getattr(config, "VERSION", "dev")]))
        elif item == "Reboot":
            app.push(ConfirmScreen("Reboot now?", self._reboot))
        elif item == "Power off":
            app.push(ConfirmScreen("Power off now?", self._power_off))

    @staticmethod
    def _ip_address():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "no network"
        finally:
            s.close()

    @staticmethod
    def _disk_free(path):
        import os
        st = os.statvfs(path)
        free_mb = st.f_bavail * st.f_frsize / (1024 * 1024)
        return "%.0f MB free" % free_mb

    @staticmethod
    def _reboot(app):
        SystemScreen._run_privileged("reboot")

    @staticmethod
    def _power_off(app):
        app.state.save()
        SystemScreen._run_privileged("poweroff")

    @staticmethod
    def _run_privileged(cmd):
        import os
        import subprocess
        argv = [cmd] if os.geteuid() == 0 else ["sudo", "-n", cmd]
        subprocess.call(argv)
```

Add `import theme` to `screens.py`'s top-of-file imports if it is not
already there (Phase 2A's imports were `books`, `render`, `Screen` from
`contracts` — add `theme` alongside them).

### One permitted `config.py` addition

`SystemScreen`'s "Version" item needs *some* string. `config.py` has no
version constant, and none of the other phases' schemas have a natural
home for one. Per `phase-2-app.md`'s Non-goals ("if something is
genuinely missing, flag it and make the minimal compatible addition"),
add exactly one line to `config.py`, in the `# --- Paths` section:

```python
VERSION = "1.0.0-sh1106"
```

Do not add, remove, or reorder anything else in `config.py`.

### Wire into `BookMenuScreen.activate` (edit these two lines only)

```python
        elif item == "Settings":
            app.push(SettingsScreen())
        elif item == "System":
            app.push(SystemScreen())
```

(Remove the two corresponding `self._not_yet(app, item)` lines. Leave
"Chapters"/"Bookmarks"/"Book info" exactly as Phase 2A or 2B left them.)

## Tests

- `SettingsScreen`: cycling "Word size"/"Pivot style" advances through
  the full tuple and wraps back to the start; `state.settings` and
  `app.theme.pivot_style` both reflect the change immediately (assert
  the next `PausedScreen`/`ReadingScreen` frame actually differs, not
  just the stored string); "Theme" and "Display" push the right screens.
- `ThemesScreen`: lists all 5 keys from `theme.THEMES`; the currently
  active one is marked; activating one calls `app.apply_theme`, updates
  `display.invert`/`display.contrast` (via the `fake_display` fixture),
  persists via `state.save()`, and preserves a previously-chosen
  `pivot_style` override across the switch; pops back to `SettingsScreen`.
- `DisplaySettingsScreen`: up/down adjust `display.contrast_level` by
  `STEP`, clamped to `[0, 0xFF]`; `k1` reverts to `app.theme.contrast`
  and pops; the adjustment does not appear in `state.settings` after
  `save()` (confirms it is intentionally session-only).
- `SystemScreen`: "IP address"/"Disk free"/"Version" push a
  `MessageScreen` with some non-empty string (don't assert exact IP —
  network state varies; do assert `_disk_free`/`_ip_address` don't
  raise, using `tmp_path` for the disk-free path); "Reboot"/"Power off"
  push a `ConfirmScreen`, and confirming (`k3`) calls the privileged
  command path (monkeypatch `subprocess.call` to a recorder — never
  actually reboot/power off in a test), declining does not call it.
- `BookMenuScreen`: "Settings"/"System" now push the real screens (update
  the Phase 2A placeholder-assertion tests for just these two items;
  leave "Chapters"/"Bookmarks"/"Book info" assertions exactly as Phase 2B
  left them).

## Definition of done

- `python3 -m pytest -q` green.
- `BookMenuScreen`'s "Settings" and "System" items are fully live.
- The only change to `config.py` is the single `VERSION` line above; no
  other landed phase's file changed.
