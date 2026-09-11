# Phase 3 — Tooling / docs

**Status:** not started. **Depends on:** Phase 0 (`config.py`, for the
exact pin numbers to write into `config.txt` and the docs).
**Parallel with:** 1A, 1B, 1C, 1D, and 2 (touches an unrelated set of
files — build script, systemd unit, markdown docs).

## Context you need

Read first:
- [`phase-0-contracts.md`](phase-0-contracts.md) — the finalized pins
  (`config.PINS`, `config.OLED_*`) and control map.
- `tools/build_card.sh` — full file (301 lines); the parts you're
  changing are the `config.txt` heredoc (`~line 96-109`) and the
  `cmdline.txt` edit (`~line 111-118`); everything else (partitioning,
  qemu chroot, user/wifi/salvage handling, service enable, smoke-test
  import) is untouched.
- `system/rapid-reader.service` — untouched by this phase (no pin/HAT-
  specific content in it).
- `README.md`, `CONTROLS.md`, `datasheets/README.md` — full rewrites/
  additions, see below.
- `datasheets/SH1106.pdf` — already present in the repo (currently
  untracked in git status; `git add` it as part of this phase's commit).

## Deliverables

### 1. `tools/build_card.sh`

- Remove the `dtoverlay=spi1-1cs` line and its comment from the
  `config.txt` heredoc — the new HAT only uses SPI0 CE0, there is no
  second SPI bus involved any more. Keep `dtparam=spi=on`.
- Add a GPIO pull-up hint for all 8 input pins so they read a clean level
  from the moment the bootloader brings up GPIO, before `gpiozero`
  configures them at the Python level (mirrors why the old file didn't
  need this for the two-key HAT, which relied solely on `gpiozero`'s
  runtime pull-up — this line is extra insurance during the brief window
  before the app starts):
  ```
  gpio=6,19,5,26,13,21,20,16=pu
  ```
  Add this to the same `config.txt` heredoc, with a comment listing which
  pins these are (joystick + K1/K2/K3, from `config.PINS`) so a future
  reader doesn't have to cross-reference `config.py` to know why these
  eight numbers are there.
- Update the heredoc's leading comment (`# --- Rapid Reader: Waveshare
  Zero LCD HAT (A) ---`) to name the new HAT instead.
- Leave `dtoverlay=disable-bt`, `disable_splash=1`, `boot_delay=0`, the
  `cmdline.txt` edits (`quiet loglevel=3 spidev.bufsiz=65536
  cfg80211.ieee80211_regdom=...`), the package list (`PKGS=`), and every
  other part of the script untouched — `python3-lgpio`/`python3-spidev`
  are still needed (GPIO + SPI, just fewer pins/one bus), and
  `fonts-dejavu-core` is still needed. **Before adding any new font
  package for the "serif"/"mono" theme faces Phase 1C's `theme.py`
  expects**, check whether `fonts-dejavu-core` already ships
  `DejaVuSerif.ttf`/`DejaVuSansMono.ttf` (it very likely does — the Debian
  "core" subset of DejaVu includes the four basic families' regular+bold
  weights, just not italics/condensed) by installing that package on any
  Debian-family box and checking `/usr/share/fonts/truetype/dejavu/` (or
  `dpkg -L fonts-dejavu-core | grep -i serif`). Only add a new package
  line to `PKGS` if a face genuinely turns out to be missing; do not add
  one speculatively.
- `spidev.bufsiz=65536` in `cmdline.txt` was sized for the old three-panel
  build's largest single transfer (a 240x240 RGB565 frame, 115,200
  bytes, sent in two chunks). The new HAT's largest transfer is one
  monochrome page write, 128 bytes, or a full-frame push of 8 such
  writes — 1024 bytes total, comfortably under any reasonable `bufsiz`.
  Leave `spidev.bufsiz=65536` as-is (harmless to keep; not worth touching
  a value used correctly by other things on the system) rather than
  "optimizing" it down — flag this reasoning in a comment if you want,
  but do not reduce the value.

### 2. `README.md` — rewrite

Update, at minimum:
- The opening description (no longer "one 1.3in IPS panel flanked by two
  0.96in panels, plus two keys" — now "a 1.3in 128x64 monochrome SH1106
  OLED display, a 5-way joystick and 3 buttons").
- The repository-layout table: `lcd.py` → `oled.py`; add `theme.py`,
  `state.py`, `screens.py`, `contracts.py` rows; remove any row that
  implied three panels.
- The hardware table: replace the three-panel table with the SH1106
  pinout from Phase 0's `config.py` (SPI0 CE0: MOSI/SCLK/DC/RST; no CS
  GPIO line to list since the kernel spidev driver owns CE0 directly; no
  backlight row — note contrast is software/register-controlled instead).
  Also replace the keys table with all 8 inputs (K1/K2/K3 + 5-way
  joystick, each with its BCM pin).
- The architecture `mermaid` diagram: one OLED panel instead of three,
  `buttons.Input` instead of `buttons.TapButton`, `main.App` with a
  `screens.py` stack instead of a fixed `MENU/READING/PAUSED/...` enum,
  `state.State`/`theme.Theme` as separate boxes feeding into it. Follow
  the mermaid syntax conventions already used in the existing diagram
  (no spaces in node IDs, quoted labels where they contain punctuation).
- The prose bullets under "Architecture" describing the old side-screen
  redraw-on-content-change optimization, backlight PWM dimming, and
  three-screen splash — replace with equivalents for: idle
  dim/off (Phase 2's `_tick_idle`), single splash file, and the
  screen-stack navigation model.
- The "Controls (summary)" table and everywhere else the old K1/K2
  tap/double/triple-tap vocabulary is mentioned — replace with the
  control map from Phase 0 (tap/hold/repeat, 8 inputs).
- "Development & tests" section's file-by-file coverage list — update
  file names (`test_lcd.py` → `test_oled.py`, add `test_state.py`,
  `test_screens.py` if it's a separate file) and drop anything describing
  three-panel-specific test behaviour.
- Any mention of `fonts-dejavu-core`/`ttf-dejavu` and `FONT_DIRS` — keep,
  but note the serif/mono faces are used by some themes now (see build
  script section above).

### 3. `CONTROLS.md` — rewrite

Replace the whole file with the new control map from Phase 0's
contracts doc: the 8 inputs and their BCM pins (cross-reference
`config.PINS`), the tap/hold/repeat timing table (`config.HOLD_DELAY`,
`config.REPEAT_SECS` — no more `TAP_WINDOW`/multi-tap section, that
vocabulary is gone), and a per-screen table (Library / Reading / Paused /
lists / idle) matching Phase 0's control map exactly, including the K3
context-action convention. Keep the file's existing tone and structure
(a "gesture -> timing" table up top, then one section per mode) — it
reads well, just needs new content.

### 4. `datasheets/README.md` — add a new hardware section

The Raspberry Pi Zero W section is unchanged (still the same board). Add
a new section for the OLED HAT, e.g.:

```markdown
## 1.3inch SH1106 OLED HAT (joystick + 3 buttons) — `datasheets/`

The current Rapid Reader hardware. Sold under several near-identical
clone brand names (this unit: "xicoolee"); electrically and pin-for-pin
compatible with Waveshare's own 1.3" OLED HAT designs built around the
same SH1106 controller. No vendor-specific schematic/mechanical PDF was
available for this exact clone at build time; the pinout below was
confirmed against the SH1106 controller datasheet and the physical unit.

| File | Source |
|---|---|
| `SH1106.pdf` | SH1106 OLED controller datasheet |

### Pinout (BCM GPIO, all active-low with pull-ups for the buttons)

| Function | Pin |
|---|---|
| OLED SPI bus | SPI0 CE0 (`/dev/spidev0.0`) |
| OLED MOSI | BCM 10 |
| OLED SCLK | BCM 11 |
| OLED CS | BCM 8 (SPI0 CE0, kernel-managed) |
| OLED DC | BCM 24 |
| OLED RST | BCM 25 |
| K1 | BCM 21 |
| K2 | BCM 20 |
| K3 | BCM 16 |
| Joystick UP | BCM 6 |
| Joystick DOWN | BCM 19 |
| Joystick LEFT | BCM 5 |
| Joystick RIGHT | BCM 26 |
| Joystick PRESS | BCM 13 |

### Controller notes

* SH1106: page-addressed, 132x64 controller RAM, 128x64 visible — column
  address offset of 2 (see `config.OLED_COL_OFFSET`). No backlight;
  brightness is the contrast register (command `0x81`). SPI mode 0, MSB
  first, max ~4 MHz per the datasheet.
* Confirm the previous section's board (Waveshare Zero LCD HAT (A)) is
  kept above for historical reference — that hardware is no longer used
  by this project as of the SH1106 overhaul, but its datasheets remain
  useful if the project is ever ported back or forked for that HAT.
```

Adjust wording/exact phrasing as needed, but keep the pin table numbers
exactly matching `rapid_reader/config.py` from Phase 0 — that table is
the thing most likely to silently drift out of sync with the code if
copied by hand, so if Phase 0 has landed by the time you write this,
copy the values directly from `config.py`, don't retype them from this
doc.

### 5. `git add datasheets/SH1106.pdf`

It's already in the working tree but untracked; include it in this
phase's commit.

## Definition of done

- `tools/build_card.sh` still passes `bash -n tools/build_card.sh` (syntax
  check) and its `set -euo pipefail` header is untouched.
- `README.md`, `CONTROLS.md`, `datasheets/README.md` describe the SH1106
  HAT throughout, with no leftover references to the three-screen
  Waveshare Zero LCD HAT (A) as *current* hardware (mentioning it as
  historical/superseded in `datasheets/README.md` is fine and expected).
- `datasheets/SH1106.pdf` is tracked in git.
- No changes to any file under `rapid_reader/` or `tests/` — this phase
  is strictly tooling/config/docs.

## Non-goals

- Do not change `system/rapid-reader.service` — nothing in this phase
  requires it, and Phase 2 doesn't either (the service already just runs
  `boot.py` regardless of which HAT is attached).
- Do not attempt to verify pin numbers against a physical board — that is
  Phase 4's job; this phase only needs internal consistency with
  `config.py`.
