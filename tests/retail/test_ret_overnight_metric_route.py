"""
A rate is a rate, an absent field is absent, and "break down" is not a fall.

Three defects found by asking the Cockpit the questions a Head of Retail Risk
asks in the first ten minutes of a session. Every one of them RAN, passed its
invariants, and put a confident number on the screen.

**A rate was answered with a sum.**

    "What is the 30+ DPD rate?"          → 425.0 days of days past due
    "Which product has the highest 30+ DPD rate?"
                                         → 1,260 days of days past due
    "What is the Stage 3 share of exposure?"  → 3.00 IFRS 9 stage in Stage 3
    "What proportion of the book is in Stage 2?" → 2.00 IFRS 9 stage in Stage 2

None of those is a rate, a share or a proportion. The last two reported the
CONTENTS of `ifrs9_stage` — the literal numbers 3 and 2 — as a percentage. The
planner composes an analysis out of governed columns and a rate is not a
column: it is a numerator, a denominator and a scope, and the only place those
live together is the Metric Catalogue, which the Cockpit never consulted.

**An absent field produced a complaint about grain.**

    "Tell me the borrower's employer name for the highest-ECL facility."

was refused with "the governed data behind it can only be reported as one row
for the whole book" — which is about the wrong thing, and is false of a book
keyed one row per facility per month.

**And the most ordinary way in English to ask for a breakdown was read as a
fall.**

    "Break ECL down by product"          → 9,517 facilities where ECL fell

because the literal DOWN direction matches a bare "down", and the concept "ECL"
had already been masked out of the clause before the scan.
"""

from __future__ import annotations

import pytest

from backend.orchestration import absent_attributes as aa
from backend.orchestration import metric_route as mr
from backend.orchestration import semantics as sm
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")


# ----------------------------------------------------- the rate is a rate


class TestAGovernedRateIsAnsweredAsOne:
    @pytest.mark.parametrize("question,metric_id", [
        ("What is the 30+ DPD rate?", "retail.dpd30_rate"),
        ("what is the 30 plus dpd rate", "retail.dpd30_rate"),
        ("What is the 90+ DPD rate?", "retail.dpd90_rate"),
        ("What is the NPL rate?", "retail.dpd90_rate"),
        ("What is ECL coverage?", "retail.ecl_coverage"),
        ("What is the Stage 2 coverage?", "retail.stage2.coverage"),
        ("What is the Stage 3 share of exposure?", "retail.stage3.share"),
        ("What is the application scorecard Gini?", "retail.application.gini"),
        ("What is the observed default rate?", "retail.observed_default_rate"),
        ("What is the forbearance rate?", "retail.forbearance_rate"),
        ("What is the salary transfer rate?", "retail.salary_transfer_rate"),
    ])
    def test_the_metric_the_question_named_is_the_one_chosen(
            self, question, metric_id):
        routed = mr.read(question)
        assert routed is not None, f"{question!r} did not reach the catalogue"
        assert routed.metric_id == metric_id

    @pytest.mark.parametrize("question,metric_id", [
        ("What proportion of the book is in Stage 2?", "retail.stage2.share"),
        ("What share of exposure is in Stage 3?", "retail.stage3.share"),
        ("What percentage of the book is Stage 1?", "retail.stage1.share"),
    ])
    def test_a_stage_share_is_read_from_the_state_and_the_word_share(
            self, question, metric_id):
        """Nobody says "Stage 2 Share of Exposure". They name the stage."""
        routed = mr.read(question)
        assert routed is not None
        assert routed.metric_id == metric_id

    def test_the_longest_name_wins(self):
        """Both "coverage" and "stage 2 coverage" are in the sentence."""
        routed = mr.read("What is Stage 2 coverage?")
        assert routed is not None
        assert routed.metric_id == "retail.stage2.coverage"

    def test_a_threshold_inside_the_metrics_own_name_is_not_a_cohort(self):
        """"30+" is the metric's name, not a filter the reader added."""
        assert mr.read("What is the 30+ DPD rate?") is not None


class TestTheBreakdownIsTheOneAsked:
    @pytest.mark.parametrize("question,dimension,ranked", [
        ("Which product has the highest 30+ DPD rate?", "product_label", True),
        ("30+ DPD rate by product", "product_label", False),
        ("ECL coverage by customer segment", "customer_segment", False),
        ("What is ECL coverage?", "", False),
    ])
    def test_the_dimension_and_the_ranking(self, question, dimension, ranked):
        routed = mr.read(question)
        assert routed is not None
        assert routed.dimension == dimension
        assert routed.ranked is ranked

    def test_a_stage_metric_is_not_broken_down_by_stage(self):
        """"Stage 3 share by product" must not group by IFRS 9 stage.

        The dimension reader sees "stage" inside the METRIC'S name. Read
        without masking it, a Stage 3 metric is broken down by stage, which is
        one bar.
        """
        routed = mr.read("Stage 3 share by product")
        assert routed is not None
        assert routed.dimension == "product_label"


class TestTheRouteDeclinesWhatThePlannerDoesBetter:
    @pytest.mark.parametrize("question", [
        # A plain sum: the planner filters, compares and ranks it.
        "What is total ECL?",
        "What is gross carrying amount by product?",
        # A cohort of rows, not a portfolio figure.
        "Which customers are 30+ DPD?",
        "List the facilities in Stage 3",
        "Show me facilities with coverage above 5%",
        # A movement or a comparison, which this engine cannot express.
        "Did the 30+ DPD rate rise since July?",
        "30+ DPD rate in July 2026 vs August 2026",
        "Show the trend in ECL coverage",
        # A single word that is an adjective here, not a metric name.
        "What is secured exposure?",
        "What is our exposure at default?",
    ])
    def test_it_falls_through(self, question):
        assert mr.read(question) is None

    def test_only_derived_metrics_are_routed(self):
        """A metric with no denominator and no function is the planner's."""
        from backend.metrics import library

        for phrase, metric in mr._phrases():
            assert metric.formula.kind in mr.DERIVED_KINDS, (
                f"{metric.metric_id} is a plain {metric.formula.kind} and "
                "belongs to the planner")
        assert any(m.formula.kind not in mr.DERIVED_KINDS
                   for m in library.ALL), (
            "the served library holds no plain metric at all, which means "
            "this guard is not testing anything")

    def test_no_one_word_alias_routes_unless_it_means_one_thing(self):
        for phrase, _metric in mr._phrases():
            if len(phrase.split()) >= 2:
                continue
            assert phrase in mr.UNAMBIGUOUS, (
                f"{phrase!r} is a single ordinary word and would route every "
                "sentence containing it")


class TestTheFigureMatchesTheCatalogue:
    """The point of the route: chat and dashboard agree by construction."""

    @pytest.mark.parametrize("question", [
        "What is ECL coverage?",
        "What is the 30+ DPD rate?",
        "What is the Stage 3 share of exposure?",
    ])
    def test_the_answer_is_the_metric_engines_own_number(self, question):
        pytest.importorskip("duckdb")
        from backend.metrics import service

        routed = mr.read(question)
        assert routed is not None
        try:
            computed = service.value(routed.metric_id, period=routed.period)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"the lake is not readable here: {e}")
        if computed.get("value") is None:
            pytest.skip("the lake holds no rows for this metric here")
        result = mr.answer(routed, question)
        shown = mr._format(computed["value"], routed.metric.unit,
                           routed.metric.decimals)
        assert shown in result.answer
        assert result.execution == "computed"

    def test_a_percentage_is_shown_as_one(self):
        assert mr._format(0.7659, "percent", 2) == "0.77%"
        assert mr._format(0.0241, "probability", 2) == "2.41%"
        assert mr._format(15952108.84, "currency", 2) == "15,952,109 SAR"
        assert mr._format(None, "percent", 2) == "not available"


# ------------------------------------------------- an absent field is absent


class TestAnAbsentIdentityFieldIsDeclaredAbsent:
    @pytest.mark.parametrize("question,attribute", [
        ("Tell me the borrower's employer name for the highest-ECL facility.",
         "name"),
        ("What is the employer name of the highest ECL facility?", "name"),
        ("Give me the customer's mobile number", "mobile number"),
        ("Show me the customer's registered address", "address"),
        ("What is the borrower's IBAN?", "iban"),
        ("What is the name of the borrower?", "name"),
    ])
    def test_it_is_refused_by_name(self, question, attribute):
        found = aa.read(question)
        assert found is not None, f"{question!r} was not recognised"
        assert found.attribute == attribute

    def test_the_refusal_names_what_is_held_instead(self):
        found = aa.read("Tell me the borrower's employer name.")
        assert found is not None
        assert found.party == "employer", (
            "the sentence names an employer name, not a borrower name")
        said = found.sentence()
        assert "Employer sector" in said
        assert "employer name" in said

    def test_the_refusal_does_not_offer_an_identifier_as_a_breakdown(self):
        """"ECL by customer id" is fourteen thousand rows, not an answer."""
        found = aa.read("What is the name of the borrower?")
        assert found is not None
        assert "Customer id" in found.instead, (
            "the list of what IS held should name the identifier")
        assert found.groupable
        assert not found.groupable.lower().endswith(" id")
        assert f"break one down by {found.groupable.lower()}" in (
            found.sentence().lower())

    @pytest.mark.parametrize("question", [
        # The book carries these under their own words, so no refusal.
        "Break ECL down by product",
        "What is the customer segment mix?",
        "Show me ECL by employer sector",
        "What is the average customer tenure?",
        "Which product has the highest ECL?",
    ])
    def test_a_field_that_is_carried_is_not_refused(self, question):
        assert aa.read(question) is None


# ------------------------------------------------ "break down" is not a fall


class TestABreakdownIsNotAFall:
    @pytest.mark.parametrize("text", [
        "Break ECL down by product",
        "Break down ECL by product",
        "Break     down by product",
        "broken down by stage",
        "drill down into stage 3",
        "a top-down view of the book",
    ])
    def test_the_idiom_asserts_no_movement(self, text):
        assert sm.find_movement(text) is None

    @pytest.mark.parametrize("text", [
        "ECL fell",
        "ECL went down",
        "PD is down",
        "coverage came down sharply",
    ])
    def test_a_real_fall_still_reads_as_one(self, text):
        found = sm.find_movement(text)
        assert found is not None
        assert found.direction.kind == "down"

    def test_a_movement_elsewhere_in_the_sentence_survives_the_mask(self):
        """Masked, not discarded: only the idiom's own "down" is blanked."""
        found = sm.find_movement(
            "break ECL down by product and say which fell")
        assert found is not None


# ------------------------------- a breakdown is not restricted to one group


class TestAFieldTheQuestionGroupsByIsNotInheritedAsAFilter:
    """Found in the browser, in a thread, and invisible to a single question.

    "Which product has the highest 30+ DPD rate?" answers "Credit Card", and
    the next question — "Break ECL down by product" — came back as **Credit
    Card only**: one bar, 3,061,762 SAR, under a heading reading BY PRODUCT
    LABEL. The whole book is 15,952,109.

    The guard against this was already written and did not fire: the carried
    filter is on `product_label` and the reader wrote "product".
    """

    @pytest.mark.parametrize("text,field", [
        ("Break ECL down by product", "product_label"),
        ("ECL by product", "product_label"),
        ("show me the product breakdown", "product_label"),
        ("for each product", "product_label"),
        ("break ECL down by stage", "ifrs9_stage"),
        ("ECL by segment", "customer_segment"),
    ])
    def test_the_field_is_recognised_by_the_word_the_reader_used(
            self, text, field):
        from backend.orchestration.analysis_planner import _groups_by

        assert _groups_by(text, field) is True

    @pytest.mark.parametrize("text,field", [
        # Naming a VALUE of the field is a restriction, not a breakdown.
        ("ECL in credit card", "product_label"),
        ("Stage 2 exposure", "ifrs9_stage"),
        # A different field entirely.
        ("break ECL down by stage", "product_label"),
        ("ECL by product", "customer_segment"),
    ])
    def test_a_field_that_is_not_the_axis_is_left_alone(self, text, field):
        from backend.orchestration.analysis_planner import _groups_by

        assert _groups_by(text, field) is False
