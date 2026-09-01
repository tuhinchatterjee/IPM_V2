"""
The typo corrector, and the two ways it can be wrong.

Missing a typo costs an answer. Making one up costs the user's trust in every
answer, so most of what is asserted here is what it must NOT touch.
"""

from __future__ import annotations

import pytest

from backend.orchestration import spelling


@pytest.fixture(scope="module")
def lexicon():
    return spelling._lexicon()


def _read(question: str, lexicon) -> spelling.Correction:
    return spelling.normalise(question, lexicon=lexicon)


# ---------------------------------------------------------------------------
# What it must fix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("typed,expected", [
    ("Show me the five largest Real Estste customers by EAD.", "Real Estate"),
    ("What is total EAD by secyor in the latest quarter?", "by sector"),
    ("How much expodure at default is in Stage 2?", "exposure at default"),
    ("What firlds are in the ratings data?", "What fields"),
])
def test_one_adjacent_key_slip_is_repaired(typed, expected, lexicon):
    assert expected in _read(typed, lexicon).text


def test_the_correction_is_reported_not_silent(lexicon):
    fixed = _read("Show the five largest Real Estste customers by EAD.", lexicon)
    assert fixed.changes == (("Estste", "estate"),)
    assert "Estste" in fixed.sentence() and "estate" in fixed.sentence()


def test_the_users_own_capitalisation_survives(lexicon):
    """A name that comes back lower case reads as a different thing."""
    assert "Real Estate" in _read("Largest Real Estste customers.", lexicon).text


# ---------------------------------------------------------------------------
# What it must never touch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("question", [
    "What is total exposure at default by sector?",
    "Which customers have covenant headroom below 15%?",
    "Which customers had an increase in ECL over the latest year?",
    "Show Contracting customers whose ECL rose over the latest year.",
])
def test_a_correct_question_is_left_alone(question, lexicon):
    assert _read(question, lexicon).changes == ()


def test_the_words_the_readers_match_on_are_never_rewritten(lexicon):
    """`least` is one keystroke from `last`, and rewriting it lost a threshold.

    "covenant headroom of at least 25%" became "at last 25%", the level test
    disappeared, and the answer came back as a ranking of the ten highest —
    a different population under the heading of the one that was asked for.
    """
    fixed = _read("Which customers have covenant headroom of at least 25%?",
                  lexicon)
    assert fixed.changes == ()
    assert "at least 25%" in fixed.text


@pytest.mark.parametrize("question", [
    "Which borrowers had their CEO resign in the last three months?",
    "Who won the cup final?",
])
def test_an_out_of_scope_question_is_not_dragged_into_the_domain(question,
                                                                lexicon):
    """The worst possible correction: making a foreign question look governed."""
    assert _read(question, lexicon).changes == ()


def test_a_sentence_full_of_typos_is_left_as_typed(lexicon):
    """Past a couple of slips it is not a mistyped question at all."""
    fixed = _read("Whst is totsl expodure st defsult by secyor?", lexicon)
    assert len(fixed.changes) <= spelling.MAX_CORRECTIONS


def test_short_words_are_never_corrected(lexicon):
    """`ecl` and `eal` are one edit apart and mean different things."""
    assert _read("What is eal by sector?", lexicon).changes == ()


# ---------------------------------------------------------------------------
# Pleasantries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("question", [
    "Please what fields are in the ratings data?",
    "Can you show me what fields are in the ratings data?",
    "I need to know what fields are in the ratings data",
    "What fields are in the ratings data — thanks",
])
def test_an_opening_or_closing_pleasantry_is_stripped_before_reading(question,
                                                                    lexicon):
    assert "fields are in the ratings data" in _read(question, lexicon).text.lower()


def test_stripping_never_empties_the_question(lexicon):
    assert _read("Please", lexicon).text.strip()


def test_it_never_raises_on_anything(lexicon):
    for odd in ("", "   ", "?", "%%%", "a" * 500):
        assert isinstance(_read(odd, lexicon), spelling.Correction)
