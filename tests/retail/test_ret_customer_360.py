"""
Customer 360, reconciled against the book rather than against the screen.

The browser suite asserts what a reader sees; this recomputes the same figures
from the published Parquet and fails if the screen and the book could disagree.
Both are needed: a page can render a number correctly and read it from the
wrong place.

The warning this file exists for: income, obligations, the debt burden and
disposable income are CUSTOMER values that repeat on every facility row. Summing
them multiplies a salary by the number of facilities, and a customer with six
facilities would appear to earn six times what they do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pandas")

ROOT = Path(__file__).resolve().parents[2]

#: The customer the browser journey opens: six facilities across three
#: products, one of them Stage 3.
CUSTOMER = "RC-0020621"
MONTH = "2026-08"

#: Fields that belong to the customer, not to the facility. Repeated on every
#: row of the book, and never to be added up.
CUSTOMER_LEVEL = (
    "verified_monthly_salary_sar",
    "verified_total_monthly_income_sar",
    "household_expenses_sar",
    "monthly_external_credit_obligations_sar",
    "monthly_total_credit_obligations_sar",
    "disposable_income_sar",
    "debt_burden_ratio",
)

#: NOT in the list above. The synthetic book records a bureau reading per
#: FACILITY observation — one customer carries six, ranging 600 to 651 at
#: 2026-08 — so there is no single "customer bureau score" to report, and the
#: endpoint says so rather than passing the first row off as the answer.
BUREAU = "bureau_score_current"


@pytest.fixture()
def retail_settings(monkeypatch, retail_book):
    """Point the router at the book this installation publishes.

    The suite runs with the repository's default data directory; the launcher
    exports `DATA_ANALYTICS_DIR=data/retail/analytics`. Rather than assert
    less, the test hands the endpoint the same lake the running product reads.
    """
    import dataclasses

    from backend import config
    from backend.api.routers import retail as router

    # The router binds `settings` at import, so patching the config module
    # alone would not reach it, and its reads are cached.
    metadata = ROOT / "metadata" / "retail"
    retail_settings = dataclasses.replace(
        config.settings,
        analytics_dir=retail_book.analytics_dir,
        metadata_dir=metadata if metadata.exists() else config.settings.metadata_dir)
    monkeypatch.setattr(router, "settings", retail_settings)
    router._manifest.cache_clear()
    yield retail_settings
    router._manifest.cache_clear()


@pytest.fixture()
def rows(retail_book):
    frame = retail_book.month(MONTH)
    found = frame[frame["customer_id"] == CUSTOMER]
    if found.empty:
        pytest.skip(f"{CUSTOMER} is not in this build of the book")
    return found


def test_the_customer_has_the_facilities_the_screen_shows(rows) -> None:
    assert len(rows) == 6
    assert rows["facility_id"].nunique() == 6
    assert set(rows["product_label"]) >= {"Personal Finance", "Credit Card"}


def test_exposure_and_allowance_are_sums_over_facilities(rows) -> None:
    """Each facility counted once — the figure on the customer header."""
    assert round(float(rows["gross_carrying_amount_sar"].sum()), 2) == 1228495.61
    assert round(float(rows["ecl_final_sar"].sum()), 2) == 29206.24


@pytest.mark.parametrize("field", CUSTOMER_LEVEL)
def test_a_customer_value_is_one_value(rows, field: str) -> None:
    """It repeats on every facility row, so it must be read once, not summed.

    A customer with six facilities whose salary was summed would appear to earn
    six times what they do, and their debt burden would be meaningless.
    """
    if field not in rows.columns:
        pytest.skip(f"{field} is not published in this build")
    distinct = rows[field].dropna().round(6).nunique()
    assert distinct <= 1, (
        f"{field} differs across this customer's facility rows, so it cannot "
        "be read as a single customer value")


def test_the_bureau_reading_is_not_passed_off_as_one_number(
        rows, retail_settings) -> None:
    """One customer carries six bureau observations, 600 to 651.

    Reporting the first facility row's value as "the customer's bureau score"
    presents one arbitrary observation as a fact about the person.
    """
    from backend.api.routers import retail as router

    body = router.customer(CUSTOMER, MONTH)
    bureau = body["customer"]
    readings = rows[BUREAU].dropna()
    assert bureau["bureau_observations"] == len(readings)
    assert bureau["bureau_score_low"] == float(readings.min())
    assert bureau["bureau_score_high"] == float(readings.max())
    # The lowest, named as such: a decision reads the worst evidence it has.
    assert bureau["bureau_score_current"] == float(readings.min())
    assert "lowest" in bureau["bureau_basis"].lower()


def test_the_retail_endpoint_reports_those_values_once(
        rows, retail_settings) -> None:
    """The API's own contract, checked rather than trusted."""
    from backend.api.routers import retail as router

    body = router.customer(CUSTOMER, MONTH)
    assert body["facility_count"] == 6
    assert round(float(body["exposure_sar"]), 2) == 1228495.61
    assert round(float(body["ecl_final_sar"]), 2) == 29206.24

    customer = body["customer"]
    income = float(rows["verified_total_monthly_income_sar"].iloc[0])
    assert round(float(customer["verified_total_monthly_income_sar"]), 2) == \
        round(income, 2), "the endpoint summed a customer value"
    assert len(body["facilities"]) == 6
    assert body["history"], "no monthly history"
    assert any("once" in note for note in body.get("notes", [])), (
        "the endpoint no longer states that customer values are reported once")


def test_the_history_is_one_row_per_month(rows, retail_settings) -> None:
    from backend.api.routers import retail as router

    body = router.customer(CUSTOMER, MONTH)
    months = [h["reporting_month"] for h in body["history"]]
    assert months == sorted(months), "the history is not in calendar order"
    assert len(months) == len(set(months)), "a month appears twice"
    assert months[-1] == MONTH


def test_score_evidence_names_its_model_and_date(retail_settings) -> None:
    """Origination inputs must not silently become current inputs."""
    from backend.api.routers import retail as router

    body = router.customer(CUSTOMER, MONTH)
    facility = body["facilities"][0]["facility_id"]
    score = router.facility_score(facility, MONTH)

    application = score.get("application")
    behavioural = score.get("behavioural")
    assert application or behavioural, "neither scorecard was returned"
    for block, kind in ((application, "application"), (behavioural, "behavioural")):
        if not block:
            continue
        assert block["model_id"], f"the {kind} score names no model"
        assert block["model_version"], f"the {kind} score names no version"
        assert block.get("contributions"), f"the {kind} score shows no inputs"

    if application:
        # The application scorecard is measured at origination and says so.
        assert "origination" in str(application.get("target_event", "")).lower() \
            or application.get("as_at") is not None
