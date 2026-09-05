"""Driver-level tests for the ST7789 / ST7735S panel code, using a recording
fake in place of spidev + lgpio."""

import struct

import pytest
from PIL import Image

import lcd


class FakeIO:
    def __init__(self):
        self.ops = []          # ("cmd", int) | ("data", bytes) | ("reset",) | ("bl", f)

    def command(self, cmd):
        self.ops.append(("cmd", cmd))

    def data(self, buf):
        if buf:
            self.ops.append(("data", bytes(buf)))

    def reset_pulse(self):
        self.ops.append(("reset",))

    def backlight(self, level):
        self.ops.append(("bl", level))

    # helpers
    def commands(self):
        return [op[1] for op in self.ops if op[0] == "cmd"]

    def after(self, cmd):
        """Data bytes that immediately follow the *last* occurrence of cmd."""
        idx = max(i for i, op in enumerate(self.ops) if op == ("cmd", cmd))
        nxt = self.ops[idx + 1] if idx + 1 < len(self.ops) else None
        return nxt[1] if nxt and nxt[0] == "data" else b""


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(lcd.time, "sleep", lambda s: None)


# ---- pixel packing -----------------------------------------------------

def test_rgb565_is_big_endian_and_channel_correct():
    img = Image.new("RGB", (4, 1))
    img.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)])
    out = lcd.rgb565(img)
    assert len(out) == 8
    assert struct.unpack(">4H", out) == (0xF800, 0x07E0, 0x001F, 0xFFFF)
    black = lcd.rgb565(Image.new("RGB", (3, 3), (0, 0, 0)))
    assert black == bytes(18)


def test_rgb565_converts_other_modes_and_keeps_raster_order():
    img = Image.new("L", (2, 2))
    img.putdata([0, 255, 128, 64])
    out = lcd.rgb565(img)
    assert struct.unpack(">4H", out) == (
        0x0000, 0xFFFF,
        ((128 >> 3) << 11) | ((128 >> 2) << 5) | (128 >> 3),
        ((64 >> 3) << 11) | ((64 >> 2) << 5) | (64 >> 3))


# ---- init sequences ----------------------------------------------------

@pytest.mark.parametrize("cls,size,madctl", [
    (lcd.ST7789, (240, 240), 0xC0),
    (lcd.ST7735S, (80, 160), 0xC8),
])
def test_init_resets_configures_blanks_then_turns_on(cls, size, madctl):
    io = FakeIO()
    p = cls(io)
    assert (p.width, p.height) == size
    p.init()
    cmds = io.commands()
    assert io.ops[0] == ("reset",)
    assert 0x11 in cmds                      # sleep out
    assert 0x21 in cmds                      # inversion on (panel is normally inverted)
    assert io.after(0x3A) == b"\x05"         # 16-bit colour
    assert io.after(0x36) == bytes([madctl])
    # blanked with a full-size black frame before DISPON
    assert cmds[-1] == 0x29
    ramwr = max(i for i, op in enumerate(io.ops) if op == ("cmd", 0x2C))
    assert io.ops[ramwr + 1] == ("data", bytes(size[0] * size[1] * 2))
    assert cmds.index(0x2C) < cmds.index(0x29)
    # the vendor init sequence is replayed verbatim
    for cmd, data, _ in cls.INIT:
        assert cmd in cmds
        if data:
            assert io.after(cmd) == bytes(data) or cmd in (0x2A, 0x2B)


def test_rotate_180_flips_madctl():
    assert lcd.ST7789(FakeIO(), rotate_180=True).madctl == 0x00
    assert lcd.ST7735S(FakeIO(), rotate_180=True).madctl == 0x08
    # both side orientations use the same memory offsets (window is centred)
    a, b = lcd.ST7735S(FakeIO()), lcd.ST7735S(FakeIO(), rotate_180=True)
    assert (a.col_offset, a.row_offset) == (b.col_offset, b.row_offset) == (26, 1)


# ---- windows / offsets -------------------------------------------------

def test_side_panel_window_is_offset_into_controller_memory():
    io = FakeIO()
    p = lcd.ST7735S(io)
    p.set_window(0, 0, 79, 159)
    assert io.after(0x2A) == bytes([0, 26, 0, 26 + 79])
    assert io.after(0x2B) == bytes([0, 1, 0, 1 + 159])
    # the window always stays within the 132x162 frame memory
    assert 26 + 79 < p.MEM_W and 1 + 159 < p.MEM_H


def test_main_panel_window_has_no_offset():
    io = FakeIO()
    p = lcd.ST7789(io)
    p.set_window(0, 0, 239, 239)
    assert io.after(0x2A) == bytes([0, 0, 0, 239])
    assert io.after(0x2B) == bytes([0, 0, 0, 239])


def test_show_packs_image_sets_window_and_writes_ram():
    io = FakeIO()
    p = lcd.ST7735S(io)
    img = Image.new("RGB", (80, 160), (255, 0, 0))
    p.show(img)
    assert io.commands() == [0x2A, 0x2B, 0x2C]
    buf = io.after(0x2C)
    assert len(buf) == 80 * 160 * 2 and buf[:2] == b"\xf8\x00"


def test_show_partial_region_and_size_checks():
    io = FakeIO()
    p = lcd.ST7789(io)
    p.show(Image.new("RGB", (100, 20)), x=10, y=200)
    assert io.after(0x2A) == bytes([0, 10, 0, 109])
    assert io.after(0x2B) == bytes([0, 200, 0, 219])
    with pytest.raises(ValueError):
        p.show(Image.new("RGB", (241, 10)))
    with pytest.raises(ValueError):
        p.show(Image.new("RGB", (100, 20)), x=200, y=0)
    with pytest.raises(ValueError):
        p.show_raw(b"\x00" * 10)


def test_backlight_and_sleep():
    io = FakeIO()
    p = lcd.ST7789(io)
    p.backlight(0.3)
    assert p.backlight_level == 0.3 and ("bl", 0.3) in io.ops
    p.sleep()
    assert io.ops[-3:] == [("bl", 0.0), ("cmd", 0x28), ("cmd", 0x10)]


def test_spi_io_uses_lgpio_and_spidev(monkeypatch):
    """SpiIO against stub lgpio/spidev modules: claims RST high, drives DC
    per command/data, PWM for mid backlight levels, plain high/low at the
    ends."""
    import sys
    import types

    calls = []

    lg = types.ModuleType("lgpio")
    lg.gpio_claim_output = lambda h, pin, level: calls.append(("claim", pin, level))
    lg.gpio_write = lambda h, pin, level: calls.append(("write", pin, level))
    lg.tx_pwm = lambda h, pin, f, duty: calls.append(("pwm", pin, duty))
    lg.gpio_free = lambda h, pin: calls.append(("free", pin))
    lg.gpiochip_open = lambda n: ("chip", n)
    lg.gpiochip_close = lambda h: calls.append(("close", h))

    class FakeSpiDev:
        def __init__(self):
            self.max_speed_hz = None
            self.mode = None

        def open(self, bus, dev):
            calls.append(("open", bus, dev))

        def writebytes(self, data):
            calls.append(("wb", bytes(data)))

        def writebytes2(self, data):
            calls.append(("wb2", bytes(data)))

        def close(self):
            calls.append(("spi_close",))

    sp = types.ModuleType("spidev")
    sp.SpiDev = FakeSpiDev
    monkeypatch.setitem(sys.modules, "lgpio", lg)
    monkeypatch.setitem(sys.modules, "spidev", sp)

    chip = lcd.open_gpiochip(0)
    io = lcd.SpiIO(chip, spi=(1, 0), dc=22, rst=27, bl=19, speed_hz=31_250_000)
    assert ("claim", 27, 1) in calls            # RST idles high: no reset glitch
    assert ("claim", 22, 0) in calls and ("claim", 19, 0) in calls
    assert ("open", 1, 0) in calls
    assert io.spi.max_speed_hz == 31_250_000 and io.spi.mode == 0

    calls.clear()
    io.command(0x2C)
    io.data(b"\x01\x02")
    assert calls == [("write", 22, 0), ("wb", b"\x2c"),
                     ("write", 22, 1), ("wb2", b"\x01\x02")]

    calls.clear()
    io.reset_pulse()
    assert [c for c in calls if c[0] == "write"] == [
        ("write", 27, 1), ("write", 27, 0), ("write", 27, 1)]

    calls.clear()
    io.backlight(0.5)
    assert ("pwm", 19, 50.0) in calls
    io.backlight(1.0)
    assert ("write", 19, 1) in calls
    io.backlight(0.0)
    assert ("write", 19, 0) in calls

    calls.clear()
    io.close()
    assert ("spi_close",) in calls and ("free", 27) in calls
    lcd.close_gpiochip(chip)
    assert ("close", ("chip", 0)) in calls
