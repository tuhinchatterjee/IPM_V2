"""Many metrics, one scan — and the same numbers.

§21 asks that a lens does not rescan its dataset once per tile. The risk in
answering that is obvious and worth stating: a second, faster path to a number
is a second place for the number to be wrong, and the fast path is the one
nobody checks because it only runs on a busy page.

So the batch is not a second calculation. Every term of every metric becomes a
conditional aggregate over one scan — the same trick a single metric already
uses on its own terms — and each metric's value still comes out of `evaluate`
over its own terms. These tests hold the two paths to that: same numbers,
fewer reads, and a metric that cannot share is not made to.
"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.metrics import execution
from backend.metrics import lenses as shipped
from backend.metrics import service as metrics

needs_lake = pytest.mark.skipif(
    not settings.analytics_dir or not settings.has_database,
    reason="needs the analytics lake")

QUARTER = "Q2 2026"

IFRS9 = ("corporate.ifrs9.total_ead", "corporate.ifrs9.total_ecl",
         "corporate.ifrs9.coverage", "corporate.ifrs9.stage1_ead",
         "corporate.ifrs9.stage2_ead", "corporate.ifrs9.stage3_ead",
         "corporate.ifrs9.stage2_share", "corporate.ifrs9.new_default_rate",
         "corporate.ifrs9.cure_rate", "corporate.ifrs9.weighted_pd")


# ------------------------------------------------------- what may share


def test_a_function_metric_never_joins_a_batch():
    """A Gini is not an aggregate, and cannot come out of a summary row.

    `evaluate` refuses to compute one from aggregates, so a function metric
    that reached the batch would come back unavailable rather than wrong — but
    it would come back unavailable on a lens where it works today, which is
    just as bad.
    """
    gini = metrics.resolve("retail.scorecard.gini")
    assert execution.batch_key(gini.formula, "2025-01", gini.scope) is None


def test_two_metrics_over_the_same_dataset_and_scope_may_share():
    a = metrics.resolve("corporate.ifrs9.total_ead")
    b = metrics.resolve("corporate.ifrs9.stage2_share")
    assert (execution.batch_key(a.formula, QUARTER, a.scope)
            == execution.batch_key(b.formula, QUARTER, b.scope) is not None)


def test_a_different_scope_is_a_different_batch():
    """A metric's scope filters the whole scan, so two scopes are two reads.

    This is the property that stops a scoped metric being computed over a
    population it does not belong to — which would be silently wrong rather
    than slow.
    """
    plain = metrics.resolve("retail.accounts")
    scoped = metrics.resolve("retail.scorecard.matured")
    assert scoped.scope and not plain.scope
    assert (execution.batch_key(plain.formula, "2025-07", plain.scope)
            != execution.batch_key(scoped.formula, "2025-07", scoped.scope))


def test_a_different_period_is_a_different_batch():
    metric = metrics.resolve("corporate.ifrs9.total_ead")
    assert (execution.batch_key(metric.formula, "Q1 2026", metric.scope)
            != execution.batch_key(metric.formula, QUARTER, metric.scope))


def test_a_different_dataset_is_a_different_batch():
    corporate = metrics.resolve("corporate.ifrs9.total_ead")
    retail = metrics.resolve("retail.balance")
    assert (execution.batch_key(corporate.formula, "", corporate.scope)
            != execution.batch_key(retail.formula, "", retail.scope))


# ------------------------------------------------------------ compiling


def test_the_batch_gives_every_term_its_own_name():
    """Term ids are unique within one metric and not between them.

    Six metrics on the IFRS 9 lens call their denominator `all`. Two
    aggregates sharing an output name is a silently wrong answer rather than
    an error, so the plan names them itself.
    """
    formulas = {m: metrics.resolve(m).formula for m in IFRS9}
    plan, aliases = execution.compile_batch(formulas, period=QUARTER)

    measures = next(op for op in plan.operations
                    if op.id == "measure").params["measures"]
    names = [m["as"] for m in measures]
    assert len(names) == len(set(names)), "two aggregates share an output name"

    # Every term of every metric is addressed, and by a name in the plan.
    for metric_id, formula in formulas.items():
        for term in formula.terms:
            assert (metric_id, term.id) in aliases
            assert aliases[(metric_id, term.id)] in names


def test_an_aggregate_wanted_twice_is_written_once():
    """Nine metrics divide by SUM(ead). Computing it nine times in one query
    would trade N scans for one scan doing N times the arithmetic."""
    formulas = {m: metrics.resolve(m).formula for m in IFRS9}
    plan, aliases = execution.compile_batch(formulas, period=QUARTER)
    measures = next(op for op in plan.operations
                    if op.id == "measure").params["measures"]
    terms = sum(len(f.terms) for f in formulas.values())
    assert len(measures) < terms + 1, (
        "no aggregate was shared, though several metrics divide by SUM(ead)")


def test_a_batch_over_two_datasets_is_refused():
    formulas = {"a": metrics.resolve("corporate.ifrs9.total_ead").formula,
                "b": metrics.resolve("retail.balance").formula}
    with pytest.raises(Exception, match="same dataset"):
        execution.compile_batch(formulas, period=QUARTER)


# -------------------------------------------------------------- running


@needs_lake
def test_a_batched_figure_is_the_figure_it_would_have_been():
    """The assertion this whole file exists for."""
    formulas = {m: metrics.resolve(m).formula for m in IFRS9}
    scope = metrics.resolve(IFRS9[0]).scope
    batched = execution.run_batch(formulas, period=QUARTER, scope=scope)

    for metric_id in IFRS9:
        metric = metrics.resolve(metric_id)
        alone = execution.run(metric.formula, period=QUARTER,
                              scope=metric.scope)
        assert batched[metric_id].value == pytest.approx(alone.value,
                                                         rel=1e-12), metric_id


@needs_lake
def test_a_batched_figure_keeps_its_working():
    """A tile that cannot show its numerator is a tile nobody trusts."""
    formulas = {m: metrics.resolve(m).formula
                for m in ("corporate.ifrs9.coverage",
                          "corporate.ifrs9.new_default_rate")}
    batched = execution.run_batch(formulas, period=QUARTER)
    for calculation in batched.values():
        shown = calculation.to_dict()
        assert shown["numerator"]["terms"]
        assert shown["denominator"]["terms"]
        assert all(t["value"] is not None
                   for t in shown["numerator"]["terms"])
        assert shown["rows_considered"] > 0


@needs_lake
def test_a_batched_figure_says_it_was_read_with_others():
    """A trace that hid the sharing would misdescribe the query it names."""
    formulas = {m: metrics.resolve(m).formula for m in IFRS9[:3]}
    batched = execution.run_batch(formulas, period=QUARTER)
    for calculation in batched.values():
        assert any("one pass" in w for w in calculation.warnings)
        assert calculation.sql


@needs_lake
def test_a_lens_worth_of_metrics_costs_one_read():
    """§21, stated as a number rather than as an intention."""
    ids = list(shipped.CORPORATE_IFRS9.metric_ids)
    answer = metrics.values(ids, period=QUARTER)
    assert answer["would_have_been"] == len(ids) > 20
    assert answer["reads"] == 1


@needs_lake
def test_values_and_value_agree_metric_for_metric():
    ids = list(shipped.CORPORATE_IFRS9.metric_ids)
    together = metrics.values(ids, period=QUARTER)["metrics"]
    for metric_id in ids:
        alone = metrics.value(metric_id, period=QUARTER)
        assert together[metric_id]["value"] == pytest.approx(
            alone["value"], rel=1e-12), metric_id
        assert together[metric_id]["period"] == alone["period"]
        assert together[metric_id]["unit"] == alone["unit"]


@needs_lake
def test_a_metric_that_does_not_exist_does_not_take_the_others_with_it():
    """A lens naming a deleted metric should lose that tile, not the page."""
    answer = metrics.values(
        ["corporate.ifrs9.total_ead", "corporate.ifrs9.invented",
         "corporate.ifrs9.coverage"], period=QUARTER)
    assert answer["metrics"]["corporate.ifrs9.invented"]["value"] is None
    assert answer["metrics"]["corporate.ifrs9.invented"]["unavailable"]
    assert answer["metrics"]["corporate.ifrs9.total_ead"]["value"] > 0
    assert answer["metrics"]["corporate.ifrs9.coverage"]["value"] > 0


@needs_lake
def test_metrics_on_two_datasets_are_two_reads_not_one_and_not_many():
    ids = ["corporate.ifrs9.total_ead", "corporate.ifrs9.coverage",
           "retail.balance", "retail.accounts"]
    answer = metrics.values(ids, period="")
    assert answer["reads"] == 2, "one read per dataset, not one per metric"
    assert all(answer["metrics"][m]["value"] is not None for m in ids)


@needs_lake
def test_asking_for_one_metric_is_still_one_metric():
    """The single-metric path must not become a special case that drifts."""
    answer = metrics.values(["corporate.ifrs9.coverage"], period=QUARTER)
    alone = metrics.value("corporate.ifrs9.coverage", period=QUARTER)
    assert answer["metrics"]["corporate.ifrs9.coverage"]["value"] == (
        alone["value"])


@needs_lake
def test_every_tile_on_a_lens_lands_on_the_same_period():
    """Resolved once per source, not once per tile.

    Two tiles that resolved separately could land on different periods, and an
    IFRS 9 lens whose stage exposures are meant to sum to its total would stop
    summing to it.
    """
    ids = list(shipped.CORPORATE_IFRS9.metric_ids)
    answer = metrics.values(ids)["metrics"]
    assert len({answer[m]["period"] for m in ids}) == 1
