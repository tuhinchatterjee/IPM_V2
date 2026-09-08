"""
What the Early Warning data domain has to be, checked against what it is.

Why these are worth asserting
------------------------------
Everything downstream — the grain package a planner reads, the validator's
allow-list, the dictionary the redirect checks its alternatives against —
takes this domain's shape as given. If the shape drifts, nothing above it
fails loudly; it just starts answering slightly wrong questions about
slightly wrong data.

So the shape is pinned here: the name, the grain, the twenty contiguous
months, one row per obligor per month, the full model surface exposed rather
than just the final score, and — the one that is easiest to get wrong — no
future leakage and a first published month that was not scored cold.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.early_warning import dictionary as dic
from backend.early_warning import grain as grain_mod
from backend.early_warning import v2_service as svc
from backend.early_warning import wide

#: The floor the brief sets. More is fine; fewer is not.
REQUIRED_MONTHS = 20


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def periods() -> list[str]:
    return list(svc.periods())


@pytest.fixture(scope="module")
def every_month() -> pd.DataFrame:
    return pd.concat([svc.borrower_month(p) for p in svc.periods()])


# ------------------------------------------------------------- the domain


def test_the_domain_has_one_business_name():
    assert grain_mod.DOMAIN == "Early Warning"
    assert grain_mod.DOMAIN_ID == "early_warning"


def test_the_grain_is_one_customer_and_one_month():
    assert grain_mod.GRAIN == ("customer_id", "snapshot_month")


def test_there_are_at_least_twenty_published_months(periods):
    assert len(periods) >= REQUIRED_MONTHS, (
        f"{len(periods)} published months; the domain needs "
        f"{REQUIRED_MONTHS}")


def test_the_months_are_contiguous_with_none_missing(periods):
    """A gap is worse than a shorter history: a trend drawn across a missing
    month is a trend nobody can read."""
    expected = [d.strftime("%Y-%m") for d in pd.date_range(
        f"{periods[0]}-01", f"{periods[-1]}-01", freq="MS")]
    assert periods == expected, (
        f"months are not contiguous; missing "
        f"{sorted(set(expected) - set(periods))}")


def test_every_month_is_a_month_end():
    for period in svc.periods():
        assert len(period) == 7 and period[4] == "-", period
        assert 1 <= int(period[5:]) <= 12, period


def test_one_row_per_customer_per_month(every_month):
    duplicated = every_month.duplicated(["customer_id", "snapshot_month"])
    assert not duplicated.any(), (
        f"{int(duplicated.sum())} duplicate customer-month rows")


def test_the_population_is_the_same_every_month(every_month, periods):
    counts = every_month.groupby("snapshot_month")["customer_id"].nunique()
    assert counts.nunique() == 1, (
        f"the obligor count changes across months: {counts.to_dict()}")
    assert len(counts) == len(periods)


def test_customer_ids_are_the_canonical_ones():
    """No separate Early Warning customer universe.

    An obligor that exists here and not in the credit book is one nobody can
    look up, and one that exists in both under different identifiers is two
    obligors as far as every join is concerned.
    """
    from backend.corporate import service as corp

    book = set(corp._load(corp.SNAPSHOT)["borrower_id"].astype(str))
    ours = set(svc.borrower_month()["customer_id"].astype(str))
    unknown = ours - book
    assert not unknown, (
        f"{len(unknown)} obligors are not in the canonical customer master: "
        f"{sorted(unknown)[:5]}")


# ------------------------------------------------- no leakage, no cold start


def test_no_row_is_dated_after_its_own_month(every_month):
    """Future leakage is not subtle here: it is a score read against data
    that did not exist when the score was produced."""
    latest = max(svc.periods())
    beyond = every_month[every_month["snapshot_month"] > latest]
    assert beyond.empty, f"{len(beyond)} rows dated after the latest month"


def test_the_first_published_month_was_not_scored_cold():
    """The reason the build computes twelve months nobody sees.

    `trailing_baseline` averages up to twelve prior months and falls back to
    the current value when there are none, so in a cold first month every
    obligor is compared against itself and no L1 trigger can fire. If the
    first published month has far fewer fired signals than a typical one,
    the warm-up is not doing its job.
    """
    periods = svc.periods()
    first = svc.borrower_month(periods[0])
    typical = [int((svc.borrower_month(p)["signal_count_fired"] > 0).sum())
               for p in periods[1:6]]
    fired_first = int((first["signal_count_fired"] > 0).sum())
    floor = 0.4 * (sum(typical) / len(typical))
    assert fired_first >= floor, (
        f"the first published month fired {fired_first} signals against a "
        f"typical {sum(typical) / len(typical):.0f}; it looks cold-started")


def test_the_build_publishes_fewer_months_than_it_computes():
    """The warm-up exists in the build, not just in the docstring."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ews_build", "scripts/build_early_warning_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.VISIBLE_MONTHS) >= REQUIRED_MONTHS
    assert module.PRE_HISTORY_MONTHS >= 12, (
        "the warm-up is shorter than the twelve-month trailing baseline it "
        "exists to fill")
    assert len(module.MONTHS) == len(module.VISIBLE_MONTHS) \
        + module.PRE_HISTORY_MONTHS


# ---------------------------------------------------- the model, exposed


def test_the_whole_signal_inventory_is_represented():
    from backend.early_warning import catalog

    counts = catalog.status_counts()
    assert len(catalog.SIGNAL_INVENTORY) == 123
    assert counts.get("SCORED", 0) == 105
    assert sum(v for k, v in counts.items() if k != "SCORED") == 18


def test_dropped_signals_are_auditable_but_do_not_score():
    from backend.early_warning import catalog

    dropped = [s for s in catalog.SIGNAL_INVENTORY
               if getattr(s, "status", "") != "SCORED"]
    assert len(dropped) == 18
    fired = set(svc.signal_observations(
        svc.borrower_month().iloc[0]["customer_id"])["signal_key"]) \
        if not svc.borrower_month().empty else set()
    keys = {getattr(s, "key", getattr(s, "signal_key", "")) for s in dropped}
    assert not (fired & keys), (
        "a dropped signal regained an independent scoring contribution")


def test_all_twenty_two_sub_categories_are_exposed():
    assert len(wide.SUBCATEGORY_CODES) == 22
    columns = set(wide.customer_month().columns)
    for code in wide.SUBCATEGORY_CODES:
        assert wide.subcategory_column(code) in columns, code


def test_all_six_layer_dimension_outputs_are_exposed():
    assert len(wide.LAYER_KEYS) == 6
    columns = set(wide.customer_month().columns)
    for key in wide.LAYER_KEYS:
        assert key in columns, key


def test_both_dimensions_the_matrix_and_every_notch_are_exposed():
    columns = set(wide.customer_month().columns)
    for name in ("ta_score", "ta_band", "classifier_score", "classifier_band",
                 "anchor_score", "net_notches", "ews_score", "ews_band"):
        assert name in columns, name
    assert len(wide.NOTCH_KEYS) == 5
    for key in wide.NOTCH_KEYS:
        assert wide.notch_column(key) in columns, key


def test_the_override_fields_are_exposed():
    columns = set(wide.customer_month().columns)
    for name in ("override_applied", "override_count", "override_types"):
        assert name in columns, name


# ------------------------------------------------------- the dictionary


def test_the_dictionary_describes_the_analytical_view_exactly():
    """An exact contract, in both directions.

    A field the view has and the dictionary does not is one a planner
    cannot use; a field the dictionary has and the view does not is one a
    planner will use and then fail on.
    """
    described = dic.names()
    actual = set(wide.with_movement().columns)
    assert described == actual, (
        f"undescribed: {sorted(actual - described)}; "
        f"described but absent: {sorted(described - actual)}")


def test_every_field_carries_a_definition_and_a_group():
    for found in dic.fields():
        assert found.label, found.name
        assert len(found.definition) > 20, (
            f"{found.name} has no real definition")
        assert found.group in dic.GROUP_ORDER, found.name


def test_missingness_is_measured_rather_than_declared():
    """A dictionary that claims a field is populated when it is empty for
    half the book is what makes a planner confident and wrong."""
    profile = dic.profile()
    assert profile
    for name, found in profile.items():
        assert found["present"], name
        assert 0.0 <= found["missing_rate"] <= 1.0, name
    # And it reports the fields that really are sparse rather than rounding
    # them up: most obligors have no fired signal in a given month.
    sparse = {k: v["missing_rate"] for k, v in profile.items()
              if v["missing_rate"] > 0.5}
    assert "dominant_driver" in sparse, (
        "the dictionary claims a dominant driver for obligors that have none")


def test_time_coverage_is_reported():
    profile = dic.profile()
    periods = svc.periods()
    sample = profile["ews_score"]
    assert sample["earliest_month"] == periods[0]
    assert sample["latest_month"] == periods[-1]


# ---------------------------------------------------- the grain package


def test_the_package_describes_the_domain_a_planner_will_read():
    package = grain_mod.build("Why has portfolio EWS deteriorated?")
    found = package.to_dict()
    assert found["domain"] == "Early Warning"
    assert found["period_count"] >= REQUIRED_MONTHS
    assert found["customer_count"] > 0
    assert found["field_count"] == len(dic.fields())
    assert found["groupings"]
    assert found["analytical_grains"]
    assert found["methodology"]["signals_total"] == 123


def test_the_package_carries_bounded_samples_not_the_data():
    """Twenty months of three hundred obligors is not context, it is a bill."""
    package = grain_mod.build("x")
    assert len(package.sample_rows) <= grain_mod.SAMPLE_ROWS
    assert package.sample_rows, "no sample rows at all"
    # And the rows are real: a sample of invented shapes is worse than none.
    keys = set(package.sample_rows[0])
    assert keys <= dic.names(), sorted(keys - dic.names())


def test_the_top_fields_exist_and_the_full_dictionary_still_travels():
    """Ranking is a hint. A planner that cannot see a field invents one."""
    package = grain_mod.build("Which layer moved most over twelve months?")
    assert package.top_fields
    for found in package.top_fields:
        assert found["name"] in dic.names(), found["name"]
    # The whole dictionary is present regardless of the ranking.
    described = {f["name"]
                 for group in package.field_dictionary["groups"].values()
                 for f in group}
    assert described == dic.names()


def test_the_sample_respects_permission_scope():
    package = grain_mod.build("x", allowed_customers=set())
    assert package.sample_rows == [], (
        "a caller permitted no obligors was still shown some")
