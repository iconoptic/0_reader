"""Best-effort LaTeX-to-Unicode conversion for math-heavy books.

Books sourced from PDFs/arXiv of math or physics texts often carry literal
LaTeX markup that the source extraction couldn't typeset -- inline math like
``$\\alpha^2 + \\beta_i$`` or bare commands like ``\\frac{a}{b}``. Flashing
that markup literally, one RSVP "word" at a time, is unreadable. This module
turns common LaTeX into the closest plain-Unicode reading before the text is
tokenized, so every screen (RSVP, paused sentence view, chapter titles) just
sees ordinary words.

This is a text substitution, not a typesetting engine -- there is no notion
of stacked fractions or multi-line layout on a 128x64 1-bit panel. Anything
not specifically handled degrades to a readable plain-text approximation
(command names lose their backslash, unknown wrapped content is unwrapped)
rather than vanishing or showing raw markup, in the same best-effort spirit
as the chapter-heading heuristics in books.py.
"""

import re

# --- symbol tables ---------------------------------------------------------

_GREEK = {
    "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3", "delta": "\u03b4",
    "epsilon": "\u03b5", "varepsilon": "\u03b5", "zeta": "\u03b6",
    "eta": "\u03b7", "theta": "\u03b8", "vartheta": "\u03d1",
    "iota": "\u03b9", "kappa": "\u03ba", "lambda": "\u03bb", "mu": "\u03bc",
    "nu": "\u03bd", "xi": "\u03be", "pi": "\u03c0", "varpi": "\u03d6",
    "rho": "\u03c1", "varrho": "\u03f1", "sigma": "\u03c3",
    "varsigma": "\u03c2", "tau": "\u03c4", "upsilon": "\u03c5",
    "phi": "\u03c6", "varphi": "\u03d5", "chi": "\u03c7", "psi": "\u03c8",
    "omega": "\u03c9",
    "Gamma": "\u0393", "Delta": "\u0394", "Theta": "\u0398",
    "Lambda": "\u039b", "Xi": "\u039e", "Pi": "\u03a0", "Sigma": "\u03a3",
    "Upsilon": "\u03a5", "Phi": "\u03a6", "Psi": "\u03a8", "Omega": "\u03a9",
}

_SYMBOLS = {
    "times": "\u00d7", "div": "\u00f7", "cdot": "\u22c5", "pm": "\u00b1",
    "mp": "\u2213", "leq": "\u2264", "le": "\u2264", "geq": "\u2265",
    "ge": "\u2265", "neq": "\u2260", "ne": "\u2260", "approx": "\u2248",
    "sim": "\u223c", "simeq": "\u2243", "cong": "\u2245", "equiv": "\u2261",
    "propto": "\u221d", "infty": "\u221e", "partial": "\u2202",
    "nabla": "\u2207", "forall": "\u2200", "exists": "\u2203",
    "nexists": "\u2204", "emptyset": "\u2205", "varnothing": "\u2205",
    "in": "\u2208", "notin": "\u2209", "ni": "\u220b", "subset": "\u2282",
    "subseteq": "\u2286", "supset": "\u2283", "supseteq": "\u2287",
    "cup": "\u222a", "cap": "\u2229", "setminus": "\u2216",
    "wedge": "\u2227", "land": "\u2227", "vee": "\u2228", "lor": "\u2228",
    "neg": "\u00ac", "lnot": "\u00ac",
    "rightarrow": "\u2192", "to": "\u2192", "leftarrow": "\u2190",
    "leftrightarrow": "\u2194", "Rightarrow": "\u21d2",
    "Leftarrow": "\u21d0", "Leftrightarrow": "\u21d4", "mapsto": "\u21a6",
    "longrightarrow": "\u27f6", "longleftarrow": "\u27f5",
    "sum": "\u2211", "prod": "\u220f", "coprod": "\u2210", "int": "\u222b",
    "iint": "\u222c", "iiint": "\u222d", "oint": "\u222e",
    "cdots": "\u22ef", "ldots": "\u2026", "dots": "\u2026",
    "vdots": "\u22ee", "ddots": "\u22f1",
    "angle": "\u2220", "perp": "\u22a5", "parallel": "\u2225",
    "aleph": "\u2135", "hbar": "\u210f", "ell": "\u2113", "Re": "\u211c",
    "Im": "\u2111", "top": "\u22a4", "bot": "\u22a5", "star": "\u22c6",
    "ast": "\u2217", "circ": "\u2218", "oplus": "\u2295",
    "ominus": "\u2296", "otimes": "\u2297", "oslash": "\u2298",
    "dagger": "\u2020", "ddagger": "\u2021", "prime": "\u2032",
    "backslash": "\\",
}

_ALL_COMMANDS = {}
_ALL_COMMANDS.update(_GREEK)
_ALL_COMMANDS.update(_SYMBOLS)
_NAMED_RE = re.compile(
    r"\\(" + "|".join(sorted((re.escape(k) for k in _ALL_COMMANDS),
                              key=len, reverse=True)) + r")(?![a-zA-Z])")

_SUPERSCRIPT = {
    "0": "\u2070", "1": "\u00b9", "2": "\u00b2", "3": "\u00b3",
    "4": "\u2074", "5": "\u2075", "6": "\u2076", "7": "\u2077",
    "8": "\u2078", "9": "\u2079", "+": "\u207a", "-": "\u207b",
    "=": "\u207c", "(": "\u207d", ")": "\u207e",
    "a": "\u1d43", "b": "\u1d47", "c": "\u1d9c", "d": "\u1d48",
    "e": "\u1d49", "f": "\u1da0", "g": "\u1d4d", "h": "\u02b0",
    "i": "\u2071", "j": "\u02b2", "k": "\u1d4f", "l": "\u02e1",
    "m": "\u1d50", "n": "\u207f", "o": "\u1d52", "p": "\u1d56",
    "r": "\u02b3", "s": "\u02e2", "t": "\u1d57", "u": "\u1d58",
    "v": "\u1d5b", "w": "\u02b7", "x": "\u02e3", "y": "\u02b8",
    "z": "\u1dbb",
}
_SUBSCRIPT = {
    "0": "\u2080", "1": "\u2081", "2": "\u2082", "3": "\u2083",
    "4": "\u2084", "5": "\u2085", "6": "\u2086", "7": "\u2087",
    "8": "\u2088", "9": "\u2089", "+": "\u208a", "-": "\u208b",
    "=": "\u208c", "(": "\u208d", ")": "\u208e",
    "a": "\u2090", "e": "\u2091", "h": "\u2095", "i": "\u1d62",
    "j": "\u2c7c", "k": "\u2096", "l": "\u2097", "m": "\u2098",
    "n": "\u2099", "o": "\u2092", "p": "\u209a", "r": "\u1d63",
    "s": "\u209b", "t": "\u209c", "u": "\u1d64", "v": "\u1d65",
    "x": "\u2093",
}

_VULGAR_FRACTIONS = {
    ("1", "2"): "\u00bd", ("1", "3"): "\u2153", ("2", "3"): "\u2154",
    ("1", "4"): "\u00bc", ("3", "4"): "\u00be", ("1", "5"): "\u2155",
    ("2", "5"): "\u2156", ("3", "5"): "\u2157", ("4", "5"): "\u2158",
    ("1", "6"): "\u2159", ("5", "6"): "\u215a", ("1", "7"): "\u2150",
    ("1", "8"): "\u215b", ("3", "8"): "\u215c", ("5", "8"): "\u215d",
    ("7", "8"): "\u215e", ("1", "9"): "\u2151", ("1", "10"): "\u2152",
}

_BLACKBOARD = {
    "R": "\u211d", "N": "\u2115", "Z": "\u2124", "Q": "\u211a",
    "C": "\u2102", "P": "\u2119", "H": "\u210d",
}

_ACCENTS = {
    "hat": "\u0302", "vec": "\u20d7", "bar": "\u0304", "dot": "\u0307",
    "ddot": "\u0308", "tilde": "\u0303", "overline": "\u0305",
    "underline": "\u0332",
}

# Wrapped commands whose content is just unwrapped in place.
_TEXTISH = ("text", "mathrm", "mathnormal", "mathsf", "mathtt", "mathcal",
            "mathfrak", "operatorname", "emph", "textbf", "textit",
            "textsc", "footnote", "mbox", "hbox", "boldsymbol")

# Commands dropped entirely, together with their single brace argument.
_DROP_NOARG = ("nonumber", "notag", "noindent", "appendix", "par")
_DROP_ONEARG = ("label", "ref", "eqref", "cite", "citep", "citet",
                "citeauthor", "citeyear", "index", "hspace", "vspace",
                "pagebreak", "newpage", "clearpage", "includegraphics")

_ENV_TAG_RE = re.compile(r"\\(?:begin|end)\{[a-zA-Z*]+\}")
_ITEM_RE = re.compile(r"\\item\b\s*")
_LEFT_RIGHT_RE = re.compile(r"\\(?:left|right)(?![a-zA-Z])")
_ACCENT_RE = re.compile(r"\\(" + "|".join(_ACCENTS) + r")\b")
_TEXTISH_RE = re.compile(r"\\(?:" + "|".join(_TEXTISH) + r")\*?\b")
_MATHBB_RE = re.compile(r"\\mathbb\b")
_DROP_NOARG_RE = re.compile(r"\\(?:" + "|".join(_DROP_NOARG) + r")\b\s*")
_DROP_ONEARG_RE = re.compile(
    r"\\(?:" + "|".join(_DROP_ONEARG) + r")\*?\s*(?:\[[^\]]*\])?")
_ESCAPED_RE = re.compile(r"\\([$%&#])")
_UNKNOWN_CMD_RE = re.compile(r"\\([a-zA-Z]+)")
_STRAY_BRACE_RE = re.compile(r"[{}]")

_DISPLAY_DOLLAR_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_DISPLAY_BRACKET_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
_INLINE_PAREN_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
_INLINE_DOLLAR_RE = re.compile(r"\$([^$\n]+?)\$")
_WS_RE = re.compile(r"[ \t]+")

# Escaped braces (``\{`` / ``\}``) are meant to render as literal, visible
# braces (set notation etc.) -- protect them with sentinels before grouping
# braces are stripped, and restore them only once the whole document has
# been converted.
_ESC_LB, _ESC_RB = "\x00LB\x00", "\x00RB\x00"


def _extract_brace(s, i):
    """``s[i]`` must be ``'{'``. Returns (content, index just past the
    matching ``'}'``). Unbalanced input consumes to the end of the string."""
    depth = 0
    j = i
    n = len(s)
    while j < n:
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], n


def _script(mapping, s):
    return "".join(mapping.get(ch, ch) for ch in s)


def _format_frac(num, den):
    v = _VULGAR_FRACTIONS.get((num, den))
    if v:
        return v
    if len(num) > 1 and not num.isalnum():
        num = "(%s)" % num
    if len(den) > 1 and not den.isalnum():
        den = "(%s)" % den
    return "%s\u2044%s" % (num, den)


def _frac(s):
    pat = re.compile(r"\\(?:d|t)?frac\b")
    out, i = [], 0
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        j = m.end()
        while j < len(s) and s[j].isspace():
            j += 1
        if j >= len(s) or s[j] != "{":
            i = m.end()
            continue
        num, j = _extract_brace(s, j)
        while j < len(s) and s[j].isspace():
            j += 1
        if j >= len(s) or s[j] != "{":
            out.append(_convert_commands(num))
            i = j
            continue
        den, j = _extract_brace(s, j)
        out.append(_format_frac(_convert_commands(num), _convert_commands(den)))
        i = j
    return "".join(out)


def _sqrt(s):
    pat = re.compile(r"\\sqrt\b")
    out, i = [], 0
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        j = m.end()
        index = None
        if j < len(s) and s[j] == "[":
            k = s.find("]", j)
            if k != -1:
                index = s[j + 1:k]
                j = k + 1
        while j < len(s) and s[j].isspace():
            j += 1
        if j >= len(s) or s[j] != "{":
            out.append("\u221a")
            i = j
            continue
        arg, j = _extract_brace(s, j)
        arg = _convert_commands(arg)
        prefix = _script(_SUPERSCRIPT, index) if index else ""
        if len(arg) > 1:
            arg = "(%s)" % arg
        out.append("%s\u221a%s" % (prefix, arg))
        i = j
    return "".join(out)


def _accents(s):
    out, i = [], 0
    while True:
        m = _ACCENT_RE.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        j = m.end()
        while j < len(s) and s[j].isspace():
            j += 1
        mark = _ACCENTS[m.group(1)]
        if j < len(s) and s[j] == "{":
            arg, j = _extract_brace(s, j)
            arg = _convert_commands(arg)
        elif j < len(s):
            arg, j = s[j], j + 1
        else:
            arg = ""
        out.append("".join(ch + mark for ch in arg) if arg else mark)
        i = j
    return "".join(out)


def _scripts(s, trigger, mapping):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != trigger:
            out.append(c)
            i += 1
            continue
        j = i + 1
        if j < n and s[j] == "{":
            content, j = _extract_brace(s, j)
            content = _convert_commands(content)
        elif j < n and s[j] == "\\":
            k = j + 1
            while k < n and s[k].isalpha():
                k += 1
            content = _named_commands(s[j:k])
            j = k
        elif j < n:
            content, j = s[j], j + 1
        else:
            content = ""
        out.append(_script(mapping, content))
        i = j
    return "".join(out)


def _superscript_sub(s):
    return _scripts(s, "^", _SUPERSCRIPT)


def _subscript_sub(s):
    return _scripts(s, "_", _SUBSCRIPT)


def _named_commands(s):
    return _NAMED_RE.sub(lambda m: _ALL_COMMANDS[m.group(1)], s)


def _unwrap_one_arg(pat, s, transform=None):
    out, i = [], 0
    while True:
        m = pat.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        j = m.end()
        while j < len(s) and s[j].isspace():
            j += 1
        if j < len(s) and s[j] == "{":
            arg, j = _extract_brace(s, j)
            out.append(transform(arg) if transform else _convert_commands(arg))
        i = j
    return "".join(out)


def _unwrap_textish(s):
    return _unwrap_one_arg(_TEXTISH_RE, s)


def _mathbb(s):
    return _unwrap_one_arg(
        _MATHBB_RE, s, lambda arg: _BLACKBOARD.get(arg, _convert_commands(arg)))


def _drop_metadata(s):
    s = _DROP_NOARG_RE.sub("", s)
    out, i = [], 0
    while True:
        m = _DROP_ONEARG_RE.search(s, i)
        if not m:
            out.append(s[i:])
            break
        out.append(s[i:m.start()])
        j = m.end()
        if j < len(s) and s[j] == "{":
            _, j = _extract_brace(s, j)
        i = j
    return "".join(out)


def _escape_specials(s):
    return _ESCAPED_RE.sub(lambda m: m.group(1), s)


def _protect_escaped_braces(s):
    return s.replace("\\{", _ESC_LB).replace("\\}", _ESC_RB)


def _convert_commands(s):
    s = _protect_escaped_braces(s)
    s = s.replace("~", " ")
    s = _ENV_TAG_RE.sub("", s)
    s = _ITEM_RE.sub("- ", s)
    s = _LEFT_RIGHT_RE.sub("", s)
    s = _frac(s)
    s = _sqrt(s)
    s = _accents(s)
    s = _superscript_sub(s)
    s = _subscript_sub(s)
    s = _named_commands(s)
    s = _unwrap_textish(s)
    s = _mathbb(s)
    s = _drop_metadata(s)
    s = _escape_specials(s)
    s = _UNKNOWN_CMD_RE.sub(lambda m: m.group(1), s)
    s = _STRAY_BRACE_RE.sub("", s)
    return s


def _inline_dollar_repl(m):
    content = m.group(1)
    if content[:1].isdigit():
        return m.group(0)  # looks like currency ("$5"); leave untouched
    return _convert_commands(content)


def convert(text):
    """Best-effort LaTeX -> Unicode conversion of ``text``.

    Plain prose passes through untouched. Display math (``$$..$$``,
    ``\\[..\\]``) and ``\\(..\\)`` are always converted; inline ``$..$`` is
    only converted when the content doesn't look like a currency amount
    (starts with a digit), so "$5 and $10" is left alone. Bare commands and
    bare ``^``/``_`` scripts outside any delimiter (common when upstream
    extraction dropped the ``$`` signs) are converted too, but only once the
    document proves it actually contains LaTeX -- if there is no backslash
    or ``$`` anywhere in ``text``, it is returned unchanged so code-like
    snake_case identifiers or a stray caret in an otherwise math-free book
    are never mistaken for scripts.
    """
    if "\\" not in text and "$" not in text:
        return text
    text = text.replace("\\\\", " ")
    text = _DISPLAY_DOLLAR_RE.sub(lambda m: _convert_commands(m.group(1)), text)
    text = _DISPLAY_BRACKET_RE.sub(lambda m: _convert_commands(m.group(1)), text)
    text = _INLINE_PAREN_RE.sub(lambda m: _convert_commands(m.group(1)), text)
    text = _INLINE_DOLLAR_RE.sub(_inline_dollar_repl, text)
    text = _convert_commands(text)
    text = _WS_RE.sub(" ", text)
    return text.replace(_ESC_LB, "{").replace(_ESC_RB, "}")
