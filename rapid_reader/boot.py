#!/usr/bin/env python3
"""Service entry point: get pixels on the screen as early as possible.

Imports only what is needed to drive the panel (config, display, oled ->
spidev + lgpio), shows the pre-rendered splash, and only then imports the
rest of the application (Pillow, the book parser, gpiozero) and hands the
already-open display over to ``main.main``. On a Pi Zero the heavy imports
take a couple of seconds, which is exactly the time the user would
otherwise spend looking at a black screen.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config           # noqa: E402
import display          # noqa: E402


def run():
    t0 = time.monotonic()
    disp = display.open_display()
    if not disp.splash():
        print("boot: no splash image in %s" % config.SPLASH_DIR)
    print("boot: panel up in %.2fs" % (time.monotonic() - t0))
    import main
    main.main(disp)


if __name__ == "__main__":
    run()
