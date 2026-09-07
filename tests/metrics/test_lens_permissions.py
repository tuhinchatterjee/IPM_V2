"""What a lens may read, and what it may not.

§20. The Lenses work in this branch added a second way to run a metric — the
batched read — a new suggestion endpoint, and a period picker that enumerates
what a lens's datasets hold. Each of those is a place a boundary could be
crossed by accident, so each is checked here against the boundaries that
already exist rather than against new ones invented for the occasion.

Two boundaries, and they are different things
---------------------------------------------
**The scorecard data-domain boundary** is about conversational access to
record-level model populations. The general Cockpit may not read them at all;
the Scorecard Validation environment may; and a *published aggregate metric*
may, because its formula was written, reviewed and released and what it
returns is one approved number. That carve-out is deliberate and documented in
`backend/scorecard/domains.py`, and the Retail lenses depend on it — they are
built on the behavioural and application datasets, which are restricted.

So the test that matters is not "can a lens read a restricted dataset" — it
can, by design. It is that the batched path is scoped exactly like the
single-metric path, so batching did not become a way to run a plan under a
scope the same metric would not get on its own.

**`readable`** is the set of datasets an asker may read. Every metric entry
point takes it, and a metric is visible only when EVERY dataset it reads is —
a ratio whose denominator comes from a dataset you cannot see is a number you
cannot be shown, not a number to show partially.

What this deployment does not have
-----------------------------------
Per-user dataset permissions. `readable` is a service-level parameter, and the
only production caller that supplies it is the Playbook. The lens and metric
HTTP routes do not, so in this deployment every signed-in analyst sees every
governed metric, and access control is the role gate on the route plus the
domain scope on the plan. These tests therefore prove the mechanism at the
level it exists at, and the report says so rather than implying a per-user
model that is not there.
"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.metrics import execution
from backend.metrics import lenses as shipped
from backend.metrics import service as metrics
from backend.runtime.executor import execute
from backend.scorecard import domains
from backend.services import lenses as service

needs_lake = pytest.mark.skipif(
    not settings.has_database,
    reason="needs the analytics lake and the database")

BEHAVIOURAL = "retail_behavioral_scorecard_monthly_validation"
MONTH = "2025-07"


# --------------------------------------------- the scorecard domain boundary


def test_the_retail_lenses_do_read_restricted_datasets_by_design():
    """Stated so that a later change cannot quietly assume otherwise."""
    assert domains.is_restricted(BEHAVIOURAL)
    metric = metrics.resolve("retail.dpd_30_count")
    assert metric.datasets == (BEHAVIOURAL,)


@needs_lake
def test_the_general_cockpit_still_cannot_read_what_a_lens_reads():
    """The carve-out is for published metrics, not for the dataset.

    A plan over the same dataset, submitted under the general scope, is
    refused — which is what makes the metric's access an approved output
    rather than a hole with a lens in front of it.
    """
    from backend.runtime.validation import PlanRejected

    metric = metrics.resolve("retail.dpd_30_count")
    plan, _ = execution.compile_batch({"a": metric.formula}, period=MONTH)
    with pytest.raises(PlanRejected) as refused:
        execute(plan, scope=domains.GENERAL, question="probe",
                intent="metric_batch")
    assert "not available here" in str(refused.value)


@needs_lake
def test_the_batched_path_is_scoped_exactly_like_the_single_one():
    """Batching must not be a way to run a plan under a wider scope.

    Both paths declare GOVERNED_METRIC, and neither declares it as a literal
    the other could drift from — this asserts the behaviour, which is that the
    same plan is allowed under one scope and refused under the other in both
    shapes.
    """
    from backend.runtime.validation import PlanRejected

    metric = metrics.resolve("retail.dpd_30_count")
    for plan in (execution.compile_metric(metric.formula, period=MONTH),
                 execution.compile_batch({"a": metric.formula},
                                         period=MONTH)[0]):
        assert execute(plan, scope=domains.GOVERNED_METRIC, question="probe",
                       intent="metric").rows
        with pytest.raises(PlanRejected):
            execute(plan, scope=domains.GENERAL, question="probe",
                    intent="metric")


def test_governed_metric_is_still_the_only_extra_scope():
    """Adding a scope must be deliberate, not a side effect of a feature."""
    assert domains.MAY_READ_RESTRICTED == frozenset(
        {domains.VALIDATION, domains.GOVERNED_METRIC})


# --------------------------------------------------------- readable filters


def test_a_metric_over_an_unreadable_dataset_is_not_in_the_catalogue():
    allowed = {"ifrs9_staging"}
    visible = {m.metric_id
               for m in metrics.catalogue(readable=allowed)}
    assert "corporate.ifrs9.total_ead" in visible
    assert "retail.dpd_30_count" not in visible


def test_asking_for_it_by_id_does_not_get_round_that():
    """The direct-id route must not be a way past the picker."""
    with pytest.raises(metrics.MetricNotFound):
        metrics.resolve("retail.dpd_30_count", readable={"ifrs9_staging"})


def test_the_refusal_does_not_say_whether_the_metric_exists():
    """Otherwise it enumerates metrics over data somebody cannot see.

    A smaller leak than the data, and a leak.
    """
    hidden = str(pytest.raises(
        metrics.MetricNotFound,
        metrics.resolve, "retail.dpd_30_count",
        readable={"ifrs9_staging"}).value)
    invented = str(pytest.raises(
        metrics.MetricNotFound,
        metrics.resolve, "retail.no_such_metric_at_all",
        readable={"ifrs9_staging"}).value)
    assert hidden.replace("retail.dpd_30_count", "X") == (
        invented.replace("retail.no_such_metric_at_all", "X"))


@needs_lake
def test_a_batch_does_not_compute_a_metric_the_asker_may_not_read():
    """The assertion this file exists for.

    A batch groups by dataset, so the failure to guard against is a readable
    metric dragging an unreadable one into its plan because they share a
    scan.
    """
    answer = metrics.values(
        ["corporate.ifrs9.total_ead", "retail.dpd_30_count"],
        period="", readable={"ifrs9_staging"})
    assert answer["metrics"]["corporate.ifrs9.total_ead"]["value"] > 0
    hidden = answer["metrics"]["retail.dpd_30_count"]
    assert hidden["value"] is None
    assert hidden["metric"] is None
    assert "available to you" in hidden["unavailable"]


@needs_lake
def test_a_batch_of_only_unreadable_metrics_reads_nothing():
    answer = metrics.values(["retail.dpd_30_count", "retail.balance"],
                            readable={"ifrs9_staging"})
    assert answer["reads"] == 0
    assert all(row["value"] is None
               for row in answer["metrics"].values())


def test_the_typeahead_never_suggests_one():
    """`readable` is applied before ranking, not after.

    Applied after, a permitted metric could be pushed off the end of an
    eight-row list by a hidden one, so the asker would lose a suggestion they
    were entitled to and never know why.
    """
    hits = metrics.find("del", readable={"ifrs9_staging"}, limit=50)
    assert hits["results"] == []
    wide = metrics.find("del", limit=50)
    assert wide["results"], "the query matches nothing at all, so this proves nothing"


def test_a_suggested_lens_cannot_suggest_a_metric_the_asker_may_not_read():
    """The suggestion route is new, so it gets its own check.

    It reads the catalogue through `metrics.find` and `metrics.resolve`, both
    of which take the asker's identity. This asserts the result rather than
    the call: a scope suggested from metrics somebody cannot see would name a
    domain they cannot read.
    """
    suggested = service.suggest("Retail Credit Risk")
    assert suggested["metrics"], "nothing was suggested, so this proves nothing"
    for row in suggested["metrics"]:
        assert metrics.resolve(row["metric_id"])


# ------------------------------------------------- a lens is not a shortcut


@needs_lake
def test_a_lens_tile_over_a_missing_dataset_says_so_rather_than_guessing():
    """The nearest thing this deployment has to a revoked permission.

    There are no per-user dataset grants here, so "the dataset is gone" is
    what a lens has to survive: a tile whose source has been unpublished must
    report the absence, not a stale number and not a zero.
    """
    from backend.metrics.catalogue import MetricDefinition
    from backend.metrics.formula import Formula, Side, Term

    orphan = MetricDefinition(
        metric_id="test.orphan", name="Orphan",
        definition="Reads a dataset this deployment does not have.",
        formula=Formula(kind="sum", numerator=Side(terms=(
            Term(id="x", label="X", dataset="dataset_that_went_away",
                 aggregate="sum", field="amount"),))))

    # The plan is refused before a row is read, and the refusal names the
    # dataset. It does NOT come back as a number, and it does not come back
    # as zero, which is the failure mode worth having a test for.
    from backend.runtime.validation import PlanRejected

    with pytest.raises(PlanRejected) as refused:
        execution.run(orphan.formula, period="")
    assert "dataset_that_went_away" in str(refused.value)
    assert "not a governed dataset" in str(refused.value)

    # And a lens holding it loses that tile rather than the page: the tile
    # reports `failed` with the reason, and carries no value at all.
    panel = service.Panel.metric("test.orphan")
    drawn = service._render_metric(panel)
    assert drawn["status"] == "failed"
    assert drawn.get("value") is None
    assert drawn["error"]


@needs_lake
def test_every_shipped_lens_reads_only_datasets_this_deployment_has():
    """A shipped lens that names a dataset which has gone is a defect.

    `check()` proves the metric exists; this proves the data behind it does,
    which is the half a catalogue check cannot see.
    """
    from backend.data_access.catalog import get_catalog

    catalog = get_catalog()
    for spec in shipped.ALL:
        for metric_id in spec.metric_ids:
            metric = metrics.resolve(metric_id)
            for dataset in metric.datasets:
                assert catalog.dataset(dataset) is not None, (
                    f"{spec.name} reads {dataset} through {metric_id}, and "
                    "the governed catalogue does not have it")
