# Phase 5 — UX polish and truthful docs

**Status:** done. **Depends on:** phases 1, 3, 4 (the doc
portion strictly last). **Fixes:** F8, F9, F10.

**What landed:** `ScreenTestScreen` suppresses idle dim/off while on
top, pins `IDLE_ACTIVE_CONTRAST` on enter and restores the theme's
contrast on exit, and cycles all-on → all-off → 1px checkerboard.
`remaining_overlay` takes the active `theme` (passed from both
`paused_frame` sites) and the overlay is drawn before a single
`_finalize`. README / CONTROLS OTA sections rewritten against the
landed sync/bootstrap/preflight/progress/failure behaviour; screen-test
third mode documented. `docs/README.md` and this directory's README
mark plan_1 as landed/historical.

Everything here is small. It lands last because the documentation must
describe what the device actually does.

## Context you need

- [README.md](README.md) findings F8, F9, F10.
- `rapid_reader/screens.py` — `ScreenTestScreen`.
- `rapid_reader/main.py` — `_tick_idle`, and `config.py:64-67`
  (`IDLE_DIM_SECS = 60`, `IDLE_OFF_SECS = 300`,
  `IDLE_DIM_CONTRAST = 0x20`, `IDLE_ACTIVE_CONTRAST = 0xCF`).
- `rapid_reader/render.py` — `remaining_overlay`, `paused_frame`,
  `_default_theme`, `_finalize`.
- `README.md` "Syncing to a live Pi (OTA)"; `CONTROLS.md` "OTA updates"
  and the System-menu table.

## Deliverables

### 1. The screen test must stay lit (F8)

`ScreenTestScreen` takes the non-reading loop arm, so `_tick_idle()`
runs every second: the panel dims at 60 s and sleeps at 300 s while the
user is looking for dim pixels. Suppress idle handling while this screen
is on top — the same exemption the in-progress OTA screen gets — and
restore normal idle behaviour on exit.

Pin contrast to `IDLE_ACTIVE_CONTRAST` (or full scale) on entry rather
than inheriting the theme's, since the whole point is a uniformly driven
field, and restore the theme's contrast on exit.

Consider a third state in the toggle cycle. All-on and all-off catch
dead and stuck-on pixels; a fine checkerboard or 1px grid additionally
exposes row/column driver faults, which on an SH1106 are the more
common failure. `config.OLED_W`/`OLED_H` are already used here, so this
is a few lines.

### 2. Overlay follows the active theme (F9)

`paused_frame` receives `theme` and draws everything else with it, then
calls `remaining_overlay`, which calls `_default_theme()` and picks its
own face. Give `remaining_overlay` a `theme` parameter and pass it
through from both call sites in `paused_frame`.

While there: `paused_frame` runs `_finalize` before drawing the overlay
and again after. Fold the overlay in before the single final
`_finalize`. Behaviourally inert — the overlay draws pure `INK`/`BG` —
but it removes a redundant full-image pass and the seam that made the
overlay look bolted on.

`tests/test_render.py::test_progress_frame_and_remaining_overlay` covers
the current signature; update it and add a non-default-theme case.

### 3. Docs describe what exists (F10)

Rewrite the README's "Syncing to a live Pi (OTA)" section and CONTROLS'
"OTA updates" section against the finished behaviour:

- the env file path chosen in phase 2,
- what `--bootstrap` does after phase 3, and that it is a one-time
  migration for cards built before OTA existed (new cards from
  `build_card.sh` need nothing),
- the preflight refusal and the message the user gets,
- what the user sees when an update fails, and **which input dismisses
  it** — this is recovery information for a device with no console and
  belongs in CONTROLS' System/OTA section, not only in the README,
- what the progress bar means after phase 4.

Drop the present-tense claims about flows that were never exercised.
Remove the README's manual `scp`/`ssh`/`sudo` block once `--bootstrap`
performs it; keep a short "if bootstrap cannot reach the device" note
rather than the full recipe.

Add the screen test's third mode to CONTROLS' System-menu table if §1
adds one.

### 4. Move plan_1 to historical

Update `docs/README.md`: `plan_1/` is currently listed under Historical
as "Empty placeholder; no content yet." While these phases are in
flight it is a live roadmap and belongs above the Historical section;
once phase 5 lands, move it down and mark it landed, matching how
`plan_0/` is described.

Update this directory's own `README.md` status line at the same time,
and add a short "what actually landed" note where the findings table is,
so a later reader can tell which findings were fixed as specified and
which were resolved differently.

## Definition of done

- `python -m pytest -q` passes.
- On the device: the screen test holds full brightness past five minutes
  and exits cleanly with the theme's contrast restored.
- The remaining-time overlay uses the active theme's face on a
  non-default theme.
- No statement in `README.md` or `CONTROLS.md` about sync or OTA
  describes behaviour that has not been run on hardware.
- `docs/README.md` and `docs/plan_1/README.md` agree on this
  directory's status.

## Non-goals

- Redesigning the pause screen or the System menu.
- Changing the wpm overlay's content or duration — d/h/m/s and the 2 s
  window are as requested.
