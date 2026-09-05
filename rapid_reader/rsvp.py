"""RSVP core: Optimal Recognition Point and per-word display timing."""

_STRIP = "\"'\u201c\u201d\u2018\u2019([{)]}.,;:!?\u2014-"

_SENT_END_CHARS = set(".!?")


def core_span(word):
    """Return (start, end) of the alphanumeric core inside the token."""
    start, end = 0, len(word)
    while start < end and word[start] in _STRIP:
        start += 1
    while end > start and word[end - 1] in _STRIP:
        end -= 1
    if start >= end:
        return 0, len(word)
    return start, end


def orp_index(word):
    """Index of the Optimal Recognition Point character within the token."""
    start, end = core_span(word)
    n = end - start
    if n <= 1:
        off = 0
    elif n <= 5:
        off = 1
    elif n <= 9:
        off = 2
    elif n <= 13:
        off = 3
    else:
        off = 4
    return start + off


def word_delay(word, wpm, is_para_end=False):
    """Seconds to show a word: longer words and clause ends linger."""
    base = 60.0 / wpm
    d = base
    start, end = core_span(word)
    if end - start >= 9:
        d += base * 0.4
    tail = word[end:] if end < len(word) else ""
    if any(c in tail for c in ".!?"):
        d += base * 1.5
    elif any(c in tail for c in ",;:\u2014"):
        d += base * 0.7
    if is_para_end:
        d += base * 1.0
    return d
