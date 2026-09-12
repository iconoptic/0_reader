import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "txt_to_txt", os.path.join(ROOT, "tools", "txt_to_txt.py")
)
txt_to_txt = importlib.util.module_from_spec(_spec)
sys.modules["txt_to_txt"] = txt_to_txt
_spec.loader.exec_module(txt_to_txt)


# --- Pass 1: rejoin line-wrapped words -------------------------------------

def test_rejoins_line_wrap_hyphen():
    text, count = txt_to_txt.rejoin_wrapped_hyphens("word pro-\ncessing here")
    assert text == "word processing here"
    assert count == 1


def test_leaves_em_dash_before_blank_line():
    text = "she said,--\n\n“Hello!”"
    out, count = txt_to_txt.rejoin_wrapped_hyphens(text)
    assert out == text
    assert count == 0


def test_leaves_em_dash_before_capitalized_line():
    text = "thoughts--from far where I abide--\nIntend a pilgrimage"
    out, count = txt_to_txt.rejoin_wrapped_hyphens(text)
    assert out == text
    assert count == 0


# --- Pass 2: split explicit hyphenated compounds ---------------------------

def test_splits_hyphenated_compound():
    out, count = txt_to_txt.split_hyphenated_compounds("out-of-the-way")
    assert out == "out- of- the- way"
    assert count == 3
    assert out.split() == ["out-", "of-", "the-", "way"]


def test_splits_hyphenated_word_with_trailing_punct():
    out, _ = txt_to_txt.split_hyphenated_compounds("self-driving,")
    assert out == "self- driving,"


def test_leaves_em_dash_and_digit_ranges_alone():
    out, count = txt_to_txt.split_hyphenated_compounds("word--other 1914-1918")
    assert out == "word--other 1914-1918"
    assert count == 0


def test_hyphen_split_is_idempotent():
    once, _ = txt_to_txt.split_hyphenated_compounds("out-of-the-way")
    twice, count2 = txt_to_txt.split_hyphenated_compounds(once)
    assert twice == once
    assert count2 == 0


# --- Pass 3a: de-concatenate accidental run-together words -----------------

wordninja = txt_to_txt.wordninja


@pytest.mark.skipif(wordninja is None, reason="wordninja not installed")
def test_debind_concatenated_words():
    out, count = txt_to_txt.debind_concatenated_words(
        "a keyboardwarrior appeared", min_split_len=11
    )
    assert out == "a keyboard warrior appeared"
    assert count == 1


@pytest.mark.skipif(wordninja is None, reason="wordninja not installed")
def test_debind_leaves_real_single_words_alone():
    out, count = txt_to_txt.debind_concatenated_words(
        "the antidisestablishmentarianism debate", min_split_len=11
    )
    assert out == "the antidisestablishmentarianism debate"
    assert count == 0


@pytest.mark.skipif(wordninja is None, reason="wordninja not installed")
def test_debind_skips_capitalized_words():
    out, count = txt_to_txt.debind_concatenated_words(
        "DerekAnderson walked in", min_split_len=11
    )
    assert out == "DerekAnderson walked in"
    assert count == 0


# --- Pass 3b: chunk remaining long words at syllable boundaries ------------

pyphen = txt_to_txt.pyphen


@pytest.mark.skipif(pyphen is None, reason="pyphen not installed")
def test_chunks_long_word_at_syllable_boundaries():
    out, count = txt_to_txt.chunk_long_words(
        "antidisestablishmentarianism", min_split_len=11, chunk_len=6
    )
    assert count == 1
    pieces = out.split(" ")
    assert len(pieces) >= 2
    assert all(p.endswith("-") for p in pieces[:-1])
    assert "".join(p.rstrip("-") for p in pieces) == "antidisestablishmentarianism"


@pytest.mark.skipif(pyphen is None, reason="pyphen not installed")
def test_chunk_leaves_short_words_alone():
    out, count = txt_to_txt.chunk_long_words("the cat sat", min_split_len=11, chunk_len=6)
    assert out == "the cat sat"
    assert count == 0


# --- Full pipeline -----------------------------------------------------------

def test_pipeline_is_idempotent():
    text = (
        "word pro-\ncessing here, out-of-the-way keyboardwarrior and\n"
        "antidisestablishmentarianism debates--\nnever end.\n"
    )
    once, _ = txt_to_txt.process_text(text)
    twice, stats2 = txt_to_txt.process_text(once)
    assert twice == once
    assert stats2 == {
        "joins": 0, "hyphen_splits": 0, "concat_splits": 0, "chunk_splits": 0,
    }


# --- CLI / backup behavior --------------------------------------------------

def test_process_file_backs_up_and_rewrites(tmp_path):
    p = tmp_path / "book.txt"
    original = "word pro-\ncessing here.\n"
    p.write_text(original, encoding="utf-8")

    txt_to_txt.process_file(str(p))

    backup = tmp_path / "book.txt.orig"
    assert backup.read_text(encoding="utf-8") == original
    assert p.read_text(encoding="utf-8") == "word processing here.\n"


def test_second_run_does_not_clobber_backup(tmp_path):
    p = tmp_path / "book.txt"
    original = "word pro-\ncessing here.\n"
    p.write_text(original, encoding="utf-8")

    txt_to_txt.process_file(str(p))
    # Mutate the (already-fixed) file directly, bypassing the tool, to
    # prove a second tool run doesn't re-snapshot it over the real backup.
    p.write_text("something else entirely\n", encoding="utf-8")
    txt_to_txt.process_file(str(p))

    backup = tmp_path / "book.txt.orig"
    assert backup.read_text(encoding="utf-8") == original
