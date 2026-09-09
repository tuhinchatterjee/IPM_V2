"""Describing what you want, and getting a governed metric for it.

§1–§11. The product claim under test is not "a model can write a formula" —
it must not — but that somebody who knows what they want and does not know the
schema can reach a governed metric without being handed a field list.

Three properties matter more than any single reading:

**It is deterministic.** No model reads a sentence here; the catalogue does.
The same words produce the same options on every machine, which is what lets
these tests assert a reading rather than assert something vague about it.

**It offers, it does not decide.** Every route returns candidates with what
they matched on. A reading that is wrong is visibly wrong before anything is
built, which is the difference between a builder people trust and one they
check twice.

**It never invents.** Every metric it offers is in the governed catalogue, and
every part of a skeleton it proposes — dataset, field, aggregation, filter —
was matched against that catalogue before it was offered. A sentence naming
something this deployment cannot calculate gets the refusal, not a guess.
"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.metrics import builder
from backend.metrics import service as metrics
from backend.metrics.formula import Condition, Formula, Side, Term

needs_lake = pytest.mark.skipif(
    not settings.has_database, reason="needs the analytics lake")


def _ids(intent) -> list[str]:
    return [m["metric_id"] for m in intent.metrics]


def _chosen(intent) -> list[str]:
    return [d.name for d in intent.domains if d.chosen]


# ------------------------------------------------------ reading a sentence


def test_the_expanded_formula_moves_when_a_label_would_not():
    """A label is prose written once; the algebra a person edits must move.

    `Formula.describe()` prefers the label — "(Breached EAD) / (Total
    exposure) × 100" — which reads well on a governed info panel and hides
    every edit somebody makes to the condition underneath it.
    """
    rate = metrics.resolve("corporate.covenant_breach_rate")
    labelled = rate.formula.describe()
    expanded = builder.expanded_formula(rate.formula)
    assert "Breached EAD" in labelled
    assert "Breached EAD" not in expanded
    assert "covenant_headroom_pct < 0" in expanded


def test_a_sentence_is_read_into_a_domain_and_metrics():
    intent = builder.interpret("show me exposure by sector")
    assert _chosen(intent)
    assert "corporate.exposure" in _ids(intent)
    assert intent.understood.startswith("Read as:")


def test_a_compound_request_keeps_both_domains():
    """§20's hardest interpretation case, and the one that decides the design.

    "IFRS 9 coverage and retail delinquency" names one domain and describes
    another. A builder that kept only the domain it could see the name of
    would silently drop half the request — so a domain that produced one of
    the best-matching metrics is chosen even when its name was never said.
    """
    intent = builder.interpret(
        "I want to monitor IFRS 9 coverage and retail delinquency")
    chosen = _chosen(intent)
    assert "Corporate IFRS 9" in chosen
    assert any(d.startswith("Retail") for d in chosen), chosen
    assert any(m.startswith("corporate.ifrs9") for m in _ids(intent))
    assert any(m.startswith("retail.") for m in _ids(intent))


def test_the_same_sentence_reads_the_same_way_twice():
    """No model, so no drift. A test can assert a reading only because of it."""
    said = "watchlist and covenant breaches in the corporate book"
    first, second = builder.interpret(said), builder.interpret(said)
    assert first.to_dict() == second.to_dict()


def test_asking_for_a_trend_produces_a_chart_over_the_period_field():
    intent = builder.interpret("delinquency trend over time")
    assert intent.over_time
    assert intent.charts, "a trend request produced no chart"
    chart = intent.charts[0]
    assert chart["over_time"] is True
    assert chart["visual"] == "line"


def test_asking_for_a_breakdown_produces_a_chart_over_that_dimension():
    intent = builder.interpret("exposure by sector")
    assert intent.charts
    assert intent.charts[0]["dimension"] == "sector"
    # A sector has no order, so a line across it would assert a progression
    # that is not there. The chart vocabulary already refuses that, and the
    # interpreter must not route around it.
    assert intent.charts[0]["visual"] == "bar"


def test_a_dimension_the_dataset_does_not_have_produces_no_chart():
    """Rather than a chart that would fail when somebody opened the lens."""
    intent = builder.interpret("exposure by favourite colour")
    assert intent.charts == []


def test_shape_words_do_not_vote_on_which_metric_is_meant():
    """"over" fuzzy-matched "Overlay", and Management Overlay came back as the
    best reading of "delinquency trend over time"."""
    intent = builder.interpret("delinquency trend over time")
    assert not any("overlay" in m for m in _ids(intent)), _ids(intent)
    assert any("dpd" in m or "delinq" in m for m in _ids(intent)), _ids(intent)


def test_an_empty_sentence_asks_rather_than_guesses():
    intent = builder.interpret("   ")
    assert intent.metrics == []
    assert intent.question


def test_a_sentence_always_says_what_it_understood():
    for said in ("exposure by sector", "zzzz nothing at all"):
        assert builder.interpret(said).understood.strip()


# ------------------------------------------------- the truthful refusal


def test_naming_something_unsupported_says_so_even_when_other_things_match():
    """§20. "Roll rate for the retail book" matches plenty of retail metrics.

    The one thing asked for by name is the one CreditProbe cannot do, so it
    has to say so beside what it found rather than quietly offering four
    things nobody asked for.
    """
    intent = builder.interpret("roll rate for the retail book")
    names = [u["name"] for u in intent.unavailable]
    assert "Delinquency Roll Rate" in names, names
    assert all(u["because"].strip() for u in intent.unavailable)


def test_a_single_word_does_not_drag_in_refusals_nobody_asked_for():
    """"retail" alone reaches Retail ECL and the retail staging split."""
    intent = builder.interpret("retail balance")
    assert intent.unavailable == []


# -------------------------------------------------- proposing a new metric


def test_a_proposal_names_only_fields_the_dataset_has():
    proposal = builder.propose("total exposure on the watchlist",
                               domain="Corporate Early Warning")
    assert proposal.dataset
    catalog = builder._catalog()
    fields = builder._fields_of(catalog, proposal.dataset)
    for term in proposal.formula.terms:
        for name in (term.field, term.weight_field):
            if name:
                assert name in fields, name
        for condition in term.where:
            assert condition.field in fields, condition.field


def test_a_proposal_says_what_it_assumed():
    """Every part of it is a guess, and a guess presented as a decision is a
    definition somebody accepts without reading."""
    proposal = builder.propose("total exposure on the watchlist",
                               domain="Corporate Early Warning")
    assert proposal.assumptions
    assert all(a.strip() for a in proposal.assumptions)


def test_a_rate_proposal_gets_a_denominator():
    proposal = builder.propose("watchlist exposure rate",
                               domain="Corporate Early Warning")
    assert proposal.kind in ("percentage", "rate", "ratio")
    assert proposal.formula.denominator is not None
    assert proposal.formula.denominator.terms


def test_a_weighted_average_asks_for_its_weight_rather_than_guessing():
    """Guessing it would change the answer, which is the one thing a builder
    must not do quietly."""
    proposal = builder.propose("weighted average probability of default",
                               domain="Corporate Portfolio")
    assert proposal.kind == "weighted_average"
    assert any("weight" in u.lower() for u in proposal.unresolved)


def test_a_proposal_with_no_domain_asks_which_dataset_rather_than_picking():
    proposal = builder.propose("something nobody has ever measured",
                               domain="A Domain That Does Not Exist")
    assert proposal.unresolved


# ------------------------------------ one definition, three readings

@pytest.fixture
def rate():
    return metrics.resolve("corporate.covenant_breach_rate")


def test_the_english_names_the_steps_in_order(rate):
    steps = builder.plain_english(rate)
    assert len(steps) >= 4
    assert steps[0].startswith("Read every row of portfolio_facility")
    assert any("covenant headroom" in s.lower() for s in steps)
    assert any("multiply by 100" in s.lower() for s in steps)


def test_a_count_counts_rows_rather_than_the_field_its_filter_reads():
    """"How many rows there are in current DPD" reads as though the field
    being filtered on were the thing being counted."""
    steps = builder.plain_english(metrics.resolve("retail.cure_rate_3m"))
    joined = " ".join(steps).lower()
    assert "how many rows there are in current" not in joined
    assert "how many rows there are" in joined


def test_a_function_metric_says_it_is_a_function_rather_than_arithmetic():
    steps = builder.plain_english(metrics.resolve("retail.scorecard.gini"))
    assert any("gini" in s.lower() for s in steps)
    assert any("governed" in s.lower() for s in steps)


@needs_lake
def test_the_sql_is_the_sql_that_will_run(rate):
    """§6 asks for the actual query logic, not a reconstruction of it."""
    shown = builder.compiled_sql(rate)
    assert shown["unavailable"] == ""
    assert "SELECT" in shown["sql"].upper()
    assert "portfolio_facility" in " ".join(shown["datasets"])


@needs_lake
def test_a_filter_value_is_a_parameter_rather_than_text_in_the_sql():
    """The security property, asserted rather than assumed.

    A value that reached the SQL by substitution would be a value somebody
    could type SQL into.
    """
    formula = Formula(
        kind="sum",
        numerator=Side(terms=(
            Term(id="n", label="Exposure", dataset="portfolio_facility",
                 aggregate="sum", field="exposure",
                 where=(Condition("sector", "=", "Healthcare"),)),)))
    from backend.metrics.catalogue import MetricDefinition

    metric = MetricDefinition(metric_id="draft", name="Draft",
                              definition="", formula=formula)
    shown = builder.compiled_sql(metric)
    assert shown["unavailable"] == ""
    assert "Healthcare" not in shown["sql"], (
        "a filter value was written into the SQL rather than bound to it")
    assert "Healthcare" in shown["params"]


@needs_lake
def test_changing_a_threshold_moves_every_reading_of_it(rate):
    """§7. Nothing is stored, so nothing can go stale.

    The SQL TEXT is deliberately unchanged here, and that is the point rather
    than an omission: a threshold is a bound parameter, so moving it from 0 to
    5 changes what is bound and not the query. Which means a screen that shows
    the SQL alone would show a person editing a threshold no change at all —
    so `explain` returns the parameters beside it and the screen has to print
    both. This test holds that contract from the other side.
    """
    from dataclasses import replace

    before = builder.explain(rate)
    edited = replace(rate, formula=Formula(
        kind="percentage",
        numerator=Side(terms=(
            Term(id="b", label="Breached EAD", dataset="portfolio_facility",
                 aggregate="sum", field="exposure",
                 where=(Condition("covenant_headroom_pct", "<", 5),)),)),
        denominator=Side(terms=(
            Term(id="all", label="Total exposure",
                 dataset="portfolio_facility", aggregate="sum",
                 field="exposure"),)),
        scale=100.0), formula_text="")
    after = builder.explain(edited)

    assert after["formula_detail"] != before["formula_detail"]
    assert after["plain_english"] != before["plain_english"]
    assert after["sql_params"] != before["sql_params"]
    # All three describe the SAME new threshold.
    assert "< 5" in after["formula_detail"]
    assert any("below 5" in s for s in after["plain_english"])
    assert "5" in " ".join(after["sql_params"])


@needs_lake
def test_changing_the_shape_of_a_definition_changes_the_query_itself(rate):
    """A structural edit is not a parameter, and must move the SQL text."""
    from dataclasses import replace

    before = builder.explain(rate)
    edited = replace(rate, formula=Formula(
        kind="sum",
        numerator=Side(terms=(
            Term(id="n", label="Undrawn", dataset="portfolio_facility",
                 aggregate="sum", field="undrawn"),)),
    ), formula_text="")
    after = builder.explain(edited)
    assert after["sql"] != before["sql"]
    assert "undrawn" in after["sql"]


# ------------------------------------------------------ the real-data preview


@needs_lake
def test_a_preview_shows_every_step_section_eight_asks_for(rate):
    shown = builder.preview(rate)
    assert shown["dataset"] == "portfolio_facility"
    assert shown["domain"]
    assert shown["grain"]
    assert shown["periods"] and shown["period"] in shown["periods"]
    assert {f["name"] for f in shown["fields"]} >= {"exposure",
                                                    "covenant_headroom_pct"}
    assert shown["aggregations"] == ["sum"]
    assert shown["numerator"] and shown["denominator"]
    assert shown["numerator"][0]["filters"]
    assert shown["numerator_value"] is not None
    assert shown["denominator_value"] is not None
    assert shown["final"]
    assert shown["value"] is not None
    assert shown["formatted"].endswith("%")
    assert shown["rows_considered"] > 0


@needs_lake
def test_a_preview_reproduces_from_its_own_terms(rate):
    """The final figure has to be the arithmetic the preview showed.

    A preview whose parts do not produce its total is worse than no preview:
    somebody checks the parts, they look right, and the number is not from
    them.
    """
    shown = builder.preview(rate)
    top = shown["numerator_value"]
    bottom = shown["denominator_value"]
    assert top / bottom * 100 == pytest.approx(shown["value"], rel=1e-12)


@needs_lake
def test_a_preview_of_a_period_with_no_data_says_so_rather_than_zero(rate):
    shown = builder.preview(rate, period="Q3 1999")
    assert shown["value"] is None
    assert shown["unavailable"]
    assert shown["periods"], "the reader is not told which periods DO exist"


@needs_lake
def test_a_preview_carries_a_sample_of_the_rows_behind_it(rate):
    shown = builder.preview(rate, rows=5)
    assert shown["sample"]["rows"]
    assert len(shown["sample"]["rows"]) <= 5
