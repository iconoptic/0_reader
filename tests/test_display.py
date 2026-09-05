"""Display facade, splash loading and boot-time hardware retry."""

import os
import sys
import types

import pytest
from PIL import Image

import config
import display
import lcd
import render
from conftest import FakePanel


def test_show_routes_frames_to_the_right_panel(fake_display):
    m = Image.new("RGB", (config.MAIN_W, config.MAIN_H))
    s = Image.new("RGB", (config.SIDE_W, config.SIDE_H))
    fake_display.show(main=m)
    fake_display.show(left=s, right=s)
    assert len(fake_display.main.frames) == 1
    assert len(fake_display.left.frames) == len(fake_display.right.frames) == 1
    fake_display.backlight(main=0.9, sides=0.1)
    assert fake_display.main.backlight_level == 0.9
    assert fake_display.left.backlight_level == fake_display.right.backlight_level == 0.1
    fake_display.sleep()
    assert all(p.sleeping for p in fake_display.panels)


def test_swap_sides_config(monkeypatch):
    monkeypatch.setattr(config, "SWAP_SIDES", True)
    a, b = FakePanel(80, 160), FakePanel(80, 160)
    d = display.Display(FakePanel(240, 240), a, b)
    assert d.left is b and d.right is a


def test_splash_files_roundtrip_through_make_splash(tmp_path, fake_display):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools"))
    import make_splash
    names = make_splash.make(str(tmp_path))
    assert names == ["left", "main", "right"]
    sizes = {n: os.path.getsize(tmp_path / (n + ".rgb565")) for n in names}
    assert sizes["main"] == config.MAIN_W * config.MAIN_H * 2
    assert sizes["left"] == sizes["right"] == config.SIDE_W * config.SIDE_H * 2
    assert fake_display.splash(str(tmp_path)) is True
    assert fake_display.main.raw[0] == lcd.rgb565(render.splash_main())
    assert fake_display.left.raw[0] == lcd.rgb565(render.splash_side("left"))


def test_splash_missing_or_wrong_size_is_skipped(tmp_path, fake_display):
    assert fake_display.splash(str(tmp_path)) is False
    for n in ("main", "left", "right"):
        (tmp_path / (n + ".rgb565")).write_bytes(b"\x00" * 10)
    assert fake_display.splash(str(tmp_path)) is False
    assert fake_display.main.raw == []       # nothing pushed on failure


def test_open_display_retries_until_hardware_appears(monkeypatch):
    """Simulate /dev/spidev* appearing a few attempts into boot."""
    attempts = {"n": 0}
    monkeypatch.setattr(display.time, "sleep", lambda s: None)
    monkeypatch.setattr(display.time, "monotonic", lambda: 0.0)

    class FakeSpiIO:
        def __init__(self, chip, spi, dc, rst, bl, speed_hz, pwm_hz=1000):
            attempts["n"] += 1
            if attempts["n"] < 4:
                raise FileNotFoundError("/dev/spidev%d.%d" % spi)
            self.ops = []

        def command(self, c): self.ops.append(("cmd", c))
        def data(self, b): self.ops.append(("data", bytes(b)))
        def reset_pulse(self): self.ops.append(("reset",))
        def backlight(self, v): self.ops.append(("bl", v))

    closed = []
    monkeypatch.setattr(lcd, "SpiIO", FakeSpiIO)
    monkeypatch.setattr(lcd, "open_gpiochip", lambda n: "chip")
    monkeypatch.setattr(lcd, "close_gpiochip", lambda h: closed.append(h))
    monkeypatch.setattr(lcd.time, "sleep", lambda s: None)
    logs = []
    d = display.open_display(retry_secs=5, log=logs.append)
    assert attempts["n"] == 6                # 3 failures + 3 panels
    assert closed == ["chip"] * 3            # handle released after each failure
    assert logs and "not ready" in logs[0]
    assert isinstance(d.main, lcd.ST7789) and isinstance(d.left, lcd.ST7735S)
    for p in d.panels:                        # every panel initialised + lit
        assert ("reset",) in p.io.ops and ("cmd", 0x29) in p.io.ops
    assert d.main.backlight_level == config.BL_MAIN
    assert d.left.backlight_level == d.right.backlight_level == config.BL_SIDE


def test_open_display_gives_up_after_deadline_and_on_other_errors(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(display.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(display.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(lcd, "open_gpiochip", lambda n: "chip")
    monkeypatch.setattr(lcd, "close_gpiochip", lambda h: None)

    def missing(*a, **k):
        raise PermissionError("/dev/gpiochip0")

    monkeypatch.setattr(lcd, "SpiIO", missing)
    with pytest.raises(PermissionError):
        display.open_display(retry_secs=1.0, log=lambda m: None)
    assert clock["t"] >= 1.0

    # an lgpio.error is retryable too ...
    lg = types.ModuleType("lgpio")

    class error(Exception):
        pass

    error.__module__ = "lgpio"
    lg.error = error
    assert display._retryable(error("GPIO busy"))
    # ... but a programming error is not
    assert not display._retryable(TypeError("bad"))

    def broken(*a, **k):
        raise TypeError("bad")

    monkeypatch.setattr(lcd, "SpiIO", broken)
    with pytest.raises(TypeError):
        display.open_display(retry_secs=10.0, log=lambda m: None)
