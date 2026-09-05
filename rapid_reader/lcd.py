"""SPI LCD drivers for the Waveshare Zero LCD HAT (A).

Two Sitronix controllers share one driver core:

* ``ST7789`` -- the centre 1.3" 240x240 panel (frame memory is exactly
  240x240, no window offsets).
* ``ST7735S`` -- the two 0.96" 80x160 side panels (frame memory is 132x162,
  so the visible window is offset by 26 columns / 1 row).

Hardware access goes through a small ``PanelIO`` interface (``command``,
``data``, ``reset_pulse``, ``backlight``) so the drivers can be exercised
with a recording fake in the tests. ``SpiIO`` is the real implementation on
top of ``spidev`` + ``lgpio``; both are imported lazily so this module can
be imported anywhere.

Pixel data is RGB565, big-endian, packed with :func:`rgb565` (pure Pillow,
no numpy).
"""

import time

# ---- RGB565 packing ----------------------------------------------------

_HI_R = bytes(v & 0xF8 for v in range(256))
_HI_G = bytes(v >> 5 for v in range(256))
_LO_G = bytes((v & 0x1C) << 3 for v in range(256))
_LO_B = bytes(v >> 3 for v in range(256))


def rgb565(image):
    """Pack a Pillow image into big-endian RGB565 bytes (2 bytes/pixel)."""
    from PIL import Image, ImageChops
    if image.mode != "RGB":
        image = image.convert("RGB")
    r, g, b = image.split()
    hi = ImageChops.add(r.point(_HI_R), g.point(_HI_G))
    lo = ImageChops.add(g.point(_LO_G), b.point(_LO_B))
    return Image.merge("LA", (hi, lo)).tobytes()


# ---- hardware access ---------------------------------------------------

class SpiIO:
    """Real panel I/O: one spidev device plus DC/RST/BL lines via lgpio.

    ``chip`` is a shared lgpio gpiochip handle (see :func:`open_gpiochip`).
    RST is claimed already *high* (it is active low) so opening a panel that
    is already showing something never resets it.
    """

    def __init__(self, chip, spi, dc, rst, bl, speed_hz, pwm_hz=1000):
        import lgpio
        import spidev
        self._lgpio = lgpio
        self._chip = chip
        self._dc, self._rst, self._bl = dc, rst, bl
        self._pwm_hz = pwm_hz
        lgpio.gpio_claim_output(chip, dc, 0)
        lgpio.gpio_claim_output(chip, rst, 1)
        lgpio.gpio_claim_output(chip, bl, 0)
        self.spi = spidev.SpiDev()
        self.spi.open(*spi)
        self.spi.max_speed_hz = speed_hz
        self.spi.mode = 0

    def command(self, cmd):
        self._lgpio.gpio_write(self._chip, self._dc, 0)
        self.spi.writebytes([cmd])

    def data(self, buf):
        if not buf:
            return
        self._lgpio.gpio_write(self._chip, self._dc, 1)
        self.spi.writebytes2(buf)

    def reset_pulse(self):
        g = self._lgpio
        g.gpio_write(self._chip, self._rst, 1)
        time.sleep(0.01)
        g.gpio_write(self._chip, self._rst, 0)
        time.sleep(0.01)
        g.gpio_write(self._chip, self._rst, 1)
        time.sleep(0.12)

    def backlight(self, level):
        level = max(0.0, min(1.0, float(level)))
        if level <= 0.0 or level >= 1.0:
            self._lgpio.tx_pwm(self._chip, self._bl, self._pwm_hz, 0)
            self._lgpio.gpio_write(self._chip, self._bl, 1 if level else 0)
        else:
            self._lgpio.tx_pwm(self._chip, self._bl, self._pwm_hz,
                               level * 100.0)

    def close(self):
        self.spi.close()
        for pin in (self._dc, self._rst, self._bl):
            self._lgpio.gpio_free(self._chip, pin)


def open_gpiochip(number=0):
    import lgpio
    return lgpio.gpiochip_open(number)


def close_gpiochip(handle):
    import lgpio
    lgpio.gpiochip_close(handle)


# ---- controllers -------------------------------------------------------

class ST77xx:
    """Common ST7789/ST7735 behaviour. Subclasses supply INIT and geometry."""

    INIT = ()           # sequence of (command, data_bytes, delay_seconds)
    MEM_W = MEM_H = 0   # controller frame memory size

    def __init__(self, io, width, height, madctl, col_offset=0, row_offset=0):
        self.io = io
        self.width, self.height = width, height
        self.madctl = madctl
        self.col_offset, self.row_offset = col_offset, row_offset
        self.backlight_level = 0.0

    # -- setup --

    def init(self):
        """Hard-reset, run the vendor init sequence, blank the panel and
        turn the display on (backlight stays as it was)."""
        self.io.reset_pulse()
        for cmd, data, delay in self.INIT:
            self.io.command(cmd)
            self.io.data(bytes(data))
            if delay:
                time.sleep(delay)
        self.io.command(0x36)                 # MADCTL
        self.io.data(bytes([self.madctl]))
        self.show_raw(bytes(self.width * self.height * 2))
        self.io.command(0x29)                 # DISPON
        time.sleep(0.02)

    # -- drawing --

    def set_window(self, x0, y0, x1, y1):
        """Address window in panel pixels (inclusive corners)."""
        cx0, cx1 = x0 + self.col_offset, x1 + self.col_offset
        ry0, ry1 = y0 + self.row_offset, y1 + self.row_offset
        self.io.command(0x2A)                 # CASET
        self.io.data(bytes([cx0 >> 8, cx0 & 0xFF, cx1 >> 8, cx1 & 0xFF]))
        self.io.command(0x2B)                 # RASET
        self.io.data(bytes([ry0 >> 8, ry0 & 0xFF, ry1 >> 8, ry1 & 0xFF]))

    def show_raw(self, buf, x=0, y=0, w=None, h=None):
        """Push pre-packed RGB565 bytes into a window (default: full panel)."""
        w = self.width if w is None else w
        h = self.height if h is None else h
        if len(buf) != w * h * 2:
            raise ValueError("buffer is %d bytes, expected %d for %dx%d"
                             % (len(buf), w * h * 2, w, h))
        self.set_window(x, y, x + w - 1, y + h - 1)
        self.io.command(0x2C)                 # RAMWR
        self.io.data(buf)

    def show(self, image, x=0, y=0):
        """Display a Pillow image at (x, y); full-frame when it is panel-sized."""
        if x + image.width > self.width or y + image.height > self.height:
            raise ValueError("image %r at (%d,%d) does not fit %dx%d panel"
                             % (image.size, x, y, self.width, self.height))
        self.show_raw(rgb565(image), x, y, image.width, image.height)

    def backlight(self, level):
        self.backlight_level = level
        self.io.backlight(level)

    def sleep(self):
        """Backlight off, display off, controller to sleep."""
        self.backlight(0.0)
        self.io.command(0x28)                 # DISPOFF
        self.io.command(0x10)                 # SLPIN
        time.sleep(0.005)


class ST7789(ST77xx):
    """1.3" 240x240 (Waveshare init sequence)."""

    MEM_W = MEM_H = 240
    INIT = (
        (0x3A, b"\x05", 0),                                   # COLMOD RGB565
        (0xB2, b"\x0c\x0c\x00\x33\x33", 0),                   # PORCTRL
        (0xB7, b"\x35", 0),                                   # GCTRL
        (0xBB, b"\x19", 0),                                   # VCOMS
        (0xC0, b"\x2c", 0),                                   # LCMCTRL
        (0xC2, b"\x01", 0),                                   # VDVVRHEN
        (0xC3, b"\x12", 0),                                   # VRHS
        (0xC4, b"\x20", 0),                                   # VDVS
        (0xC6, b"\x0f", 0),                                   # FRCTRL2 60Hz
        (0xD0, b"\xa4\xa1", 0),                               # PWCTRL1
        (0xE0, bytes([0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54,
                      0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23]), 0),  # PVGAMCTRL
        (0xE1, bytes([0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44,
                      0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23]), 0),  # NVGAMCTRL
        (0x21, b"", 0),                                       # INVON
        (0x11, b"", 0.12),                                    # SLPOUT
    )

    # Vendor demo: MADCTL 0x70 with the image rotated 270 degrees, which is
    # the same memory mapping as MADCTL 0xC0 (MX|MY) with an unrotated image.
    MADCTL_NORMAL = 0xC0
    MADCTL_FLIPPED = 0x00

    def __init__(self, io, rotate_180=False):
        super().__init__(io, 240, 240,
                         self.MADCTL_FLIPPED if rotate_180 else self.MADCTL_NORMAL)


class ST7735S(ST77xx):
    """0.96" 80x160, driven portrait (80 wide, 160 tall, ribbon at the bottom)."""

    MEM_W, MEM_H = 132, 162
    INIT = (
        (0x11, b"", 0.12),                                    # SLPOUT
        (0x21, b"", 0),                                       # INVON
        (0xB1, b"\x05\x3a\x3a", 0),                           # FRMCTR1
        (0xB2, b"\x05\x3a\x3a", 0),                           # FRMCTR2
        (0xB3, b"\x05\x3a\x3a\x05\x3a\x3a", 0),               # FRMCTR3
        (0xB4, b"\x03", 0),                                   # INVCTR
        (0xC0, b"\x62\x02\x04", 0),                           # PWCTR1
        (0xC1, b"\xc0", 0),                                   # PWCTR2
        (0xC2, b"\x0d\x00", 0),                               # PWCTR3
        (0xC3, b"\x8d\x6a", 0),                               # PWCTR4
        (0xC4, b"\x8d\xee", 0),                               # PWCTR5
        (0xC5, b"\x0e", 0),                                   # VMCTR1
        (0xE0, bytes([0x10, 0x0E, 0x02, 0x03, 0x0E, 0x07, 0x02, 0x07,
                      0x0A, 0x12, 0x27, 0x37, 0x00, 0x0D, 0x0E, 0x10]), 0),
        (0xE1, bytes([0x10, 0x0E, 0x03, 0x03, 0x0F, 0x06, 0x02, 0x08,
                      0x0A, 0x13, 0x26, 0x36, 0x00, 0x0D, 0x0E, 0x10]), 0),
        (0x3A, b"\x05", 0),                                   # COLMOD RGB565
    )

    # Vendor demo drives these landscape with MADCTL 0xA8 (MY|MV|BGR) and
    # offsets x+1, y+26. Dropping MV gives portrait; the visible window is
    # centred in the 132x162 memory so the offsets are the same whichever
    # way the panel is flipped.
    MADCTL_NORMAL = 0xC8   # MX|MY|BGR  (Adafruit "rotation 0": ribbon at bottom)
    MADCTL_FLIPPED = 0x08  # BGR only    (180 degrees)
    COL_OFFSET, ROW_OFFSET = 26, 1

    def __init__(self, io, rotate_180=False):
        super().__init__(io, 80, 160,
                         self.MADCTL_FLIPPED if rotate_180 else self.MADCTL_NORMAL,
                         self.COL_OFFSET, self.ROW_OFFSET)
