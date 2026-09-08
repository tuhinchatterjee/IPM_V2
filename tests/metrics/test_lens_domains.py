"""§1's boundary: a Lens reads Cockpit and Early Warning, and nothing else.

The tests that matter here are the refusals. A boundary that admits everything
it should is worth nothing if it also admits one thing it should not, so most
of this file is about what does NOT get through — and about the registry
staying honest as the deployment's catalogue changes underneath it.
"""

from __future__ import annotations

import pytest

from backend.metrics import lens_domains as domains
from backend.metrics.formula import Condition, Formula, Side, Term

# ---------------------------------------------------------------------- shape


def test_the_two_domains_are_the_only_ones():
    assert domains.LENS_DOMAINS == (domains.COCKPIT, domains.EWS)


def test_every_registered_dataset_serves_at_least_one_domain():
    for name in domains.DATASET_DOMAINS:
        assert domains.domains_of(name), name


def test_a_dataset_in_both_sets_serves_both():
    assert set(domains.domains_of("portfolio_facility")) == {
        domains.COCKPIT, domains.EWS}


# ------------------------------------------------------------------ refusals


@pytest.mark.parametrize("dataset,owner", [
    ("pd_model_performance", "Scorecard"),
    ("scenario_definitions", "What-If"),
    ("retail_behavioral_scorecard_development_reference", "Scorecard"),
    ("retail_application_scorecard_development_reference", "Scorecard"),
])
def test_another_products_data_is_refused_by_name(dataset, owner):
    assert not domains.permitted(dataset)
    # The sentence has to say WHOSE it is. "There is no rule for this" and
    # "this belongs to another product" are different answers and only the
    # second tells somebody what to do next.
    assert owner in domains.refusal(dataset)


def test_an_unknown_dataset_is_refused_rather_than_assumed():
    assert not domains.permitted("some_table_nobody_registered")
    assert "Cockpit and Early Warning" in domains.refusal(
        "some_table_nobody_registered")


def test_check_datasets_reports_every_refusal_at_once():
    found = domains.check_datasets(
        ["portfolio_facility", "pd_model_performance", "scenario_definitions"])
    assert len(found) == 2


def test_require_raises_with_all_of_them():
    with pytest.raises(domains.DomainRefused) as caught:
        domains.require(["pd_model_performance", "scenario_definitions"])
    assert "Scorecard" in str(caught.value)
    assert "What-If" in str(caught.value)


# ----------------------------------------------------- field-level attribution


def test_the_shared_table_splits_by_field():
    """Cockpit and Early Warning share the facility position in this
    deployment, and which domain a TERM reads is decided by its field."""
    assert domains.domain_of_field("portfolio_facility", "exposure") == \
        domains.COCKPIT
    assert domains.domain_of_field("portfolio_facility", "ifrs9_stage") == \
        domains.COCKPIT
    assert domains.domain_of_field("portfolio_facility", "severity") == \
        domains.EWS
    assert domains.domain_of_field("portfolio_facility", "watchlist") == \
        domains.EWS


def test_a_single_domain_dataset_ignores_the_field():
    assert domains.domain_of_field("watchlist_register", "anything") == \
        domains.EWS
    assert domains.domain_of_field("ifrs9_staging", "anything") == \
        domains.COCKPIT


def test_a_formula_that_reads_both_reports_both():
    """The §35 shape: an EWS filter over a Cockpit measure."""
    formula = Formula(
        kind="percentage",
        numerator=Side(terms=(Term(
            id="hs", label="High severity", dataset="portfolio_facility",
            aggregate="sum", field="exposure",
            where=(Condition(field="severity", op="=", value="Critical"),)),)),
        denominator=Side(terms=(Term(
            id="all", label="Total", dataset="portfolio_facility",
            aggregate="sum", field="exposure"),)),
        scale=100.0)
    assert domains.formula_domains(formula) == (domains.COCKPIT, domains.EWS)


def test_domains_come_back_in_a_stable_order():
    formula = Formula(kind="sum", numerator=Side(terms=(
        Term(id="s", label="Severity", dataset="portfolio_facility",
             aggregate="count", where=(
                 Condition(field="severity", op="=", value="High"),)),
        Term(id="e", label="Exposure", dataset="portfolio_facility",
             aggregate="sum", field="exposure"))))
    assert domains.formula_domains(formula) == (domains.COCKPIT, domains.EWS)


# ------------------------------------------------- the registry stays honest


def test_every_governed_metric_is_inside_the_boundary():
    """§42. Every shipped Lens is built from these, so a metric that fell
    outside would take a shipped Lens down with it."""
    from backend.metrics import library

    outside = [m.metric_id for m in library.ALL
               if not domains.metric_permitted(m)]
    assert outside == []


def test_the_registry_covers_every_dataset_the_catalogue_has():
    """A dataset added to a deployment must fail HERE, not silently land
    inside or outside the boundary at whatever its Data Builder domain
    happens to be.

    The Data Builder domain is deployment state — a steward edits it, and a
    catalogue republish rewrote the whole taxonomy during this feature's
    development, silently moving `watchlist_register` from Early Warning into
    Cockpit. This test is what stops that being invisible.
    """
    from backend.data_access.catalog import get_catalog

    try:
        names = get_catalog().names()
    except Exception:  # pragma: no cover - no catalogue in this environment
        pytest.skip("no governed catalogue available here")
    if not names:
        pytest.skip("the catalogue is empty in this environment")

    unregistered = [n for n in names
                    if n not in domains.DATASET_DOMAINS
                    and n not in domains.REFUSED]
    assert unregistered == [], (
        "These governed datasets are named in neither COCKPIT_DATASETS, "
        "EWS_DATASETS nor REFUSED, so whether a Lens may read them is being "
        "decided by a Data Builder domain label rather than by this "
        f"registry: {unregistered}")


def test_a_refused_dataset_is_not_in_either_domain_set():
    for name in domains.REFUSED:
        assert name not in domains.COCKPIT_DATASETS
        assert name not in domains.EWS_DATASETS


def test_permitted_datasets_excludes_the_refused_ones():
    permitted = set(domains.permitted_datasets())
    assert not (permitted & set(domains.REFUSED))
