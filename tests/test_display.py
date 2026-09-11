"""Display facade, splash loading and boot-time hardware retry."""

import os
import sys
import types

import pytest
from PIL import Image

import config
import display
import oled
from conftest import FakePanel


def test_show_routes_to_panel(fake_display):
    img = Image.new("1", (config.OLED_W, config.OLED_H), 1)
    fake_display.show(img)
    assert len(fake_display.panel.frames) == 1
    assert fake_display.panel.last is img
    fake_display.contrast(0x40)
    assert fake_display.panel.contrast_level == 0x40
    fake_display.invert(True)
    assert fake_display.panel.inverted is True
    fake_display.sleep()
    assert fake_display.panel.sleeping
    fake_display.wake()
    assert not fake_display.panel.sleeping


def test_splash_files_roundtrip_through_make_splash(tmp_path, fake_display):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools"))
    import make_splash
    path = make_splash.make(str(tmp_path))
    assert path.endswith("splash.bin")
    assert os.path.getsize(path) == 1024
    assert fake_display.splash(path) is True
    assert fake_display.panel.raw[0] == open(path, "rb").read()


def test_splash_missing_or_wrong_size_is_skipped(tmp_path, fake_display):
    assert fake_display.splash(str(tmp_path / "missing.bin")) is False
    bad = tmp_path / "splash.bin"
    bad.write_bytes(b"\x00" * 10)
    assert fake_display.splash(str(bad)) is False
    assert fake_display.panel.raw == []       # nothing pushed on failure


def test_open_display_retries_until_hardware_appears(monkeypatch):
    """Simulate /dev/spidev* appearing a few attempts into boot."""
    attempts = {"n": 0}
    monkeypatch.setattr(display.time, "sleep", lambda s: None)
    monkeypatch.setattr(display.time, "monotonic", lambda: 0.0)

    class FakeSpiIO:
        def __init__(self, chip, spi, dc, rst, speed_hz):
            attempts["n"] += 1
            if attempts["n"] < 4:
                raise FileNotFoundError("/dev/spidev%d.%d" % spi)
            self.ops = []

        def command(self, c): self.ops.append(("cmd", c))
        def data(self, b): self.ops.append(("data", bytes(b)))
        def reset_pulse(self): self.ops.append(("reset",))

    closed = []
    monkeypatch.setattr(oled, "SpiIO", FakeSpiIO)
    monkeypatch.setattr(oled, "open_gpiochip", lambda n: "chip")
    monkeypatch.setattr(oled, "close_gpiochip", lambda h: closed.append(h))
    monkeypatch.setattr(oled.time, "sleep", lambda s: None)
    logs = []
    d = display.open_display(retry_secs=5, log=logs.append)
    assert attempts["n"] == 4
    assert closed == ["chip"] * 3
    assert logs and "not ready" in logs[0]
    assert isinstance(d.panel, oled.SH1106)
    assert ("reset",) in d.panel.io.ops and ("cmd", 0xAF) in d.panel.io.ops
    # boot contrast applied after init
    assert ("cmd", 0x81) in d.panel.io.ops


def test_open_display_gives_up_after_deadline_and_on_other_errors(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(display.time, "sleep",
                        lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(display.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(oled, "open_gpiochip", lambda n: "chip")
    monkeypatch.setattr(oled, "close_gpiochip", lambda h: None)

    def missing(*a, **k):
        raise PermissionError("/dev/gpiochip0")

    monkeypatch.setattr(oled, "SpiIO", missing)
    with pytest.raises(PermissionError):
        display.open_display(retry_secs=1.0, log=lambda m: None)
    assert clock["t"] >= 1.0

    lg = types.ModuleType("lgpio")

    class error(Exception):
        pass

    error.__module__ = "lgpio"
    lg.error = error
    assert display._retryable(error("GPIO busy"))
    assert not display._retryable(TypeError("bad"))

    def broken(*a, **k):
        raise TypeError("bad")

    monkeypatch.setattr(oled, "SpiIO", broken)
    with pytest.raises(TypeError):
        display.open_display(retry_secs=10.0, log=lambda m: None)
