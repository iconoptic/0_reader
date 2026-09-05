"""Minimal SSD1680 driver for the 2.13" 250x122 mono e-ink panel
(Adafruit e-Ink Bonnet #4687), using spidev + gpiozero.

Supports full refresh (flashing, crisp) and fast partial refresh
(~0.3s, no flash) for RSVP word display.
"""

import time

import spidev
from gpiozero import DigitalInputDevice, DigitalOutputDevice

import config

# Panel native orientation is portrait: 122 sources (x) by 250 gates (y)
_P_WIDTH = 122
_P_HEIGHT = 250
_LINE_BYTES = 16  # ceil(122 / 8)


class EPD:
    def __init__(self):
        self.spi = spidev.SpiDev()
        self.spi.open(config.SPI_BUS, config.SPI_DEV)
        self.spi.max_speed_hz = 4_000_000
        self.spi.mode = 0
        self.dc = DigitalOutputDevice(config.PIN_DC)
        self.rst = DigitalOutputDevice(config.PIN_RST, initial_value=True)
        self.busy = DigitalInputDevice(config.PIN_BUSY, pull_up=None,
                                       active_state=True)
        self._partials = 0
        self._sleeping = True

    # ---- low level -------------------------------------------------

    def _wait_busy(self, timeout=20.0):
        t0 = time.monotonic()
        while self.busy.value:  # BUSY is high while the controller works
            if time.monotonic() - t0 > timeout:
                raise TimeoutError("e-ink BUSY stuck high")
            time.sleep(0.005)

    def _reset(self):
        self.rst.on()
        time.sleep(0.02)
        self.rst.off()
        time.sleep(0.002)
        self.rst.on()
        time.sleep(0.02)
        self._sleeping = False

    def _cmd(self, cmd):
        self.dc.off()
        self.spi.writebytes([cmd])

    def _data(self, data):
        self.dc.on()
        self.spi.writebytes2(bytearray(data))

    def _set_window_full(self):
        self._cmd(0x44)               # x window, in bytes
        self._data([0x00, _LINE_BYTES - 1])
        self._cmd(0x45)               # y window
        self._data([0x00, 0x00, (_P_HEIGHT - 1) & 0xFF, (_P_HEIGHT - 1) >> 8])
        self._cmd(0x4E)
        self._data([0x00])
        self._cmd(0x4F)
        self._data([0x00, 0x00])

    def _init(self):
        self._reset()
        self._wait_busy()
        self._cmd(0x12)               # software reset
        self._wait_busy()
        self._cmd(0x01)               # driver output control: 250 gates
        self._data([(_P_HEIGHT - 1) & 0xFF, (_P_HEIGHT - 1) >> 8, 0x00])
        self._cmd(0x11)               # data entry: x+, y+
        self._data([0x03])
        self._cmd(0x21)               # display update control
        self._data([0x00, 0x80])
        self._cmd(0x18)               # internal temperature sensor
        self._data([0x80])
        self._cmd(0x3C)               # border waveform
        self._data([0x05])
        self._set_window_full()
        self._wait_busy()

    # ---- buffer packing --------------------------------------------

    @staticmethod
    def _pack(image):
        """PIL landscape image (250x122, mode-convertible) -> RAM bytes."""
        img = image.convert("1")
        angle = 270 if config.ROTATE_180 else 90
        img = img.rotate(angle, expand=True)  # -> 122x250 portrait
        return img.tobytes()  # rows padded to 16 bytes, bit 1 = white

    # ---- public API -------------------------------------------------

    def display_full(self, image):
        buf = self._pack(image)
        self._init()
        self._cmd(0x24)               # B/W RAM
        self._data(buf)
        self._cmd(0x26)               # "old" RAM: base for future partials
        self._data(buf)
        self._cmd(0x22)
        self._data([0xF7])            # full update sequence
        self._cmd(0x20)
        self._wait_busy()
        self._partials = 0

    def display_partial(self, image):
        if self._sleeping or self._partials >= config.FULL_REFRESH_EVERY:
            self.display_full(image)
            return
        buf = self._pack(image)
        # brief hardware reset before partial update (per vendor reference)
        self.rst.off()
        time.sleep(0.001)
        self.rst.on()
        time.sleep(0.002)
        self._cmd(0x3C)
        self._data([0x80])
        self._cmd(0x01)
        self._data([(_P_HEIGHT - 1) & 0xFF, (_P_HEIGHT - 1) >> 8, 0x00])
        self._cmd(0x11)
        self._data([0x03])
        self._set_window_full()
        self._cmd(0x24)
        self._data(buf)
        self._cmd(0x22)
        self._data([0xFF])            # partial (differential) update
        self._cmd(0x20)
        self._wait_busy()
        self._partials += 1

    def sleep(self):
        if self._sleeping:
            return
        self._cmd(0x10)               # deep sleep
        self._data([0x01])
        self._sleeping = True
