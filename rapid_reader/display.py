"""Three-screen display facade used by the app.

``Display`` owns the centre panel plus the two portrait side panels and
exposes just what the app needs: ``show(main=, left=, right=)``,
``backlight(...)``, ``splash()`` and ``sleep()``. The panels can be any
objects with ``show(image)``, ``show_raw(bytes)``, ``backlight(level)`` and
``sleep()`` (see ``lcd.ST77xx``); tests pass recording fakes.

:func:`open_display` builds the real thing, retrying while the SPI/GPIO
device nodes are still appearing during early boot.
"""

import os
import time

import config


class Display:
    def __init__(self, main, left, right):
        self.main = main
        if config.SWAP_SIDES:
            left, right = right, left
        self.left = left
        self.right = right

    @property
    def panels(self):
        return (self.main, self.left, self.right)

    def show(self, main=None, left=None, right=None):
        """Push whichever frames are given; the others are left untouched."""
        if main is not None:
            self.main.show(main)
        if left is not None:
            self.left.show(left)
        if right is not None:
            self.right.show(right)

    def backlight(self, main=None, sides=None):
        if main is not None:
            self.main.backlight(main)
        if sides is not None:
            self.left.backlight(sides)
            self.right.backlight(sides)

    def splash(self, directory=None):
        """Show the pre-rendered boot splash (raw RGB565 files) if present.
        Returns True when all three files were found and pushed."""
        directory = directory or config.SPLASH_DIR
        frames = []
        for name, panel in (("main", self.main), ("left", self.left),
                            ("right", self.right)):
            path = os.path.join(directory, name + ".rgb565")
            try:
                with open(path, "rb") as f:
                    buf = f.read()
            except OSError:
                return False
            if len(buf) != panel.width * panel.height * 2:
                return False
            frames.append((panel, buf))
        for panel, buf in frames:
            panel.show_raw(buf)
        return True

    def sleep(self):
        for p in self.panels:
            p.sleep()


def _retryable(exc):
    """OSError covers missing /dev nodes and udev permissions not yet
    applied; lgpio raises its own ``lgpio.error`` for a busy/absent chip."""
    return isinstance(exc, OSError) or type(exc).__module__ == "lgpio"


def open_display(retry_secs=None, log=print):
    """Initialise the three panels on the HAT, retrying for a while if the
    kernel has not created /dev/spidev* / /dev/gpiochip* yet. Backlights
    come up only after the panels have been blanked, so there is no flash of
    garbage on power-up."""
    import lcd
    retry_secs = config.HW_RETRY_SECS if retry_secs is None else retry_secs
    deadline = time.monotonic() + retry_secs
    attempt = 0
    while True:
        attempt += 1
        chip = None
        try:
            chip = lcd.open_gpiochip(config.GPIO_CHIP)
            panels = []
            for cls, cfg, flip in ((lcd.ST7789, config.MAIN, config.MAIN_ROTATE_180),
                                   (lcd.ST7735S, config.LEFT, config.SIDE_ROTATE_180),
                                   (lcd.ST7735S, config.RIGHT, config.SIDE_ROTATE_180)):
                io = lcd.SpiIO(chip, pwm_hz=config.BACKLIGHT_PWM_HZ, **cfg)
                panels.append(cls(io, rotate_180=flip))
            break
        except Exception as e:
            if chip is not None:
                try:
                    lcd.close_gpiochip(chip)
                except Exception:
                    pass
            if not _retryable(e) or time.monotonic() > deadline:
                raise
            if attempt in (1, 8, 40):
                log("display: hardware not ready (%s), retrying" % e)
            time.sleep(0.25)
    for p in panels:
        p.init()
    disp = Display(*panels)
    disp.backlight(main=config.BL_MAIN, sides=config.BL_SIDE)
    return disp
