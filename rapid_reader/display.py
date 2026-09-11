"""Single-panel display facade used by the app.

``Display`` owns one SH1106 panel and exposes just what the app needs:
``show(image)``, ``contrast``, ``invert``, ``splash()``, ``sleep()`` and
``wake()``. The panel can be any object with those methods (see
``oled.SH1106``); tests pass recording fakes.

:func:`open_display` builds the real thing, retrying while the SPI/GPIO
device nodes are still appearing during early boot.
"""

import os
import time

import config


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
        """Show the pre-rendered boot splash (raw SH1106 page bytes) if present.

        Loads ``config.SPLASH_DIR + '/splash.bin'`` (or ``path``), a raw
        1024-byte buffer, and pushes it via ``show_raw`` so boot does not
        need Pillow. Returns True when the file existed, was exactly 1024
        bytes, and was pushed; False otherwise.
        """
        path = path or os.path.join(config.SPLASH_DIR, "splash.bin")
        try:
            with open(path, "rb") as f:
                buf = f.read()
        except OSError:
            return False
        if len(buf) != 1024:
            return False
        self.panel.show_raw(buf)
        return True

    def sleep(self):
        self.panel.sleep()

    def wake(self):
        self.panel.wake()


def _retryable(exc):
    """OSError covers missing /dev nodes and udev permissions not yet
    applied; lgpio raises its own ``lgpio.error`` for a busy/absent chip."""
    return isinstance(exc, OSError) or type(exc).__module__ == "lgpio"


def open_display(retry_secs=None, log=print):
    """Initialise the OLED on the HAT, retrying for a while if the kernel
    has not created /dev/spidev* / /dev/gpiochip* yet. The panel is blanked
    inside ``init()`` before display-on, so there is no flash of garbage."""
    import oled
    retry_secs = config.HW_RETRY_SECS if retry_secs is None else retry_secs
    deadline = time.monotonic() + retry_secs
    attempt = 0
    while True:
        attempt += 1
        chip = None
        try:
            chip = oled.open_gpiochip(config.GPIO_CHIP)
            io = oled.SpiIO(chip, spi=config.OLED_SPI, dc=config.OLED_DC,
                            rst=config.OLED_RST, speed_hz=config.OLED_SPEED_HZ)
            panel = oled.SH1106(io, col_offset=config.OLED_COL_OFFSET,
                                rotate_180=config.ROTATE_180)
            break
        except Exception as e:
            if chip is not None:
                try:
                    oled.close_gpiochip(chip)
                except Exception:
                    pass
            if not _retryable(e) or time.monotonic() > deadline:
                raise
            if attempt in (1, 8, 40):
                log("display: hardware not ready (%s), retrying" % e)
            time.sleep(0.25)
    panel.init()
    disp = Display(panel)
    disp.contrast(config.IDLE_ACTIVE_CONTRAST)
    return disp
