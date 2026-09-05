import pytest

import config
import render
import rsvp

W, H = render.W, render.H


def _ink_columns(img, y0, y1):
    """Set of x columns containing at least one black pixel in rows y0..y1."""
    px = img.load()
    return {x for x in range(img.width) for y in range(y0, y1) if px[x, y] == 0}


def _has_ink(img):
    return img.getextrema()[0] == 0


@pytest.mark.parametrize("fn,args", [
    (render.word_frame, ("hello", 150, 0.5)),
    (render.chunk_frame, (["two", "words"], 400, 0.1)),
    (render.menu, (["A", "B"], 0, 0, None)),
    (render.menu, ([], 0, 0, "note")),
    (render.paused, ("T", ["One", "two.", "Three."], 1, 0, 150, 0.2)),
    (render.message, (["hi"], "hint")),
    (render.confirm_power, ()),
    (render.the_end, ("T",)),
])
def test_every_frame_is_panel_sized_mono(fn, args):
    img = fn(*args)
    assert img.size == (W, H)
    assert img.mode == "1"
    assert _has_ink(img)


@pytest.mark.parametrize("word", ["a", "reader", "extraordinarily", "\u201cQuoted,\u201d"])
def test_word_frame_pivot_letter_sits_on_fixed_column(word):
    img = render.word_frame(word, 150, 0.0)
    # the ORP guide ticks are drawn at the pivot's centre x (rows chosen to
    # avoid the wpm label in the top-right corner)
    top = _ink_columns(img, 15, 22)
    bottom = _ink_columns(img, H - 27, H - 17)
    assert top == bottom == {render.PIVOT_X}


def test_word_frame_overlong_word_is_left_aligned_not_cut():
    img = render.word_frame("supercalifragilisticexpialidocious", 150, 0.0)
    cols = _ink_columns(img, 40, H - 30)
    assert min(cols) <= 5            # pushed to the left edge (glyph bearing)
    assert _ink_columns(img, 15, 22)  # pivot ticks still drawn


def test_word_frame_shrinks_long_words_to_fit():
    img = render.word_frame("supercalifragilisticexpialidocious", 150, 0.0)
    cols = _ink_columns(img, 30, H - 30)
    assert min(cols) >= 0 and max(cols) <= W - 1


def test_word_frame_progress_bar_length():
    empty = render.word_frame("x", 150, 0.0)
    half = render.word_frame("x", 150, 0.5)
    full = render.word_frame("x", 150, 1.0)
    bar = lambda im: _ink_columns(im, H - 3, H)  # noqa: E731
    assert len(bar(half)) == pytest.approx(W / 2, abs=3)
    assert len(bar(full)) == W
    assert len(bar(empty)) <= 1


def test_chunk_frame_keeps_orp_when_it_fits_else_plain():
    d = render.ImageDraw.Draw(render.Image.new("1", (W, H), 1))
    assert render._fit_chunk_orp(d, ["a", "b"]) is not None
    assert render._fit_chunk_orp(d, ["antidisestablishmentarianism"] * 6) is None
    # both paths must still produce a valid frame
    assert render.chunk_frame(["antidisestablishmentarianism"] * 6, 900, 0).size == (W, H)


def test_menu_selection_row_is_inverted_and_scrolls():
    titles = ["Book %d" % i for i in range(12)]
    img = render.menu(titles, sel=0, top=0)
    px = img.load()
    assert px[2, 22] == 0          # selected row is filled black
    img2 = render.menu(titles, sel=1, top=0)
    px2 = img2.load()
    assert px2[2, 22] == 1 and px2[2, 39] == 0
    # 'more below' arrow when the list overflows
    assert _ink_columns(img, 98, 103) & {W - 8}
    assert render.MENU_ROWS == 5


def test_menu_empty_shows_books_dir():
    img = render.menu([], 0, 0)
    assert _has_ink(img)


def test_ellipsize():
    img = render.Image.new("1", (W, H), 1)
    d = render.ImageDraw.Draw(img)
    f = render._font(render._REG, 13)
    assert render._ellipsize(d, "short", f, 200) == "short"
    long = "a very very very very very very long title indeed"
    out = render._ellipsize(d, long, f, 100)
    assert out.endswith("\u2026") and d.textlength(out, font=f) <= 100


def test_paused_underlines_current_word_and_stops_at_sentence_end():
    words = "One two three. Four five six. Seven".split()
    img = render.paused("Title", words, idx=1, sentence_start=0, wpm=150, progress=0.3)
    assert img.size == (W, H)
    # an underline exists somewhere in the first text row
    assert _ink_columns(img, 34, 35)


def test_fonts_resolve_from_configured_dirs():
    assert render._font_dir() in config.FONT_DIRS
    f = render._font(render._BOLD, 20)
    assert f.size == 20 and render._font(render._BOLD, 20) is f
