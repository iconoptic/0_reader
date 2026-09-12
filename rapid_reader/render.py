"""All screen rendering for the 128x64 SH1106 panel.

Frame functions return mode-'L' images (values 0/255 only). Theme invert is
applied later by the driver / App — never here. No colour, no side cards.
"""

from PIL import Image, ImageDraw

import config
import rsvp
import theme as themes

W, H = config.OLED_W, config.OLED_H   # 128, 64
CENTER_Y = H // 2                     # 32
PIVOT_X = 50
INK, BG = 255, 0

_WORD_SIZE_TIERS = {
    "small":  (18, 15, 13, 11),
    "medium": (22, 19, 16, 13),
    "large":  (28, 24, 20, 16),
}

# Fixed tick geometry for pivot_style="ticks" (not per-theme).
_TICK_ABOVE = (16, 10)   # CENTER_Y - these
_TICK_BELOW = (10, 16)   # CENTER_Y + these

_UI = themes.THEMES[themes.DEFAULT_THEME_KEY]


def _canvas():
    """Mode 'L', background 0. All frames draw ink=255 on bg=0."""
    img = Image.new("L", (W, H), BG)
    return img, ImageDraw.Draw(img)


def _finalize(img):
    """Collapse FreeType antialias mid-tones to strict 0/255."""
    return img.point(lambda p: INK if p >= 128 else BG, mode="L")


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


def _center(draw, text, fnt, y, w=None, x0=0):
    w = W if w is None else w
    tw = draw.textlength(text, font=fnt)
    draw.text((x0 + (w - tw) / 2, y), text, font=fnt, fill=INK)


def fmt_minutes(minutes):
    minutes = int(round(minutes))
    if minutes < 1:
        return "<1m"
    if minutes < 60:
        return "%dm" % minutes
    h, m = divmod(minutes, 60)
    return "%dh" % h if h >= 10 else "%dh %02dm" % (h, m)


def fmt_duration_hms(seconds):
    """Compact remaining-time string: omit leading zero units, always show seconds."""
    seconds = max(0, int(round(seconds)))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append("%dd" % days)
    if days or hours:
        parts.append("%dh" % hours)
    if days or hours or minutes:
        parts.append("%dm" % minutes)
    parts.append("%ds" % secs)
    return " ".join(parts)


def fmt_words(n):
    if n >= 10_000:
        return "%.0fk" % (n / 1000)
    if n >= 1000:
        return "%.1fk" % (n / 1000)
    return str(n)


def _default_theme():
    return _UI


def _header_band(d, title, note=None, title_fnt=None, note_fnt=None):
    """Shared header: bold title at (3,1), optional right note, rule at y=12."""
    t = _default_theme()
    title_fnt = title_fnt or themes.font(t, 11, bold=True)
    note_fnt = note_fnt or themes.font(t, 9)
    note_w = 0
    if note:
        note = _ellipsize(d, note, note_fnt, W // 2)
        note_w = d.textlength(note, font=note_fnt) + 4
        d.text((W - 3 - d.textlength(note, font=note_fnt), 2), note,
               font=note_fnt, fill=INK)
    d.text((3, 1), _ellipsize(d, title, title_fnt, W - 6 - note_w),
           font=title_fnt, fill=INK)
    d.line([(0, 12), (W - 1, 12)], fill=INK)


def _draw_ticks(d, cx):
    d.line([(cx, CENTER_Y - _TICK_ABOVE[0]), (cx, CENTER_Y - _TICK_ABOVE[1])],
           fill=INK)
    d.line([(cx, CENTER_Y + _TICK_BELOW[0]), (cx, CENTER_Y + _TICK_BELOW[1])],
           fill=INK)


def _draw_pivot_char(d, th, ch, x, y, reg, bold):
    """Draw the ORP character with theme.pivot_style. Returns width of ch."""
    style = th.pivot_style
    if style == "box":
        fnt = reg
        bbox = d.textbbox((x, y), ch, font=fnt, anchor="lm")
        pad = 1
        d.rectangle([bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
                    fill=INK)
        d.text((x, y), ch, font=fnt, fill=BG, anchor="lm")
        return d.textlength(ch, font=fnt)
    fnt = bold
    w_ch = d.textlength(ch, font=fnt)
    d.text((x, y), ch, font=fnt, fill=INK, anchor="lm")
    if style == "ticks":
        _draw_ticks(d, x + w_ch / 2)
    elif style == "underline":
        bbox = d.textbbox((x, y), ch, font=fnt, anchor="lm")
        uy = bbox[3] + 2
        d.line([(x, uy), (x + w_ch, uy)], fill=INK)
    # "bold" and unknown: weight alone
    return w_ch


def _draw_orp_parts(d, th, pre, ch, post, x, y, reg, bold):
    """Draw pre/ch/post at (x,y) with pivot styling. Returns end x."""
    if pre:
        d.text((x, y), pre, font=reg, fill=INK, anchor="lm")
        x += d.textlength(pre, font=reg)
    x += _draw_pivot_char(d, th, ch, x, y, reg, bold)
    if post:
        d.text((x, y), post, font=reg, fill=INK, anchor="lm")
        x += d.textlength(post, font=reg)
    return x


def _flash_badge(d, text):
    """Top-right inverted badge for transient status (e.g. wpm change)."""
    t = _default_theme()
    fnt = themes.font(t, 9, bold=True)
    text = _ellipsize(d, text, fnt, 30)
    x0, y0, x1, y1 = W - 34, 2, W - 2, 12
    d.rectangle([x0, y0, x1, y1], fill=INK)
    tw = d.textlength(text, font=fnt)
    d.text((x0 + (x1 - x0 - tw) / 2, y0 + 1), text, font=fnt, fill=BG)


def remaining_overlay(img, text, theme):
    """Centered inverted band for remaining-time flash on the pause screen.
    Uses the same theme face as the surrounding paused_frame."""
    d = ImageDraw.Draw(img)
    fnt = themes.font(theme, 10, bold=True)
    text = _ellipsize(d, text, fnt, W - 10)
    tw = d.textlength(text, font=fnt)
    pad_x, bh = 5, 14
    bw = int(tw) + pad_x * 2
    x0 = max(0, (W - bw) // 2)
    y0 = (H - bh) // 2
    d.rectangle([x0, y0, x0 + bw - 1, y0 + bh - 1], fill=INK)
    d.text((x0 + pad_x, y0 + 2), text, font=fnt, fill=BG)
    return img


def progress_frame(fraction, label="Updating..."):
    """Full-screen OTA / progress UI with a horizontal bar."""
    img, d = _canvas()
    t = _default_theme()
    f = themes.font(t, 11, bold=True)
    _center(d, _ellipsize(d, label, f, W - 8), f, 16)
    x0, y0, x1, y1 = 8, 34, W - 9, 46
    d.rectangle([x0, y0, x1, y1], outline=INK)
    frac = max(0.0, min(1.0, float(fraction)))
    inner = x1 - x0 - 3
    fill_w = int(inner * frac)
    if fill_w > 0:
        d.rectangle([x0 + 2, y0 + 2, x0 + 2 + fill_w, y1 - 2], fill=INK)
    _center(d, "%d%%" % round(frac * 100), themes.font(t, 9), 50)
    return _finalize(img)


# ---- RSVP word frame -------------------------------------------------

def word_frame(word, theme, flash=None, word_size=None):
    """One word, ORP marked per theme.pivot_style, sitting on PIVOT_X."""
    img, d = _canvas()
    word_size = word_size or config.SETTINGS_DEFAULTS["word_size"]
    sizes = _WORD_SIZE_TIERS.get(word_size, _WORD_SIZE_TIERS["medium"])
    orp = rsvp.orp_index(word)
    pre, ch, post = word[:orp], word[orp], word[orp + 1:]

    reg = bold = None
    x0 = 4
    for size in sizes:
        reg = themes.font(theme, size)
        bold = themes.font(theme, size, bold=True)
        # Measure pivot glyph with the font the style will actually use.
        ch_fnt = reg if theme.pivot_style == "box" else bold
        w_pre = d.textlength(pre, font=reg)
        w_ch = d.textlength(ch, font=ch_fnt)
        w_post = d.textlength(post, font=reg)
        x0 = PIVOT_X - w_pre - w_ch / 2
        if x0 >= 4 and x0 + w_pre + w_ch + w_post <= W - 4:
            break
    ch_fnt = reg if theme.pivot_style == "box" else bold
    total = (d.textlength(pre, font=reg) + d.textlength(ch, font=ch_fnt)
             + d.textlength(post, font=reg))
    if total > W - 8:
        img = _two_line_word(img, d, word, orp, theme)
        if flash:
            _flash_badge(ImageDraw.Draw(img), flash)
        return _finalize(img)
    x0 = max(4, min(x0, W - 4 - total))
    _draw_orp_parts(d, theme, pre, ch, post, x0, CENTER_Y, reg, bold)
    if flash:
        _flash_badge(d, flash)
    return _finalize(img)


def _two_line_word(img, d, word, orp, theme):
    """Hyphenate onto two lines so no glyph is cut off at the edge."""
    reg = themes.font(theme, 13)
    bold = themes.font(theme, 13, bold=True)
    k = len(word) - 1
    while k > 1 and d.textlength(word[:k] + "-", font=reg) > W - 8:
        k -= 1
    first, second = word[:k] + "-", word[k:]
    second = _ellipsize(d, second, reg, W - 8)
    y1, y2 = CENTER_Y - 10, CENTER_Y + 10
    if orp < k:
        x = 4
        pre, ch, post = first[:orp], first[orp], first[orp + 1:]
        _draw_orp_parts(d, theme, pre, ch, post, x, y1, reg, bold)
        d.text((4, y2), second, font=reg, fill=INK, anchor="lm")
    else:
        d.text((4, y1), first, font=reg, fill=INK, anchor="lm")
        d.text((4, y2), second, font=reg, fill=INK, anchor="lm")
    return img


def _fit_chunk_orp(d, words, theme, word_size=None):
    """Largest size where every word's ORP pieces fit on one line, or None."""
    sizes = _WORD_SIZE_TIERS.get(word_size, _WORD_SIZE_TIERS["medium"])
    for size in sizes:
        reg = themes.font(theme, size)
        bold = themes.font(theme, size, bold=True)
        ch_fnt = reg if theme.pivot_style == "box" else bold
        space_w = d.textlength(" ", font=reg)
        parts = []
        total = 0.0
        for w in words:
            orp = rsvp.orp_index(w)
            pre, ch, post = w[:orp], w[orp], w[orp + 1:]
            total += (d.textlength(pre, font=reg) + d.textlength(ch, font=ch_fnt)
                      + d.textlength(post, font=reg))
            parts.append((pre, ch, post))
        total += space_w * (len(words) - 1)
        if total <= W - 8:
            return size, parts
    return None


def chunk_frame(words, theme, word_size=None):
    """2+ words at once when wpm outpaces the frame rate."""
    img, d = _canvas()
    fitted = _fit_chunk_orp(d, words, theme, word_size)
    if fitted is None:
        text = " ".join(words)
        sizes = _WORD_SIZE_TIERS.get(word_size, _WORD_SIZE_TIERS["medium"])
        fnt = themes.font(theme, sizes[-1])
        for size in sizes:
            fnt = themes.font(theme, size)
            if d.textlength(text, font=fnt) <= W - 8:
                break
        text = _ellipsize(d, text, fnt, W - 8)
        x = (W - d.textlength(text, font=fnt)) / 2
        d.text((x, CENTER_Y), text, font=fnt, fill=INK, anchor="lm")
    else:
        size, parts = fitted
        reg = themes.font(theme, size)
        bold = themes.font(theme, size, bold=True)
        space_w = d.textlength(" ", font=reg)
        ch_fnt = reg if theme.pivot_style == "box" else bold
        total_w = sum(d.textlength(pre, font=reg) + d.textlength(ch, font=ch_fnt)
                      + d.textlength(post, font=reg) for pre, ch, post in parts)
        total_w += space_w * (len(parts) - 1)
        x = (W - total_w) / 2
        for pre, ch, post in parts:
            x = _draw_orp_parts(d, theme, pre, ch, post, x, CENTER_Y, reg, bold)
            x += space_w
    return _finalize(img)


# ---- list / info / paused --------------------------------------------

def list_frame(header, rows, sel, top, rows_visible=4, footer=None, note=None,
               empty_lines=None):
    """Generic scrollable list used by every list-shaped screen."""
    img, d = _canvas()
    _header_band(d, header, note)
    t = _default_theme()
    row_f = themes.font(t, 10)
    row_h = 12
    y0 = 14

    if not rows:
        lines = empty_lines or ("No items.",)
        f = themes.font(t, 10)
        y = 22
        for line in lines[:3]:
            d.text((3, y), _ellipsize(d, line, f, W - 6), font=f, fill=INK)
            y += 12
        return _finalize(img)

    for i in range(top, min(top + rows_visible, len(rows))):
        y = y0 + (i - top) * row_h
        label = _ellipsize(d, rows[i], row_f, W - 16)
        if i == sel:
            d.rectangle([0, y, W - 1, y + row_h - 1], fill=INK)
            d.text((3, y + 1), label, font=row_f, fill=BG)
        else:
            d.text((3, y + 1), label, font=row_f, fill=INK)

    # scroll indicators (filled triangles at top-right / bottom-right)
    if top > 0:
        d.polygon([(W - 6, y0 + 2), (W - 3, y0 + 6), (W - 9, y0 + 6)], fill=INK)
    if top + rows_visible < len(rows):
        yb = y0 + rows_visible * row_h - 2
        d.polygon([(W - 6, yb), (W - 3, yb - 4), (W - 9, yb - 4)], fill=INK)

    if footer:
        ff = themes.font(t, 9)
        d.text((3, H - 9), _ellipsize(d, footer, ff, W - 6), font=ff, fill=INK)
    return _finalize(img)


def paused_frame(title, words, idx, sentence_start, wpm, progress, theme,
                 flash=None):
    """Paused context: current sentence with current word bold+underlined."""
    img, d = _canvas()
    right = "%d%%  %d wpm" % (round(progress * 100), wpm)
    _header_band(d, title, note=right)

    # Current sentence only: from sentence_start to next sentence end (at/after idx).
    end = len(words)
    for i in range(max(sentence_start, idx), len(words)):
        tok = words[i]
        if rsvp._SENT_END_CHARS.intersection(tok[-2:]):
            end = i + 1
            break
    sentence = words[sentence_start:end]
    if not sentence:
        if flash:
            remaining_overlay(img, flash, theme)
        return _finalize(img)

    reg = themes.font(theme, 10)
    bold = themes.font(theme, 10, bold=True)
    max_w = W - 6
    y0, line_h = 15, 11
    max_lines = max(1, (H - 2 - y0) // line_h)

    # Build wrapped lines of (token, is_current) pairs.
    lines, cur, cur_w = [], [], 0.0
    for i, tok in enumerate(sentence):
        abs_i = sentence_start + i
        fnt = bold if abs_i == idx else reg
        tw = d.textlength(tok + " ", font=fnt)
        if cur and cur_w + tw > max_w:
            lines.append(cur)
            cur, cur_w = [], 0.0
            if len(lines) == max_lines:
                break
        cur.append((tok, abs_i == idx))
        cur_w += tw
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # Ellipsize last line if we ran out of room mid-sentence.
    used = sum(len(ln) for ln in lines)
    if used < len(sentence) and lines:
        # replace last token cluster with ellipsized plain text
        plain = " ".join(t for t, _ in lines[-1])
        lines[-1] = [(_ellipsize(d, plain + " \u2026", reg, max_w), False)]

    y = y0
    for ln in lines:
        x = 3
        for tok, is_cur in ln:
            fnt = bold if is_cur else reg
            d.text((x, y), tok, font=fnt, fill=INK)
            if is_cur:
                wlen = d.textlength(tok, font=fnt)
                d.line([(x, y + 10), (x + wlen, y + 10)], fill=INK)
            x += d.textlength(tok + " ", font=fnt)
        y += line_h
    if flash:
        remaining_overlay(img, flash, theme)
    return _finalize(img)


def info_frame(title, ext, position, total_words, wpm, time_read_secs):
    """Read-only book info stack under a list-style header."""
    img, d = _canvas()
    _header_band(d, "BOOK")
    t = _default_theme()
    title_f = themes.font(t, 11, bold=True)
    body = themes.font(t, 10)
    y = 14
    for line in _wrap(d, title, title_f, W - 6, 2):
        d.text((3, y), line, font=title_f, fill=INK)
        y += 12
    facts = [
        "Format: %s" % ((ext or "").lstrip(".").upper() or "TXT"),
    ]
    if total_words:
        facts.append("Length: %s words" % fmt_words(total_words))
        pos = position or 0
        pct = int(100 * pos / total_words) if total_words else 0
        left = ""
        if wpm and pos < total_words:
            left = "  ·  %s left" % fmt_minutes((total_words - pos) / max(1, wpm))
        facts.append("Progress: %d%%%s" % (pct, left))
    facts.append("Time read: %s" % fmt_minutes(time_read_secs / 60.0))
    for fact in facts:
        d.text((3, y), _ellipsize(d, fact, body, W - 6), font=body, fill=INK)
        y += 12
        if y > H - 10:
            break
    return _finalize(img)


# ---- simple screens --------------------------------------------------

def message_frame(lines, hint=None, big=None):
    """Centred lines; ``big`` (optional) is drawn larger above them."""
    img, d = _canvas()
    t = _default_theme()
    f = themes.font(t, 11, bold=True)
    n = len(lines) + (1 if big else 0)
    y = (H - n * 14) // 2 - (6 if hint else 0)
    if big:
        bf = themes.font(t, 16, bold=True)
        _center(d, big, bf, y - 2)
        y += 18
    for line in lines:
        _center(d, _ellipsize(d, line, f, W - 8), f, y)
        y += 14
    if hint:
        _center(d, hint, themes.font(t, 9), H - 12)
    return _finalize(img)


def confirm_frame(text, yes_hint, no_hint):
    """Generic yes/no confirm dialog."""
    hint = "%s    %s" % (yes_hint, no_hint)
    return message_frame([text], hint=hint)


def end_frame(title):
    img, d = _canvas()
    t = _default_theme()
    _center(d, "The End", themes.font(t, 16, bold=True), 18)
    tf = themes.font(t, 11)
    _center(d, _ellipsize(d, title, tf, W - 8), tf, 38)
    _center(d, "any key: library", themes.font(t, 9), H - 12)
    return _finalize(img)


def splash():
    """Boot splash: 'Rapid' with ORP pivot + ticks, 'Reader' below."""
    img, d = _canvas()
    th = _default_theme()
    word = "Rapid"
    orp = rsvp.orp_index(word)
    pre, ch, post = word[:orp], word[orp], word[orp + 1:]
    bf = themes.font(th, 18, bold=True)
    rf = themes.font(th, 18)
    # Measure with bold for pivot (ticks style).
    total = (d.textlength(pre, font=rf) + d.textlength(ch, font=bf)
             + d.textlength(post, font=rf))
    x = (W - total) / 2
    y = CENTER_Y - 8
    if pre:
        d.text((x, y), pre, font=rf, fill=INK, anchor="lm")
        x += d.textlength(pre, font=rf)
    w_ch = d.textlength(ch, font=bf)
    d.text((x, y), ch, font=bf, fill=INK, anchor="lm")
    _draw_ticks(d, x + w_ch / 2)
    x += w_ch
    if post:
        d.text((x, y), post, font=rf, fill=INK, anchor="lm")
    _center(d, "Reader", themes.font(th, 14), CENTER_Y + 14)
    _center(d, "starting\u2026", themes.font(th, 9), H - 12)
    return _finalize(img)
