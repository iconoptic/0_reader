"""Book discovery, loading (.txt and .epub) and tokenization."""

import bisect
import html.parser
import os
import posixpath
import re
import urllib.parse
import zipfile

import config

EXTENSIONS = (".txt", ".epub")

_SENT_END = re.compile(r'[.!?]["\'\u201d\u2019)\]]*$')

# Marks the start of an HTML heading (h1-h6) so _tokenize can record it as a
# chapter start; stripped back out before the words are shown.
_CHAPTER_MARK = "\x00CH\x00"


class _HTMLText(html.parser.HTMLParser):
    _BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
              "li", "tr", "section", "blockquote"}
    _HEADING = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP = {"style", "script", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._HEADING:
            self.parts.append("\n\n" + _CHAPTER_MARK + " ")
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)

    def text(self):
        return "".join(self.parts)


def _html_to_text(markup):
    p = _HTMLText()
    try:
        p.feed(markup)
        p.close()
    except Exception:
        pass
    return p.text()


def _extract_epub(path):
    """Return (title, plain_text) from an EPUB using only the stdlib."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
        m = re.search(r'full-path="([^"]+)"', container)
        if not m:
            raise ValueError("bad epub: no rootfile")
        opf_path = m.group(1)
        opf = z.read(opf_path).decode("utf-8", "ignore")
        opf_dir = posixpath.dirname(opf_path)

        title = None
        tm = re.search(r"<dc:title[^>]*>([^<]+)</dc:title>", opf)
        if tm:
            title = tm.group(1).strip()

        manifest = {}
        for tag in re.finditer(r"<item\b[^>]*>", opf):
            t = tag.group(0)
            mid = re.search(r'\bid="([^"]+)"', t)
            href = re.search(r'\bhref="([^"]+)"', t)
            mtype = re.search(r'\bmedia-type="([^"]+)"', t)
            if mid and href and mtype and "html" in mtype.group(1):
                manifest[mid.group(1)] = href.group(1)

        chunks = []
        for idref in re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf):
            href = manifest.get(idref)
            if not href:
                continue
            name = posixpath.normpath(
                posixpath.join(opf_dir, urllib.parse.unquote(href)))
            if name in names:
                markup = z.read(name).decode("utf-8", "ignore")
                chunks.append(_html_to_text(markup))
        return title, "\n\n".join(chunks)



# --- chapter heading heuristics -------------------------------------------
#
# Two independent signals are used, either of which marks a paragraph as a
# chapter start:
#  1. For epubs, an <h1>-<h6> tag (see _CHAPTER_MARK above) -- the most
#     reliable signal since it comes from real document structure.
#  2. For plain text, a short standalone paragraph that looks like a
#     heading: "Chapter 12", "CHAPTER I. Down the Rabbit-Hole",
#     "Letter 1", or a bare roman numeral like "I. A SCANDAL IN BOHEMIA".
# This is a best-effort heuristic, not a guarantee -- books with unusual
# formatting (e.g. chapters titled only with running prose) simply won't
# get any chapter markers, and jump_chapter() degrades gracefully when
# chapter_starts is empty.
_HEADING_MAX_WORDS = 12
_SECTION_WORDS = {"chapter", "letter", "book", "part", "volume"}
_NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty",
}
_ROMAN_RE = re.compile(
    r"M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$", re.IGNORECASE)


def _is_roman(tok):
    return bool(tok) and bool(_ROMAN_RE.fullmatch(tok))


def _looks_like_chapter_heading(toks):
    """True for a short standalone paragraph such as 'CHAPTER I.',
    'Chapter 12', 'Letter 1', 'XIV' or 'I. A SCANDAL IN BOHEMIA'."""
    if not toks or len(toks) > _HEADING_MAX_WORDS:
        return False
    first = toks[0].strip(".:)]").lower()
    if first in _SECTION_WORDS:
        if len(toks) < 2:
            return False
        num = toks[1].strip(".:)]")
        return num.isdigit() or _is_roman(num) or num.lower() in _NUMBER_WORDS
    if not _is_roman(toks[0].strip(".:)]")):
        return False
    # A bare numeral is a heading only when it stands alone ("XIV"), is
    # punctuated like one ("I." / "I. A SCANDAL..."), or is followed by an
    # all-caps title. This keeps short first-person paragraphs ("I went
    # home.") from being mistaken for chapter "I".
    if len(toks) == 1 or toks[0][-1] in ".:":
        return True
    rest = " ".join(toks[1:])
    return rest.isupper()


def _tokenize(text):
    """Split text into words plus sentence-start, paragraph and chapter
    metadata.

    Returns (words, sentence_starts, para_ends, chapter_starts,
    chapter_titles) where para_ends is a set of word indexes that close a
    paragraph, chapter_starts is a sorted list of word indexes where a
    chapter/section heading was detected, and chapter_titles is a parallel
    list of heading strings (same length/order as chapter_starts).
    """
    words = []
    sentence_starts = [0]
    para_ends = set()
    chapter_starts = []
    chapter_titles = []
    # If the source has real heading markup (epub h1-h6), trust that signal
    # alone -- applying the plain-text heuristic too would also flag short
    # table-of-contents list items (e.g. "<li>Chapter 1. Loomings.</li>") as
    # false chapter starts.
    has_marks = _CHAPTER_MARK in text
    for para in re.split(r"\n\s*\n", text):
        toks = para.split()
        if not toks:
            continue
        is_chapter = False
        if toks[0] == _CHAPTER_MARK:
            is_chapter = True
            toks = toks[1:]
            if not toks:
                continue
        elif not has_marks and _looks_like_chapter_heading(toks):
            is_chapter = True
        if words:
            sentence_starts.append(len(words))
        if is_chapter:
            chapter_starts.append(len(words))
            # Join heading tokens after the sentinel is removed so titles
            # never include _CHAPTER_MARK.
            chapter_titles.append(" ".join(toks))
        for tok in toks:
            words.append(tok)
            if _SENT_END.search(tok):
                sentence_starts.append(len(words))
        para_ends.add(len(words) - 1)
    # drop trailing/duplicate starts; keep titles aligned with unique starts
    starts = sorted({s for s in sentence_starts if s < len(words)})
    by_start = {}
    for c, title in zip(chapter_starts, chapter_titles):
        if c < len(words) and c not in by_start:
            by_start[c] = title
    chapters = sorted(by_start)
    titles = [by_start[c] for c in chapters]
    return words, starts, para_ends, chapters, titles


class Book:
    def __init__(self, path, title, words, sentence_starts, para_ends,
                 chapter_starts=(), chapter_titles=()):
        self.path = path
        self.title = title
        self.words = words
        self.sentence_starts = sentence_starts
        self.para_ends = para_ends
        self.chapter_starts = list(chapter_starts)
        self.chapter_titles = list(chapter_titles)

    def chapter_title(self, idx):
        """Title of the chapter containing word index `idx`, or None if this
        book has no detected chapters."""
        if not self.chapter_starts:
            return None
        i = bisect.bisect_right(self.chapter_starts, idx) - 1
        if i < 0:
            return None
        return self.chapter_titles[i]

    @classmethod
    def load(cls, path):
        stem = os.path.splitext(os.path.basename(path))[0]
        if path.lower().endswith(".epub"):
            title, text = _extract_epub(path)
            title = title or stem
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            title = stem
        words, starts, para_ends, chapters, titles = _tokenize(text)
        return cls(path, title, words, starts, para_ends, chapters, titles)


def sort_by_recency(library, last_opened):
    """library: list of (title, path), as returned by scan_library().
    last_opened: {path: epoch_seconds, ...}. Returns a new list: books with
    a last_opened timestamp first (most recent first), then never-opened
    books after them sorted by title (case-insensitive)."""
    def key(item):
        title, path = item
        t = last_opened.get(path)
        return (0, -t) if t else (1, title.lower())
    return sorted(library, key=key)


def scan_library(directory=None):
    """Return sorted list of (title, path) for supported files."""
    directory = directory or config.BOOKS_DIR
    out = []
    try:
        for name in sorted(os.listdir(directory), key=str.lower):
            if name.lower().endswith(EXTENSIONS) and not name.startswith("."):
                out.append((os.path.splitext(name)[0],
                            os.path.join(directory, name)))
    except FileNotFoundError:
        pass
    return out
