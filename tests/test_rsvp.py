import pytest

import rsvp


@pytest.mark.parametrize("word,expected", [
    ("hello", (0, 5)),
    ("\u201chello,\u201d", (1, 6)),
    ("(hello)", (1, 6)),
    ("...", (0, 3)),          # all punctuation: whole token is the core
    ("", (0, 0)),
    ("a", (0, 1)),
])
def test_core_span(word, expected):
    assert rsvp.core_span(word) == expected


@pytest.mark.parametrize("word,expected", [
    ("a", 0),
    ("to", 1),
    ("hello", 1),          # 2-5 letters -> 2nd letter
    ("reader", 2),         # 6-9 -> 3rd
    ("presentation", 3),   # 10-13 -> 4th
    ("characteristically", 4),
    ("\u201chello\u201d", 2),   # leading quote shifts the index by one
])
def test_orp_index(word, expected):
    assert rsvp.orp_index(word) == expected


def test_orp_index_always_inside_token():
    for w in ["x", "xy", "(x)", "\"quoted.\"", "long-hyphenated-word!!", "--"]:
        i = rsvp.orp_index(w)
        assert 0 <= i < len(w)


def test_word_delay_scales_with_wpm():
    assert rsvp.word_delay("word", 300) == pytest.approx(rsvp.word_delay("word", 150) / 2)
    assert rsvp.word_delay("word", 150) == pytest.approx(0.4)


def test_word_delay_lingers_on_punctuation_and_length():
    base = rsvp.word_delay("word", 150)
    assert rsvp.word_delay("word.", 150) == pytest.approx(base * 2.5)
    assert rsvp.word_delay("word,", 150) == pytest.approx(base * 1.7)
    assert rsvp.word_delay("extraordinary", 150) == pytest.approx(base * 1.4)
    # sentence end dominates clause end when both are present in the tail
    assert rsvp.word_delay("word.\u201d", 150) == pytest.approx(base * 2.5)


def test_word_delay_paragraph_end():
    base = rsvp.word_delay("word", 150)
    assert rsvp.word_delay("word", 150, is_para_end=True) == pytest.approx(base * 2.0)


def test_word_delay_internal_punctuation_does_not_linger():
    # punctuation inside the core (e.g. hyphen or apostrophe) is not a pause
    assert rsvp.word_delay("don't", 150) == pytest.approx(rsvp.word_delay("dont", 150))


def test_word_delay_without_weights_matches_hardcoded_constants():
    """Regression: omitting weights must match the pre-weights formula."""
    wpm = 150
    base = 60.0 / wpm
    cases = [
        ("word", False, base),
        ("extraordinary", False, base + base * 0.4),
        ("word.", False, base + base * 1.5),
        ("word,", False, base + base * 0.7),
        ("word", True, base + base * 1.0),
        ("extraordinary.", True, base + base * 0.4 + base * 1.5 + base * 1.0),
    ]
    for word, is_para_end, expected in cases:
        assert rsvp.word_delay(word, wpm, is_para_end) == pytest.approx(expected)


def test_word_delay_weights_override_one_component():
    wpm = 150
    base = 60.0 / wpm
    # sentence weight zeroed: period no longer adds linger
    assert rsvp.word_delay("word.", wpm, weights={"sentence": 0.0}) == pytest.approx(base)
    # clause still uses default
    assert rsvp.word_delay("word,", wpm, weights={"sentence": 0.0}) == pytest.approx(
        base + base * 0.7)
    # long overridden only
    assert rsvp.word_delay("extraordinary", wpm, weights={"long": 0.0}) == pytest.approx(base)
    assert rsvp.word_delay("word", wpm, True, weights={"para": 0.0}) == pytest.approx(base)
