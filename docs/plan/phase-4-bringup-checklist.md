# Phase 4 — Bring-up

**Status:** not started. **Depends on:** Phase 2 (a working build to
flash). **This is not a coding-agent prompt** — every item here requires
the physical Pi Zero W + SH1106 HAT in hand and is checked by a human
(or by an agent with real hardware access via SSH to the device, which is
a very different, much higher-trust setup than the nimble text-editing
agents used for Phases 0/1A/1B/1C/1D/3). Treat this file as a checklist to
work through on the bench, not a task to delegate blind.

## Before you start

- Build a card: `sudo tools/salvage_card.sh /dev/sdX /root/rr-salvage`
  (if replacing an existing card) then `sudo tools/build_card.sh /dev/sdX
  /root/rr-salvage`.
- Have `ssh reader@rapidreader.local` working before disconnecting from a
  monitor — there is no monitor output on this HAT to fall back on.
- Keep `journalctl -u rapid-reader -f` open in a second terminal the
  whole time.

## Checklist

- [ ] **Boot / splash.** Power on; the SH1106 should show the splash
  frame within a few seconds (kernel SPI bring-up), library within
  another few seconds (Python/Pillow import). If nothing appears, check
  `journalctl` for `display: hardware not ready` retries — if these never
  resolve, re-check the SPI0 CE0 wiring and `dtparam=spi=on` in
  `config.txt` before touching software.
- [ ] **Orientation.** If the image is upside down or mirrored, that's
  the segment-remap/COM-scan pair Phase 1A left as a to-be-confirmed
  choice — flip `config.ROTATE_180` (this also swaps the joystick's
  up/down/left/right mapping to match, so check both together, not just
  the picture).
- [ ] **Column offset.** If the image is shifted left/right by a
  consistent small number of pixels (text clipped on one edge, blank
  strip on the other), adjust `config.OLED_COL_OFFSET` (Phase 0 defaults
  it to `2`, the SH1106 standard, but clone boards occasionally differ).
- [ ] **Key mapping.** Press each of K1/K2/K3 and each joystick direction
  one at a time from the library screen; confirm each produces the event
  the control map says it should (a stray `journalctl` print statement or
  a temporary debug screen showing the last event name is the fastest way
  to check this without guessing from UI behaviour alone). Fix any
  mismatch in `config.PINS`, not by editing `buttons.py`'s logic.
- [ ] **Frame timing.** At `config.MAX_WPM` (900), confirm words are not
  visibly stuttering or skipping — this exercises the real SPI transfer
  time, which Phase 0's hardware-facts estimate (~5ms/frame at 4MHz) said
  should have ~13x headroom. If it doesn't, check the actual negotiated
  SPI clock (`config.OLED_SPEED_HZ`) took effect — Pi SPI clocks are
  quantised to divisors of the core clock, so the effective rate may be
  lower than requested; log it once at startup if it's not obviously
  right from behaviour alone.
- [ ] **Theme presets.** Cycle through all 5 themes on a real page of
  text; confirm each is legible at arm's length and that `"paper"`
  (inverted, mostly-lit background) doesn't look broken or feel
  uncomfortably bright — note this mode also draws more current than the
  others (more OLED pixels lit); if that's a problem in practice,
  consider capping `"paper"`'s contrast lower than the other presets'
  default in `theme.py` and revisit.
- [ ] **Idle dim → off → wake.** Sit on the library screen without
  input; confirm dimming at `config.IDLE_DIM_SECS` and sleep at
  `config.IDLE_OFF_SECS`, and that the very next key press after sleep
  wakes the display and is swallowed (no accidental navigation from the
  waking key), matching Phase 2's `App._tick_idle`/`run()` logic.
- [ ] **Power / reboot.** Exercise `SystemScreen`'s reboot and power-off
  actions end to end (not just that the confirm dialog appears) — confirm
  the display actually sleeps before power is cut, matching the SIGTERM
  handler's behaviour.
- [ ] **SIGTERM / service restart.** `sudo systemctl restart
  rapid-reader` while a book is open and playing; confirm position/time-
  read are saved (compare `state.json` before/after) and the display
  goes dark cleanly rather than freezing mid-frame.
- [ ] **Resume after power-cut.** Pull power while `in_book` is true
  (mid-reading, not paused); reboot; confirm it resumes paused at
  (approximately) the last saved position, per the existing
  `save_every_words`/periodic-save behaviour.
- [ ] **Full control-map walk.** Go through every row of Phase 0's
  control map on the physical device, not just the items above — this is
  the same checklist Phase 2's automated tests already exercise in
  simulation; the point here is confirming nothing was lost in the
  translation from fake hardware to real hardware (timing feel, bounce,
  double-firing on release, etc.).

## If something's wrong

- Software logic bugs (wrong screen, wrong data) → file it against
  Phase 2.
- Timing/orientation/pin issues → fix in `config.py` directly on the
  device first (`/opt/rapid-reader/config.py`,
  `sudo systemctl restart rapid-reader` to pick it up), confirm the fix,
  *then* port the same constant change back into the repo's `config.py`
  and rebuild future cards from that.
- Anything that looks like an SH1106 init-sequence problem (ghosting,
  dim/washed-out picture, noise) → re-check the exact command bytes in
  `oled.py`'s `SH1106.init()` against `datasheets/SH1106.pdf` — Phase 1A's
  doc flagged the VCOM/pre-charge values as the most likely to need
  tuning for this specific clone board.
