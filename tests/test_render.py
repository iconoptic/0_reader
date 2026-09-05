import pytest

import config
import render
import rsvp

MW, MH = render.MW, render.MH
SW, SH = render.SW, render.SH


def _lit_columns(img, y0, y1, colour=None):
    """Columns with at least one non-background pixel in rows y0..y1
    (or, if ``colour`` is given, at least one pixel of exactly that colour)."""
    px = img.load()
    out = set()
    for x in range(img.width):
        for y in range(y0, y1):
            p = px[x, y]
            if (p == colour) if colour else (p != render.BG):
                out.add(x)
                break
    return out


def _has_ink(img):
    return any(hi > 0 for _, hi in img.getextrema())


def _has_colour(img, colour):
    return any(c == colour for _, c in img.getcolors(1 << 16) or [])


# ---- main screen -----------------------------------------------------

@pytest.mark.parametrize("fn,args", [
    (render.word_frame, ("hello",)),
    (render.word_frame, ("supercalifragilisticexpialidocious",)),
    (render.chunk_frame, (["two", "words"],)),
    (render.menu, (["A", "B"], 0, 0, None)),
    (render.menu, ([], 0, 0, "note")),
    (render.paused, ("T", ["One", "two.", "Three."], 1, 0, 150, 0.2)),
    (render.message, (["hi"], "hint")),
    (render.message, (["hi"], None, "Big")),
    (render.confirm_power, ()),
    (render.the_end, ("T",)),
    (render.splash_main, ()),
])
def test_every_main_frame_is_panel_sized_rgb_on_black(fn, args):
    img = fn(*args)
    assert img.size == (MW, MH)
    assert img.mode == "RGB"
    assert _has_ink(img)
    # dark theme: the background must dominate
    black = dict((c, n) for n, c in img.getcolors(1 << 16)).get(render.BG, 0)
    assert black > 0.6 * MW * MH


@pytest.mark.parametrize("fn,args", [
    (render.progress_card, (0.42, 5000, 250, (3, 12))),
    (render.progress_card, (0.0, 5000, 250, None)),
    (render.progress_card, (1.0, 0, 250, (12, 12))),
    (render.speed_card, (60,)),
    (render.speed_card, (900,)),
    (render.book_card, ("Title", ".epub", 100, 1000, 250)),
    (render.book_card, ("A very long title that wraps and wraps and wraps on",
                        ".txt", None, None, 250)),
    (render.book_card, ("T", ".txt", 0, 1000, 250)),
    (render.side_message, (["a", "b"], True)),
    (render.blank_side, ()),
    (render.splash_side, ("left",)),
    (render.splash_side, ("right",)),
] + [(render.hints, (m,)) for m in render.HINTS])
def test_every_side_card_is_side_sized_rgb(fn, args):
    img = fn(*args)
    assert img.size == (SW, SH)
    assert img.mode == "RGB"
    if fn is not render.blank_side:
        assert _has_ink(img)


@pytest.mark.parametrize("word", ["a", "reader", "extraordinarily", "\u201cQuoted,\u201d"])
def test_word_frame_pivot_letter_sits_on_fixed_column(word):
    img = render.word_frame(word)
    # the guide ticks above/below the word are drawn at the pivot's centre x
    top = _lit_columns(img, render.CENTER_Y - render._TICK[1],
                       render.CENTER_Y - render._TICK[0] + 1)
    bottom = _lit_columns(img, render.CENTER_Y + render._TICK[0],
                          render.CENTER_Y + render._TICK[1] + 1)
    assert top == bottom == {render.PIVOT_X}
    # and the pivot letter itself is the only accent-coloured thing
    accent = _lit_columns(img, 0, MH, render.ACCENT)
    assert accent and min(accent) <= render.PIVOT_X <= max(accent)


def test_word_frame_never_clips_at_the_edges():
    for word in ("supercalifragilisticexpialidocious",
                 "Pneumonoultramicroscopicsilicovolcanoconiosis",
                 "x" * 80):
        img = render.word_frame(word)
        cols = _lit_columns(img, 0, MH)
        assert cols and min(cols) >= 2 and max(cols) <= MW - 3
        # a hyphenated two-line fallback keeps its pivot letter highlighted
        assert _has_colour(img, render.ACCENT)


def test_word_frame_shrinks_font_before_giving_up():
    small = render.word_frame("a")
    big = render.word_frame("internationalization")
    rows = lambda im: {y for y in range(MH) if _lit_columns(im, y, y + 1) - {render.PIVOT_X}}  # noqa: E731
    # longer word -> smaller font -> fewer text rows
    assert len(rows(big)) < len(rows(small)) + 5


def test_chunk_frame_keeps_orp_when_it_fits_else_plain():
    d = render.ImageDraw.Draw(render.Image.new("RGB", (MW, MH), render.BG))
    assert render._fit_chunk_orp(d, ["a", "b"]) is not None
    assert render._fit_chunk_orp(d, ["antidisestablishmentarianism"] * 6) is None
    assert _has_colour(render.chunk_frame(["a", "b"]), render.ACCENT)
    plain = render.chunk_frame(["antidisestablishmentarianism"] * 6)
    assert plain.size == (MW, MH) and not _has_colour(plain, render.ACCENT)


def test_menu_selection_row_is_highlighted_and_scrolls():
    titles = ["Book %d" % i for i in range(12)]
    y_row = lambda i: render._MENU_Y0 + i * render._MENU_ROW_H + 5  # noqa: E731
    img = render.menu(titles, sel=0, top=0)
    px = img.load()
    assert px[1, y_row(0)] == render.ACCENT          # selection marker
    assert px[MW - 20, y_row(0)] == render.ACCENT_BG  # selection band
    assert px[MW - 20, y_row(1)] == render.BG
    img2 = render.menu(titles, sel=1, top=0)
    px2 = img2.load()
    assert px2[1, y_row(0)] == render.BG and px2[1, y_row(1)] == render.ACCENT
    # 'more below' arrow when the list overflows, 'more above' when scrolled
    assert render.MENU_ROWS == 8
    yb = render._MENU_Y0 + render.MENU_ROWS * render._MENU_ROW_H
    arrow_rows_top = (render._MENU_Y0 + 3, render._MENU_Y0 + 10)
    assert _lit_columns(img, yb - 10, yb, render.DIM) & {MW - 10}
    assert not _lit_columns(img, *arrow_rows_top, render.DIM) & {MW - 10}
    img3 = render.menu(titles, sel=9, top=4)
    assert _lit_columns(img3, *arrow_rows_top, render.DIM) & {MW - 10}


def test_menu_empty_shows_books_dir():
    img = render.menu([], 0, 0)
    assert _has_ink(img)


def test_ellipsize_and_wrap():
    img = render.Image.new("RGB", (MW, MH), render.BG)
    d = render.ImageDraw.Draw(img)
    f = render._font(render._REG, 13)
    assert render._ellipsize(d, "short", f, 200) == "short"
    long = "a very very very very very very long title indeed"
    out = render._ellipsize(d, long, f, 100)
    assert out.endswith("\u2026") and d.textlength(out, font=f) <= 100
    lines = render._wrap(d, long, f, 100, 3)
    assert len(lines) == 3 and lines[-1].endswith("\u2026")
    assert all(d.textlength(l, font=f) <= 100 for l in lines)
    assert render._wrap(d, "two words", f, 200, 3) == ["two words"]


def test_paused_highlights_current_word_and_dims_following_sentences():
    words = "One two three. Four five six. Seven".split()
    img = render.paused("Title", words, idx=1, sentence_start=0, wpm=150,
                        progress=0.3)
    assert img.size == (MW, MH)
    assert _has_colour(img, render.ACCENT)
    assert _has_colour(img, render.DIM)   # the following sentence
    # a very long sentence is cut off with an ellipsis inside the frame
    # (rows below the full-width header rule)
    big = render.paused("T", ["word"] * 400, 0, 0, 150, 0.0)
    assert max(_lit_columns(big, 27, MH)) <= MW - 3


def test_progress_card_bar_and_time_scale():
    empty = render.progress_card(0.0, 10_000, 250)
    full = render.progress_card(1.0, 0, 250)
    assert not _has_colour(empty, render.ACCENT)
    assert _has_colour(full, render.ACCENT)
    assert render.fmt_minutes(0.4) == "<1m"
    assert render.fmt_minutes(45) == "45m"
    assert render.fmt_minutes(72) == "1h 12m"
    assert render.fmt_minutes(60 * 12) == "12h"
    assert render.fmt_words(269) == "269"
    assert render.fmt_words(1500) == "1.5k"
    assert render.fmt_words(215845) == "216k"


def test_hints_put_k1_in_upper_half_and_k2_in_lower():
    img = render.hints("menu")
    top = _lit_columns(img.crop((0, 0, SW, SH // 2 - 2)), 0, SH // 2 - 2, render.ACCENT)
    bottom = _lit_columns(img.crop((0, SH // 2, SW, SH)), 0, SH // 2, render.ACCENT)
    assert top and bottom
    for mode in render.HINTS:
        k1, k2 = render.HINTS[mode]
        assert 1 <= len(k1) <= 4 and 1 <= len(k2) <= 4


def test_fonts_resolve_from_configured_dirs():
    assert render._font_dir() in config.FONT_DIRS
    f = render._font(render._BOLD, 20)
    assert f.size == 20 and render._font(render._BOLD, 20) is f


def test_orp_helper_is_what_the_renderer_uses():
    assert rsvp.orp_index("hello") == 1
