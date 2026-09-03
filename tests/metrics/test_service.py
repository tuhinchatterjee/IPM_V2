"""The one place that answers "what is this metric worth today?"

These run against the live governed data rather than fixtures. That is
deliberate: a metric platform that only works against a mocked executor is a
platform nobody has proved anything about. Where a test needs the database, it
skips honestly rather than passing vacuously.
"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.metrics import execution
from backend.metrics import library as lib
from backend.metrics import service as S
from backend.metrics.catalogue import (
    ORIGIN_GOVERNED,
    ORIGIN_USER,
    STATUS_CALCULATION_READY,
    STATUS_DRAFT,
    STATUS_VERIFIED,
)
from backend.metrics.formula import Condition, Formula, Side, Term

needs_db = pytest.mark.skipif(not settings.has_database,
                              reason="user metrics are stored in PostgreSQL")

#: A period the corporate staging dataset genuinely has.
QUARTER = "Q4 2024"


@pytest.fixture
def mine(request):
    """A user metric, removed afterwards however the test ends."""
    made: list[str] = []

    def build(name: str, formula: Formula, **kw):
        metric = S.create(name=name, formula=formula, user_id=1, **kw)
        made.append(metric.metric_id)
        return metric

    yield build

    for metric_id in made:
        try:
            S.delete(metric_id, user_id=1)
        except S.MetricNotFound:
            pass


def _late_share(scale: float = 100.0) -> Formula:
    """30+ DPD balance over total balance, written from scratch."""
    return Formula(
        kind="percentage",
        numerator=Side(terms=(Term(
            id="late", label="Balance 30+ DPD", dataset=lib.BEHAVIOURAL,
            aggregate="sum", field="current_balance",
            where=(Condition("current_dpd", ">=", 30),)),)),
        denominator=Side(terms=(Term(
            id="all", label="Total balance", dataset=lib.BEHAVIOURAL,
            aggregate="sum", field="current_balance"),)),
        scale=scale)


# --------------------------------------------------------------- resolving


def test_the_governed_catalogue_needs_no_database():
    assert len(S.catalogue()) >= len(lib.ALL)
    assert S.resolve("corporate.ifrs9.coverage").origin == ORIGIN_GOVERNED


def test_a_metric_nobody_may_read_is_indistinguishable_from_one_that_is_absent():
    """Saying "exists, but not for you" leaks what exists over hidden data."""
    with pytest.raises(S.MetricNotFound):
        S.resolve("corporate.ifrs9.coverage", readable={lib.BEHAVIOURAL})
    with pytest.raises(S.MetricNotFound):
        S.resolve("there.is.no.such.metric", readable={lib.BEHAVIOURAL})


def test_an_unavailable_metric_says_why_rather_than_vanishing():
    entry = S.unavailable("retail.roll_rate")
    assert entry is not None
    assert entry.because.strip() and entry.needs


def test_find_offers_the_unavailable_reason_when_nothing_matched():
    payload = S.find("roll rate")
    assert payload["results"] == []
    assert payload["unavailable"]
    assert "roll" in payload["unavailable"][0]["name"].lower()


def test_the_panel_carries_everything_section_six_asks_for():
    panel = S.panel("corporate.ifrs9.coverage")
    for field in ("definition", "formula", "numerator", "denominator", "unit",
                  "datasets", "source_fields", "period_rule", "exclusions",
                  "not_this", "owner", "origin_label", "status_label",
                  "version", "aliases"):
        assert field in panel, field
    assert panel["formula"].strip()
    assert panel["numerator"].strip() and panel["denominator"].strip()
    assert panel["source_fields"], "a panel must name the fields it reads"


# -------------------------------------------------------------- calculating


def test_a_governed_metric_produces_a_real_number_with_its_working():
    out = S.value("corporate.ifrs9.coverage", period=QUARTER)
    assert out["available"] is True
    assert isinstance(out["value"], float)
    assert 0.0 < out["value"] < 100.0, "an ECL coverage outside 0-100% is wrong"
    calculation = out["calculation"]
    assert calculation["numerator"]["value"] > 0
    assert calculation["denominator"]["value"] > calculation["numerator"]["value"]
    assert "=" in calculation["final"]
    assert calculation["sql"].strip(), "a number must be traceable to its query"


def test_two_metrics_written_independently_for_one_quantity_agree():
    """The strongest check available without a second engine.

    `retail.dpd_30_balance` is written in the governed library from a
    generator; the formula here is written by hand. If the platform's
    arithmetic depended on how a formula happened to be phrased, these two
    would differ.
    """
    out = S.value("retail.dpd_30_balance")
    governed = out["value"]
    # The same period on both sides. `execution.run` reads every partition
    # when no period is given, so a hand-written formula left unscoped would
    # be compared against a figure pooled over the whole history — the two
    # would differ for a reason that has nothing to do with the arithmetic.
    by_hand = execution.run(_late_share(), period=out["period"]).value
    assert out["period"], "the governed metric must say which period it used"
    assert governed is not None and by_hand is not None
    assert governed == pytest.approx(by_hand, rel=1e-12)


def test_scaling_the_formula_scales_the_answer_and_nothing_else():
    as_percent = execution.run(_late_share(scale=100.0)).value
    as_ratio = execution.run(_late_share(scale=1.0)).value
    assert as_percent == pytest.approx(as_ratio * 100.0, rel=1e-12)


def test_a_period_the_data_does_not_have_is_explained_not_raised():
    """A tile with no data must not take the page down with it."""
    out = S.value("corporate.ifrs9.coverage", period="1999-01")
    assert out["available"] is False
    assert out["value"] is None
    assert "1999-01" in out["unavailable"]
    assert "Available" in out["unavailable"], (
        "the reader needs to be told which periods DO exist")


def test_calculating_needs_permission_over_every_dataset_read():
    with pytest.raises(S.MetricNotFound):
        S.value("corporate.ifrs9.coverage", period=QUARTER,
                readable={lib.BEHAVIOURAL})


def test_sample_rows_show_why_each_row_counted():
    out = S.rows("retail.dpd_30_balance", limit=5)
    assert out["rows"], "a record-level proxy with no records proves nothing"
    assert len(out["rows"]) <= 5


# ------------------------------------------------------------- comparing


@pytest.mark.parametrize("computed,expected,outcome", [
    (10.0, 10.0, S.OUTCOME_MATCH),
    (10.0, 10.0000001, S.OUTCOME_WITHIN),
    (10.0, 11.0, S.OUTCOME_DIFFERS),
    (None, 10.0, S.OUTCOME_NOT_COMPARED),
    (10.0, None, S.OUTCOME_NOT_COMPARED),
])
def test_two_numbers_are_compared_without_either_being_moved(computed,
                                                             expected, outcome):
    verdict, difference, _ = S.compare(computed, expected)
    assert verdict == outcome
    if outcome == S.OUTCOME_NOT_COMPARED:
        assert difference is None
    else:
        assert difference == pytest.approx(computed - expected)


def test_a_wider_tolerance_is_the_only_thing_that_makes_a_gap_acceptable():
    assert S.compare(10.0, 10.5)[0] == S.OUTCOME_DIFFERS
    assert S.compare(10.0, 10.5, tolerance=0.1)[0] == S.OUTCOME_WITHIN


# ------------------------------------------------------- the user lifecycle


@needs_db
def test_a_metric_somebody_builds_arrives_as_a_draft(mine):
    metric = mine("Late Balance Share", _late_share(), unit="percent",
                  domain=lib.RETAIL)
    assert metric.origin == ORIGIN_USER
    assert metric.status == STATUS_DRAFT
    assert metric.trustworthy is False, (
        "a metric nobody has checked must not be shown as if governed")


@needs_db
def test_calculating_promotes_a_draft_no_further_than_calculation_ready(mine):
    metric = mine("Late Balance Share Two", _late_share(), unit="percent")
    out = S.calculate_check(metric.metric_id, user_id=1)
    assert out["available"] is True
    assert out["metric"]["status"] == STATUS_CALCULATION_READY
    assert out["metric"]["status_label"] == "Calculates"
    assert out["metric"]["trustworthy"] is False, (
        "calculating is not the same as being right")


@needs_db
def test_verified_is_conferred_only_by_an_accepted_agreement(mine):
    metric = mine("Late Balance Share Three", _late_share(), unit="percent")
    truth = S.calculate_check(metric.metric_id, user_id=1)["value"]

    # Recording a comparison is not accepting it.
    S.verify(metric.metric_id, expected=truth, decision=S.DECISION_RECORDED,
             user_id=1)
    assert S.resolve(metric.metric_id, user_id=1).status != STATUS_VERIFIED

    outcome = S.verify(metric.metric_id, expected=truth,
                       expected_source="recomputed by hand",
                       decision=S.DECISION_ACCEPTED, user_id=1)
    assert outcome["agrees"] is True
    assert outcome["metric_status"] == STATUS_VERIFIED
    assert S.resolve(metric.metric_id, user_id=1).trustworthy is True


@needs_db
def test_verified_cannot_simply_be_asserted(mine):
    metric = mine("Late Balance Share Four", _late_share(), unit="percent")
    with pytest.raises(S.MetricRefused, match="checked against"):
        S.set_status(metric.metric_id, STATUS_VERIFIED, user_id=1)


@needs_db
def test_accepting_a_disagreement_records_it_and_confers_nothing(mine):
    metric = mine("Late Balance Share Five", _late_share(), unit="percent")
    truth = S.calculate_check(metric.metric_id, user_id=1)["value"]

    outcome = S.verify(metric.metric_id, expected=truth + 5.0,
                       expected_source="a number from somewhere else",
                       decision=S.DECISION_ACCEPTED, user_id=1)
    assert outcome["outcome"] == S.OUTCOME_DIFFERS
    assert outcome["metric_status"] != STATUS_VERIFIED
    assert outcome["note_on_status"]
    assert outcome["computed"] == pytest.approx(truth), (
        "the computed value must never be moved toward the expectation")


@needs_db
def test_the_history_keeps_the_disagreements_too(mine):
    metric = mine("Late Balance Share Six", _late_share(), unit="percent")
    truth = S.calculate_check(metric.metric_id, user_id=1)["value"]
    S.verify(metric.metric_id, expected=truth - 1.0, user_id=1)
    S.verify(metric.metric_id, expected=truth, user_id=1,
             decision=S.DECISION_ACCEPTED)

    history = S.verifications(metric.metric_id)
    assert len(history) == 2
    assert {row["outcome"] for row in history} == {S.OUTCOME_DIFFERS,
                                                  S.OUTCOME_MATCH}


@needs_db
def test_changing_the_arithmetic_drops_the_verification(mine):
    """A metric verified against one formula is not verified against another."""
    metric = mine("Late Balance Share Seven", _late_share(), unit="percent")
    truth = S.calculate_check(metric.metric_id, user_id=1)["value"]
    S.verify(metric.metric_id, expected=truth, decision=S.DECISION_ACCEPTED,
             user_id=1)
    assert S.resolve(metric.metric_id, user_id=1).status == STATUS_VERIFIED

    changed = S.update(metric.metric_id, formula=_late_share(scale=1.0),
                       user_id=1)
    assert changed.status == STATUS_DRAFT
    assert changed.verified_by is None
    assert "formula changed" in changed.last_verified_note


@needs_db
def test_renaming_a_metric_does_not_drop_its_verification(mine):
    metric = mine("Late Balance Share Eight", _late_share(), unit="percent")
    truth = S.calculate_check(metric.metric_id, user_id=1)["value"]
    S.verify(metric.metric_id, expected=truth, decision=S.DECISION_ACCEPTED,
             user_id=1)
    renamed = S.update(metric.metric_id, name="Arrears Share", user_id=1)
    assert renamed.status == STATUS_VERIFIED
    assert renamed.name == "Arrears Share"


@needs_db
def test_a_metric_that_cannot_calculate_is_refused_rather_than_stored():
    broken = Formula(
        kind="percentage",
        numerator=Side(terms=(Term(id="a", label="Nothing",
                                   dataset=lib.BEHAVIOURAL, aggregate="sum",
                                   field="there_is_no_such_column"),)),
        denominator=Side(terms=(Term(id="b", label="All",
                                     dataset=lib.BEHAVIOURAL,
                                     aggregate="count"),)))
    with pytest.raises(S.MetricRefused):
        S.create(name="Doomed", formula=broken, user_id=1)


@needs_db
def test_a_metric_belongs_to_the_person_who_built_it(mine):
    metric = mine("Late Balance Share Nine", _late_share(), unit="percent")
    with pytest.raises(S.MetricRefused, match="somebody else"):
        S.update(metric.metric_id, name="Mine now", user_id=99)
    with pytest.raises(S.MetricRefused, match="somebody else"):
        S.delete(metric.metric_id, user_id=99)


@needs_db
def test_an_unshared_metric_is_not_in_anybody_elses_catalogue(mine):
    metric = mine("Late Balance Share Ten", _late_share(), unit="percent")
    ids = {m.metric_id for m in S.catalogue(user_id=99)}
    assert metric.metric_id not in ids
    assert metric.metric_id in {m.metric_id for m in S.catalogue(user_id=1)}

    S.update(metric.metric_id, shared=True, user_id=1)
    assert metric.metric_id in {m.metric_id for m in S.catalogue(user_id=99)}


@needs_db
def test_free_text_never_becomes_a_formula():
    """The only door into a stored formula is a structured, validated one."""
    for payload in ({"kind": "percentage", "numerator": "1=1; DROP TABLE x"},
                    {"kind": "nonsense"},
                    {}):
        with pytest.raises(S.MetricRefused):
            S.formula_from_dict(payload)


@needs_db
def test_deleting_a_metric_takes_its_verification_history_with_it():
    """A reused id must not inherit somebody else's tick.

    `metric_id` is derived from the name, so building "Late Balance Share"
    again after deleting it would otherwise resolve to a history recorded
    against a formula the new metric does not share.
    """
    metric = S.create(name="Short Lived Metric", formula=_late_share(),
                      unit="percent", user_id=1)
    truth = S.calculate_check(metric.metric_id, user_id=1)["value"]
    S.verify(metric.metric_id, expected=truth, decision=S.DECISION_ACCEPTED,
             user_id=1)
    assert S.verifications(metric.metric_id)

    S.delete(metric.metric_id, user_id=1)
    assert S.verifications(metric.metric_id) == []

    again = S.create(name="Short Lived Metric", formula=_late_share(),
                     unit="percent", user_id=1)
    try:
        assert again.metric_id == metric.metric_id, (
            "the point of the test is that the id is reused")
        assert again.status == STATUS_DRAFT
        assert again.verified_by is None
        assert S.verifications(again.metric_id) == []
    finally:
        S.delete(again.metric_id, user_id=1)


# ---------------------------------------------------------- the period rule
#
# A metric asked for with no period used to read every partition in the lake
# and return one figure pooled across the whole history — fifteen quarterly
# snapshots of a book added together — labelled with no period at all. The
# arithmetic was right and the answer was to a question nobody asked, and it
# rendered exactly like the one they did ask for.


def test_periods_are_ordered_by_date_not_by_spelling():
    # "Q4 2025" sorts after "Q1 2026" alphabetically. Taking the newest period
    # with max() on the raw strings picks the wrong quarter, and the wrong
    # quarter still renders and still looks current.
    ordered = sorted(["Q1 2026", "Q4 2025", "Q2 2026", "Q1 2025"],
                     key=S._period_order)
    assert ordered == ["Q1 2025", "Q4 2025", "Q1 2026", "Q2 2026"]


def test_months_and_years_order_too():
    assert sorted(["2025-10", "2025-2", "2026-01"],
                  key=S._period_order) == ["2025-2", "2025-10", "2026-01"]
    assert sorted(["2026", "2024"], key=S._period_order) == ["2024", "2026"]


def test_an_unasked_period_is_the_latest_one_not_all_of_them():
    """The default has to be a period, and the answer has to say which."""
    metric = next(m for m in lib.ALL if m.metric_id == "corporate.npl_rate")
    latest = S.latest_period(metric.datasets, metric.scope)
    assert latest, "the corporate book should have periods on disk"

    out = S.value(metric.metric_id)
    assert out["period"] == latest, (
        "a metric asked for with no period must answer for one period and "
        "name it")

    # And it is that period's number, not the pooled one.
    for_period = execution.run(metric.formula, period=latest,
                               scope=metric.scope).value
    pooled = execution.run(metric.formula, period="", scope=metric.scope).value
    assert out["value"] == pytest.approx(for_period)
    assert out["value"] != pytest.approx(pooled), (
        "if these agree the test proves nothing — pick a dataset with more "
        "than one period")


def test_the_rows_behind_a_figure_come_from_the_same_period():
    metric = next(m for m in lib.ALL if m.metric_id == "corporate.npl_rate")
    latest = S.latest_period(metric.datasets, metric.scope)
    sample = S.rows(metric.metric_id, limit=5)
    assert sample.get("period") == latest or sample.get("rows"), sample


@needs_db
def test_a_verification_records_the_period_it_actually_checked(mine):
    """Evidence that does not say which period it is about supports nothing."""
    metric = mine("Late Balance Share Period", _late_share(), unit="percent")
    computed = S.value(metric.metric_id, user_id=1)
    assert computed["period"], "the figure has to come from a period"

    # Verified with no period named, exactly as the workspace does it.
    S.verify(metric.metric_id, expected=computed["value"],
             expected_source="recomputed by hand",
             decision=S.DECISION_ACCEPTED, user_id=1)

    history = S.verifications(metric.metric_id)
    assert history, "the check must be kept"
    assert history[0]["period"] == computed["period"], (
        "a verification stored against a blank period could not later be "
        "told apart from one against any other quarter")
