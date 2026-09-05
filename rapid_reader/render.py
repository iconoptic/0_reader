"""All screen rendering. Every function returns a 250x122 PIL image."""

import os

from PIL import Image, ImageDraw, ImageFont

import config
import rsvp

W, H = config.EPD_WIDTH, config.EPD_HEIGHT


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


def _blank():
    img = Image.new("1", (W, H), 1)
    return img, ImageDraw.Draw(img)


def _ellipsize(draw, text, fnt, max_w):
    if draw.textlength(text, font=fnt) <= max_w:
        return text
    while text and draw.textlength(text + "\u2026", font=fnt) > max_w:
        text = text[:-1]
    return text + "\u2026"


# ---- RSVP word frame -----------------------------------------------

PIVOT_X = 100
_WORD_SIZES = (32, 26, 20, 15)


def word_frame(word, wpm, progress):
    img, d = _blank()
    orp = rsvp.orp_index(word)
    pre, ch, post = word[:orp], word[orp], word[orp + 1:]

    x0 = 2
    reg = bold = None
    for size in _WORD_SIZES:
        reg = _font(_REG, size)
        bold = _font(_BOLD, size)
        w_pre = d.textlength(pre, font=reg)
        w_ch = d.textlength(ch, font=bold)
        w_post = d.textlength(post, font=reg)
        x0 = PIVOT_X - w_pre - w_ch / 2
        if x0 >= 2 and x0 + w_pre + w_ch + w_post <= W - 2:
            break
    x0 = max(2, min(x0, W - 2 - (d.textlength(pre, font=reg)
                                 + d.textlength(ch, font=bold)
                                 + d.textlength(post, font=reg))))

    size = reg.size
    y = (H - size) // 2 - 6
    x = x0
    d.text((x, y), pre, font=reg, fill=0)
    x += d.textlength(pre, font=reg)
    cx = x + d.textlength(ch, font=bold) / 2
    d.text((x, y), ch, font=bold, fill=0)
    x += d.textlength(ch, font=bold)
    d.text((x, y), post, font=reg, fill=0)

    # ORP guides above/below the pivot letter
    d.line([(cx, 12), (cx, 24)], fill=0)
    d.line([(cx, H - 16), (cx, H - 28)], fill=0)

    small = _font(_REG, 10)
    label = "%d wpm" % wpm
    d.text((W - 4 - d.textlength(label, font=small), 2), label,
           font=small, fill=0)
    d.rectangle([0, H - 3, int((W - 1) * progress), H - 1], fill=0)
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
        if total <= W - 4:
            return size, parts
    return None


def chunk_frame(words, wpm, progress):
    """Frame for 2+ words shown at once (wpm outpacing the panel's refresh).

    Keeps each word's own ORP pivot letter bolded, like word_frame, as long
    as the whole chunk fits on one line without cutting any word off;
    otherwise falls back to plain (possibly ellipsized) text so nothing
    gets visually cut in a confusing way.
    """
    img, d = _blank()
    fitted = _fit_chunk_orp(d, words)
    if fitted is None:
        text = " ".join(words)
        fnt = _WORD_SIZES[-1]
        for size in _WORD_SIZES:
            fnt = _font(_REG, size)
            if d.textlength(text, font=fnt) <= W - 4:
                break
        text = _ellipsize(d, text, fnt, W - 4)
        y = (H - fnt.size) // 2 - 6
        x = (W - d.textlength(text, font=fnt)) / 2
        d.text((x, y), text, font=fnt, fill=0)
    else:
        size, parts = fitted
        reg, bold = _font(_REG, size), _font(_BOLD, size)
        space_w = d.textlength(" ", font=reg)
        total_w = sum(d.textlength(pre, font=reg) + d.textlength(ch, font=bold)
                     + d.textlength(post, font=reg) for pre, ch, post in parts)
        total_w += space_w * (len(parts) - 1)
        y = (H - size) // 2 - 6
        x = (W - total_w) / 2
        for pre, ch, post in parts:
            d.text((x, y), pre, font=reg, fill=0)
            x += d.textlength(pre, font=reg)
            d.text((x, y), ch, font=bold, fill=0)
            x += d.textlength(ch, font=bold)
            d.text((x, y), post, font=reg, fill=0)
            x += d.textlength(post, font=reg) + space_w

    small = _font(_REG, 10)
    label = "%d wpm" % wpm
    d.text((W - 4 - d.textlength(label, font=small), 2), label,
           font=small, fill=0)
    d.rectangle([0, H - 3, int((W - 1) * progress), H - 1], fill=0)
    return img

MENU_ROWS = 5


def menu(titles, sel, top, note=None):
    img, d = _blank()
    hdr = _font(_BOLD, 13)
    d.rectangle([0, 0, W - 1, 17], fill=0)
    d.text((4, 2), "RAPID READER", font=hdr, fill=1)
    if note:
        d.text((W - 4 - d.textlength(note, font=_font(_REG, 10)), 4),
               note, font=_font(_REG, 10), fill=1)

    row_f = _font(_REG, 13)
    if not titles:
        msg = _font(_REG, 12)
        d.text((6, 34), "No books found.", font=msg, fill=0)
        d.text((6, 52), "Copy .txt / .epub files to:", font=msg, fill=0)
        d.text((6, 68), config.BOOKS_DIR, font=_font(_BOLD, 12), fill=0)
        d.text((6, 86), "scp book.epub reader@rapidreader.local:ebooks/",
               font=_font(_REG, 9), fill=0)
    else:
        y = 20
        for i in range(top, min(top + MENU_ROWS, len(titles))):
            label = _ellipsize(d, titles[i], row_f, W - 16)
            if i == sel:
                d.rectangle([0, y, W - 1, y + 16], fill=0)
                d.text((6, y + 1), label, font=row_f, fill=1)
            else:
                d.text((6, y + 1), label, font=row_f, fill=0)
            y += 17
        if top > 0:
            d.polygon([(W - 8, 22), (W - 4, 26), (W - 12, 26)], fill=sel != top)
        if top + MENU_ROWS < len(titles):
            d.polygon([(W - 8, 102), (W - 4, 98), (W - 12, 98)], fill=0)

    hint = _font(_REG, 9)
    d.line([(0, H - 13), (W, H - 13)], fill=0)
    d.text((3, H - 11),
           "5:down  5x2:up  6:open  6x2:rescan  hold5:power",
           font=hint, fill=0)
    return img


# ---- pause / context ------------------------------------------------

def paused(title, words, idx, sentence_start, wpm, progress):
    img, d = _blank()
    hdr = _font(_BOLD, 11)
    d.text((3, 1), _ellipsize(d, title, hdr, W - 60), font=hdr, fill=0)
    pf = _font(_REG, 10)
    pct = "%d%%  %d wpm" % (round(progress * 100), wpm)
    d.text((W - 3 - d.textlength(pct, font=pf), 2), pct, font=pf, fill=0)
    d.line([(0, 15), (W, 15)], fill=0)

    # wrap the current sentence, underlining the current word
    body = _font(_REG, 13)
    x, y = 3, 20
    line_h = 16
    for i in range(sentence_start, len(words)):
        tok = words[i]
        tw = d.textlength(tok + " ", font=body)
        if x + tw > W - 3:
            x = 3
            y += line_h
            if y > H - 30:
                d.text((x, y - line_h + 12), "\u2026", font=body, fill=0)
                break
        d.text((x, y), tok, font=body, fill=0)
        if i == idx:
            wlen = d.textlength(tok, font=body)
            d.line([(x, y + 14), (x + wlen, y + 14)], fill=0)
        x += tw
        if i > idx and rsvp._SENT_END_CHARS.intersection(tok[-2:]):
            break

    hint = _font(_REG, 9)
    d.line([(0, H - 13), (W, H - 13)], fill=0)
    d.text((3, H - 11),
           "6:play  5:back  5x2:prevCh  6x2:nextCh  hold5:menu",
           font=hint, fill=0)
    return img


# ---- simple screens --------------------------------------------------

def message(lines, hint=None):
    img, d = _blank()
    f = _font(_BOLD, 15)
    y = (H - len(lines) * 20) // 2 - (8 if hint else 0)
    for line in lines:
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, y), line, font=f, fill=0)
        y += 20
    if hint:
        hf = _font(_REG, 10)
        w = d.textlength(hint, font=hf)
        d.text(((W - w) / 2, H - 18), hint, font=hf, fill=0)
    return img


def confirm_power():
    return message(["Power off?"], hint="6: yes    5: no")


def the_end(title):
    return message(["The End", ""], hint="any button: back to library")
