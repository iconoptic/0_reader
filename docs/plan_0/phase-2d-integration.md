# Phase 2D — Integration pass and sign-off

**Status:** done. **Depends on:** [`phase-2a-core.md`](phase-2a-core.md),
[`phase-2b-book-nav.md`](phase-2b-book-nav.md),
[`phase-2c-settings-system.md`](phase-2c-settings-system.md) all landed.
**Part of the Phase 2 split** — see [`phase-2-app.md`](phase-2-app.md)
and [`README.md`](README.md). **This is the one piece of the Phase 2
split still worth running on a stronger/more capable model rather than
the nimble tier** — it is a verification and cleanup pass across
everything 2A/2B/2C produced, exactly the kind of cross-cutting checking
the original Phase 2 doc was worried about a nimble model missing. It is
much smaller than the original monolithic Phase 2 now, though: no new
screens, no new design decisions — just confirm the seams are sound and
tie off the two known loose ends.

## Checklist

1. **No placeholders remain.** `grep -n "_not_yet\|not yet available" rapid_reader/screens.py`
   should return nothing outside the `BookMenuScreen._not_yet` method
   definition itself (the method can stay as dead code removed, or left
   in case a future screen needs a "not implemented" stub — your call,
   but every one of its five call sites from Phase 2A must be gone).
2. **`config.py` temporary LCD-HAT block removed.** Per
   [`corrections-phase-0-1.md`](corrections-phase-0-1.md) Fix 3: delete
   the `# --- Temporary: LCD HAT (remove in Phases 1A / 1B / 2) ---`
   block (`MAIN`, `LEFT`, `RIGHT`, `MAIN_W`, `MAIN_H`, `SIDE_W`,
   `SIDE_H`, `MAIN_ROTATE_180`, `SIDE_ROTATE_180`, `SWAP_SIDES`,
   `BACKLIGHT_PWM_HZ`, `BL_MAIN`, `BL_SIDE`, `BL_SIDE_READING`,
   `TAP_WINDOW`, `HOLD_TIME`) now that `main.py`/`test_app.py` no longer
   reference it (2A rewrote both). Re-run
   `grep -rn "config\.\(MAIN\b\|LEFT\b\|RIGHT\b\|SIDE_W\|SIDE_H\|BL_\|TAP_WINDOW\|HOLD_TIME\)" rapid_reader/ tests/`
   afterwards — the only remaining hit should be `tools/build_card.sh`
   (Phase 3's file, untouched here; it still imports the retired `lcd`
   module for its own smoke test and is out of scope for Phase 2).
3. **Full control-map walk.** Using [`phase-0-contracts.md`](phase-0-contracts.md)'s
   control map as the checklist, write (or confirm 2A/2B/2C already
   wrote) one test per binding, not just per screen. Every row of the
   control map's tables must have a test that fires that exact
   `(name, kind)` tuple from that exact screen and asserts the
   documented effect. Cross-reference against `screens.py` line by line
   — this is the single highest-value thing this phase does; a nimble
   model working screen-by-group-by-group in 2A/2B/2C has no way to
   verify the *seams* between groups (e.g. does every path that can
   reach `PausedScreen` actually leave `app.idx` in a sane state? Does
   every `ConfirmScreen` actually get popped exactly once regardless of
   which branch fires?).
4. **Stack-depth invariants.** Add an assertion-style test that walks
   Library -> open book -> Paused -> BookMenu -> Chapters -> (activate)
   -> back on Paused with `len(app.stack) == 2`; same for Bookmarks;
   same for Settings -> Theme -> (activate) -> back on Settings with
   `len(app.stack) == 3`. Also confirm `EndScreen` -> any key ->
   `len(app.stack) == 1` from every possible depth it could have been
   reached from (only one: Library -> Paused -> Reading -> End, so this
   is a single test, not a matrix).
5. **`state.save()` timing audit.** Confirm (via a counting fake `State`
   or by spying on `state.State.save`) that a save happens at every one
   of: every `config.SAVE_EVERY_WORDS` words consumed, entering
   `PausedScreen` from `ReadingScreen`, leaving to the library, any
   settings change (`word_size`/`pivot_style`/`theme`), adding/removing
   a bookmark, and `SIGTERM`. Confirm it does **not** save on every
   single word during normal reading (only every `SAVE_EVERY_WORDS`) —
   a save-every-frame regression would be a real (if minor) SD-card-wear
   problem on a Pi Zero.
6. **`boot.py` still works end to end.** `boot.py` calls `display.splash()`
   then `import main; main.main(disp)` — confirm `main.main`'s signature
   (`main(display=None)`) still matches what `boot.py` passes, and that
   nothing in Phase 2A/2B/2C's rewrite of `main.py` changed that contract.
7. **Dead-code sweep.** Confirm the old mode-constant style (`MENU`,
   `READING`, `PAUSED`, `CONFIRM_OFF`, `END`, `_LegacyMultiTap`) and the
   old in-`main.py` `State` class are fully gone — `grep -n
   "class State\|_LegacyMultiTap\|^MENU =\|^READING =" rapid_reader/main.py`
   should return nothing.

## Definition of done (for all of Phase 2)

- `python3 -m pytest -q` green, with real (not skipped) coverage for
  every screen and every control-map binding.
- `rapid_reader/main.py` no longer defines its own `State` class; it
  imports `state` (matching the existing flat-module layout).
- `rapid_reader/main.py` and `rapid_reader/screens.py` together are the
  only files importing `contracts.Screen`/`contracts.Theme` and treating
  them as base classes — no other module reaches into the stack
  directly.
- `config.py` contains no LCD-HAT-era constants; its only Phase-2-era
  addition is the single `VERSION` line from
  [`phase-2c-settings-system.md`](phase-2c-settings-system.md).
- Every item in this checklist has a corresponding test or an explicit,
  written reason it doesn't need one — do not just eyeball the checklist
  and move on.

Once this phase is done, Phase 2 as a whole is complete and
[`phase-4-bringup-checklist.md`](phase-4-bringup-checklist.md) (manual,
on real hardware) is the only remaining step before this is a working
reader.
