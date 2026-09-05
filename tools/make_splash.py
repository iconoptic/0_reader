#!/usr/bin/env python3
"""Pre-render the boot splash as raw RGB565 frames.

Usage: tools/make_splash.py [OUTPUT_DIR]   (default: rapid_reader/splash)

boot.py pushes these bytes straight to the panels before Pillow is even
imported, so the screens light up a couple of seconds sooner on a Pi Zero.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "rapid_reader"))

import lcd      # noqa: E402
import render   # noqa: E402


def make(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    frames = {"main": render.splash_main(),
              "left": render.splash_side("left"),
              "right": render.splash_side("right")}
    for name, img in frames.items():
        with open(os.path.join(out_dir, name + ".rgb565"), "wb") as f:
            f.write(lcd.rgb565(img))
    return sorted(frames)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(HERE), "rapid_reader", "splash")
    for name in make(out):
        print(os.path.join(out, name + ".rgb565"))
