import io
import os
import zipfile

import pytest

import books
import config


# ---- tokenizer ---------------------------------------------------------

def test_tokenize_words_sentences_paragraphs():
    text = "Hello there. How are you?\n\nFine, thanks!"
    words, starts, para_ends, chapters, titles = books._tokenize(text)
    assert words == ["Hello", "there.", "How", "are", "you?", "Fine,", "thanks!"]
    # sentence starts: beginning, after "there.", paragraph start (after "you?")
    assert starts == [0, 2, 5]
    assert para_ends == {4, 6}
    assert chapters == []
    assert titles == []


def test_tokenize_sentence_end_with_closing_quote():
    words, starts, _, _, _ = books._tokenize('"Go away!" she said. Then silence.')
    assert words[1] == 'away!"'
    assert 2 in starts and 4 in starts


def test_tokenize_ignores_blank_paragraphs_and_no_trailing_start():
    words, starts, para_ends, _, _ = books._tokenize("\n\n  \n\nOne two.\n\n\n\n")
    assert words == ["One", "two."]
    assert starts == [0]           # the start after "two." would be == len(words)
    assert para_ends == {1}


def test_tokenize_empty():
    assert books._tokenize("") == ([], [], set(), [], [])


# ---- chapter detection -------------------------------------------------

@pytest.mark.parametrize("heading", [
    "CHAPTER I.",
    "Chapter 12",
    "Chapter Twelve",
    "Letter 1",
    "BOOK III",
    "I. A SCANDAL IN BOHEMIA",
    "XIV.",
])
def test_heading_heuristic_positive(heading):
    assert books._looks_like_chapter_heading(heading.split())


@pytest.mark.parametrize("not_heading", [
    "Chapter",                                    # section word with no number
    "Chapter the first of many things to come in this long book indeed ok",
    "I went to the shop.",                        # 'I' as a pronoun sentence
    "I did, and so did Mr. Darcy",
    "It was the best of times.",
    "Ivan said hello.",                           # roman-looking but not roman
    "",
])
def test_heading_heuristic_negative(not_heading):
    assert not books._looks_like_chapter_heading(not_heading.split())


def test_heading_heuristic_pronoun_I_alone_is_a_heading_edge_case():
    # A lone "I." paragraph is indistinguishable from a roman numeral; the
    # heuristic accepts it, which is the documented trade-off.
    assert books._looks_like_chapter_heading(["I."])
    assert books._looks_like_chapter_heading(["I"])
    assert books._looks_like_chapter_heading("II. THE RED-HEADED LEAGUE".split())


def test_tokenize_plain_text_chapters():
    text = ("Title of Book\n\nCHAPTER I.\n\nIt begins. Really.\n\n"
            "CHAPTER II.\n\nIt continues.\n\nThe end.")
    words, starts, para_ends, chapters, titles = books._tokenize(text)
    assert words[chapters[0]] == "CHAPTER"
    assert words[chapters[1]] == "CHAPTER"
    assert chapters == [3, 8]
    assert titles == ["CHAPTER I.", "CHAPTER II."]


def test_tokenize_epub_marks_take_precedence_over_heuristic():
    m = books._CHAPTER_MARK
    # a TOC list item that *looks* like a heading must not be flagged when
    # the document has real heading markup
    text = "Chapter 1. Loomings.\n\n" + m + " Chapter 1\n\nCall me Ishmael."
    words, _, _, chapters, titles = books._tokenize(text)
    assert m not in words
    assert chapters == [3]
    assert words[3:5] == ["Chapter", "1"]
    assert titles == ["Chapter 1"]
    assert m not in titles[0]


def test_tokenize_empty_heading_mark_is_dropped():
    m = books._CHAPTER_MARK
    words, _, _, chapters, titles = books._tokenize(m + "\n\nText here.")
    assert words == ["Text", "here."]
    assert chapters == []
    assert titles == []


# ---- html / epub -------------------------------------------------------

def test_html_to_text_blocks_headings_and_skips_style():
    html = ("<html><head><title>T</title><style>p{}</style></head><body>"
            "<h1>Chapter 1</h1><p>First para.</p><p>Second &amp; last.</p>"
            "<script>x()</script></body></html>")
    text = books._html_to_text(html)
    assert "T" not in text.split("\n")[0] or "Chapter" in text  # title skipped
    assert "p{}" not in text and "x()" not in text
    assert books._CHAPTER_MARK in text
    assert "Second & last." in text
    words, _, _, chapters, titles = books._tokenize(text)
    assert words == ["Chapter", "1", "First", "para.", "Second", "&", "last."]
    assert chapters == [0]
    assert titles == ["Chapter 1"]
    assert books._CHAPTER_MARK not in titles[0]


def _make_epub(path, title="Test Book", chapters=2, opf_dir="OEBPS"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container><rootfiles>'
                   '<rootfile full-path="%s/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>' % opf_dir)
        items = "".join(
            '<item id="c%d" href="text/ch%%20%d.xhtml" media-type="application/xhtml+xml"/>' % (i, i)
            for i in range(chapters))
        items += '<item id="css" href="style.css" media-type="text/css"/>'
        spine = "".join('<itemref idref="c%d"/>' % i for i in range(chapters))
        z.writestr("%s/content.opf" % opf_dir,
                   '<package xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   '<metadata><dc:title>%s</dc:title></metadata>'
                   '<manifest>%s</manifest><spine>%s</spine></package>' % (title, items, spine))
        for i in range(chapters):
            z.writestr("%s/text/ch %d.xhtml" % (opf_dir, i),
                       "<html><body><h2>Chapter %d</h2><p>Words of chapter %d.</p></body></html>" % (i + 1, i + 1))


def test_extract_epub_title_spine_order_and_url_decoding(tmp_path):
    p = tmp_path / "b.epub"
    _make_epub(p, chapters=3)
    title, text = books._extract_epub(str(p))
    assert title == "Test Book"
    assert text.index("Chapter 1") < text.index("Chapter 2") < text.index("Chapter 3")
    assert text.count(books._CHAPTER_MARK) == 3


def test_book_load_epub(tmp_path):
    p = tmp_path / "b.epub"
    _make_epub(p, chapters=2)
    b = books.Book.load(str(p))
    assert b.title == "Test Book"
    assert b.path == str(p)
    assert b.words[:2] == ["Chapter", "1"]
    assert len(b.chapter_starts) == 2
    assert b.words[b.chapter_starts[1]:b.chapter_starts[1] + 2] == ["Chapter", "2"]


def test_book_load_epub_falls_back_to_filename_title(tmp_path):
    p = tmp_path / "My Fallback.epub"
    _make_epub(p, title="", chapters=1)
    b = books.Book.load(str(p))
    assert b.title == "My Fallback"


def test_book_load_epub_without_rootfile_raises(tmp_path):
    p = tmp_path / "bad.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("META-INF/container.xml", "<container/>")
    with pytest.raises(ValueError):
        books.Book.load(str(p))


def test_book_load_txt_uses_filename_and_replaces_bad_bytes(tmp_path):
    p = tmp_path / "Some Title.txt"
    p.write_bytes(b"Good text. \xff\xfe Bad bytes.")
    b = books.Book.load(str(p))
    assert b.title == "Some Title"
    assert b.words[0] == "Good"
    assert b.sentence_starts[0] == 0


# ---- library scan -------------------------------------------------------

def test_scan_library_filters_sorts_and_titles(books_dir):
    for name in ["zeta.txt", "Alpha.epub", "notes.pdf", ".hidden.txt", "Beta.TXT"]:
        open(os.path.join(books_dir, name), "w").close()
    lib = books.scan_library()
    assert [t for t, _ in lib] == ["Alpha", "Beta", "zeta"]
    assert all(p.startswith(books_dir) for _, p in lib)


def test_scan_library_missing_dir(tmp_path):
    assert books.scan_library(str(tmp_path / "nope")) == []


def test_bundled_ebooks_load_and_have_chapters():
    """The sample library shipped in ebooks/ must tokenize and (for the
    Gutenberg titles) yield chapter markers."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lib = books.scan_library(os.path.join(here, "ebooks"))
    assert len(lib) >= 5
    for title, path in lib:
        b = books.Book.load(path)
        assert b.words, title
        assert b.sentence_starts[0] == 0
        assert all(0 <= c < len(b.words) for c in b.chapter_starts)
        assert len(b.chapter_titles) == len(b.chapter_starts)
        if title.startswith("Welcome"):
            assert b.chapter_starts == []
        else:
            assert len(b.chapter_starts) >= 5, title


def test_chapter_titles_and_chapter_title_lookup():
    text = ("Preamble words here.\n\nChapter 1\n\nBody of one. More.\n\n"
            "Chapter 2\n\nBody of two.")
    words, _, _, chapters, titles = books._tokenize(text)
    assert len(titles) == len(chapters) == 2
    assert titles == ["Chapter 1", "Chapter 2"]
    b = books.Book("x.txt", "x", words, [0], set(), chapters, titles)
    assert b.chapter_title(0) is None  # before first chapter
    assert b.chapter_title(chapters[0]) == "Chapter 1"
    assert b.chapter_title(chapters[0] + 1) == "Chapter 1"
    assert b.chapter_title(chapters[1]) == "Chapter 2"
    assert b.chapter_title(len(words) - 1) == "Chapter 2"
    empty = books.Book("y.txt", "y", ["hi"], [0], set())
    assert empty.chapter_title(0) is None


def test_chapter_titles_from_epub_headings(tmp_path):
    p = tmp_path / "b.epub"
    _make_epub(p, chapters=2)
    b = books.Book.load(str(p))
    assert len(b.chapter_titles) == len(b.chapter_starts) == 2
    assert b.chapter_titles == ["Chapter 1", "Chapter 2"]
    assert books._CHAPTER_MARK not in b.chapter_titles[0]
    assert b.chapter_title(b.chapter_starts[0]) == "Chapter 1"
    assert b.chapter_title(b.chapter_starts[1]) == "Chapter 2"


def test_sort_by_recency():
    lib = [
        ("Zebra", "/z.txt"),
        ("Alpha", "/a.txt"),
        ("Middle", "/m.txt"),
        ("Beta", "/b.txt"),
    ]
    last = {"/m.txt": 100.0, "/z.txt": 200.0, "/a.txt": 0.0}
    # 0.0 is falsy -> treated as never-opened; timestamped first by -t
    ordered = books.sort_by_recency(lib, last)
    assert [t for t, _ in ordered] == ["Zebra", "Middle", "Alpha", "Beta"]
