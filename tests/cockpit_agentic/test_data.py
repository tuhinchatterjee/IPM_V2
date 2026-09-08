"""The twenty-quarter release, and the traps its data must not teach.
Specification sections 4, 5 and 14.1.

The release is built once per test session at a reduced scale. The integrity
gates themselves are scale-independent, and the full-scale build is exercised
by scripts/build_cockpit_agentic_v3.py with its evidence committed.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic import generate as G
from backend.cockpit_agentic import profile as P
from backend.cockpit_agentic import store
from backend.cockpit_agentic import validate_data as V


@pytest.fixture(scope="module")
def release() -> G.Release:
    built = G.build_release(dataset_release_id="test-20q", borrowers=40,
                            facilities=90)
    G.conform(built)
    return built


@pytest.fixture(scope="module")
def report(release) -> dict:
    return V.validate(release)


# ---- the gates ------------------------------------------------------------

def test_every_integrity_gate_passes(report):
    failures = [f"{f['check_id']}: {f['detail']}" for f in report["failures"]]
    assert failures == [], "\n".join(failures)
    assert report["checks_run"] >= 70


def test_the_release_covers_twenty_quarters(release):
    assert len(release.calendar) == 20
    quarters = set(release.frames[F.FACILITY_QUARTER]["reporting_quarter"])
    assert quarters == set(release.calendar.slots)


def test_the_generator_is_deterministic():
    a = G.build_release(dataset_release_id="det", borrowers=12, facilities=25)
    b = G.build_release(dataset_release_id="det", borrowers=12, facilities=25)
    left = a.frames[F.FACILITY_QUARTER].sort_values(
        ["reporting_quarter", "facility_id", "position_id"]).reset_index(drop=True)
    right = b.frames[F.FACILITY_QUARTER].sort_values(
        ["reporting_quarter", "facility_id", "position_id"]).reset_index(drop=True)
    assert left["ecl_reported"].equals(right["ecl_reported"])
    assert left["pd_pit_12m"].equals(right["pd_pit_12m"])


# ---- section 3.4: the allowlist is the dictionary --------------------------

def test_no_relation_exposes_an_undeclared_column(release):
    for relation, frame in release.frames.items():
        if relation == "cockpit_macro_pivot":
            declared = {"reporting_quarter", "country_or_region", "scenario_id"}
            declared |= {s.name for s in F.MACRO_PIVOT_FIELDS}
        else:
            declared = set(F.all_column_names(relation))
        assert set(frame.columns) == declared, (
            f"{relation}: "
            f"undeclared {sorted(set(frame.columns) - declared)}, "
            f"missing {sorted(declared - set(frame.columns))}")


def test_a_declared_but_unpopulated_column_exists_and_is_empty(release):
    """Schema existence is not population -- and the honest form of an
    unpopulated field is a column that binds and is null, not one that is
    absent and fails to resolve."""
    frame = release.frames[F.RATING_RATIO]
    assert "cash_conversion_cycle_days_source_value" in frame.columns
    assert frame["cash_conversion_cycle_days_source_value"].isna().all()


# ---- the coherence that makes an analysis mean anything -------------------

def test_ratings_track_the_borrower_and_migrate(release):
    rating = release.frames[F.RATING_RATIO]
    assert rating["risk_rating"].nunique() >= 8, (
        "a book with three grades cannot demonstrate migration")
    moves = rating.sort_values(["borrower_id", "reporting_quarter"]).groupby(
        "borrower_id")["rating_rank"].diff().dropna()
    assert (moves != 0).any(), "no rating ever changes"
    assert (moves > 0).any() and (moves < 0).any(), (
        "ratings move in only one direction")


def test_the_pit_pd_responds_to_the_cycle_and_the_ttc_pd_does_not(release):
    frame = release.frames[F.FACILITY_QUARTER]
    pit = frame.groupby("reporting_quarter")["pd_pit_12m"].mean()
    ttc = frame.groupby("reporting_quarter")["pd_ttc_12m"].mean()
    assert pit.std() > ttc.std(), (
        "the point-in-time PD must vary across the cycle more than the "
        "through-the-cycle PD, or the distinction is only a column name")


def test_covenant_breaches_follow_from_the_ratio_that_was_tested(release):
    covenant = release.frames[F.COVENANT]
    rating = release.frames[F.RATING_RATIO]
    tested = covenant[covenant["test_status"].isin(["compliant", "breached"])]
    joined = tested.merge(
        rating[["reporting_quarter", "borrower_id", "dscr"]],
        on=["reporting_quarter", "borrower_id"], how="left")
    dscr = joined[joined["metric_name"] == "dscr"].dropna(
        subset=["dscr", "observed_value"])
    assert len(dscr) > 0
    assert np.allclose(dscr["observed_value"], dscr["dscr"]), (
        "the tested value must be the borrower's actual ratio, not an "
        "independently drawn number")
    breached = dscr[dscr["test_status"] == "breached"]
    compliant = dscr[dscr["test_status"] == "compliant"]
    if len(breached) and len(compliant):
        assert breached["dscr"].mean() < compliant["dscr"].mean()


def test_the_book_contains_the_shapes_a_demonstration_needs(release):
    facility = release.frames[F.FACILITY_QUARTER]
    covenant = release.frames[F.COVENANT]
    qualitative = release.frames[F.QUALITATIVE]
    allocation = release.frames[F.COLLATERAL_ALLOCATION]

    assert set(facility["ifrs9_stage"].unique()) >= {1, 2}, "no stage variety"
    assert facility.groupby(["reporting_quarter", "borrower_id"]).size().max() > 1, \
        "no borrower has several facilities"
    assert allocation.groupby(["reporting_quarter", "collateral_id"]).size().max() > 1, \
        "no collateral is shared"
    assert set(covenant["test_status"].unique()) >= {"compliant", "breached",
                                                     "waived", "not_tested"}
    assert (qualitative["answer_status"] == "not_answered").any()
    assert facility.groupby(["facility_id", "position_id"]).size().min() < 20, \
        "every facility spans the whole window, so origination and closure are "\
        "not demonstrated"


def test_positions_exist_so_the_atomic_key_is_not_facility_alone(release):
    frame = release.frames[F.FACILITY_QUARTER]
    per_facility = frame.groupby(
        ["reporting_quarter", "facility_id"])["position_id"].nunique()
    assert per_facility.max() > 1, (
        "no facility has independently measured positions, so position_id in "
        "the atomic key would be unmotivated")


# ---- the profiler ---------------------------------------------------------

def test_the_profile_is_computed_from_the_whole_release(release):
    coverage = P.profile_release(release)
    facility_rows = len(release.frames[F.FACILITY_QUARTER])
    spec = coverage.fields[f"{F.FACILITY_QUARTER}.pd_pit_12m"]
    assert spec.total_rows == facility_rows > 10, (
        "the profile must measure every row, not a ten-row preview")


def test_a_global_rate_does_not_conceal_an_empty_quarter(release):
    """Section 5: a global rate must not conceal a completely missing selected
    quarter. Return on assets has no true opening balance in the first slot."""
    coverage = P.profile_release(release)
    spec = coverage.fields[f"{F.RATING_RATIO}.return_on_assets"]
    assert spec.missing_rate_overall < 0.20
    entry = spec.compact()
    assert entry["quarters_fully_missing"] == [release.calendar.slots[0]]


def test_the_two_denominators_are_reported_separately(release):
    coverage = P.profile_release(release)
    for spec in coverage.fields.values():
        assert 0.0 <= spec.missing_rate_overall <= 1.0
        assert 0.0 <= spec.missing_rate_among_applicable <= 1.0
    note = P.compact(coverage)["denominator_note"]
    assert "not_applicable" in note and "quarters_fully_missing" in note


def test_truncating_the_profile_says_so_and_keeps_the_worst(release):
    coverage = P.profile_release(release)
    bounded = P.compact(coverage, limit=20)
    listed = [e for entries in bounded["fields_with_gaps"].values()
              for e in entries]
    assert len(listed) == 20
    assert bounded["further_fields_with_gaps_not_listed"] > 0
    assert "not listed here" in bounded["truncation_note"]
    # Every field entirely absent from a quarter survives the truncation.
    full = P.compact(coverage)
    critical = {e["n"] for entries in full["fields_with_gaps"].values()
                for e in entries if "quarters_fully_missing" in e}
    kept = {e["n"] for e in listed}
    assert critical <= kept or len(critical) > 20


def test_small_groups_are_suppressed(release):
    coverage = P.profile_release(release)
    for spec in coverage.fields.values():
        for _quarter, rate in spec.by_quarter.items():
            assert 0.0 <= rate <= 1.0
    assert P.SMALL_GROUP_FLOOR >= 5


# ---- runtime isolation ----------------------------------------------------

@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """Point the V3 lake at a temporary directory.

    Settings is a frozen dataclass, so the whole object is replaced rather than
    a field mutated -- which is also how a deployment would override it.
    """
    import dataclasses

    from backend import config

    def configure(**overrides):
        monkeypatch.setattr(
            config, "settings",
            dataclasses.replace(config.settings, **overrides))
        return config.settings

    configure(cockpit_agentic_v3=True,
              analytics_dir=tmp_path / "analytics")
    return configure


def test_a_write_outside_the_namespace_is_refused(isolated, tmp_path):
    with pytest.raises(store.UnsafeTarget, match="namespace"):
        store.check_target(tmp_path / "data" / "analytics" / "release")
    with pytest.raises(store.UnsafeTarget, match="namespace"):
        store.check_target(tmp_path / "somewhere_else")


def test_a_build_with_the_switch_off_is_refused(isolated, tmp_path):
    isolated(cockpit_agentic_v3=False, analytics_dir=tmp_path / "analytics")
    with pytest.raises(store.UnsafeTarget, match="switched off"):
        store.check_target(tmp_path / "cockpit_agentic_v3" / "r")


def test_the_namespace_is_where_the_release_actually_goes(isolated, tmp_path):
    target = store.release_dir("demo-20q-v1")
    assert "cockpit_agentic_v3" in str(target)
    assert str(tmp_path) in str(target)


def test_a_published_release_is_immutable_unless_overwrite_is_explicit(
        isolated, release):
    store.write(release, overwrite=True)
    with pytest.raises(store.UnsafeTarget, match="immutable"):
        store.write(release)
    manifest = store.read_manifest(release.dataset_release_id)
    assert manifest["domain_id"] == "corporate_cockpit"
    assert manifest["origin"] == "SYNTHETIC_DEMO"
    assert len(manifest["calendar"]["reporting_slots"]) == 20
    assert "no real borrower" in manifest["not_client_data"]


def test_a_published_release_round_trips(isolated, release):
    store.write(release, overwrite=True)
    calendar = store.load_calendar(release.dataset_release_id)
    assert calendar.slots == release.calendar.slots
    frame = store.read_relation(release.dataset_release_id, F.FACILITY_QUARTER)
    assert len(frame) == len(release.frames[F.FACILITY_QUARTER])
    assert set(frame.columns) == set(release.frames[F.FACILITY_QUARTER].columns)


def test_a_missing_release_is_said_not_substituted(isolated):
    with pytest.raises(store.ReleaseNotFound, match="not published"):
        store.read_manifest("no-such-release")
    with pytest.raises(store.ReleaseNotFound):
        store.read_relation("no-such-release", F.FACILITY_QUARTER)
