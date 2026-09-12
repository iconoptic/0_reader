#!/usr/bin/env python3
"""Reformat Rapid Reader .txt ebooks to be more RSVP-friendly, in place.

Fixes two things the tokenizer (rapid_reader/books.py) doesn't itself
handle, since it just splits on whitespace:

  1. PDF/OCR line-wrap hyphens: "...re-\\nsources..." -> "...resources..."
     (leaves the Gutenberg "--" em-dash convention alone).
  2. Long words that make for a single hard-to-parse RSVP flash:
       - explicit hyphenated compounds get a space after each hyphen
         ("out-of-the-way" -> "out- of- the- way")
       - accidental run-together words are de-concatenated (wordninja)
       - anything still long gets chunked at syllable boundaries (pyphen)

Requires: pip install -r tools/requirements.txt (wordninja, pyphen). If
either is missing, that sub-pass is skipped with a warning.

Usage:
  python3 tools/txt_to_txt.py                  # all ebooks/*.txt, in place
  python3 tools/txt_to_txt.py path.txt ...
  python3 tools/txt_to_txt.py --min-split-len 9 --chunk-len 5 path.txt
"""

from __future__ import annotations

import argparse
import os
import re
import sys

try:
    import wordninja
except ImportError:
    wordninja = None

try:
    import pyphen
except ImportError:
    pyphen = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_DIR = os.path.join(ROOT, "ebooks")

DEFAULT_MIN_SPLIT_LEN = 15
DEFAULT_CHUNK_LEN = 8
_MIN_PIECE = 3

_WRAP_HYPHEN = re.compile(r"(?<!-)([A-Za-z])-\n([a-z])")
_MID_HYPHEN = re.compile(r"(?<=[A-Za-z])-(?=[A-Za-z])")
_TOKEN = re.compile(r"\S+")
_CORE = re.compile(r"^(\W*)([A-Za-z]+)(\W*)$")

_pyphen_dic = pyphen.Pyphen(lang="en_US") if pyphen else None


def rejoin_wrapped_hyphens(text: str) -> tuple[str, int]:
    """Join a word hard-wrapped across a line break: "re-\\nsources" ->
    "resources". A single trailing hyphen followed by a lowercase letter on
    the next line is a wrap artifact; "--" (Gutenberg em-dash convention)
    and paragraph breaks never match, so they're left alone untouched."""
    count = 0

    def _join(m: re.Match) -> str:
        nonlocal count
        count += 1
        return m.group(1) + m.group(2)

    return _WRAP_HYPHEN.sub(_join, text), count


def split_hyphenated_compounds(text: str) -> tuple[str, int]:
    """"out-of-the-way" -> "out- of- the- way": a hyphen between two
    letters becomes its own RSVP token boundary. "--" and digit-only
    ranges never match, so they're left alone."""
    return _MID_HYPHEN.subn("- ", text)


def _split_core(word: str) -> tuple[str, str, str] | None:
    m = _CORE.match(word)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _wordninja_split(core: str) -> list[str] | None:
    if wordninja is None or not core.islower():
        return None
    parts = wordninja.split(core)
    if len(parts) < 2 or any(len(p) < _MIN_PIECE for p in parts):
        return None
    return parts


def debind_concatenated_words(text: str, min_split_len: int) -> tuple[str, int]:
    """Un-glue accidental run-together words ("keyboardwarrior" ->
    "keyboard warrior") using wordninja's word-frequency corpus. Real single
    long words (already whole corpus entries) are left untouched -- this
    only fires when the whole token isn't itself a known word but two or
    more shorter pieces are."""
    if wordninja is None:
        return text, 0
    count = 0

    def _repl(m: re.Match) -> str:
        nonlocal count
        word = m.group(0)
        parsed = _split_core(word)
        if not parsed:
            return word
        pre, core, post = parsed
        if len(core) < min_split_len:
            return word
        parts = _wordninja_split(core)
        if not parts:
            return word
        count += 1
        return pre + " ".join(parts) + post

    return _TOKEN.sub(_repl, text), count


def _pyphen_chunks(core: str, chunk_len: int) -> list[str] | None:
    chunks: list[str] = []
    rest = core
    while True:
        part = _pyphen_dic.wrap(rest, chunk_len)
        if not part:
            chunks.append(rest)
            break
        head, rest = part
        chunks.append(head)
    if len(chunks) < 2:
        return None
    return chunks


def chunk_long_words(text: str, min_split_len: int, chunk_len: int) -> tuple[str, int]:
    """Any word still >= min_split_len (after the passes above) gets broken
    into syllable-safe chunks via pyphen (TeX/Liang hyphenation); pyphen's
    wrap() already appends the hyphen to each piece, so chunks are joined
    with a plain space -- e.g. "antidisestablishmentarianism" ->
    "antidis- establish- mentari- anism"."""
    if _pyphen_dic is None:
        return text, 0
    count = 0

    def _repl(m: re.Match) -> str:
        nonlocal count
        word = m.group(0)
        parsed = _split_core(word)
        if not parsed:
            return word
        pre, core, post = parsed
        if len(core) < min_split_len:
            return word
        chunks = _pyphen_chunks(core, chunk_len)
        if not chunks:
            return word
        count += 1
        return pre + " ".join(chunks) + post

    return _TOKEN.sub(_repl, text), count


def process_text(
    text: str, min_split_len: int = DEFAULT_MIN_SPLIT_LEN,
    chunk_len: int = DEFAULT_CHUNK_LEN, split_long_words: bool = True,
) -> tuple[str, dict[str, int]]:
    text, joins = rejoin_wrapped_hyphens(text)
    text, hyphen_splits = split_hyphenated_compounds(text)
    concat_splits = chunk_splits = 0
    if split_long_words:
        text, concat_splits = debind_concatenated_words(text, min_split_len)
        text, chunk_splits = chunk_long_words(text, min_split_len, chunk_len)
    stats = {
        "joins": joins,
        "hyphen_splits": hyphen_splits,
        "concat_splits": concat_splits,
        "chunk_splits": chunk_splits,
    }
    return text, stats


def process_file(
    path: str, min_split_len: int = DEFAULT_MIN_SPLIT_LEN,
    chunk_len: int = DEFAULT_CHUNK_LEN, split_long_words: bool = True,
) -> dict[str, int]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()
    new_text, stats = process_text(original, min_split_len, chunk_len, split_long_words)
    if new_text != original:
        backup = path + ".orig"
        if not os.path.exists(backup):
            with open(backup, "w", encoding="utf-8") as f:
                f.write(original)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
    return stats


def _default_txts() -> list[str]:
    if not os.path.isdir(DEFAULT_DIR):
        return []
    return sorted(
        os.path.join(DEFAULT_DIR, name)
        for name in os.listdir(DEFAULT_DIR)
        if name.lower().endswith(".txt") and not name.startswith(".")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reformat Rapid Reader .txt ebooks for RSVP, in place."
    )
    parser.add_argument(
        "paths", nargs="*", help=f"txt paths (default: {DEFAULT_DIR}/*.txt)"
    )
    parser.add_argument(
        "--min-split-len", type=int, default=DEFAULT_MIN_SPLIT_LEN,
        help=f"minimum word length to consider splitting (default: {DEFAULT_MIN_SPLIT_LEN})",
    )
    parser.add_argument(
        "--chunk-len", type=int, default=DEFAULT_CHUNK_LEN,
        help=f"target chunk length for syllable splitting (default: {DEFAULT_CHUNK_LEN})",
    )
    parser.add_argument(
        "--no-long-word-split", action="store_true",
        help="skip the wordninja/pyphen long-word passes",
    )
    args = parser.parse_args(argv)

    paths = args.paths or _default_txts()
    if not paths:
        sys.exit(f"no paths given and none found in {DEFAULT_DIR}/")

    split_long_words = not args.no_long_word_split
    if split_long_words and wordninja is None:
        print("warning: wordninja not installed, skipping run-together-word pass",
              file=sys.stderr)
    if split_long_words and pyphen is None:
        print("warning: pyphen not installed, skipping long-word chunking pass",
              file=sys.stderr)

    for path in paths:
        if not os.path.isfile(path):
            sys.exit(f"not a file: {path}")
        stats = process_file(path, args.min_split_len, args.chunk_len, split_long_words)
        print(
            f"{path}: joins={stats['joins']} hyphen-splits={stats['hyphen_splits']} "
            f"concat-splits={stats['concat_splits']} chunk-splits={stats['chunk_splits']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
