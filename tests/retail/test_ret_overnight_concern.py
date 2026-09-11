"""
"What needs my attention this month?", and the signals that answer it.

The failure this closes
------------------------
    "What needs my attention in the retail portfolio this month?"

is the first question anybody asks this product. It was answered:

    CreditProbe has no governed data about what that asks for. It answers from
    the figures a steward has published — exposure, impairment, ratings,
    delinquency, covenants — and it holds nothing that measures this.

Four separate faults sat behind that one sentence.

  * The list of what it answers from named RATINGS and COVENANTS, corporate
    objects with nothing behind them here.
  * The three composites that answer exactly this question — credit concern,
    deterioration, affordability stress — were declared entirely over
    `portfolio_facility`, so under the retail profile every signal was missing
    and each composite degraded to nothing.
  * The pattern allowed "requires attention" and "needs attention" and not
    "needs MY attention", which is how a person writes it.
  * And the grain reader saw the word "portfolio" and asked for one row for
    the whole book, while a composite ranking returns N subjects by
    construction — so even once it matched, it was refused.

And a fifth, found only by reading the table: `ABOVE` is `field >= value`, so
`dpd ABOVE 0` read as "days past due of zero or more" and fired on every
facility in the book. The answer was "6,301 of its 6,301 customers show at
least one of 8 signals" — a hundred per cent of every sector, in a sentence
nobody would believe and nobody could disprove without opening the table.
"""

from __future__ import annotations

import pytest

from backend.orchestration import composites
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

#: Columns of the corporate facility book. A retail signal reading one of
#: these is a signal with nothing behind it.
CORPORATE_COLUMNS = {
    "dpd_days", "utilisation_pct", "dscr", "covenant_headroom_pct",
    "watchlist", "npl", "internal_grade", "pd_12m_pct", "news_sentiment",
}


class TestTheCompositesAreConstitutedFromThisBook:
    def test_three_are_served(self):
        keys = {c.key for c in composites.COMPOSITES}
        assert keys == {"affordability_stress", "deterioration",
                        "credit_concern"}

    def test_every_signal_reads_the_governed_retail_book(self):
        for composite in composites.COMPOSITES:
            for signal in composite.signals:
                assert signal.dataset == "retail_facility_month", (
                    f"{composite.key}/{signal.key} reads {signal.dataset}")
                assert signal.field not in CORPORATE_COLUMNS, (
                    f"{composite.key}/{signal.key} reads {signal.field}, "
                    "which belongs to the corporate book")

    def test_every_signal_reads_a_published_column(self):
        from backend.data_access.catalog import Catalog

        try:
            held = set(Catalog.load().dataset("retail_facility_month").fields)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"the governed catalogue is not readable here: {e}")
        for composite in composites.COMPOSITES:
            for signal in composite.signals:
                assert signal.field in held, (
                    f"{composite.key}/{signal.key} declares {signal.field}, "
                    "which the book does not carry")

    def test_the_corporate_set_is_retained(self):
        assert composites.CORPORATE_COMPOSITES
        assert any(s.field == "covenant_headroom_pct"
                   for c in composites.CORPORATE_COMPOSITES
                   for s in c.signals)

    def test_nothing_a_retail_customer_does_not_have_is_described(self):
        forbidden = ("covenant", "debt service coverage", "rating",
                     "news sentiment")
        for composite in composites.COMPOSITES:
            blob = (composite.means + " " + " ".join(
                s.label for s in composite.signals)).lower()
            for word in forbidden:
                assert word not in blob, f"{composite.key}: {blob}"


class TestTheQuestionsThatNameThem:
    @pytest.mark.parametrize("question,key", [
        ("What needs my attention in the retail portfolio this month?",
         "credit_concern"),
        ("What needs our attention?", "credit_concern"),
        ("Which customers require the most attention?", "credit_concern"),
        ("Which customers worry you most?", "credit_concern"),
        ("What should I be looking at?", "credit_concern"),
        ("Which customers are deteriorating?", "deterioration"),
        ("Which customers are showing affordability stress?",
         "affordability_stress"),
        ("Who is short of cash?", "affordability_stress"),
    ])
    def test_the_question_reaches_the_right_composite(self, question, key):
        found = composites.find(question)
        assert found is not None, f"{question!r} matched no composite"
        assert found.composite.key == key

    @pytest.mark.parametrize("question", [
        # Filters, not concerns.
        "Which customers are in personal finance?",
        "How many customers are there?",
        "What is total ECL?",
    ])
    def test_a_plain_question_matches_no_composite(self, question):
        assert composites.find(question) is None


class TestAScreeningQuestionIsNotAScenario:
    """A condition named in a question is not an instruction to create it."""

    @pytest.mark.parametrize("question", [
        "Which customers are showing affordability stress?",
        "Show me the customers under affordability stress",
        "Which customers are showing signs of financial strain?",
    ])
    def test_it_is_read_as_a_report(self, question):
        from backend.whatif import language

        assert language.read(question).opens_whatif is False

    @pytest.mark.parametrize("question", [
        "Stress the retail portfolio",
        "Use the severe scenario",
        "What if we stress the book by 20%?",
        # "UNDER stress" is a deliberate exception the language reader already
        # documents: it reads as "under the stress scenario", and this gate is
        # here so a later widening of the screening rule cannot quietly take
        # that decision away.
        "Which facilities are under the most stress?",
    ])
    def test_an_instruction_still_opens_what_if(self, question):
        from backend.whatif import language

        made = language.read(question)
        assert made.opens_whatif or made.scenario is not None


class TestTheThresholdIsTheOneTheLabelDescribes:
    """`ABOVE` is `>=`. A count threshold of 0 fires on the whole book."""

    @pytest.mark.parametrize("key,signal_key,least", [
        ("credit_concern", "arrears", 1),
        ("credit_concern", "salary_stopped", 1),
        ("credit_concern", "stage_2_or_worse", 2),
        ("deterioration", "recently_late", 1),
        ("affordability_stress", "salary_missed", 1),
        ("affordability_stress", "missed_payment", 1),
    ])
    def test_a_count_signal_needs_at_least_one(self, key, signal_key, least):
        composite = next(c for c in composites.COMPOSITES if c.key == key)
        signal = next(s for s in composite.signals if s.key == signal_key)
        assert signal.test == composites.ABOVE
        assert signal.value >= least, (
            f"{key}/{signal_key} at {signal.value} with an inclusive test "
            "fires on every row in the book")

    def test_no_signal_fires_on_the_whole_book(self, retail_book):
        """The gate that would have caught it: run them and count."""
        import pandas as pd

        frame = retail_book.month("2026-08")
        for composite in composites.COMPOSITES:
            for signal in composite.signals:
                if signal.field not in frame.columns:
                    continue
                column = frame[signal.field]
                if signal.test == composites.TRUE:
                    fires = column.fillna(False).astype(bool)
                elif signal.test == composites.ABOVE:
                    fires = pd.to_numeric(column, errors="coerce") >= signal.value
                elif signal.test == composites.BELOW:
                    fires = pd.to_numeric(column, errors="coerce") < signal.value
                else:
                    continue
                share = float(fires.fillna(False).mean())
                assert share < 0.95, (
                    f"{composite.key}/{signal.key} fires on {share:.1%} of the "
                    "book, so it separates nothing")
