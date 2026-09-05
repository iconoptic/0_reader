"""All screen rendering for the three LCDs, dark theme throughout.

Main-screen functions return a 240x240 RGB image; side-card functions
return an 80x160 (portrait) RGB image. Nothing here touches hardware.
"""

import os

from PIL import Image, ImageDraw, ImageFont

import config
import rsvp

MW, MH = config.MAIN_W, config.MAIN_H
SW, SH = config.SIDE_W, config.SIDE_H

# Palette (dark theme)
BG = (0, 0, 0)
FG = (228, 228, 228)
DIM = (125, 125, 125)
FAINT = (52, 52, 52)
ACCENT = (255, 150, 30)
ACCENT_BG = (58, 34, 0)


def _font_dir():
    for d in config.FONT_DIRS:
        if os.path.exists(os.path.join(d, "DejaVuSans.ttf")):
            return d
    raise FileNotFoundError("DejaVuSans.ttf not found in %r" % (config.FONT_DIRS,))


_REG = os.path.join(_font_dir(), "DejaVuSans.ttf")
_BOLD = os.path.join(_font_dir(), "DejaVuSans-Bold.ttf")

_fonts = {}


def _font(path, size):
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]


def _canvas(w, h):
    img = Image.new("RGB", (w, h), BG)
    return img, ImageDraw.Draw(img)


def _ellipsize(draw, text, fnt, max_w):
    if draw.textlength(text, font=fnt) <= max_w:
        return text
    while text and draw.textlength(text + "\u2026", font=fnt) > max_w:
        text = text[:-1]
    return text + "\u2026"


def _wrap(draw, text, fnt, max_w, max_lines):
    """Greedy word wrap; the last line is ellipsized if text is left over."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if draw.textlength(cand, font=fnt) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    used = sum(len(l.split()) for l in lines)
    if used < len(words) and lines:
        lines[-1] = _ellipsize(draw, lines[-1] + " " + " ".join(words[used:]),
                               fnt, max_w)
    return [_ellipsize(draw, l, fnt, max_w) for l in lines]


def _center(draw, text, fnt, y, fill, w=None, x0=0):
    w = MW if w is None else w
    tw = draw.textlength(text, font=fnt)
    draw.text((x0 + (w - tw) / 2, y), text, font=fnt, fill=fill)


def fmt_minutes(minutes):
    minutes = int(round(minutes))
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return "%dm" % minutes
    h, m = divmod(minutes, 60)
    return "%dh" % h if h >= 10 else "%dh %02dm" % (h, m)


def fmt_words(n):
    if n >= 10_000:
        return "%.0fk" % (n / 1000)
    if n >= 1000:
        return "%.1fk" % (n / 1000)
    return str(n)


# ====================================================================
# Main screen (240x240)
# ====================================================================

# ---- RSVP word frame -----------------------------------------------

PIVOT_X = 96              # fixed column the pivot letter is centred on
CENTER_Y = MH // 2
_WORD_SIZES = (40, 34, 28, 22, 17)
_TICK = (44, 58)          # tick marks span CENTER_Y +/- these


def _draw_ticks(d, cx):
    d.line([(cx, CENTER_Y - _TICK[1]), (cx, CENTER_Y - _TICK[0])], fill=DIM)
    d.line([(cx, CENTER_Y + _TICK[0]), (cx, CENTER_Y + _TICK[1])], fill=DIM)


def word_frame(word):
    """One word, pivot letter in accent colour sitting on PIVOT_X."""
    img, d = _canvas(MW, MH)
    orp = rsvp.orp_index(word)
    pre, ch, post = word[:orp], word[orp], word[orp + 1:]

    reg = bold = None
    x0 = 4
    for size in _WORD_SIZES:
        reg, bold = _font(_REG, size), _font(_BOLD, size)
        w_pre = d.textlength(pre, font=reg)
        w_ch = d.textlength(ch, font=bold)
        w_post = d.textlength(post, font=reg)
        x0 = PIVOT_X - w_pre - w_ch / 2
        if x0 >= 4 and x0 + w_pre + w_ch + w_post <= MW - 4:
            break
    total = (d.textlength(pre, font=reg) + d.textlength(ch, font=bold)
             + d.textlength(post, font=reg))
    if total > MW - 8:
        return _two_line_word(img, d, word, orp)
    x0 = max(4, min(x0, MW - 4 - total))

    x = x0
    d.text((x, CENTER_Y), pre, font=reg, fill=FG, anchor="lm")
    x += d.textlength(pre, font=reg)
    cx = x + d.textlength(ch, font=bold) / 2
    d.text((x, CENTER_Y), ch, font=bold, fill=ACCENT, anchor="lm")
    x += d.textlength(ch, font=bold)
    d.text((x, CENTER_Y), post, font=reg, fill=FG, anchor="lm")
    _draw_ticks(d, cx)
    return img


def _two_line_word(img, d, word, orp):
    """A word too long even at the smallest size: hyphenate onto two lines
    (left-aligned) so no glyph is ever cut off at the edge."""
    reg, bold = _font(_REG, 26), _font(_BOLD, 26)
    k = len(word) - 1
    while k > 1 and d.textlength(word[:k] + "-", font=reg) > MW - 8:
        k -= 1
    first, second = word[:k] + "-", word[k:]
    second = _ellipsize(d, second, reg, MW - 8)
    y1, y2 = CENTER_Y - 17, CENTER_Y + 17
    if orp < k:
        x = 4
        d.text((x, y1), first[:orp], font=reg, fill=FG, anchor="lm")
        x += d.textlength(first[:orp], font=reg)
        d.text((x, y1), first[orp], font=bold, fill=ACCENT, anchor="lm")
        x += d.textlength(first[orp], font=bold)
        d.text((x, y1), first[orp + 1:], font=reg, fill=FG, anchor="lm")
        d.text((4, y2), second, font=reg, fill=FG, anchor="lm")
    else:
        d.text((4, y1), first, font=reg, fill=FG, anchor="lm")
        d.text((4, y2), second, font=reg, fill=FG, anchor="lm")
    return img


def _fit_chunk_orp(d, words):
    """Try each word size (largest first) and return (size, parts) for the
    first one where every word's pre/pivot/post pieces fit on one line
    without truncating anything, or None if even the smallest doesn't fit.
    parts is a list of (pre, ch, post) per word, in order."""
    for size in _WORD_SIZES:
        reg, bold = _font(_REG, size), _font(_BOLD, size)
        space_w = d.textlength(" ", font=reg)
        parts = []
        total = 0.0
        for w in words:
            orp = rsvp.orp_index(w)
            pre, ch, post = w[:orp], w[orp], w[orp + 1:]
            total += (d.textlength(pre, font=reg) + d.textlength(ch, font=bold)
                      + d.textlength(post, font=reg))
            parts.append((pre, ch, post))
        total += space_w * (len(words) - 1)
        if total <= MW - 8:
            return size, parts
    return None


def chunk_frame(words):
    """Frame for 2+ words shown at once (wpm outpacing the frame rate).

    Keeps each word's own pivot letter highlighted as long as the whole
    chunk fits on one line; otherwise falls back to plain, ellipsized text.
    """
    img, d = _canvas(MW, MH)
    fitted = _fit_chunk_orp(d, words)
    if fitted is None:
        text = " ".join(words)
        fnt = _font(_REG, _WORD_SIZES[-1])
        for size in _WORD_SIZES:
            fnt = _font(_REG, size)
            if d.textlength(text, font=fnt) <= MW - 8:
                break
        text = _ellipsize(d, text, fnt, MW - 8)
        x = (MW - d.textlength(text, font=fnt)) / 2
        d.text((x, CENTER_Y), text, font=fnt, fill=FG, anchor="lm")
    else:
        size, parts = fitted
        reg, bold = _font(_REG, size), _font(_BOLD, size)
        space_w = d.textlength(" ", font=reg)
        total_w = sum(d.textlength(pre, font=reg) + d.textlength(ch, font=bold)
                      + d.textlength(post, font=reg) for pre, ch, post in parts)
        total_w += space_w * (len(parts) - 1)
        x = (MW - total_w) / 2
        for pre, ch, post in parts:
            d.text((x, CENTER_Y), pre, font=reg, fill=FG, anchor="lm")
            x += d.textlength(pre, font=reg)
            d.text((x, CENTER_Y), ch, font=bold, fill=ACCENT, anchor="lm")
            x += d.textlength(ch, font=bold)
            d.text((x, CENTER_Y), post, font=reg, fill=FG, anchor="lm")
            x += d.textlength(post, font=reg) + space_w
    return img


# ---- library ---------------------------------------------------------

MENU_ROWS = 8
_MENU_Y0 = 30
_MENU_ROW_H = 24


def _header(d, title, note=None):
    d.text((8, 5), title, font=_font(_BOLD, 14), fill=ACCENT)
    if note:
        nf = _font(_REG, 11)
        d.text((MW - 8 - d.textlength(note, font=nf), 8), note, font=nf, fill=DIM)
    d.line([(0, 25), (MW, 25)], fill=FAINT)


def menu(titles, sel, top, note=None):
    img, d = _canvas(MW, MH)
    _header(d, "LIBRARY", note)
    row_f = _font(_REG, 14)
    if not titles:
        f = _font(_REG, 13)
        d.text((10, 48), "No books found.", font=f, fill=FG)
        d.text((10, 72), "Copy .txt / .epub files to", font=f, fill=DIM)
        d.text((10, 92), config.BOOKS_DIR, font=_font(_BOLD, 12), fill=FG)
        d.text((10, 116), "e.g. from another machine:", font=f, fill=DIM)
        d.text((10, 136), "scp book.epub \\", font=_font(_REG, 11), fill=FG)
        d.text((10, 152), "  reader@rapidreader.local:ebooks/",
               font=_font(_REG, 11), fill=FG)
        return img

    y = _MENU_Y0
    for i in range(top, min(top + MENU_ROWS, len(titles))):
        label = _ellipsize(d, titles[i], row_f, MW - 30)
        if i == sel:
            d.rectangle([0, y, MW - 1, y + _MENU_ROW_H - 1], fill=ACCENT_BG)
            d.rectangle([0, y, 3, y + _MENU_ROW_H - 1], fill=ACCENT)
            d.text((12, y + 4), label, font=row_f, fill=FG)
        else:
            d.text((12, y + 4), label, font=row_f, fill=DIM)
        y += _MENU_ROW_H
    # scroll indicators
    if top > 0:
        d.polygon([(MW - 10, _MENU_Y0 + 3), (MW - 6, _MENU_Y0 + 9),
                   (MW - 14, _MENU_Y0 + 9)], fill=DIM)
    if top + MENU_ROWS < len(titles):
        yb = _MENU_Y0 + MENU_ROWS * _MENU_ROW_H - 4
        d.polygon([(MW - 10, yb), (MW - 6, yb - 6), (MW - 14, yb - 6)], fill=DIM)
    cf = _font(_REG, 11)
    _center(d, "%d / %d" % (sel + 1, len(titles)), cf, MH - 15, DIM)
    return img


# ---- pause / context ------------------------------------------------

def paused(title, words, idx, sentence_start, wpm, progress):
    img, d = _canvas(MW, MH)
    hf = _font(_BOLD, 13)
    right = "%d%%  %d wpm" % (round(progress * 100), wpm)
    rf = _font(_REG, 11)
    rw = d.textlength(right, font=rf)
    d.text((8, 6), _ellipsize(d, title, hf, MW - 24 - rw), font=hf, fill=ACCENT)
    d.text((MW - 8 - rw, 8), right, font=rf, fill=DIM)
    d.line([(0, 25), (MW, 25)], fill=FAINT)

    # wrap from the start of the current sentence; the current word is in
    # accent, the rest of its sentence in FG, following sentences in DIM
    body = _font(_REG, 16)
    x, y = 8, 34
    line_h = 21
    in_current = True
    for i in range(sentence_start, len(words)):
        tok = words[i]
        tw = d.textlength(tok + " ", font=body)
        if x + tw > MW - 8:
            if y + 2 * line_h > MH - 4:
                # out of room: tack an ellipsis onto the end of this line
                ew = d.textlength("\u2026", font=body)
                d.text((min(x, MW - 8 - ew), y), "\u2026", font=body, fill=DIM)
                break
            x = 8
            y += line_h
        colour = ACCENT if i == idx else (FG if in_current else DIM)
        d.text((x, y), tok, font=body, fill=colour)
        if i == idx:
            wlen = d.textlength(tok, font=body)
            d.line([(x, y + 19), (x + wlen, y + 19)], fill=ACCENT)
        x += tw
        if rsvp._SENT_END_CHARS.intersection(tok[-2:]) and i >= idx:
            in_current = False
    return img


# ---- simple screens --------------------------------------------------

def message(lines, hint=None, big=None):
    """Centred lines; ``big`` (optional) is drawn larger above them."""
    img, d = _canvas(MW, MH)
    f = _font(_BOLD, 18)
    n = len(lines) + (1 if big else 0)
    y = (MH - n * 26) // 2 - (8 if hint else 0)
    if big:
        bf = _font(_BOLD, 26)
        _center(d, big, bf, y - 8, ACCENT)
        y += 36
    for line in lines:
        _center(d, _ellipsize(d, line, f, MW - 16), f, y, FG)
        y += 26
    if hint:
        _center(d, hint, _font(_REG, 12), MH - 24, DIM)
    return img


def confirm_power():
    return message(["Power off?"], hint="K1: yes    K2: no")


def the_end(title):
    img, d = _canvas(MW, MH)
    _center(d, "The End", _font(_BOLD, 26), 78, ACCENT)
    tf = _font(_REG, 14)
    _center(d, _ellipsize(d, title, tf, MW - 24), tf, 124, FG)
    _center(d, "any key: back to library", _font(_REG, 12), MH - 24, DIM)
    return img


def splash_main():
    img, d = _canvas(MW, MH)
    bf = _font(_BOLD, 30)
    # "Rapid" with its pivot letter highlighted, like a real frame
    pre, ch, post = "Ra", "p", "id"
    total = (d.textlength(pre, font=bf) + d.textlength(ch, font=bf)
             + d.textlength(post, font=bf))
    x = (MW - total) / 2
    d.text((x, CENTER_Y - 18), pre, font=bf, fill=FG, anchor="lm")
    x += d.textlength(pre, font=bf)
    cx = x + d.textlength(ch, font=bf) / 2
    d.text((x, CENTER_Y - 18), ch, font=bf, fill=ACCENT, anchor="lm")
    x += d.textlength(ch, font=bf)
    d.text((x, CENTER_Y - 18), post, font=bf, fill=FG, anchor="lm")
    d.line([(cx, CENTER_Y - 18 - 42), (cx, CENTER_Y - 18 - 30)], fill=DIM)
    d.line([(cx, CENTER_Y - 18 + 30), (cx, CENTER_Y - 18 + 42)], fill=DIM)
    _center(d, "Reader", _font(_REG, 20), CENTER_Y + 30, DIM)
    _center(d, "starting\u2026", _font(_REG, 12), MH - 30, FAINT)
    return img


# ====================================================================
# Side cards (80x160 portrait)
# ====================================================================

def _side():
    return _canvas(SW, SH)


def _label(d, text, y=6):
    _center(d, text, _font(_REG, 10), y, DIM, w=SW)


def _vbar(d, x, y0, y1, frac, w=14):
    """Vertical bar filling upward by ``frac``."""
    frac = max(0.0, min(1.0, frac))
    d.rectangle([x, y0, x + w - 1, y1], outline=FAINT)
    fill_h = int(round((y1 - y0 - 3) * frac))
    if fill_h > 0:
        d.rectangle([x + 2, y1 - 2 - fill_h + 1, x + w - 3, y1 - 2], fill=ACCENT)


def progress_card(progress, remaining_words, wpm, chapter=None):
    """Left card while reading/paused: % done, bar, chapter, time left.
    ``chapter`` is (n, total) or None when the book has no detected chapters."""
    img, d = _side()
    _label(d, "READ")
    _center(d, "%d%%" % int(progress * 100), _font(_BOLD, 22), 20, FG, w=SW)
    _vbar(d, SW // 2 - 7, 54, 122, progress)
    if chapter:
        _center(d, "ch %d/%d" % chapter, _font(_REG, 11), 128, DIM, w=SW)
    mins = remaining_words / max(1, wpm)
    _center(d, fmt_minutes(mins) + " left", _font(_REG, 11), 143, FG, w=SW)
    return img


def speed_card(wpm):
    """Right card while reading: current pace and how to change it."""
    img, d = _side()
    _label(d, "SPEED")
    _center(d, str(wpm), _font(_BOLD, 26), 18, FG, w=SW)
    _center(d, "wpm", _font(_REG, 10), 50, DIM, w=SW)
    frac = (wpm - config.MIN_WPM) / float(config.MAX_WPM - config.MIN_WPM)
    _vbar(d, SW // 2 - 7, 66, 122, frac)
    f = _font(_REG, 10)
    _center(d, "K1 \u00d72  +", f, 130, DIM, w=SW)
    _center(d, "K2 \u00d72  \u2212", f, 144, DIM, w=SW)
    return img


def hints_card(k1, k2):
    """Right card: what the keys do. ``k1``/``k2`` are lists of
    (gesture, action) pairs; K1 is drawn in the upper half to match the
    physical key positions."""
    img, d = _side()
    kf, gf, af = _font(_BOLD, 12), _font(_REG, 10), _font(_REG, 11)
    for base, key, items in ((0, "K1", k1), (SH // 2, "K2", k2)):
        d.text((6, base + 5), key, font=kf, fill=ACCENT)
        y = base + 23
        for gesture, action in items[:4]:
            d.text((6, y + 1), gesture, font=gf, fill=DIM)
            d.text((32, y), _ellipsize(d, action, af, SW - 34), font=af, fill=FG)
            y += 14
    d.line([(6, SH // 2 - 1), (SW - 6, SH // 2 - 1)], fill=FAINT)
    return img


def book_card(title, ext, position=None, total_words=None, wpm=None):
    """Left card in the library: details of the highlighted book."""
    img, d = _side()
    _label(d, "BOOK")
    tf = _font(_BOLD, 12)
    y = 20
    for line in _wrap(d, title, tf, SW - 8, 5):
        d.text((4, y), line, font=tf, fill=FG)
        y += 15
    y = max(y + 4, 100)
    d.text((4, y), ext.lstrip(".").upper() or "TXT", font=_font(_REG, 10), fill=DIM)
    if total_words:
        d.text((4, y + 14), fmt_words(total_words) + " words",
               font=_font(_REG, 10), fill=DIM)
        pos = position or 0
        if pos > 0:
            pct = int(100 * pos / total_words)
            d.text((4, y + 29), "%d%% read" % pct, font=_font(_BOLD, 11), fill=ACCENT)
            if wpm:
                d.text((4, y + 44), fmt_minutes((total_words - pos) / wpm) + " left",
                       font=_font(_REG, 10), fill=FG)
        else:
            d.text((4, y + 29), "not started", font=_font(_REG, 11), fill=DIM)
    else:
        d.text((4, y + 14), "new", font=_font(_BOLD, 11), fill=ACCENT)
        if wpm:
            d.text((4, y + 29), "open to see", font=_font(_REG, 10), fill=DIM)
            d.text((4, y + 43), "length", font=_font(_REG, 10), fill=DIM)
    return img


def side_message(lines, accent_first=False):
    img, d = _side()
    f = _font(_BOLD, 12)
    y = (SH - len(lines) * 16) // 2
    for i, line in enumerate(lines):
        _center(d, line, f, y, ACCENT if (accent_first and i == 0) else FG, w=SW)
        y += 16
    return img


def blank_side():
    return _side()[0]


def splash_side(which):
    img, d = _side()
    d.line([(SW // 2, SH // 2 - 20), (SW // 2, SH // 2 + 20)], fill=FAINT)
    _center(d, "RAPID" if which == "left" else "READER", _font(_BOLD, 11),
            SH // 2 + 28, DIM, w=SW)
    return img


# Key hints per app mode: (K1 items, K2 items)
HINTS = {
    "menu": ([("tap", "open"), ("\u00d72", "rescan")],
             [("tap", "down"), ("\u00d72", "up"), ("hold", "power")]),
    "paused": ([("tap", "play"), ("\u00d72", "next ch"), ("\u00d73", "forward")],
               [("tap", "back"), ("\u00d72", "prev ch"), ("hold", "library")]),
    "reading": ([("tap", "pause"), ("\u00d72", "faster"), ("\u00d73", "forward")],
                [("tap", "back"), ("\u00d72", "slower"), ("hold", "library")]),
    "confirm": ([("tap", "yes, off")], [("tap", "no")]),
    "end": ([("tap", "library")], [("tap", "library")]),
}


def hints(mode):
    return hints_card(*HINTS[mode])
