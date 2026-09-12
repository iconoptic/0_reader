# Phase 1A — Driver

**Status:** done. **Depends on:** Phase 0 (`config.py`, `contracts.py`).
**Parallel with:** 1B, 1C, 1D, 3.

## Context you need

Read first:
- [`phase-0-contracts.md`](phase-0-contracts.md) — the exact `config.py`
  constants this phase uses (`OLED_SPI`, `OLED_DC`, `OLED_RST`,
  `OLED_SPEED_HZ`, `OLED_W`, `OLED_H`, `OLED_COL_OFFSET`, `GPIO_CHIP`,
  `ROTATE_180`).
- `rapid_reader/lcd.py` (current file, being replaced) — study its
  structure for conventions to reuse: a `PanelIO` duck-typed interface
  (`command`/`data`/`reset_pulse`), a real `SpiIO` on top of `spidev` +
  `lgpio` imported lazily, `open_gpiochip`/`close_gpiochip` helpers, and the
  no-numpy, lookup-table style used for `rgb565()` — apply that same style
  to the new bit-packing function.
- `rapid_reader/display.py` (current file, being replaced) — the
  `Display` facade shape, `open_display()`'s retry loop against transient
  `OSError`/`lgpio.error`, and the splash-loading pattern in
  `Display.splash()`.
- `rapid_reader/boot.py` — how the splash is pushed before the rest of the
  app is imported.
- `tests/test_lcd.py` and `tests/test_display.py` — current test shapes
  for the same driver/display responsibilities; the new tests should cover
  equivalent ground for one panel instead of three.

## Deliverables

- **New** `rapid_reader/oled.py` — replaces `rapid_reader/lcd.py`.
- **Rewrite** `rapid_reader/display.py` — single panel instead of three.
- **Rewrite** `rapid_reader/boot.py` — one splash file instead of three.
- **Rewrite** `tools/make_splash.py` — writes one `splash.bin` instead of
  three `.rgb565` files.
- **Delete** `rapid_reader/lcd.py`, `tests/test_lcd.py`.
- **New** `tests/test_oled.py` (replaces `test_lcd.py`'s coverage).
- **Update** `tests/test_display.py` for the single-panel `Display`.
- **Update** `tests/conftest.py`: replace the three-panel `FakePanel`
  fixture wiring with a single fake panel sized `config.OLED_W x
  config.OLED_H`; keep the `FakePanel` class itself (it is generic) but
  update the `fake_display` fixture to build one panel, and update
  `Display(...)` construction to match the new single-panel signature.

## `rapid_reader/oled.py` — required contents

### Pixel packing — `pack_pages(image)`

The SH1106 is page-addressed: 8 pages of 8 rows each (8 x 8 = 64), 128
columns. Each byte of the wire format covers one column of one page: bit 0
is the top row of that 8-row band, bit 7 the bottom row (this is the
opposite bit order from what `Pillow` mode `"1"` packs natively, which is
MSB-first along each row — see the transpose+reverse trick below).

```python
def pack_pages(image):
    """image: Pillow mode '1', size (config.OLED_W, config.OLED_H).
    Returns 1024 bytes: page 0's 128 column-bytes, then page 1's, ... page 7's.
    """
```

Suggested approach (avoids numpy, mirrors the lookup-table style already
used for `rgb565()` in the old `lcd.py`):

1. `image.transpose(Image.TRANSPOSE)` — swaps width/height to
   `(config.OLED_H, config.OLED_W)` = `(64, 128)`. After this,
   `transposed.getpixel((a, b)) == image.getpixel((b, a))`.
2. `transposed.tobytes()` — for a 64-wide `"1"`-mode image this packs each
   of the 128 rows into exactly 8 bytes (64/8, byte-aligned, no padding),
   MSB-first — i.e. row `b`'s byte `k` covers original pixels
   `image.getpixel((b, k*8))` .. `image.getpixel((b, k*8+7))`, with
   `getpixel((b, k*8))` as that byte's **bit 7** (need it as bit 0 — hence
   step 3), and `k` is exactly the SH1106 page number.
3. Bit-reverse every byte of the result (build a 256-entry `bytes.translate`
   table once at import time, e.g.
   `_BIT_REVERSE = bytes(int(f"{v:08b}"[::-1], 2) for v in range(256))`,
   then `raw.translate(_BIT_REVERSE)`).
4. The reversed buffer is 1024 bytes, laid out as `row0[8 bytes],
   row1[8 bytes], ...` where "row" = original column `x` and the 8 bytes
   per row are pages 0..7 for that column. Regroup into page-major order
   with `b"".join(reversed_buf[k::8] for k in range(8))`.

**Do not trust this derivation blindly.** Before wiring `pack_pages` into
the rest of the driver, write a slow, obviously-correct reference
implementation in the test file using nested loops and `image.getpixel()`
— no transpose, no lookup tables, just:

```python
def _reference_pack_pages(image):
    w, h = image.size
    out = bytearray(w * h // 8)
    for page in range(h // 8):
        for x in range(w):
            byte = 0
            for bit in range(8):
                if image.getpixel((x, page * 8 + bit)):
                    byte |= 1 << bit
            out[page * w + x] = byte
    return bytes(out)
```

Then assert `pack_pages(img) == _reference_pack_pages(img)` for at least:
an all-black image, an all-white image, a single lit pixel at `(0,0)`,
`(127,0)`, `(0,63)`, `(127,63)`, and one hand-drawn asymmetric pattern
(e.g. a diagonal line). If the fast version disagrees with the reference,
trust the reference and fix the fast version (or ship the reference
implementation as `pack_pages` outright if the optimisation doesn't matter
for performance — measure first: even the pure-Python reference loop is
~8k iterations, likely still well under 1ms, which is far below the ~5ms
frame budget at `OLED_SPEED_HZ`).

### `SpiIO` — real hardware I/O

Same shape as the old `lcd.py`'s `SpiIO`, minus everything backlight/PWM
related (there is no backlight pin on this HAT — "brightness" is the SH1106
contrast register, handled entirely by commands, not GPIO):

```python
class SpiIO:
    def __init__(self, chip, spi, dc, rst, speed_hz):
        # lgpio.gpio_claim_output(chip, dc, 0); lgpio.gpio_claim_output(chip, rst, 1)
        # spidev.SpiDev(); .open(*spi); .max_speed_hz = speed_hz; .mode = 0
        ...
    def command(self, cmd):       # DC low, write one byte
        ...
    def data(self, buf):          # DC high, write bytes (writebytes2)
        ...
    def reset_pulse(self):        # same high/low/high timing pattern as old lcd.py
        ...
    def close(self):
        ...
```

### `SH1106` controller class

```python
class SH1106:
    WIDTH, HEIGHT = 128, 64

    def __init__(self, io, col_offset=None, rotate_180=False):
        # col_offset defaults to config.OLED_COL_OFFSET
        ...

    def init(self):
        """reset_pulse(), run the init command sequence below, clear the
        whole panel (show an all-black frame) before turning the display on
        so there's no garbage flash, then DISPLAY ON."""

    def show(self, image):
        """image: Pillow mode '1' (or convertible — accept 'L' with a
        threshold too, document which), size WIDTHxHEIGHT. pack_pages(),
        then for each page 0..7: send the page/column-address commands,
        then DATA the page's 128 bytes."""

    def contrast(self, value):
        """0x81, value (0-255 int)."""

    def invert(self, on):
        """0xA7 if on else 0xA6."""

    def sleep(self):
        """0xAE (display off). No separate SLPIN register on SH1106."""

    def wake(self):
        """0xAF (display on)."""
```

**Init command sequence** (standard SH1106 128x64 init used by common
open-source drivers — Adafruit's SH1106 library, luma.oled's SH1106
variant, U8g2 — but **verify every byte against `datasheets/SH1106.pdf`
before finalizing**, since VCOM/pre-charge defaults are known to vary
slightly between vendor datasheets and cheap clone boards, and a wrong
value here typically shows up as a dim, ghosted, or noisy picture rather
than a hard failure):

```
0xAE                 ; display off
0xD5, 0x80            ; display clock divide / osc frequency
0xA8, 0x3F            ; multiplex ratio = 64
0xD3, 0x00            ; display offset = 0
0x40                  ; display start line = 0
0xAD, 0x8B            ; DC-DC control (SH1106-specific)
0xA0 or 0xA1          ; segment remap -- pick whichever gives correct
                      ; left/right orientation on the real panel; note
                      ; both as a config knob if unsure, resolve in Phase 4
0xC0 or 0xC8          ; COM output scan direction -- same caveat, resolve
                      ; the up/down pairing together with the segment
                      ; remap and `rotate_180` in Phase 4 bring-up
0xDA, 0x12            ; COM pins hardware configuration
0x81, 0xCF            ; contrast (config.SETTINGS defaults' initial value)
0xD9, 0x22            ; pre-charge period
0xDB, 0x35            ; VCOM deselect level
0xA6                  ; normal (non-inverted) display
0xAF                  ; display on
```

Expose the segment-remap / COM-scan pair as driven by the `rotate_180`
constructor argument (two fixed alternatives, not four independent
combinations) exactly like the old `lcd.py` did with `MADCTL_NORMAL` /
`MADCTL_FLIPPED` for the ST7789/ST7735S — same pattern, new registers.

**Column addressing per page** (needed inside `show()`):
```
0xB0 | page                              ; set page address (0-7)
0x00 | ((col_offset) & 0x0F)             ; set lower column address nibble
0x10 | ((col_offset) >> 4)               ; set higher column address nibble
```
then `data()` that page's 128 bytes.

## `rapid_reader/display.py` — single panel

Collapse the three-panel `Display` to one:

```python
class Display:
    def __init__(self, panel):
        self.panel = panel

    def show(self, image):
        self.panel.show(image)

    def contrast(self, value):
        self.panel.contrast(value)

    def invert(self, on):
        self.panel.invert(on)

    def splash(self, path=None):
        """Load config.SPLASH_DIR + '/splash.bin' (or `path`), a raw
        1024-byte SH1106 page-format buffer, and push it directly via a new
        SH1106.show_raw(buf) (add this method: same as show() but skips
        pack_pages, since the buffer is already packed) -- this keeps boot
        fast by not needing Pillow for the splash. Returns True if the file
        existed and was exactly 1024 bytes and was pushed, False otherwise
        (mirrors the old three-file all-or-nothing behaviour, just for one
        file)."""

    def sleep(self):
        self.panel.sleep()

    def wake(self):
        self.panel.wake()
```

Keep `open_display(retry_secs=None, log=print)` and its retry loop
against `_retryable(exc)` (`OSError`, or `lgpio` errors) essentially as-is,
just building one `SH1106`/`SpiIO` pair off `config.OLED_SPI` etc. instead
of three ST77xx panels. `init()` the panel, `contrast(config.SETTINGS_DEFAULTS["wpm"]` — no,
use `config.IDLE_ACTIVE_CONTRAST` or a sensible boot-time default, not a
settings-derived value; Phase 2's `App` is responsible for applying the
user's actual theme/contrast once state is loaded) before returning.

## `tools/make_splash.py` and `rapid_reader/boot.py`

- `make_splash.py`: render one frame via a new `render.splash()` (Phase 1C
  owns `render.py`; if it does not exist yet when you write this, stub a
  minimal placeholder frame here — a centered "Rapid Reader" message drawn
  with raw `PIL.ImageDraw` — and leave a `# TODO(Phase 1C): replace with
  render.splash()` comment; do not block on Phase 1C), `oled.pack_pages()`
  it, write exactly one `splash.bin` (1024 bytes) to the output dir
  (default `rapid_reader/splash`).
- `boot.py`: same early-imports-only structure as today, but call
  `disp.splash()` (no per-panel names) and update the log line
  accordingly.

## Tests (`tests/test_oled.py`)

Cover, using a fake `PanelIO` (recording fake exposing `command`/`data`/
`reset_pulse`, same pattern as the old `test_lcd.py`'s stub):
- `pack_pages` bit-exactness against the slow reference (see above).
- `SH1106.init()` sends exactly the finalized command sequence, blanks the
  panel before `0xAF`, and doesn't turn the display on before that.
- `SH1106.show(image)` sends the right page/column-address commands per
  page (0xB0..0xB7, correct lower/higher column nibbles including
  `col_offset`), in order, with the right 128-byte payload per page.
- `contrast()`, `invert(True/False)`, `sleep()`, `wake()` send exactly the
  expected bytes.
- `rotate_180=True` changes the segment-remap/COM-scan pair, not the
  column offset math.
- `SpiIO` against a stub `spidev`/`lgpio` (same technique as old
  `test_lcd.py`): claims the right GPIO pins, opens the right spi bus/dev,
  sets `max_speed_hz`/`mode`, DC pin toggles correctly around
  `command`/`data`.

## Definition of done

- `python3 -m pytest -q` green, including new/updated `test_oled.py` and
  `test_display.py`.
- `python3 tools/make_splash.py` writes a 1024-byte `splash.bin`.
- `rapid_reader/lcd.py` and `tests/test_lcd.py` no longer exist.
- No `numpy` dependency introduced.

## Non-goals

- Do not touch `buttons.py`, `render.py`, `theme.py`, `state.py`,
  `main.py`, `screens.py` — those belong to Phases 1B/1C/1D/2.
- Do not resolve the segment-remap/COM-scan/`rotate_180` orientation
  ambiguity by guessing "correct" on paper — pick one default, note the
  alternative in a comment, and leave final confirmation to Phase 4
  (on-device bring-up), exactly as `MAIN_ROTATE_180`/`SIDE_ROTATE_180` were
  handled in the old build.
