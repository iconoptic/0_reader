"""Theme presets and font resolution. No hardware, drawing only via render.py."""

import os

from PIL import ImageFont

import config
from contracts import Theme

THEMES = {
    "night": Theme("Night", invert=False, font_key="sans",  pivot_style="ticks",     contrast=0xCF),
    "paper": Theme("Paper", invert=True,   font_key="serif", pivot_style="underline", contrast=0xCF),
    "focus": Theme("Focus", invert=False,  font_key="sans",  pivot_style="box",       contrast=0xFF),
    "dim":   Theme("Dim",   invert=False,  font_key="mono",  pivot_style="bold",      contrast=0x40),
    "mono":  Theme("Mono",  invert=False,  font_key="mono",  pivot_style="ticks",     contrast=0xCF),
}
DEFAULT_THEME_KEY = "night"

_fonts = {}


def _face_dir(reg_name):
    for d in config.FONT_DIRS:
        if os.path.exists(os.path.join(d, reg_name)):
            return d
    raise FileNotFoundError("%r not found in %r" % (reg_name, config.FONT_DIRS))


def fonts(theme):
    """Return (regular_path, bold_path) for theme.font_key."""
    reg_name, bold_name = config.FONT_FACES[theme.font_key]
    d = _face_dir(reg_name)
    return os.path.join(d, reg_name), os.path.join(d, bold_name)


def font(theme, size, bold=False):
    """Cached ImageFont.truetype for this theme's face at `size`."""
    reg, bold_path = fonts(theme)
    path = bold_path if bold else reg
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]
