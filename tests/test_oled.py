"""Driver-level tests for the SH1106 panel code, using a recording fake
in place of spidev + lgpio."""

import pytest
from PIL import Image, ImageDraw

import config
import oled


class FakeIO:
    def __init__(self):
        self.ops = []          # ("cmd", int) | ("data", bytes) | ("reset",)

    def command(self, cmd):
        self.ops.append(("cmd", cmd))

    def data(self, buf):
        if buf:
            self.ops.append(("data", bytes(buf)))

    def reset_pulse(self):
        self.ops.append(("reset",))

    def commands(self):
        return [op[1] for op in self.ops if op[0] == "cmd"]

    def after(self, cmd):
        """Data bytes that immediately follow the *last* occurrence of cmd."""
        idx = max(i for i, op in enumerate(self.ops) if op == ("cmd", cmd))
        nxt = self.ops[idx + 1] if idx + 1 < len(self.ops) else None
        return nxt[1] if nxt and nxt[0] == "data" else b""


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(oled.time, "sleep", lambda s: None)


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


def _mono(w=config.OLED_W, h=config.OLED_H, fill=0):
    return Image.new("1", (w, h), fill)


# ---- pixel packing -----------------------------------------------------

@pytest.mark.parametrize("builder", [
    lambda: _mono(fill=0),
    lambda: _mono(fill=1),
    lambda: (lambda i: (i.putpixel((0, 0), 1), i)[1])(_mono()),
    lambda: (lambda i: (i.putpixel((127, 0), 1), i)[1])(_mono()),
    lambda: (lambda i: (i.putpixel((0, 63), 1), i)[1])(_mono()),
    lambda: (lambda i: (i.putpixel((127, 63), 1), i)[1])(_mono()),
])
def test_pack_pages_matches_reference_corners_and_solids(builder):
    img = builder()
    assert oled.pack_pages(img) == _reference_pack_pages(img)


def test_pack_pages_matches_reference_diagonal():
    img = _mono()
    draw = ImageDraw.Draw(img)
    draw.line((0, 0, 127, 63), fill=1)
    assert oled.pack_pages(img) == _reference_pack_pages(img)
    assert len(oled.pack_pages(img)) == 1024


# ---- init / orientation ------------------------------------------------

def test_init_resets_configures_blanks_then_turns_on():
    io = FakeIO()
    p = oled.SH1106(io)
    p.init()
    cmds = io.commands()
    assert io.ops[0] == ("reset",)
    assert cmds[0] == 0xAE                       # display off first
    assert 0xAF not in cmds[:-1]                 # not on before the end
    assert cmds[-1] == 0xAF
    # blanked page-by-page (8 x 128 zero bytes) before DISPLAY ON
    af = max(i for i, op in enumerate(io.ops) if op == ("cmd", 0xAF))
    pre_data = [op[1] for op in io.ops[:af] if op[0] == "data"]
    assert pre_data == [bytes(128)] * 8
    # multi-byte cmds are successive command() calls (SPI A0=low for both)
    i = cmds.index
    assert cmds[i(0xD5) + 1] == 0x80
    assert cmds[i(0xA8) + 1] == 0x3F
    assert cmds[i(0xD3) + 1] == 0x00
    assert 0x40 in cmds
    assert cmds[i(0xAD) + 1] == 0x8B
    assert 0xA1 in cmds and 0xC8 in cmds         # default orientation pair
    assert cmds[i(0xDA) + 1] == 0x12
    assert cmds[i(0x81) + 1] == 0xCF
    assert cmds[i(0xD9) + 1] == 0x22
    assert cmds[i(0xDB) + 1] == 0x35
    assert 0xA6 in cmds


def test_rotate_180_swaps_seg_com_not_column_offset():
    a = oled.SH1106(FakeIO())
    b = oled.SH1106(FakeIO(), rotate_180=True)
    assert a.seg_com == oled.SH1106.SEG_COM_NORMAL == (0xA1, 0xC8)
    assert b.seg_com == oled.SH1106.SEG_COM_FLIPPED == (0xA0, 0xC0)
    assert a.col_offset == b.col_offset == config.OLED_COL_OFFSET
    io = FakeIO()
    oled.SH1106(io, rotate_180=True).init()
    cmds = io.commands()
    assert 0xA0 in cmds and 0xC0 in cmds
    assert 0xA1 not in cmds and 0xC8 not in cmds


# ---- show / addressing -------------------------------------------------

def test_show_sends_page_column_address_and_payload():
    io = FakeIO()
    p = oled.SH1106(io, col_offset=2)
    img = _mono(fill=1)
    p.show(img)
    cmds = io.commands()
    packed = oled.pack_pages(img)
    assert cmds == [
        c for page in range(8)
        for c in (0xB0 | page, 0x00 | 2, 0x10 | 0)
    ]
    data_ops = [op[1] for op in io.ops if op[0] == "data"]
    assert data_ops == [packed[page * 128:(page + 1) * 128] for page in range(8)]


def test_show_raw_size_check_and_threshold_from_L():
    io = FakeIO()
    p = oled.SH1106(io)
    with pytest.raises(ValueError):
        p.show_raw(b"\x00" * 10)
    gray = Image.new("L", (128, 64), 200)
    p.show(gray)
    assert any(op[0] == "data" for op in io.ops)


def test_contrast_invert_sleep_wake():
    io = FakeIO()
    p = oled.SH1106(io)
    p.contrast(0x80)
    assert io.ops[-2:] == [("cmd", 0x81), ("cmd", 0x80)]
    p.invert(True)
    assert io.ops[-1] == ("cmd", 0xA7)
    p.invert(False)
    assert io.ops[-1] == ("cmd", 0xA6)
    p.sleep()
    assert io.ops[-1] == ("cmd", 0xAE)
    p.wake()
    assert io.ops[-1] == ("cmd", 0xAF)


def test_spi_io_uses_lgpio_and_spidev(monkeypatch):
    """SpiIO against stub lgpio/spidev: claims RST high, drives DC per
    command/data, opens the configured SPI bus."""
    import sys
    import types

    calls = []

    lg = types.ModuleType("lgpio")
    lg.gpio_claim_output = lambda h, pin, level: calls.append(("claim", pin, level))
    lg.gpio_write = lambda h, pin, level: calls.append(("write", pin, level))
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

    chip = oled.open_gpiochip(0)
    io = oled.SpiIO(chip, spi=(0, 0), dc=24, rst=25, speed_hz=4_000_000)
    assert ("claim", 25, 1) in calls            # RST idles high
    assert ("claim", 24, 0) in calls
    assert ("open", 0, 0) in calls
    assert io.spi.max_speed_hz == 4_000_000 and io.spi.mode == 0

    calls.clear()
    io.command(0xAF)
    io.data(b"\x01\x02")
    assert calls == [("write", 24, 0), ("wb", b"\xaf"),
                     ("write", 24, 1), ("wb2", b"\x01\x02")]

    calls.clear()
    io.reset_pulse()
    assert [c for c in calls if c[0] == "write"] == [
        ("write", 25, 1), ("write", 25, 0), ("write", 25, 1)]

    calls.clear()
    io.close()
    assert ("spi_close",) in calls and ("free", 25) in calls
    oled.close_gpiochip(chip)
    assert ("close", ("chip", 0)) in calls
