# Datasheets

Reference documents for the hardware used by Rapid Reader. The current
design is the SH1106 OLED HAT below; the Waveshare Zero LCD HAT (A)
section is kept for historical reference. All files were downloaded from
the vendors' own servers where a URL exists; the source URL for each is
listed so it can be re-fetched or checked for newer revisions.

## 1.3inch SH1106 OLED HAT (joystick + 3 buttons) — `datasheets/`

The current Rapid Reader hardware. Sold under several near-identical
clone brand names (this unit: "xicoolee"); electrically and pin-for-pin
compatible with Waveshare's own 1.3" OLED HAT designs built around the
same SH1106 controller. No vendor-specific schematic/mechanical PDF was
available for this exact clone at build time; the pinout below was
confirmed against the SH1106 controller datasheet and the physical unit,
and matches `rapid_reader/config.py`.

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
| K1 | BCM 16 |
| K2 | BCM 20 |
| K3 | BCM 21 |
| Joystick UP | BCM 13 |
| Joystick DOWN | BCM 19 |
| Joystick LEFT | BCM 5 |
| Joystick RIGHT | BCM 26 |
| Joystick PRESS | BCM 6 |

K1/K3 and UP/PRESS differ from the common Waveshare wiki values; this HAT
wires those pairs swapped. Canonical map: `config.PINS`.

### Controller notes

* SH1106: page-addressed, 132×64 controller RAM, 128×64 visible — column
  address offset of 2 (see `config.OLED_COL_OFFSET`). No backlight;
  brightness is the contrast register (command `0x81`). SPI mode 0, MSB
  first, max ~4 MHz per the datasheet.
* The previous section's board (Waveshare Zero LCD HAT (A)) is kept below
  for historical reference — that hardware is no longer used by this
  project as of the SH1106 overhaul, but its datasheets remain useful if
  the project is ever ported back or forked for that HAT.

## Raspberry Pi Zero W v1.1 — `raspberry-pi-zero-w/`

| File | Source |
|---|---|
| `raspberry-pi-zero-w-reduced-schematics.pdf` | <https://datasheets.raspberrypi.com/rpizero/raspberry-pi-zero-w-reduced-schematics.pdf> |
| `raspberry-pi-zero-w-mechanical-drawing.pdf` | <https://datasheets.raspberrypi.com/rpizero/raspberry-pi-zero-w-mechanical-drawing.pdf> |
| `bcm2835-peripherals.pdf` (SoC peripherals: GPIO, SPI0/SPI1, PWM, clocks) | <https://datasheets.raspberrypi.com/bcm2835/bcm2835-peripherals.pdf> |

Raspberry Pi does not publish a separate "datasheet"/product brief PDF for
the Zero W; the product page is <https://www.raspberrypi.com/products/raspberry-pi-zero-w/>.

User documentation (getting started, OS install, GPIO/SPI usage, config.txt,
boot options) is web-based, not a downloadable PDF:
<https://www.raspberrypi.com/documentation/computers/raspberry-pi.html>
<https://www.raspberrypi.com/documentation/computers/getting-started.html>

## Waveshare Zero LCD HAT (A) — `waveshare-zero-lcd-hat-a/` (historical / superseded)

Previous Rapid Reader hardware (three SPI LCDs + two keys). Kept for
reference only; the app no longer targets this HAT.

Wiki (pinout, demo download, FAQ): <https://www.waveshare.com/wiki/Zero_LCD_HAT_(A)>

| File | Source |
|---|---|
| `Zero_LCD_HAT_A-schematic.pdf` | <https://files.waveshare.com/wiki/Zero-LCD-HAT-A/Zero_LCD_HAT_(A)-schematic.pdf> |
| `Zero_LCD_HAT_A-mechanical-drawing.pdf` | <https://files.waveshare.com/wiki/Zero-LCD-HAT-A/zero-lcd-hat_a.pdf> |
| `1.3inch_LCD_Module-Datasheet.pdf` (240×240 panel module) | <https://files.waveshare.com/wiki/Zero-LCD-HAT-A/1.3inch_LCD_Module-Datasheet.pdf> |
| `0.96inch_LCD_Module-Datasheet.pdf` (160×80 panel module) | <https://files.waveshare.com/wiki/Zero-LCD-HAT-A/0.96inch_LCD_Module-Datasheet.pdf> |
| `ST7789VW-Datasheet.pdf` (controller of the 1.3" panel) | <https://files.waveshare.com/upload/a/ad/ST7789VW.pdf> |
| `ST7735S-Datasheet-V1.1.pdf` (controller of the 0.96" panels) | <https://www.waveshare.com/w/upload/e/e2/ST7735S_V1.1_20111121.pdf> |

Waveshare does not publish a separate PDF "manual" either; the wiki page
linked above *is* the user manual (specs, pinout, SPI/library setup,
demo download, framebuffer/desktop setup, FAQ).

The vendor demo code (`Zero_LCD_HAT_A_Demo.zip`, linked from the wiki) is
not committed here; the init sequences it uses were transcribed into
`rapid_reader/lcd.py`.

### Board summary

* Supply 3.3 V, up to ~840 mA with all three backlights at full brightness.
* Three SPI LCDs plus two side-actuated push buttons (K1 above K2 on the
  right edge). All signals are 3.3 V and go straight to the 40-pin header.
* Physical layout (board held with the ribbon cables at the bottom): a
  1.3" 240×240 screen in the centre with a portrait 0.96" 80×160 screen on
  each side.

### Pinout (physical header pin → BCM GPIO)

| Function | Screen 0 (1.3" ST7789VW) | Screen 1 (left 0.96" ST7735S) | Screen 2 (right 0.96" ST7735S) |
|---|---|---|---|
| SPI bus | SPI1 (`/dev/spidev1.0`, needs `dtoverlay=spi1-1cs`) | SPI0 CE0 (`/dev/spidev0.0`) | SPI0 CE1 (`/dev/spidev0.1`) |
| MOSI | pin 38 → BCM20 (SPI1 MOSI) | pin 19 → BCM10 (SPI0 MOSI) | pin 19 → BCM10 |
| SCLK | pin 40 → BCM21 (SPI1 SCLK) | pin 23 → BCM11 (SPI0 SCLK) | pin 23 → BCM11 |
| CS | pin 12 → BCM18 (SPI1 CE0) | pin 24 → BCM8 (SPI0 CE0) | pin 26 → BCM7 (SPI0 CE1) |
| DC | pin 15 → BCM22 | pin 7 → BCM4 | pin 29 → BCM5 |
| RST | pin 13 → BCM27 | pin 18 → BCM24 | pin 16 → BCM23 |
| BL (PWM-able) | pin 35 → BCM19 | pin 33 → BCM13 | pin 32 → BCM12 |

| Key | Pin | Notes |
|---|---|---|
| KEY1 (upper) | pin 22 → BCM25 | active low, use internal pull-up |
| KEY2 (lower) | pin 37 → BCM26 | active low, use internal pull-up |

### Controller notes (from the datasheets + vendor demo)

* **ST7789VW (1.3")**: frame memory is exactly 240×240 for this module, so
  no window offsets are needed. Vendor demo uses `MADCTL = 0x70`,
  `COLMOD = 0x05` (RGB565), `INVON` (0x21) — the panel is normally-inverted
  so *inversion on* gives correct colours — and sends the image rotated 270°.
* **ST7735S (0.96")**: frame memory is 132×162 but the glass is 80×160, so
  the visible window is offset. Vendor demo (landscape, `MADCTL = 0xA8`)
  uses column offset +1 and row offset +26; for the portrait orientation
  used in this project the offsets swap to column +26, row +1. Also needs
  `INVON` and `COLMOD = 0x05`.
* Both controllers accept SPI mode 0, MSB first, 8-bit words. The ST7789
  is specified to ~62.5 MHz write clock; the ST7735S to ~15 MHz. The Pi
  Zero's SPI clock is derived from the 250 MHz core clock by even
  division, so practical settings are 31.25 MHz (main) and 15.625 MHz
  (sides).
