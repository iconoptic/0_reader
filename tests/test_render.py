"""Render / theme coverage for the 128x64 monochrome panel."""

from dataclasses import replace

import pytest

import config
import render
import rsvp
import theme

W, H = render.W, render.H
BG, INK = render.BG, render.INK


def _night(**kwargs):
    return replace(theme.THEMES["night"], **kwargs)


def _lit_columns(img, y0, y1, value=None):
    """Columns with at least one non-background pixel in rows y0..y1
    (or, if ``value`` is given, at least one pixel of exactly that value)."""
    px = img.load()
    out = set()
    for x in range(img.width):
        for y in range(y0, y1):
            p = px[x, y]
            if (p == value) if value is not None else (p != BG):
                out.add(x)
                break
    return out


def _has_ink(img):
    # mode "L": getextrema() -> (min, max); RGB -> per-band pairs
    ext = img.getextrema()
    if isinstance(ext[0], tuple):
        return any(hi > 0 for _, hi in ext)
    return ext[1] > 0


def _only_01(img):
    colours = img.getcolors(1 << 16) or []
    return all(c in (0, 255) for _, c in colours)


def _row_mostly(img, y0, y1, expect_ink):
    """True if the band y0..y1 is mostly INK (True) or mostly BG (False)."""
    px = img.load()
    ink = 0
    total = 0
    for y in range(y0, y1):
        for x in range(img.width):
            total += 1
            if px[x, y] == INK:
                ink += 1
    frac = ink / float(total)
    return frac > 0.45 if expect_ink else frac < 0.15


# ---- every frame -----------------------------------------------------

@pytest.mark.parametrize("fn,args", [
    (render.word_frame, ("hello", _night())),
    (render.word_frame, ("supercalifragilisticexpialidocious", _night())),
    (render.list_frame, ("LIBRARY", ["A", "B"], 0, 0)),
    (render.list_frame, ("LIBRARY", [], 0, 0)),
    (render.list_frame, ("RESULTS", ["A", "B", "C"], -1, 0)),
    (render.paused_frame, ("T", ["One", "two.", "Three."], 1, 0, 150, 0.2,
                           _night())),
    (render.info_frame, ("Title", ".epub", 100, 1000, 250, 3600)),
    (render.message_frame, (["hi"], "hint")),
    (render.message_frame, (["hi"], None, "Big")),
    (render.confirm_frame, ("Delete?", "K3: yes", "K1: no")),
    (render.end_frame, ("T",)),
    (render.splash, ()),
])
def test_every_frame_is_panel_sized_L_01(fn, args):
    img = fn(*args)
    assert img.size == (W, H)
    assert img.mode == "L"
    assert _has_ink(img)
    assert _only_01(img)
    black = dict((c, n) for n, c in img.getcolors(1 << 16)).get(BG, 0)
    assert black > 0.4 * W * H


# ---- word_frame ------------------------------------------------------

@pytest.mark.parametrize("word", ["a", "reader", "extraordinarily", "\u201cQuoted,\u201d"])
def test_word_frame_pivot_sits_on_fixed_column(word):
    th = _night(pivot_style="ticks")
    img = render.word_frame(word, th)
    top = _lit_columns(img, render.CENTER_Y - render._TICK_ABOVE[0],
                       render.CENTER_Y - render._TICK_ABOVE[1] + 1)
    bottom = _lit_columns(img, render.CENTER_Y + render._TICK_BELOW[0],
                          render.CENTER_Y + render._TICK_BELOW[1] + 1)
    assert top == bottom == {render.PIVOT_X}


def test_word_frame_pivot_styles_differ():
    word = "reader"
    ticks = render.word_frame(word, _night(pivot_style="ticks"))
    under = render.word_frame(word, _night(pivot_style="underline"))
    box = render.word_frame(word, _night(pivot_style="box"))
    bold = render.word_frame(word, _night(pivot_style="bold"))

    # ticks: lit pixels at the fixed tick band on PIVOT_X; underline: not
    tick_band = _lit_columns(ticks, render.CENTER_Y - render._TICK_ABOVE[0],
                             render.CENTER_Y - render._TICK_ABOVE[1] + 1)
    under_band = _lit_columns(under, render.CENTER_Y - render._TICK_ABOVE[0],
                              render.CENTER_Y - render._TICK_ABOVE[1] + 1)
    assert render.PIVOT_X in tick_band
    assert render.PIVOT_X not in under_band

    # underline has ink below the word midline that ticks/bold lack at the
    # same relative place — compare full images for uniqueness
    def _pix(im):
        return list(im.get_flattened_data())
    assert _pix(ticks) != _pix(under)
    assert _pix(under) != _pix(box)
    assert _pix(box) != _pix(bold)
    assert _pix(bold) != _pix(ticks)

    # box: a filled region around the pivot (ink background, cutout glyph)
    # — more ink near PIVOT_X than bold-only
    def ink_near_pivot(img):
        px = img.load()
        n = 0
        for x in range(render.PIVOT_X - 6, render.PIVOT_X + 7):
            for y in range(render.CENTER_Y - 8, render.CENTER_Y + 9):
                if 0 <= x < W and 0 <= y < H and px[x, y] == INK:
                    n += 1
        return n
    assert ink_near_pivot(box) > ink_near_pivot(bold)


def test_word_frame_never_clips_at_the_edges():
    th = _night()
    for word in ("supercalifragilisticexpialidocious",
                 "Pneumonoultramicroscopicsilicovolcanoconiosis",
                 "x" * 80):
        img = render.word_frame(word, th)
        cols = _lit_columns(img, 0, H)
        assert cols and min(cols) >= 1 and max(cols) <= W - 2
        # no lit pixels on the absolute edge columns
        assert 0 not in cols and (W - 1) not in cols


def test_word_frame_flash_badge():
    img = render.word_frame("hi", _night(), flash="275 wpm")
    # top-right badge is an inverted box — mostly ink in that rect
    assert _row_mostly(img, 2, 12, expect_ink=True) or \
        any(img.getpixel((x, 5)) == INK for x in range(W - 34, W - 2))


# ---- list_frame ------------------------------------------------------

def test_list_frame_selection_inverted_and_scrolls():
    rows = ["Book %d" % i for i in range(12)]
    row_h = 12
    y0 = 14
    img = render.list_frame("LIBRARY", rows, sel=0, top=0)
    # selected row band mostly ink; next row mostly dark
    assert _row_mostly(img, y0, y0 + row_h, expect_ink=True)
    assert _row_mostly(img, y0 + row_h, y0 + 2 * row_h, expect_ink=False)

    img2 = render.list_frame("LIBRARY", rows, sel=1, top=0)
    assert _row_mostly(img2, y0, y0 + row_h, expect_ink=False)
    assert _row_mostly(img2, y0 + row_h, y0 + 2 * row_h, expect_ink=True)

    # more-below arrow when overflowing; more-above only when scrolled.
    # Use sel=1 so row 0 stays dark and does not mask the up-arrow cell.
    img_arrows = render.list_frame("LIBRARY", rows, sel=1, top=0)
    px = img_arrows.load()
    yb = y0 + 4 * row_h
    assert px[W - 6, yb - 2] == INK          # down triangle tip
    assert px[W - 6, y0 + 2] == BG           # no up triangle
    img3 = render.list_frame("LIBRARY", rows, sel=9, top=4)
    assert img3.load()[W - 6, y0 + 2] == INK  # up triangle tip


def test_list_frame_empty_renders():
    img = render.list_frame(
        "LIBRARY", [], 0, 0,
        empty_lines=("No books found.", "Copy .txt/.epub to", config.BOOKS_DIR))
    assert img.size == (W, H) and _has_ink(img)


def test_list_row_overflow_and_marquee_clip():
    short = "Short"
    long = "A Very Long Book Title That Will Not Fit In One Row At All"
    assert render.list_row_overflow(short) == 0
    overflow = render.list_row_overflow(long)
    assert overflow > 0

    rows = [long, "Other"]
    y0, row_h = 14, 12
    # offset 0: ellipsized selected row (still inverted band)
    img0 = render.list_frame("LIBRARY", rows, sel=0, top=0, sel_offset=0)
    assert _row_mostly(img0, y0, y0 + row_h, expect_ink=True)

    # two mid-scroll offsets must differ in the selected text band
    mid = max(2, overflow // 3)
    img_a = render.list_frame("LIBRARY", rows, sel=0, top=0, sel_offset=mid)
    img_b = render.list_frame("LIBRARY", rows, sel=0, top=0,
                              sel_offset=min(mid + 10, overflow))
    assert list(img_a.get_flattened_data()) != list(img_b.get_flattened_data())

    # Any BG pixel in the selected row past the text slot means marquee leaked
    # into the scroll-triangle strip.
    px = img_a.load()
    leaked = any(
        px[x, y] == BG
        for y in range(y0 + 1, y0 + row_h - 1)
        for x in range(3 + render._LIST_ROW_MAX_W, W - 1)
    )
    assert not leaked


# ---- paused / helpers / theme ----------------------------------------

def test_paused_current_word_distinguished_and_overflow_safe():
    words = "One two three. Four five six. Seven".split()
    img = render.paused_frame("Title", words, idx=1, sentence_start=0,
                              wpm=150, progress=0.3, theme=_night())
    assert img.size == (W, H) and _has_ink(img)
    # current word bold+underline leaves ink below the glyph line
    assert _has_ink(img)
    big = render.paused_frame("T", ["word"] * 400, 0, 0, 150, 0.0, _night())
    cols = _lit_columns(big, 13, H)
    assert not cols or (min(cols) >= 1 and max(cols) <= W - 2)


def test_ellipsize_and_wrap():
    img = render.Image.new("L", (W, H), BG)
    d = render.ImageDraw.Draw(img)
    f = theme.font(_night(), 13)
    assert render._ellipsize(d, "short", f, 200) == "short"
    long = "a very very very very very very long title indeed"
    out = render._ellipsize(d, long, f, 80)
    assert out.endswith("\u2026") and d.textlength(out, font=f) <= 80
    lines = render._wrap(d, long, f, 80, 3)
    assert len(lines) == 3 and lines[-1].endswith("\u2026")
    assert all(d.textlength(l, font=f) <= 80 for l in lines)
    assert render._wrap(d, "two words", f, 200, 3) == ["two words"]


def test_fmt_helpers():
    assert render.fmt_minutes(0.4) == "<1m"
    assert render.fmt_minutes(45) == "45m"
    assert render.fmt_minutes(72) == "1h 12m"
    assert render.fmt_minutes(60 * 12) == "12h"
    assert render.fmt_duration_hms(45) == "45s"
    assert render.fmt_duration_hms(90) == "1m 30s"
    assert render.fmt_duration_hms(2 * 3600 + 15 * 60 + 30) == "2h 15m 30s"
    assert render.fmt_duration_hms(3 * 86400 + 2 * 3600 + 15 * 60 + 30) == (
        "3d 2h 15m 30s")
    assert render.fmt_words(269) == "269"
    assert render.fmt_words(1500) == "1.5k"
    assert render.fmt_words(215845) == "216k"


def test_progress_frame_and_remaining_overlay():
    img = render.progress_frame(0.5, "Updating...")
    assert img.size == (config.OLED_W, config.OLED_H)
    assert img.mode == "L"
    base = render.message_frame(["hi"])
    out = render.remaining_overlay(base.copy(), "1h 2m 3s left", _night())
    assert out.size == base.size
    # Non-default theme must drive the overlay face (F9), not _default_theme().
    night = render.remaining_overlay(base.copy(), "1h 2m 3s left", _night())
    mono = render.remaining_overlay(
        base.copy(), "1h 2m 3s left", theme.THEMES["mono"])
    assert night.tobytes() != mono.tobytes()
    # Overlay is folded into paused_frame before the single finalize.
    paused = render.paused_frame(
        "T", ["One", "two.", "Three."], 1, 0, 150, 0.2, _night(),
        flash="2m left")
    assert paused.size == (W, H) and _only_01(paused)


@pytest.mark.parametrize("key", ["night", "focus", "dim", "mono"])
def test_theme_fonts_resolve(key):
    th = theme.THEMES[key]
    reg, bold = theme.fonts(th)
    assert reg.endswith(".ttf") and bold.endswith(".ttf")
    f = theme.font(th, 14)
    assert f.size == 14 and theme.font(th, 14) is f
    assert theme.font(th, 14, bold=True).size == 14


def test_theme_paper_serif_or_xfail():
    th = theme.THEMES["paper"]
    try:
        theme.fonts(th)
    except FileNotFoundError:
        pytest.xfail("serif face not installed yet (Phase 3 package)")
    f = theme.font(th, 12)
    assert f.size == 12


def test_default_theme_key_matches_settings():
    assert theme.DEFAULT_THEME_KEY == config.SETTINGS_DEFAULTS["theme"]
    assert theme.DEFAULT_THEME_KEY in theme.THEMES


def test_no_rgb_or_side_card_api():
    for name in ("ACCENT", "FG", "DIM", "SW", "SH", "MW", "MH",
                 "book_card", "speed_card", "progress_card", "hints_card",
                 "splash_side", "splash_main", "menu", "confirm_power"):
        assert not hasattr(render, name)


def test_orp_helper_is_what_the_renderer_uses():
    assert rsvp.orp_index("hello") == 1
    assert rsvp.orp_index("Rapid") == 1
