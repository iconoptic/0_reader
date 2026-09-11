#!/usr/bin/env python3
"""Pre-render the boot splash as a raw SH1106 page-format buffer.

Usage: tools/make_splash.py [OUTPUT_DIR]   (default: rapid_reader/splash)

boot.py pushes these bytes straight to the panel before Pillow is even
imported, so the screen lights up a couple of seconds sooner on a Pi Zero.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "rapid_reader"))

import oled     # noqa: E402
import render   # noqa: E402


def _as_mode1(img):
    """Threshold mode-'L' (or convertible) frames to mode '1' for packing."""
    if img.mode == "1":
        return img
    if img.mode != "L":
        img = img.convert("L")
    return img.point(lambda p: 255 if p >= 128 else 0, mode="1")


def make(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    img = _as_mode1(render.splash())
    path = os.path.join(out_dir, "splash.bin")
    with open(path, "wb") as f:
        f.write(oled.pack_pages(img))
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(HERE), "rapid_reader", "splash")
    print(make(out))
