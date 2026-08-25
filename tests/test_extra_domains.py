"""
The additional domains, and whether they agree with the book.

A demonstration where the collateral register contradicts the facility book is
a demonstration of nothing, so these tests are almost entirely reconciliations:
the same figure read two ways has to come back the same. They are the reason
the domains are DERIVED from the simulation rather than generated beside it.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source

EXTRA = [
    "collateral_register", "covenant_tests", "facility_limits",
    "watchlist_register", "recoveries", "payment_history", "group_structure",
    "rating_transitions", "risk_appetite_limits", "pd_model_performance",
    "scenario_definitions", "facility_profitability", "climate_risk",
]


@pytest.fixture(scope="module")
def source():
    return get_data_source()


@pytest.fixture(scope="module", autouse=True)
def require_lake(source):
    if "portfolio_facility" not in source.datasets():
        pytest.skip("Analytical lake not built")
    missing = [d for d in EXTRA if d not in source.datasets()]
    if missing:
        pytest.skip(f"Additional domains not generated: {', '.join(missing)}")


@pytest.fixture(scope="module")
def period(source):
    return source.periods("portfolio_facility")[-1]


def read(source, dataset, period=None, columns=None):
    """One dataset, through the Data Access Layer the product itself uses."""
    from backend.data_access.context import AnalysisContext

    return source.fetch(dataset, context=AnalysisContext(period=period),
                        fields=columns, period=period)


# ------------------------------------------------------------------ coverage


def test_the_book_carries_twenty_governed_datasets(source):
    assert len(source.datasets()) >= 20


def test_every_additional_domain_has_rows(source):
    for dataset in EXTRA:
        assert source.row_count(dataset) > 0, f"{dataset} is empty"


def test_every_additional_domain_is_marked_synthetic(source):
    from backend.data_access.catalog import get_catalog

    catalog = get_catalog()
    for dataset in EXTRA:
        assert catalog.dataset(dataset).is_synthetic, (
            f"{dataset} does not carry the SYNTHETIC marker."
        )


def test_every_additional_domain_states_its_grain(source):
    from backend.data_access.catalog import get_catalog

    catalog = get_catalog()
    for dataset in EXTRA:
        definition = catalog.dataset(dataset)
        assert definition.grain.strip(), f"{dataset} does not say what a row is"
        assert definition.purpose.strip()
        assert definition.primary_keys


def test_no_additional_domain_claims_to_be_authoritative(source):
    """None of them may stand in for the facility position. A supporting
    dataset that answers 'give me the book' is how a partial view becomes the
    book."""
    from backend.data_access.catalog import get_catalog

    catalog = get_catalog()
    for dataset in EXTRA:
        assert not catalog.dataset(dataset).authoritative_for


# ------------------------------------------------------------ reconciliation


def test_collateral_reconciles_to_the_facility_book(source, period):
    facility = read(source, "portfolio_facility", period,
                    ["account_id", "collateral_value"])
    register = read(source, "collateral_register", period,
                    ["account_id", "market_value"])
    held = facility[facility["collateral_value"] > 0]
    by_account = register.groupby("account_id")["market_value"].sum()
    merged = held.set_index("account_id").join(by_account, how="inner")
    assert len(merged) > 100
    difference = (merged["market_value"] - merged["collateral_value"]).abs()
    assert difference.max() < 0.02, (
        "The register's items must sum to the collateral the facility book "
        "carries, or 'our collateral coverage is X' depends on which table you "
        "read."
    )


def test_a_covenant_breach_matches_the_headroom_it_came_from(source, period):
    facility = read(source, "portfolio_facility", period,
                    ["account_id", "dscr"])
    tests = read(source, "covenant_tests", period,
                 ["account_id", "covenant_name", "actual_value"])
    dscr = tests[tests["covenant_name"] == "Debt Service Coverage"]
    merged = facility.set_index("account_id").join(
        dscr.set_index("account_id")[["actual_value"]], how="inner")
    assert len(merged) > 100
    assert (merged["actual_value"] - merged["dscr"]).abs().max() < 1e-6


def test_payments_agree_with_arrears(source, period):
    """A facility at zero days past due paid in full; one 90 days down did
    not. Generating payments independently would produce a book whose arrears
    and payment tables disagree."""
    payments = read(source, "payment_history", period,
                    ["account_id", "days_past_due", "paid_in_full", "shortfall"])
    current = payments[payments["days_past_due"] == 0]
    late = payments[payments["days_past_due"] >= 90]
    assert current["paid_in_full"].all()
    assert not late["paid_in_full"].any()
    assert late["shortfall"].min() >= 0


def test_the_watchlist_is_exactly_the_flagged_customers(source, period):
    facility = read(source, "portfolio_facility", period,
                    ["customer_id", "watchlist"])
    register = read(source, "watchlist_register", period, ["customer_id"])
    flagged = set(facility[facility["watchlist"]]["customer_id"])
    listed = set(register["customer_id"])
    assert listed == flagged, (
        "A customer is on the watchlist exactly when one of its facilities "
        "says it should be."
    )


def test_recoveries_cover_the_defaulted_facilities(source, period):
    facility = read(source, "portfolio_facility", period,
                    ["account_id", "ifrs9_stage"])
    recoveries = read(source, "recoveries", period, ["account_id"])
    defaulted = set(facility[facility["ifrs9_stage"] == 3]["account_id"])
    assert set(recoveries["account_id"]) == defaulted


def test_realised_lgd_is_anchored_on_the_modelled_one(source, period):
    """Not equal — a back-test where realised equals modelled proves nothing —
    but centred on it, so a calibration finding is a real property of the data."""
    recoveries = read(source, "recoveries", period,
                      ["modelled_lgd_pct", "realised_lgd_pct"])
    gap = (recoveries["realised_lgd_pct"] - recoveries["modelled_lgd_pct"]).mean()
    assert abs(gap) < 8.0, f"Realised LGD is {gap:.1f} points off the model."
    assert recoveries["realised_lgd_pct"].std() > 1.0, (
        "Realised LGD with no dispersion is the model copied, not a back-test."
    )


def test_appetite_percentages_sum_to_the_whole_book(source, period):
    appetite = read(source, "risk_appetite_limits", period,
                    ["sector", "actual_pct_of_book", "exposure"])
    assert abs(appetite["actual_pct_of_book"].sum() - 100.0) < 0.1
    facility = read(source, "portfolio_facility", period, ["ead"])
    assert abs(appetite["exposure"].sum() - facility["ead"].sum()) < 1.0


def test_profitability_raroc_matches_the_facility_book(source, period):
    """Recomputed from its parts rather than copied, so 'why did RAROC fall'
    has an answer with components to it."""
    profit = read(source, "facility_profitability", period,
                  ["account_id", "interest_revenue", "funding_cost",
                   "operating_cost", "expected_loss_charge", "net_profit"])
    rebuilt = (profit["interest_revenue"] - profit["funding_cost"]
               - profit["operating_cost"] - profit["expected_loss_charge"])
    assert (rebuilt - profit["net_profit"]).abs().max() < 0.001


def test_model_performance_reconciles_to_the_book(source, period):
    performance = read(source, "pd_model_performance", period,
                       ["segment", "facilities", "observed_default_rate_pct"])
    facility = read(source, "portfolio_facility", period,
                    ["segment", "ifrs9_stage"])
    assert performance["facilities"].sum() == len(facility)
    for _, row in performance.iterrows():
        segment = facility[facility["segment"] == row["segment"]]
        observed = 100.0 * (segment["ifrs9_stage"] == 3).mean()
        assert abs(observed - row["observed_default_rate_pct"]) < 0.01


def test_rating_transitions_reconcile_to_the_rating_history(source):
    transitions = read(source, "rating_transitions",
                       columns=["customer_id", "from_year", "to_year",
                                "from_grade", "to_grade", "notches_moved"])
    assert (transitions["to_year"] - transitions["from_year"] == 1).all()
    assert (transitions["to_grade"] - transitions["from_grade"]
            == transitions["notches_moved"]).all()


def test_every_group_member_points_at_a_real_parent(source):
    groups = read(source, "group_structure",
                  columns=["customer_id", "parent_customer_id", "relationship"])
    known = set(groups["customer_id"])
    children = groups[groups["parent_customer_id"] != ""]
    assert set(children["parent_customer_id"]) <= known
    for _, members in groups.groupby("customer_id"):
        assert len(members) == 1, "A customer belongs to one group."


def test_the_base_scenario_shocks_nothing(source):
    scenarios = read(source, "scenario_definitions",
                     columns=["scenario", "gdp_growth_shock_pct",
                              "oil_price_shock_pct", "policy_rate_shock_pct"])
    base = scenarios[scenarios["scenario"] == "Base"]
    assert len(base) > 0
    assert base[["gdp_growth_shock_pct", "oil_price_shock_pct",
                 "policy_rate_shock_pct"]].abs().to_numpy().max() == 0.0


def test_climate_bands_follow_the_sector(source):
    climate = read(source, "climate_risk",
                   columns=["sector", "transition_risk_band"])
    by_sector = climate.groupby("sector")["transition_risk_band"].nunique()
    assert (by_sector == 1).all(), (
        "A transition band that varies within a sector is not a banding."
    )
    assert climate[climate["sector"] == "Petrochemicals"][
        "transition_risk_band"].iloc[0] == "High"


# --------------------------------------------------------------- runnability


def test_the_runtime_can_read_every_additional_domain(source, period):
    """The whole point of a governed domain is that the analytical runtime can
    read it. A dataset in the catalogue the runtime refuses is not a domain."""
    from backend.runtime.executor import execute

    for dataset in EXTRA:
        has_period = "period" in source.fields(dataset)
        plan = {
            "id": f"probe_{dataset}",
            "operations": [
                {"id": "scan", "op": "SCAN",
                 "params": {"dataset": dataset,
                            **({"period": period} if has_period else {})}},
                {"id": "total", "op": "AGGREGATE", "inputs": ["scan"],
                 "params": {"aggregates": [{"function": "count", "as": "rows"}]}},
            ],
        }
        result = execute(plan, question=f"How many rows in {dataset}?")
        assert result.rows[0]["rows"] > 0, f"{dataset} returned nothing"
