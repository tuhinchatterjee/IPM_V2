"""§8's nine checks, and the tenth §8 does not list.

Every rule gets a case that passes and a case that fails, because a validator
tested only on failures is one nobody can tell from a validator that refuses
everything.
"""

from __future__ import annotations

import pytest

from backend.metrics import codeguard as guard
from backend.metrics.composite import Composite, Leg
from backend.metrics.formula import Condition, Formula, Side, Term
from backend.metrics.metric_code import MetricCode

EXPOSURE = Formula(kind="sum", numerator=Side(terms=(
    Term(id="e", label="Exposure", dataset="portfolio_facility",
         aggregate="sum", field="exposure"),)))

STAGE2_RATIO = Formula(
    kind="percentage",
    numerator=Side(terms=(Term(
        id="s2", label="Stage 2", dataset="portfolio_facility",
        aggregate="sum", field="exposure",
        where=(Condition(field="ifrs9_stage", op="=", value=2),)),)),
    denominator=Side(terms=(Term(
        id="all", label="Total", dataset="portfolio_facility",
        aggregate="sum", field="exposure"),)),
    scale=100.0)


def code(**kw) -> MetricCode:
    base = dict(
        name="Test metric", user_formula="a / b",
        interpreted_formula="a / b", unit="percent", language="sql",
        sql=("SELECT SUM(exposure) FILTER (WHERE ifrs9_stage = 2) / "
             "SUM(exposure) AS ratio FROM portfolio_facility WHERE period = ?"),
        formula=STAGE2_RATIO)
    base.update(kw)
    return MetricCode(**base)


# ------------------------------------------------------------ what passes


def test_an_ordinary_ratio_passes_every_check():
    verdict = guard.check(code(), period="Q2 2026")
    assert verdict.ok, [f.message for f in verdict.failures]
    assert verdict.compiled_sql


def test_a_composite_over_two_periods_passes():
    metric = code(
        formula=None, sql=(
            "WITH cur AS (SELECT SUM(exposure) AS e FROM portfolio_facility "
            "WHERE period = ?), prev AS (SELECT SUM(exposure) AS e FROM "
            "portfolio_facility WHERE period = ?) "
            "SELECT cur.e / prev.e - 1 AS qoq FROM cur CROSS JOIN prev"),
        composite=Composite(
            operation="growth",
            numerator=Leg(id="cur", label="Current", formula=EXPOSURE),
            denominator=Leg(id="prev", label="Previous", formula=EXPOSURE,
                            period_offset=1),
            scale=100.0))
    verdict = guard.check(metric, period="Q2 2026")
    assert verdict.ok, [f.message for f in verdict.failures]


# ------------------------------------------------------------ A: domain


def test_a_scorecard_dataset_is_refused_and_is_not_repairable():
    """A model asking for another product's domain does not need another try
    at writing a query."""
    metric = code(
        sql="SELECT AVG(gini) FROM pd_model_performance",
        formula=Formula(kind="average", numerator=Side(terms=(
            Term(id="g", label="Gini", dataset="pd_model_performance",
                 aggregate="avg", field="gini"),))))
    verdict = guard.check(metric, period="Q2 2026")
    assert not verdict.ok
    domain = [f for f in verdict.failures if f.rule == guard.RULE_DOMAIN]
    assert domain
    assert not domain[0].repairable
    assert not verdict.repairable


# -------------------------------------------------------- B: permission


def test_a_dataset_outside_the_readable_set_is_refused():
    verdict = guard.check(code(), period="Q2 2026", readable=["ifrs9_staging"])
    assert any(f.rule == guard.RULE_PERMISSION for f in verdict.failures)


def test_no_readable_restriction_means_no_permission_failure():
    verdict = guard.check(code(), period="Q2 2026", readable=None)
    assert not any(f.rule == guard.RULE_PERMISSION for f in verdict.failures)


# ------------------------------------------------------------- C: fields


def test_a_field_that_does_not_exist_is_refused_with_the_ones_that_do():
    """§9's own example. A model told only that a field is missing picks
    another missing one about as often as not."""
    metric = code(
        sql="SELECT SUM(p.ead_amount) FROM portfolio_facility p",
        formula=Formula(kind="sum", numerator=Side(terms=(
            Term(id="e", label="EAD", dataset="portfolio_facility",
                 aggregate="sum", field="ead_amount"),))))
    verdict = guard.check(metric, period="Q2 2026")
    failures = [f for f in verdict.failures if f.rule == guard.RULE_FIELD]
    assert failures
    hints = failures[0].hints
    assert hints["dataset"] == "portfolio_facility"
    assert hints["related_fields"], "a repair round with no candidates guesses"
    assert "exposure" in hints["available_fields"]


# --------------------------------------------------------------- E: joins


def test_an_ungoverned_join_between_two_base_tables_is_refused():
    metric = code(
        sql=("SELECT SUM(p.exposure) FROM portfolio_facility p "
             "JOIN watchlist_register w ON p.customer_id = w.customer_id"),
        formula=EXPOSURE, unit="currency")
    verdict = guard.check(metric, period="Q2 2026")
    assert any(f.rule == guard.RULE_JOIN for f in verdict.failures)


def test_a_composite_cross_join_of_two_ctes_is_not_a_join():
    """Two aggregates divided cannot fan out. Refusing this would refuse the
    shape §14 asks the builder to prefer."""
    watchlist = Formula(kind="sum", numerator=Side(terms=(
        Term(id="w", label="Watchlist EAD", dataset="watchlist_register",
             aggregate="sum", field="total_ead"),)))
    metric = code(
        formula=None,
        sql=("WITH numerator AS (SELECT SUM(total_ead) AS value FROM "
             "watchlist_register WHERE period = ?), denominator AS (SELECT "
             "SUM(exposure) AS value FROM portfolio_facility WHERE period = ?) "
             "SELECT numerator.value / denominator.value AS share "
             "FROM numerator CROSS JOIN denominator"),
        composite=Composite(
            operation="ratio",
            numerator=Leg(id="numerator", label="Watchlist",
                          formula=watchlist),
            denominator=Leg(id="denominator", label="Total",
                            formula=EXPOSURE),
            scale=100.0))
    verdict = guard.check(metric, period="Q2 2026")
    assert not any(f.rule == guard.RULE_JOIN for f in verdict.failures), \
        [f.message for f in verdict.failures]


# ------------------------------------------------------------ F: temporal


def test_a_period_before_the_book_starts_is_refused_with_the_range():
    metric = code(
        formula=None, sql="SELECT 1 / 1 AS x FROM portfolio_facility",
        composite=Composite(
            operation="growth",
            numerator=Leg(id="a", label="Now", formula=EXPOSURE),
            denominator=Leg(id="b", label="Then", formula=EXPOSURE,
                            period_offset=16),
            scale=100.0))
    verdict = guard.check(metric, period="Q2 2026")
    failures = [f for f in verdict.failures if f.rule == guard.RULE_TEMPORAL]
    assert failures
    assert failures[0].hints.get("periods")


# -------------------------------------------------------- G: mathematical


def test_a_ratio_reported_as_currency_is_refused():
    """Dividing an amount by the same kind of thing gives a share. A metric
    that says otherwise is off by whatever the denominator was."""
    verdict = guard.check(code(unit="currency"), period="Q2 2026")
    assert any(f.rule == guard.RULE_MATH for f in verdict.failures)


def test_a_ratio_multiplied_by_a_hundred_must_say_it_is_a_percentage():
    verdict = guard.check(code(unit="ratio"), period="Q2 2026")
    assert any("percentage" in f.message for f in verdict.failures
               if f.rule == guard.RULE_MATH)


def test_a_filtered_denominator_is_warned_about_not_refused():
    """A zero denominator is a real state of a book. Worth saying; not worth
    refusing."""
    metric = code(formula=Formula(
        kind="percentage",
        numerator=Side(terms=(Term(
            id="a", label="Stage 3", dataset="portfolio_facility",
            aggregate="sum", field="exposure",
            where=(Condition(field="ifrs9_stage", op="=", value=3),)),)),
        denominator=Side(terms=(Term(
            id="b", label="Watchlist", dataset="portfolio_facility",
            aggregate="sum", field="exposure",
            where=(Condition(field="watchlist", op="=", value=True),)),)),
        scale=100.0),
        sql=("SELECT SUM(exposure) FILTER (WHERE ifrs9_stage = 3) / "
             "SUM(exposure) FILTER (WHERE watchlist) AS share "
             "FROM portfolio_facility WHERE period = ?"))
    verdict = guard.check(metric, period="Q2 2026")
    assert verdict.ok, [f.message for f in verdict.failures]
    assert any("zero" in w.message for w in verdict.warnings)


def test_a_rate_divided_by_an_amount_is_refused():
    """The most plausible-looking wrong metric there is: a percentage over
    billions renders as 0.00% and is not obviously wrong to anybody."""
    metric = code(
        formula=None,
        sql=("WITH a AS (SELECT 1 AS value), b AS (SELECT 2 AS value) "
             "SELECT a.value / b.value AS x FROM a CROSS JOIN b"),
        composite=Composite(
            operation="ratio",
            numerator=Leg(id="n", label="Breach rate",
                          metric_id="corporate.covenant_breach_rate"),
            denominator=Leg(id="d", label="Exposure",
                            metric_id="corporate.exposure"),
            scale=100.0))
    verdict = guard.check(metric, period="Q2 2026")
    assert any("share over an amount" in f.message
               for f in verdict.failures if f.rule == guard.RULE_MATH), \
        [f.message for f in verdict.failures]


# ------------------------------------------------------- I: python safety


@pytest.mark.parametrize("source", [
    "import os\nresult = os.popen('ls').read()",
    "result = open('/etc/passwd').read()",
    "result = __import__('subprocess').run(['ls'])",
    "result = getattr(__builtins__, 'op' + 'en')('/etc/passwd')",
    "import socket\nresult = socket.socket()",
])
def test_python_that_reaches_outside_is_refused(source):
    metric = code(language="python", python=source, sql="")
    verdict = guard.check(metric, period="Q2 2026")
    assert any(f.rule == guard.RULE_PYTHON for f in verdict.failures), source


def test_ordinary_analytical_python_passes_the_python_check():
    metric = code(language="python", sql="",
                  python="result = frame['exposure'].sum()")
    verdict = guard.check(metric, period="Q2 2026")
    assert not any(f.rule == guard.RULE_PYTHON for f in verdict.failures)


def test_python_that_does_not_parse_says_where():
    metric = code(language="python", sql="", python="result = (")
    verdict = guard.check(metric, period="Q2 2026")
    assert any("does not parse" in f.message for f in verdict.failures)


# ---------------------------------------------------- the tenth: reconcile


def test_sql_that_divides_when_the_calculation_does_not_is_refused():
    metric = code(
        sql="SELECT SUM(exposure) / COUNT(*) FROM portfolio_facility",
        formula=EXPOSURE, unit="currency")
    verdict = guard.check(metric, period="Q2 2026")
    assert any("SQL divides and the calculation does not" in f.message
               for f in verdict.failures)


def test_a_calculation_that_divides_when_the_sql_does_not_is_refused():
    metric = code(sql="SELECT SUM(exposure) FROM portfolio_facility")
    verdict = guard.check(metric, period="Q2 2026")
    assert any("contains no division" in f.message
               for f in verdict.failures)


def test_sql_and_calculation_reading_different_datasets_is_refused():
    metric = code(sql=("SELECT SUM(ead) / SUM(ead) AS x FROM ifrs9_staging "
                       "WHERE period = ?"))
    verdict = guard.check(metric, period="Q2 2026")
    assert any(f.rule == guard.RULE_RECONCILE for f in verdict.failures)


def test_a_field_the_calculation_uses_and_the_sql_omits_is_refused():
    metric = code(sql=("SELECT SUM(exposure) / SUM(exposure) AS ratio "
                       "FROM portfolio_facility WHERE period = ?"))
    verdict = guard.check(metric, period="Q2 2026")
    assert any("ifrs9_stage" in f.message for f in verdict.failures
               if f.rule == guard.RULE_RECONCILE)


# ------------------------------------------------------------- the packet


def test_every_check_runs_even_after_one_fails():
    """§9's repair packet is only worth a round trip if it carries the whole
    picture."""
    metric = code(
        unit="currency",
        sql="SELECT SUM(p.ead_amount) FROM portfolio_facility p; DROP TABLE x",
        formula=Formula(kind="sum", numerator=Side(terms=(
            Term(id="e", label="EAD", dataset="portfolio_facility",
                 aggregate="sum", field="ead_amount"),))))
    verdict = guard.check(metric, period="Q2 2026")
    rules = {f.rule for f in verdict.failures}
    assert guard.RULE_SQL in rules
    assert guard.RULE_FIELD in rules
    assert len(rules) >= 2


def test_the_packet_carries_the_hints_a_repair_needs():
    metric = code(
        sql="SELECT SUM(p.ead_amount) FROM portfolio_facility p",
        formula=Formula(kind="sum", numerator=Side(terms=(
            Term(id="e", label="EAD", dataset="portfolio_facility",
                 aggregate="sum", field="ead_amount"),))))
    packet = guard.check(metric, period="Q2 2026").packet()
    assert packet["failed"]
    assert any(f["hints"].get("related_fields") for f in packet["failed"])


def test_a_metric_with_no_program_is_refused_whatever_the_sql_says():
    metric = code(formula=None, composite=None)
    verdict = guard.check(metric, period="Q2 2026")
    assert any("no execution program" in f.message for f in verdict.failures)
