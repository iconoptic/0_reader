"""Characterization of upper-tick / long-word overlap (visual bug repro).

These tests lock the current behaviour so a future fix has a clear red→green
signal. They do **not** write the HTML report; run
``python3 tools/sim_tick_overlap.py`` for visual inspection.
"""

from __future__ import annotations

import importlib.util
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "sim_tick_overlap", os.path.join(ROOT, "tools", "sim_tick_overlap.py")
)
sim = importlib.util.module_from_spec(_spec)
sys.modules["sim_tick_overlap"] = sim
_spec.loader.exec_module(sim)

# Locked lemma: at word_size=large, bare form stays single-line; trailing
# comma pushes measured width past W-8 and takes _two_line_word.
_LEMMA = "extraordinarily"
_LEMMA_PUNCT = "extraordinarily,"


def test_punct_pushes_borderline_word_into_two_line_at_large():
    bare = sim.analyze(_LEMMA, "large")
    with_comma = sim.analyze(_LEMMA_PUNCT, "large")
    assert bare.two_line is False
    assert bare.total <= 120
    assert with_comma.two_line is True
    assert with_comma.total > 120


def test_two_line_frame_has_word_ink_in_upper_tick_band():
    case = sim.analyze(_LEMMA_PUNCT, "large")
    assert case.two_line is True
    # Substantial shared ink (not a single ascender nick).
    assert case.overlap_px > 50


def test_bare_borderline_word_does_not_overlap_tick_at_large():
    case = sim.analyze(_LEMMA, "large")
    assert case.two_line is False
    assert case.overlap_px == 0


def test_short_word_at_medium_is_clean():
    case = sim.analyze("hello", "medium")
    assert case.two_line is False
    assert case.overlap_px == 0


@pytest.mark.parametrize("word,punct", [
    ("understanding", "understanding."),
    ("circumstances", "circumstances;"),
    ("representative", "representative,"),
])
def test_other_punct_triggers_match_locked_pattern(word, punct):
    """Same large-tier pattern: bare fits, trailing punct → two-line + overlap."""
    bare = sim.analyze(word, "large")
    with_p = sim.analyze(punct, "large")
    assert bare.two_line is False
    assert with_p.two_line is True
    assert with_p.overlap_px > 50


def test_measure_total_agrees_with_is_two_line():
    th = sim.ticks_theme()
    for word in (_LEMMA, _LEMMA_PUNCT, "hello", "communication"):
        total, _ = sim.measure_total(word, th, "large")
        assert sim.is_two_line(word, th, "large") == (total > 120)


def _fake_ebooks(tmp_path):
    """Tiny library: Zipf-bait short words plus long / punctuated types."""
    d = tmp_path / "ebooks" / "Classics"
    d.mkdir(parents=True)
    shorts = "the of and a to in that is was he for it with as his on be at by".split()
    longs12 = [
        "extraordinary", "understanding", "circumstances", "representative",
        "establishment", "philosophical", "international", "revolutionary",
        "consideration", "infrastructure",
    ]
    longs15 = [
        "extraordinarily", "characteristically", "straightforwardly",
        "uncharacteristically",
    ]
    punct = [
        "understanding.", "circumstances;", "representative,",
        "extraordinary!", "together?", "something:",
    ]
    hyphens = ["out-", "self-", "well-", "over-", "under-", "after-"]
    mids = ["something", "together", "anything", "everything",
            "important", "different", "possible", "themselves"]
    # Repeat shorts so an occurrence-weighted draw would be useless.
    text = " ".join(shorts * 80 + longs12 + longs15 + punct + hyphens + mids)
    (d / "book.txt").write_text(text, encoding="utf-8")
    (tmp_path / "ebooks" / "other.txt").write_text(
        "hello world. " + " ".join(longs12), encoding="utf-8")
    return str(tmp_path / "ebooks")


def test_sample_is_stratified_not_zipf(tmp_path):
    rng = random.Random(1)
    picked = sim.sample_ebook_tokens(_fake_ebooks(tmp_path), rng)
    words = [w for w, _ in picked]
    strata = {s for _, s in picked}
    assert "trailing_punct" in strata
    assert "long_under_split" in strata
    assert "hyphen_chunk" in strata
    # Unique types, and short function words cannot fill the whole sample.
    assert len(words) == len(set(words))
    short = [w for w, s in picked if s == "short"]
    assert len(short) <= sim.STRATUM_QUOTAS["short"]
    assert len(short) < len(picked) / 2
    cores = [sim.core_len(w) for w in words]
    assert sum(1 for n in cores if n >= 8) >= len(words) // 2


def test_sample_changes_across_seeds(tmp_path):
    lib = _fake_ebooks(tmp_path)
    a = {w for w, _ in sim.sample_ebook_tokens(lib, random.Random(1))}
    b = {w for w, _ in sim.sample_ebook_tokens(lib, random.Random(2))}
    assert a != b
    same = {w for w, _ in sim.sample_ebook_tokens(lib, random.Random(1))}
    assert same == a


def test_classify_stratum_prefers_punct_and_hyphen():
    assert sim.classify_stratum("understanding.") == "trailing_punct"
    assert sim.classify_stratum("out-") == "hyphen_chunk"
    assert sim.classify_stratum("extraordinary") == "long_under_split"
    assert sim.classify_stratum("extraordinarily") == "long"
    assert sim.classify_stratum("something") == "mid"
    assert sim.classify_stratum("the") == "short"


def _tiny_quotas():
    return {
        "short": 2,
        "mid": 2,
        "long_under_split": 2,
        "long": 2,
        "trailing_punct": 2,
        "hyphen_chunk": 2,
    }


def _flagged_ebooks(tmp_path):
    """Minimal library: a clean short word plus a known two-line overlap."""
    d = tmp_path / "flagged_ebooks"
    d.mkdir()
    (d / "book.txt").write_text("was extraordinarily,", encoding="utf-8")
    return str(d)


def test_run_appends_and_skips_seen_words(tmp_path, monkeypatch):
    monkeypatch.setattr(sim, "STRATUM_QUOTAS", _tiny_quotas())
    lib = _fake_ebooks(tmp_path)
    out = tmp_path / "report"
    first = sim.run(str(out), ebooks_dir=lib, seed=1)
    words_first = {c.word for c in first}
    n_png = len(list(out.glob("*.png")))
    assert n_png == 6 * len(words_first)
    assert (out / "results.jsonl").is_file()

    same = sim.run(str(out), ebooks_dir=lib, seed=1)
    assert {c.word for c in same} == words_first
    assert len(list(out.glob("*.png"))) == n_png

    sampled_second = [w for w, _ in sim.sample_ebook_tokens(lib, random.Random(2))]
    new_words = {w for w in sampled_second if w not in words_first}
    second = sim.run(str(out), ebooks_dir=lib, seed=2)
    assert len(list(out.glob("*.png"))) == n_png + 6 * len(new_words)
    assert words_first <= {c.word for c in second}
    pairs = [(c.word, c.word_size) for c in second]
    assert len(pairs) == len(set(pairs))
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Seeds: 1, 2" in html


def test_run_reset_clears_and_starts_over(tmp_path, monkeypatch):
    monkeypatch.setattr(sim, "STRATUM_QUOTAS", _tiny_quotas())
    lib = _fake_ebooks(tmp_path)
    out = tmp_path / "report"
    sim.run(str(out), ebooks_dir=lib, seed=1)
    second = sim.run(str(out), ebooks_dir=lib, seed=2, reset=True)
    sampled_second = {w for w, _ in sim.sample_ebook_tokens(lib, random.Random(2))}
    assert {c.word for c in second} == sampled_second
    pngs = {p.name for p in out.glob("*.png")}
    expected = {name for c in second for name in (c.plain, c.ann)}
    assert pngs == expected
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "Seeds: 2" in html
    assert "Seeds: 1, 2" not in html


def test_flagged_md_embeds_frames_and_omits_clean_short(tmp_path):
    out = tmp_path / "report"
    results = sim.run(str(out), ebooks_dir=_flagged_ebooks(tmp_path), seed=1)
    assert any(c.flagged for c in results)
    md = (out / "flagged.md").read_text(encoding="utf-8")
    assert "![OLED](" in md
    assert "![annotated](" in md
    assert "extraordinarily," in md
    assert "`was`" not in md


def test_parse_seen_words_unescapes():
    html = "<code>pell&#x27;impossibilità</code> <code>hello</code>"
    assert sim.parse_seen_words(html) == {"pell'impossibilità", "hello"}


def test_parse_html_cases_reads_section_metrics():
    snippet = (
        "<section class='case overlap twoline'>"
        "<h2>TWO-LINE OVERLAP — <code>Abbandonarono</code> (large)</h2>"
        "<p class='meta'>total=128.1px (threshold 120) · fit_size=None · "
        "overlap_px=127 · tick_cols=[33] · ebook long_under_split</p>"
        "<div class='frames'>"
        "<figure><img src='large_Abbandonarono_0534.png' alt='frame'></figure>"
        "<figure><img src='large_Abbandonarono_0534_ann.png' alt='annotated'></figure>"
        "</div></section>"
    )
    cases = sim.parse_html_cases(snippet)
    assert len(cases) == 1
    case = cases[0]
    assert case.word == "Abbandonarono"
    assert case.word_size == "large"
    assert case.two_line is True
    assert case.overlaps is True
    assert case.total == 128.1
    assert case.fit_size is None
    assert case.overlap_px == 127
    assert case.tick_cols == {33}
    assert case.note == "ebook long_under_split"
    assert case.plain == "large_Abbandonarono_0534.png"
    assert case.ann == "large_Abbandonarono_0534_ann.png"


def test_html_only_tree_seeds_jsonl_and_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(sim, "STRATUM_QUOTAS", _tiny_quotas())
    lib = _fake_ebooks(tmp_path)
    out = tmp_path / "report"
    first = sim.run(str(out), ebooks_dir=lib, seed=1)
    (out / "results.jsonl").unlink()
    n_png = len(list(out.glob("*.png")))
    second = sim.run(str(out), ebooks_dir=lib, seed=1)
    assert (out / "results.jsonl").is_file()
    assert len(list(out.glob("*.png"))) == n_png
    assert {c.word for c in second} == {c.word for c in first}
