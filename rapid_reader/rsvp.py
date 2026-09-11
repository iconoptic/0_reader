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


DEFAULT_WEIGHTS = {"long": 0.4, "clause": 0.7, "sentence": 1.5, "para": 1.0}


def word_delay(word, wpm, is_para_end=False, weights=None):
    """Seconds to show a word. `weights` (optional) overrides any subset
    of DEFAULT_WEIGHTS's keys; unspecified keys keep their default."""
    w = DEFAULT_WEIGHTS if weights is None else {**DEFAULT_WEIGHTS, **weights}
    base = 60.0 / wpm
    d = base
    start, end = core_span(word)
    if end - start >= 9:
        d += base * w["long"]
    tail = word[end:] if end < len(word) else ""
    if any(c in tail for c in ".!?"):
        d += base * w["sentence"]
    elif any(c in tail for c in ",;:\u2014"):
        d += base * w["clause"]
    if is_para_end:
        d += base * w["para"]
    return d
