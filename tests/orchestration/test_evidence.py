"""
What a written answer is allowed to say.

The check this replaces asked one question: is every NUMBER in this prose
somewhere in the result? That catches an invented figure, which is the loudest
failure and not the most common one. A borrower named who is not in the table,
a period the analysis never read, and a cause nothing established all pass a
numeric check and are all wrong.

The other half of these tests is about false positives, which matter just as
much: a grounding check that rejects correct sentences gets turned off.
"""

from __future__ import annotations

from typing import Any

from backend.orchestration import evidence as ev


class Result:
    """A small governed result, shaped like the runtime's."""

    row_count = 3
    summary = {"total_ecl": 10.0838, "change": -0.62}
    columns = [{"name": "customer_id"}, {"name": "total_ecl"}]
    rows = [
        {"customer_id": "SA-101771", "borrower_name": "Ghat Holding 1771",
         "total_ecl": 0.3536, "sector": "Real Estate", "period": "Q2 2026"},
        {"customer_id": "SA-104015", "borrower_name": "Sabya Projects 4015",
         "total_ecl": 0.7419, "sector": "Real Estate", "period": "Q2 2026"},
        {"customer_id": "SA-103333", "borrower_name": "Najran Works 3333",
         "total_ecl": 8.9883, "sector": "Real Estate", "period": "Q2 2026"},
    ]


class Plan:
    period = "Q2 2026"
    opening = "Q2 2025"
    closing = "Q2 2026"
    conditions: list[Any] = []
    filters = [("sector", "Real Estate")]


def package() -> ev.Package:
    return ev.build(Result(), Plan())


# --------------------------------------------------------- what it accepts


def test_a_sentence_quoting_the_result_is_grounded():
    grounding = ev.check(
        "Ghat Holding 1771 carries 0.35 SAR mn of expected credit loss at "
        "Q2 2026.", package())

    assert grounding.ok, grounding.problems


def test_a_rounded_figure_is_the_same_fact():
    """Prose rounds. 8.9883 quoted as 9.0 is the same number."""
    assert ev.check("The largest is 9.0 SAR mn.", package()).ok


def test_a_name_the_result_carries_in_a_longer_form_is_accepted():
    """"Ghat Holding" is the borrower "Ghat Holding 1771".

    Rejecting it would discard a correct sentence about a row on the screen,
    which is how a grounding check gets switched off.
    """
    assert ev.check("Ghat Holding carries the smallest provision.",
                    package()).ok


def test_a_name_in_the_MIDDLE_of_a_longer_one_is_accepted():
    """The sector "Wholesale & Retail Trade" reaches this check as "Retail
    Trade", because an ampersand is not a word and the name pattern stops at
    it. A prefix test alone rejected the sentence that named it — a correct
    sentence about the largest row on the screen — and the interpretation
    rubric marked the answer unsafe.
    """
    sectors = ev.Package(entities={"wholesale & retail trade", "contracting"})
    assert ev.check("Retail Trade carries the largest exposure.", sectors).ok
    assert ev.check("Wholesale carries the largest exposure.", sectors).ok


def test_a_name_the_result_does_not_carry_is_still_rejected():
    """The looser test must not switch the check off."""
    sectors = ev.Package(entities={"wholesale & retail trade", "contracting"})
    found = ev.check("Marine Logistics carries the largest exposure.", sectors)
    assert found.unknown_entities == ["Marine Logistics"]


def test_the_fragment_test_is_word_wise_not_character_wise():
    """"Trade" must not match "Trading", and a run of words must be
    contiguous: "Wholesale Trade" is not "Wholesale & Retail Trade"."""
    sectors = ev.Package(entities={"wholesale & retail trade"})
    assert ev.check("Wholesale Trade leads.", sectors).unknown_entities == [
        "Wholesale Trade"]


def test_a_portfolio_sentence_naming_nobody_is_grounded():
    assert ev.check(
        "Expected credit loss across the three names is 10.08 SAR mn.",
        package()).ok


def test_a_sentence_starting_with_a_capital_is_not_a_borrower():
    assert ev.check("Provisions are concentrated in one name.", package()).ok


# --------------------------------------------------------- what it rejects


def test_an_invented_figure_is_caught():
    grounding = ev.check("Total expected credit loss is 42.7 SAR mn.",
                         package())

    assert not grounding.ok
    assert "42.7" in grounding.ungrounded_figures


def test_a_borrower_who_is_not_in_the_result_is_caught():
    """The failure a numeric check misses entirely."""
    grounding = ev.check("Northwind Trading carries 0.35 SAR mn.", package())

    assert not grounding.ok
    assert "Northwind Trading" in grounding.unknown_entities


def test_a_period_the_analysis_never_read_is_caught():
    grounding = ev.check("Expected credit loss rose at Q4 2019.", package())

    assert not grounding.ok
    assert "Q4 2019" in grounding.wrong_periods
    assert not grounding.ungrounded_figures, (
        "the 4 in Q4 must not be reported as an invented figure — a nonsense "
        "finding buries the real one")
    assert not grounding.unknown_entities, "nor as a borrower called Q4 2019"


def test_an_asserted_cause_is_caught():
    """CreditProbe computes what moved. It does not establish why."""
    grounding = ev.check(
        "Expected credit loss rose because the sector is distressed.",
        package())

    assert not grounding.ok
    assert grounding.causal_claims
    assert "distressed" in grounding.causal_claims[0]


def test_every_causal_phrasing_is_caught():
    for sentence in (
        "The increase is due to weaker collateral.",
        "The rise was driven by three borrowers.",
        "Higher leverage resulted in the downgrade.",
        "The move is attributable to one facility.",
    ):
        assert not ev.check(sentence, package()).ok, sentence


# ------------------------------------------------------------- the package


def test_the_package_names_its_sources():
    built = package()

    assert built.facts
    assert all(f.id and f.kind for f in built.facts)
    assert any(f.source.startswith("summary.") for f in built.facts)
    assert any(f.kind == "entity" for f in built.facts)
    assert "Q2 2026" in built.periods and "Q2 2025" in built.periods


def test_the_withheld_sentence_says_what_was_wrong_and_what_still_stands():
    grounding = ev.check("Northwind Trading carries 42.7 SAR mn.", package())

    sentence = ev.withheld(grounding)

    assert "withheld" in sentence
    assert "Northwind Trading" in sentence
    assert "figures below are unaffected" in sentence


def test_an_empty_package_does_not_reject_everything():
    """No result to check against is not evidence of invention.

    Rejecting prose because there was nothing to check it against would make
    every metadata answer look like a fabrication.
    """
    grounding = ev.check("Nothing matched the conditions.", ev.Package())

    assert grounding.ok
