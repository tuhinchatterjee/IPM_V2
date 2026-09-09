"""Deterioration, and the exclusion that makes it an early-warning question.

Three of the Cockpit's five approved questions could not be answered before
this: "which exposures have deteriorated this quarter?" asked the reader which
figure to measure, "where are multiple warning signals appearing together?" was
refused as something the governed universe holds nothing about, and "which
borrowers are weakening but are not yet on the watchlist?" was withheld with a
plan-validator message where the answer belonged.

None of them names a measure. All three are composite questions, and the
composite machinery was already there — what was missing was the vocabulary
that reaches it and a way to say "not yet".
"""

from __future__ import annotations

import pytest

from backend.metadata.service import catalogue
from backend.orchestration import composites as cmp
from backend.orchestration import gate


@pytest.fixture(scope="module")
def installed():
    return catalogue()


class TestTheVocabularyReachesIt:

    @pytest.mark.parametrize("question,key", [
        ("Which exposures have deteriorated this quarter?", "deterioration"),
        ("Which borrowers are weakening?", "deterioration"),
        ("Which names have got worse?", "deterioration"),
        ("Which borrowers are getting worse?", "deterioration"),
        ("What has deteriorated?", "deterioration"),
        # The exact sentence `test_investigation_and_modification` used as its
        # example of a question the composer cannot read. It now reads.
        ("What deteriorated this period?", "deterioration"),
        ("Which credits have worsened?", "deterioration"),
        ("Where are multiple warning signals appearing together?",
         "credit_concern"),
        ("Which names have several red flags at once?", "credit_concern"),
        ("Which borrowers are the real issues?", "credit_concern"),
        ("Which borrowers have the strongest evidence of liquidity stress?",
         "liquidity_stress"),
    ])
    def test_it_is_read_as_a_composite(self, question, key, installed):
        found = cmp.find(question, installed)
        assert found is not None, f"{question!r} reached no composite."
        assert found.composite.key == key


class TestAMeasureQuestionStaysAMeasureQuestion:
    """A named measure means the sentence said WHAT deteriorated.

    That is an ordinary movement on that measure, and hijacking it into a
    seven-signal ranking would answer a different question — the exact
    substitution the composite module exists to prevent, running the other way.
    """

    @pytest.mark.parametrize("question", [
        "Which borrowers had deteriorating DSCR?",
        "Which borrowers have worsening leverage and declining DSCR?",
        "Which customers had a rating downgrade and an increase in ECL "
        "over the latest year?",
        "Which sectors deteriorated the most in ECL?",
        "Which names have weakening interest coverage?",
        "Show the five largest Real Estate customers by EAD.",
        "What is total ECL in the latest quarter?",
        "Which borrowers are in Contracting?",
        "How many borrowers are in Stage 2?",
    ])
    def test_no_composite_is_taken(self, question, installed):
        assert cmp.find(question, installed) is None


class TestTheSignalsAreGoverned:

    def test_every_deterioration_signal_reads_an_installed_column(
            self, installed):
        fields = {d.name: {f.name for f in d.fields}
                  for d in installed.datasets}
        for signal in cmp.DETERIORATION.signals:
            have = fields.get(signal.dataset, set())
            for column in signal.columns:
                assert column in have, (
                    f"{signal.key} reads {signal.dataset}.{column}, which the "
                    f"catalogue does not carry.")

    def test_it_is_usable_on_this_installation(self, installed):
        found = cmp.find("Which exposures have deteriorated?", installed)
        assert found is not None
        assert found.usable
        assert len(found.available) == len(cmp.DETERIORATION.signals)

    def test_the_rating_movement_is_declared_absent_rather_than_dropped(self):
        stated = " ".join(cmp.DETERIORATION.absent).lower()
        assert "internal rating" in stated

    def test_every_signal_states_its_threshold_in_words(self):
        for signal in cmp.DETERIORATION.signals:
            said = signal.sentence()
            assert signal.label in said
            assert signal.field in said


class TestTheEqualsTest:
    """A governed enumeration stating the thing outright.

    `trend` reads "Deteriorating" in the book. Reading that as a threshold on a
    number, or leaving it out because it is not one, both throw away the
    bank's own published statement about the facility.
    """

    def test_it_needs_the_value_it_tests_for(self):
        with pytest.raises(ValueError):
            cmp.Signal(key="x", label="x", dimension="x",
                       dataset="portfolio_facility", field="trend",
                       test=cmp.EQUALS)

    def test_the_value_must_be_the_spelling_in_the_column(self):
        with pytest.raises(ValueError):
            cmp.Signal(key="x", label="x", dimension="x",
                       dataset="portfolio_facility", field="trend",
                       test=cmp.EQUALS, value=1)

    def test_it_compiles_to_an_equality_on_the_governed_value(self):
        from backend.orchestration.analysis_planner import _signal_expression

        signal = cmp.Signal(key="t", label="Deteriorating", dimension="trend",
                            dataset="portfolio_facility", field="trend",
                            test=cmp.EQUALS, value="Deteriorating")
        built = _signal_expression(signal)
        when = built["whens"][0]["when"]
        assert when["function"] == "eq"
        assert when["args"][0] == {"type": "column", "name": "trend"}
        assert when["args"][1] == {"type": "literal", "value": "Deteriorating"}


class TestTheExclusion:
    """"Not yet on the watchlist" — the evidence before the formal flag."""

    HAVE = {"watchlist", "npl", "ead"}

    @pytest.mark.parametrize("question,field", [
        ("Which borrowers are weakening but are not yet on the watchlist?",
         "watchlist"),
        ("Which names are deteriorating and not watchlisted?", "watchlist"),
        ("Which deteriorating names are not on the watchlist?", "watchlist"),
        ("Which weakening borrowers are excluding the watchlist?", "watchlist"),
        ("Which deteriorating names are still performing?", "npl"),
    ])
    def test_it_is_read(self, question, field):
        found = cmp.excluded(question, self.HAVE)
        assert [e.field for e in found] == [field]

    @pytest.mark.parametrize("question", [
        "Which borrowers are on the watchlist?",
        "Which borrowers are weakening?",
        "Show watchlisted borrowers by EAD",
        "Which non-performing borrowers have the largest EAD?",
    ])
    def test_a_question_that_did_not_exclude_produces_nothing(self, question):
        assert cmp.excluded(question, self.HAVE) == ()

    def test_a_flag_this_installation_lacks_produces_nothing(self):
        assert cmp.excluded(
            "Which borrowers are not on the watchlist?", {"ead"}) == ()

    def test_it_quotes_the_reader_own_words(self):
        found = cmp.excluded(
            "Which borrowers are weakening but are not yet on the watchlist?",
            self.HAVE)
        assert found[0].phrase == "are not yet on the watchlist"
        assert "watchlist" in found[0].says


class TestTheCoverageGateIsNotContradicted:
    """Two sentences from CreditProbe, on one screen, disagreeing.

    The caveats said the watchlist had been removed before the evidence was
    counted. Two lines below, the coverage gate — which reads predicates, and
    a composite has none — said CreditProbe could not apply "weakening and the
    exclusion the question stated". Both were on the answer.
    """

    QUESTION = ("Which borrowers are weakening but are not yet on the "
                "watchlist?")

    def test_without_the_exemption_the_gate_reports_the_exclusion(self):
        dropped = gate.dropped_structure(
            self.QUESTION, None, None, [], [], [])
        assert any("exclusion" in d for d in dropped)

    def test_the_reading_that_applied_it_clears_it(self):
        dropped = gate.dropped_structure(
            self.QUESTION, None, None, [], [], [],
            covered=["are weakening", "are not yet on the watchlist"])
        assert not any("exclusion" in d for d in dropped)

    def test_an_unrelated_dropped_condition_is_still_reported(self):
        dropped = gate.dropped_structure(
            "Which borrowers have worsening cash conversion and are not on "
            "the watchlist?", None, None, [], [], [],
            covered=["are not on the watchlist"])
        assert not any("exclusion" in d for d in dropped)
        assert dropped, "a genuinely dropped condition must still be reported"

    def test_covering_nothing_changes_nothing(self):
        assert gate.dropped_structure(self.QUESTION, None, None, [], [], []) \
            == gate.dropped_structure(self.QUESTION, None, None, [], [], [],
                                      covered=[])


class TestOrderMatters:
    """Liquidity first, then deterioration, then the general concern."""

    def test_liquidity_wins_over_the_general_reading(self, installed):
        found = cmp.find("Which borrowers have liquidity problems?", installed)
        assert found is not None
        assert found.composite.key == "liquidity_stress"

    def test_the_registered_order_is_the_one_documented(self):
        assert [c.key for c in cmp.COMPOSITES] == [
            "liquidity_stress", "deterioration", "credit_concern"]
