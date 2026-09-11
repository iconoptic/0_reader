"""SH1106 OLED driver for the 1.3" SPI HAT.

Hardware access goes through a small ``PanelIO`` duck type (``command``,
``data``, ``reset_pulse``) so the controller can be exercised with a
recording fake in the tests. ``SpiIO`` is the real implementation on top
of ``spidev`` + ``lgpio``; both are imported lazily so this module can be
imported anywhere.

Pixels are 1-bit, packed page-major for the SH1106 with :func:`pack_pages`
(pure Pillow, no numpy). There is no backlight GPIO — brightness is the
controller contrast register.
"""

import time

import config

# Bit-reverse every byte so Pillow mode-"1" MSB-first packing becomes the
# SH1106's LSB-at-top-of-page order (see :func:`pack_pages`).
_BIT_REVERSE = bytes(int(f"{v:08b}"[::-1], 2) for v in range(256))


def pack_pages(image):
    """Pack a Pillow mode-``"1"`` image into SH1106 page-major bytes.

    ``image`` must be size ``(config.OLED_W, config.OLED_H)``. Returns
    1024 bytes: page 0's 128 column-bytes, then page 1's, ... page 7's.
    Bit 0 of each column-byte is the top row of that 8-row page band.
    """
    from PIL import Image

    if image.mode != "1":
        raise ValueError("pack_pages expects mode '1', got %r" % image.mode)
    if image.size != (config.OLED_W, config.OLED_H):
        raise ValueError("pack_pages expects %dx%d, got %r"
                         % (config.OLED_W, config.OLED_H, image.size))
    # Transpose so each original column becomes a row of 64 pixels (= 8
    # bytes, one per page). tobytes() packs MSB-first; bit-reverse so bit 0
    # is the top of the page. Then stride-gather into page-major order.
    transposed = image.transpose(Image.TRANSPOSE)
    reversed_buf = transposed.tobytes().translate(_BIT_REVERSE)
    return b"".join(reversed_buf[k::8] for k in range(8))


# ---- hardware access ---------------------------------------------------

class SpiIO:
    """Real panel I/O: one spidev device plus DC/RST lines via lgpio.

    ``chip`` is a shared lgpio gpiochip handle (see :func:`open_gpiochip`).
    RST is claimed already *high* (it is active low) so opening a panel that
    is already showing something never resets it.
    """

    def __init__(self, chip, spi, dc, rst, speed_hz):
        import lgpio
        import spidev
        self._lgpio = lgpio
        self._chip = chip
        self._dc, self._rst = dc, rst
        lgpio.gpio_claim_output(chip, dc, 0)
        lgpio.gpio_claim_output(chip, rst, 1)
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

    def close(self):
        self.spi.close()
        for pin in (self._dc, self._rst):
            self._lgpio.gpio_free(self._chip, pin)


def open_gpiochip(number=0):
    import lgpio
    return lgpio.gpiochip_open(number)


def close_gpiochip(handle):
    import lgpio
    lgpio.gpiochip_close(handle)


# ---- controller --------------------------------------------------------

class SH1106:
    """1.3" 128x64 SH1106 over 4-wire SPI."""

    WIDTH, HEIGHT = 128, 64
    FRAME_BYTES = WIDTH * HEIGHT // 8  # 1024

    # Segment-remap / COM-scan pairs (datasheet A0/A1 + C0/C8). Defaults
    # match common 128x64 modules; Phase 4 bring-up confirms which pair is
    # upright on this HAT and may swap NORMAL/FLIPPED.
    SEG_COM_NORMAL = (0xA1, 0xC8)
    SEG_COM_FLIPPED = (0xA0, 0xC0)  # rotate_180=True

    def __init__(self, io, col_offset=None, rotate_180=False):
        self.io = io
        self.width, self.height = self.WIDTH, self.HEIGHT
        self.col_offset = (config.OLED_COL_OFFSET if col_offset is None
                           else col_offset)
        self.rotate_180 = bool(rotate_180)
        self.seg_com = (self.SEG_COM_FLIPPED if self.rotate_180
                        else self.SEG_COM_NORMAL)

    def _cmd(self, *bytes_):
        for b in bytes_:
            self.io.command(b)

    def init(self):
        """Hard-reset, configure, blank the panel, then display on."""
        self.io.reset_pulse()
        seg, com = self.seg_com
        # Verified against datasheets/SH1106.pdf (cmds AE/AF, AD/8B DC-DC,
        # A0/A1, C0/C8, DA alternative COM, D9/DB POR-ish defaults).
        # 0xAF is deliberately *not* here — blank first, then wake.
        seq = (
            0xAE,                 # display off
            0xD5, 0x80,           # display clock divide / osc frequency
            0xA8, 0x3F,           # multiplex ratio = 64
            0xD3, 0x00,           # display offset = 0
            0x40,                 # display start line = 0
            0xAD, 0x8B,           # DC-DC control (internal pump on)
            seg,                  # segment remap
            com,                  # COM output scan direction
            0xDA, 0x12,           # COM pins hardware config (alternative)
            0x81, 0xCF,           # contrast (matches IDLE_ACTIVE_CONTRAST)
            0xD9, 0x22,           # pre-charge period (POR: 2/2 DCLKs)
            0xDB, 0x35,           # VCOM deselect level (POR)
            0xA6,                 # normal (non-inverted) display
        )
        self._cmd(*seq)
        self.show_raw(bytes(self.FRAME_BYTES))
        self.io.command(0xAF)     # display on

    def _set_page_column(self, page):
        off = self.col_offset
        self._cmd(0xB0 | page,
                  0x00 | (off & 0x0F),
                  0x10 | (off >> 4))

    def show_raw(self, buf):
        """Push a pre-packed 1024-byte SH1106 page buffer."""
        if len(buf) != self.FRAME_BYTES:
            raise ValueError("buffer is %d bytes, expected %d"
                             % (len(buf), self.FRAME_BYTES))
        w = self.WIDTH
        for page in range(8):
            self._set_page_column(page)
            self.io.data(buf[page * w:(page + 1) * w])

    def show(self, image):
        """Display a Pillow image. Accepts mode ``"1"``, or ``"L"`` /
        convertible modes thresholded at 128 with no dithering."""
        from PIL import Image

        if image.size != (self.WIDTH, self.HEIGHT):
            raise ValueError("image %r does not fit %dx%d panel"
                             % (image.size, self.WIDTH, self.HEIGHT))
        if image.mode != "1":
            if image.mode != "L":
                image = image.convert("L")
            image = image.point(lambda p: 255 if p >= 128 else 0, mode="1")
        self.show_raw(pack_pages(image))

    def contrast(self, value):
        value = max(0, min(255, int(value)))
        self._cmd(0x81, value)

    def invert(self, on):
        self.io.command(0xA7 if on else 0xA6)

    def sleep(self):
        self.io.command(0xAE)

    def wake(self):
        self.io.command(0xAF)
