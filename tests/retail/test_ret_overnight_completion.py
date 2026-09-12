"""
The overnight product-completion pass, and what it found.

**A governed metric answered about the wrong population.** "What is the 30+
DPD rate for credit cards?" came back **1.79%**. That is the whole book. The
card book is at **3.70%** — more than twice as far behind — and nothing on the
screen said the figure was not about cards. The metric library computes over
the book or over one dimension of it and holds no filters of its own, so every
population a question named was dropped on the way in. The same drop turned
"show the 30+ DPD rate for credit cards by card behaviour segment" into the
whole book grouped by a card-only column, with 13,213 non-card facilities
reported under "(not set)".

**A breakdown dimension outlived the question that asked for it.** "Break the
credit card book down by subsegment" then "give me the worst 20 customers by
expected credit loss" returned the right twenty customers under the headline
"545,568 SAR of final ECL in Credit Card across 20 SUBSEGMENTS". The rows were
customers; the carried dimension was product_subsegment; the sentence counted
one and named the other. The book has nine subsegments.

**A card portfolio had no dimension to be reviewed by.** `product_subsegment`
holds a single value for Credit Card, so the most ordinary card question —
"break it down by subsegment" — was truthfully answered "across 1 subsegment"
and showed the reader nothing. `card_behaviour_segment` is a real, populated,
three-valued column of the same book and is what a card review opens with; it
was not governed, so naming it resolved no grouping at all.
"""

from __future__ import annotations

import glob

import pandas as pd
import pytest

from backend.orchestration import conversation as cv
from backend.orchestration import orchestrator
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

LATEST = "2026-08"


@pytest.fixture(scope="module")
def book() -> pd.DataFrame:
    paths = glob.glob("data/retail/analytics/retail_facility_month/"
                      f"reporting_month={LATEST}/*.parquet")
    if not paths:
        pytest.skip("the shipped retail lake has not been built")
    return pd.read_parquet(paths[0])


def answer(question: str, *, state: cv.ConversationState | None = None):
    answered = orchestrator.answer(question, state=state)
    assert not answered.clarification, (
        f"{question!r} was refused: {answered.clarification}")
    return answered


def said(answered) -> str:
    result = getattr(answered, "result", None)
    if result is not None:
        return str(getattr(result, "answer", ""))
    from backend.orchestration import assembly
    built = assembly.from_analysis(
        answered.question, answered.reading, answered.build, answered.runtime,
        duration_ms=0, mode={})
    return str(getattr(built.narrative, "direct_answer", "") or "")


def advanced(question: str, state: cv.ConversationState | None = None):
    answered = orchestrator.answer(question, state=state)
    return answered, orchestrator.remember(state or cv.ConversationState(),
                                           answered)


def _rate(frame: pd.DataFrame) -> float:
    behind = frame[frame.dpd >= 30].gross_carrying_amount_sar.sum()
    return float(behind / frame.gross_carrying_amount_sar.sum() * 100)


class TestAGovernedMetricIsAboutThePopulationTheQuestionNamed:
    """A true figure about the wrong population is still the wrong answer."""

    def test_the_card_rate_is_the_card_books(self, book):
        answered = answer("What is the 30+ DPD rate for credit cards?")
        truth = _rate(book[book.product_label == "Credit Card"])
        whole = _rate(book)
        assert truth > whole * 1.5, (
            f"the shipped book has moved: cards {truth:.2f}% against "
            f"{whole:.2f}% for the book")
        value = float(answered.result.rows[0]["value"])
        assert value == pytest.approx(truth, abs=0.01), (value, truth)

    def test_the_sentence_says_which_population(self):
        answered = answer("What is the 30+ DPD rate for credit cards?")
        assert "Credit Card" in said(answered), said(answered)

    def test_the_whole_book_is_still_the_whole_book(self, book):
        answered = answer("What is the 30+ DPD rate?")
        value = float(answered.result.rows[0]["value"])
        assert value == pytest.approx(_rate(book), abs=0.01)

    def test_a_breakdown_is_restricted_too(self, book):
        answered = answer("Show the 30+ DPD rate for credit cards by card "
                          "behaviour segment.")
        labels = {str(r.get("label")) for r in answered.result.rows}
        assert "(not set)" not in labels, labels
        cards = book[book.product_label == "Credit Card"]
        assert labels == set(cards.card_behaviour_segment.unique()), labels

    def test_every_group_reconciles(self, book):
        answered = answer("Show the 30+ DPD rate for credit cards by card "
                          "behaviour segment.")
        cards = book[book.product_label == "Credit Card"]
        got = {str(r["label"]): float(r["value"]) for r in answered.result.rows}
        for segment, frame in cards.groupby("card_behaviour_segment"):
            assert got[str(segment)] == pytest.approx(_rate(frame), abs=0.01)


class TestACardBookHasADimensionToBeReviewedBy:
    """`card_behaviour_segment` is governed, and names what it holds."""

    def test_it_is_a_governed_dimension(self):
        from backend.orchestration.vocabulary import get_vocabulary

        assert "card_behaviour_segment" in (get_vocabulary().dimensions or {})

    def test_its_values_are_the_books(self, book):
        from backend.orchestration.vocabulary import get_vocabulary

        governed = set(get_vocabulary().dimensions["card_behaviour_segment"])
        assert governed == set(book.card_behaviour_segment.dropna().unique())


class TestABreakdownDimensionDoesNotOutliveItsQuestion:
    """Twenty customers were counted and called twenty subsegments."""

    def test_a_customer_question_is_answered_at_the_customer_grain(self):
        _, state = advanced("Break the credit card book down by subsegment.")
        answered = answer("Give me the worst 20 customers by expected credit "
                          "loss.", state=state)
        assert "subsegment" not in said(answered).lower(), said(answered)
        assert "customers" in said(answered).lower(), said(answered)

    def test_the_rows_are_still_customers(self):
        _, state = advanced("Break the credit card book down by subsegment.")
        answered = answer("Give me the worst 20 customers by expected credit "
                          "loss.", state=state)
        assert all("customer_id" in r for r in answered.runtime.rows)

    def test_a_breakdown_that_names_no_grain_still_inherits(self):
        """The inheritance itself is right and must stay."""
        # A measure that needs no clarification: "exposure" is genuinely
        # ambiguous on this book and the product asks which one, which is the
        # right behaviour and not what this gate is about.
        _, state = advanced("Show gross carrying amount by product for "
                            "August 2026.")
        answered = answer("Now only personal finance.", state=state)
        assert answered.build.dimension == "product_label", \
            answered.build.dimension


class TestFourDomainsOneBook:
    """The derived domains are views, and a view that drifted is not one."""

    def test_every_derived_domain_is_built(self):
        from backend.retail import domains

        problems = domains.reconcile()
        assert not problems, problems

    def test_the_catalogue_holds_all_four(self):
        from backend.data_access.catalog import get_catalog

        names = set(get_catalog().names())
        assert {"retail_facility_month", "retail_early_warning",
                "retail_credit_scorecard", "retail_whatif"} <= names, names

    def test_data_builder_offers_all_four_and_nothing_corporate(self):
        from backend.services import data_domains as dd

        offered = set(dd.active_domain_names())
        assert offered == {"Cockpit Data", "Early Warning Data",
                           "Credit Scorecard Data",
                           "What-If Analysis Data"}, offered

    def test_a_view_carries_no_column_the_book_does_not_hold(self):
        import glob

        import pandas as pd

        from backend.retail import domains

        canonical = pd.read_parquet(glob.glob(
            "data/retail/analytics/retail_facility_month/"
            f"reporting_month={LATEST}/*.parquet")[0])
        for view in domains.DERIVED:
            paths = glob.glob(f"data/retail/analytics/{view.dataset}/"
                              f"reporting_month={LATEST}/*.parquet")
            assert paths, f"{view.dataset} has no {LATEST}"
            frame = pd.read_parquet(paths[0])
            extra = set(frame.columns) - set(canonical.columns)
            assert not extra, (view.dataset, extra)


class TestTheWorkspaceIsNotEmpty:
    """A fresh retail installation must not open on three empty screens."""

    def test_the_seeder_reports_ready(self):
        from backend.db.engine import get_session
        from backend.retail import workspace_seed

        with get_session() as session:
            assert not workspace_seed.check(session)

    def test_every_seeded_project_is_there(self):
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import Project
        from backend.retail import workspace_seed

        with get_session() as session:
            seeded = {
                str((row.default_context or {}).get("seed_key") or "")
                for row in session.execute(select(Project)).scalars().all()}
        assert {s.key for s in workspace_seed.PROJECTS} <= seeded

    def test_seeding_twice_creates_nothing_twice(self):
        from backend.db.engine import get_session
        from backend.retail import workspace_seed

        with get_session() as session:
            again = workspace_seed.seed(session)
            session.commit()
        assert not again.created, again.created

    def test_every_case_study_holds_real_answers(self):
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import Investigation, InvestigationMessage
        from backend.retail import workspace_seed

        with get_session() as session:
            for spec in workspace_seed.CASES:
                thread = session.execute(
                    select(Investigation).where(
                        Investigation.context["seed_key"].astext == spec.key)
                ).scalars().first()
                assert thread is not None, spec.title
                rows = session.execute(
                    select(InvestigationMessage).where(
                        InvestigationMessage.investigation_id == thread.id)
                ).scalars().all()
                asked = [r for r in rows if r.role == "user"]
                answers = [r for r in rows if r.role == "assistant"]
                assert len(asked) == len(spec.questions), (spec.title, len(asked))
                assert len(answers) == len(spec.questions), spec.title
                for row in answers:
                    assert (row.content or "").strip(), spec.title


class TestASettledPopulationSurvivesABareFollowUp:
    """"Now by utilisation band" widened silently back to the whole book."""

    def test_the_follow_up_stays_inside_the_card_book(self, book):
        _, state = advanced("Show the 30+ DPD rate for credit cards by card "
                            "behaviour segment.")
        answered = answer("Now by utilisation band.", state=state)
        labels = {str(r["label"]) for r in answered.result.rows}
        assert "(not set)" not in labels, labels
        cards = book[book.product_label == "Credit Card"]
        assert labels == set(cards.utilisation_band.dropna().unique()), labels

    def test_every_band_reconciles_to_the_card_book(self, book):
        _, state = advanced("Show the 30+ DPD rate for credit cards by card "
                            "behaviour segment.")
        answered = answer("Now by utilisation band.", state=state)
        cards = book[book.product_label == "Credit Card"]
        got = {str(r["label"]): float(r["value"]) for r in answered.result.rows}
        for band, frame in cards.groupby("utilisation_band"):
            assert got[str(band)] == pytest.approx(_rate(frame), abs=0.01)

    def test_a_question_that_widens_is_not_held_in(self, book):
        _, state = advanced("Show the 30+ DPD rate for credit cards by card "
                            "behaviour segment.")
        _, state = advanced("Now by utilisation band.", state)
        answered = answer("What is the 30+ DPD rate for the whole book?",
                          state=state)
        value = float(answered.result.rows[0]["value"])
        assert value == pytest.approx(_rate(book), abs=0.01)
