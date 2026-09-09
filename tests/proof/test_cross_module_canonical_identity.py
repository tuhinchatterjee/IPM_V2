"""
The same borrower is the same borrower in every module.

This is the test the integration exists for. Eight sessions each built a
module; four of them read a corporate book; and until the Cockpit was repointed
two of those books were different populations in different currencies on
different calendars. A product where "CORP-100000" means one thing in Borrower
360 and nothing at all in the Cockpit is eight products sharing a menu.

So: pick real borrowers and real facilities, and prove that Cockpit, Early
Warning, What-If and Borrower 360 are all describing the SAME rows. Not that
each module is internally consistent — each was already that — but that they
agree with each other.

Where a module deliberately owns a field, it is named as owned rather than
compared. A silent contradiction is the failure; a declared difference is not.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd
import pytest



LAKE = Path("data/analytics")
COCKPIT_RELEASE = "canonical-16q-v1"

#: The quarter every module is asked about. The last canonical one.
PERIOD = "Q2 2026"
SLOT = "2026Q2"


def _read(name: str) -> pd.DataFrame:
    parts = sorted(glob.glob(str(LAKE / name / "**" / "*.parquet"),
                             recursive=True))
    if not parts:
        pytest.skip(f"{name} is not built in this environment")
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)


def _cockpit(relation: str) -> pd.DataFrame:
    path = Path("data/cockpit_agentic_v3") / COCKPIT_RELEASE / f"{relation}.parquet"
    if not path.exists():
        pytest.skip(f"the canonical Cockpit release is not built here "
                    f"({path}); run scripts/build_cockpit_canonical.py")
    return pd.read_parquet(path)


@pytest.fixture(scope="module")
def canonical() -> pd.DataFrame:
    frame = _read("corporate_ifrs9")
    return frame[frame["period"] == PERIOD].set_index("borrower_id")


@pytest.fixture(scope="module")
def borrowers(canonical: pd.DataFrame) -> list[str]:
    """Several real borrowers, chosen to span the staging, not the top of a
    sorted list.

    One from each IFRS 9 stage plus the largest exposure: a check that passed
    only on well-behaved Stage 1 names would prove very little.
    """
    picked: list[str] = []
    for stage in (1, 2, 3):
        block = canonical[canonical["stage"] == stage]
        if len(block):
            picked.extend(block.sort_values("ead", ascending=False)
                          .head(2).index.tolist())
    picked.append(canonical["ead"].idxmax())
    return sorted(set(picked))


@pytest.fixture(scope="module")
def facilities(borrowers: list[str]) -> list[str]:
    frame = _read("corporate_facilities")
    block = frame[(frame["period"] == PERIOD)
                  & (frame["borrower_id"].isin(borrowers))]
    return sorted(block["facility_id"].unique())[:12]


# ---------------------------------------------------------------- the sample

def test_the_sample_is_real_and_spans_the_staging(borrowers, canonical):
    assert len(borrowers) >= 4, borrowers
    stages = set(canonical.loc[borrowers, "stage"].unique())
    assert stages == {1, 2, 3}, (
        f"the sample must span every stage to be worth anything; got {stages}")


def test_several_facilities_are_addressed_not_one(facilities):
    assert len(facilities) >= 4, facilities
    assert all(f.startswith("CFAC-") for f in facilities), facilities


# ------------------------------------------------------------------- Cockpit

def test_cockpit_addresses_the_same_borrowers(borrowers):
    frame = _cockpit("cockpit_facility_quarter")
    present = set(frame[frame["reporting_quarter"] == SLOT]["borrower_id"])
    missing = [b for b in borrowers if b not in present]
    assert not missing, (
        f"the Cockpit cannot address {missing}, which every other module can. "
        f"That is the two-populations defect this test exists to catch.")


def test_cockpit_addresses_the_same_facilities(facilities):
    frame = _cockpit("cockpit_facility_quarter")
    present = set(frame[frame["reporting_quarter"] == SLOT]["facility_id"])
    missing = [f for f in facilities if f not in present]
    assert not missing, f"the Cockpit cannot address {missing}"


def test_cockpit_carries_no_identifier_from_the_retired_private_book():
    frame = _cockpit("cockpit_facility_quarter")
    for column in ("borrower_id", "facility_id", "borrower_group_id"):
        values = frame[column].astype(str)
        stray = values[values.str.match(r"^(BRW|FAC0|GRP0)")]
        assert stray.empty, (
            f"{len(stray)} {column} values still come from the Cockpit's own "
            f"book, e.g. {stray.head(3).tolist()}")


def test_cockpit_reports_in_the_canonical_denomination():
    frame = _cockpit("cockpit_facility_quarter")
    assert set(frame["reporting_currency"].unique()) == {"SAR"}
    assert set(frame["amount_scale"].unique()) == {"millions"}


def test_cockpit_stage_pd_lgd_and_ead_equal_the_canonical_book(
        borrowers, canonical):
    """The whole point. Cockpit READS the book; it does not assign one."""
    frame = _cockpit("cockpit_facility_quarter")
    frame = frame[(frame["reporting_quarter"] == SLOT)
                  & (frame["borrower_id"].isin(borrowers))]
    grouped = frame.groupby("borrower_id")

    for borrower in borrowers:
        block = grouped.get_group(borrower)
        want = canonical.loc[borrower]

        # Stage, SICR and default are obligor properties: every facility of the
        # borrower must carry the borrower's, and it must be the canonical one.
        assert set(block["ifrs9_stage"].unique()) == {int(want["stage"])}, (
            f"{borrower}: Cockpit stage {set(block['ifrs9_stage'].unique())} "
            f"against canonical {int(want['stage'])}")
        assert set(block["sicr_flag"].unique()) == {bool(want["sicr_flag"])}
        assert set(block["default_flag"].unique()) == {bool(want["default_flag"])}
        assert set(block["days_past_due"].unique()) == {int(want["current_dpd"])}

        # PD and LGD are stated as probabilities by the Cockpit and as
        # percentages by the canonical book. One conversion, asserted.
        assert block["pd_pit_12m"].round(8).nunique() == 1
        assert block["pd_pit_12m"].iloc[0] == pytest.approx(
            want["pit_pd_12m_pct"] / 100.0, abs=1e-9)
        assert block["lgd_pit"].iloc[0] == pytest.approx(
            want["lgd"] / 100.0, abs=1e-9)

        # EAD and ECL are facility quantities that must SUM to the obligor's.
        assert block["ead_reported"].sum() == pytest.approx(
            float(want["ead"]), abs=0.01), (
            f"{borrower}: Cockpit EAD {block['ead_reported'].sum():,.4f} "
            f"against canonical {float(want['ead']):,.4f}")
        assert block["ecl_reported"].sum() == pytest.approx(
            float(want["final_ecl"]), abs=0.01)


def test_cockpit_rating_equals_the_canonical_rating(borrowers):
    ratings = _read("corporate_ratings")
    ratings = ratings[ratings["period"] == PERIOD].set_index("borrower_id")
    frame = _cockpit("cockpit_rating_ratio_quarter")
    frame = frame[(frame["reporting_quarter"] == SLOT)
                  & (frame["borrower_id"].isin(borrowers))].set_index("borrower_id")
    for borrower in borrowers:
        assert frame.loc[borrower, "risk_rating"] == \
            ratings.loc[borrower, "internal_rating"]
        assert int(frame.loc[borrower, "rating_rank"]) == \
            int(ratings.loc[borrower, "internal_rating_ordinal"])


def test_the_cockpit_calendar_is_the_canonical_calendar():
    calendar = _cockpit("cockpit_reporting_calendar")
    populated = sorted(calendar[calendar["is_populated"]]["reporting_quarter"])
    assert len(populated) == 16, populated
    assert populated[0] == "2022Q3" and populated[-1] == "2026Q2", populated
    # The four unpopulated slots exist because a Cockpit release has twenty.
    # They must be EMPTY, not back-filled with a quarter canonical never had.
    empty = calendar[~calendar["is_populated"]]
    assert len(empty) == 4
    assert set(empty["facility_row_count"]) == {0}
    assert set(empty["borrower_row_count"]) == {0}


# -------------------------------------------------------------- Early Warning

def test_early_warning_addresses_canonical_borrowers():
    frame = _read("early_warning_borrower_month")
    column = "customer_id" if "customer_id" in frame.columns else "borrower_id"
    ids = frame[column].astype(str)
    assert ids.str.startswith("CORP-").all(), (
        f"{(~ids.str.startswith('CORP-')).sum()} Early Warning rows carry a "
        f"non-canonical identifier")


def test_every_early_warning_borrower_exists_in_the_canonical_book():
    ews = _read("early_warning_borrower_month")
    column = "customer_id" if "customer_id" in ews.columns else "borrower_id"
    known = set(_read("corporate_ifrs9")["borrower_id"])
    orphans = sorted(set(ews[column].astype(str)) - known)
    assert not orphans, f"{len(orphans)} orphan EWS borrowers, e.g. {orphans[:5]}"


# -------------------------------------------------------------------- What-If

def test_whatif_reads_the_same_book_the_cockpit_now_reads(borrowers):
    """What-If selects from `corporate_borrower_360` and `corporate_ifrs9`.

    Asserting the sample resolves there is what makes "the same borrower" true
    across What-If and the Cockpit rather than merely likely.
    """
    frame = _read("corporate_borrower_360")
    frame = frame[frame["period"] == PERIOD]
    present = set(frame["borrower_id"])
    missing = [b for b in borrowers if b not in present]
    assert not missing, missing


def test_the_reported_period_set_is_sixteen_quarters_everywhere():
    corporate = set(_read("corporate_ifrs9")["period"])
    assert len(corporate) == 16, sorted(corporate)
    facility = set(_read("corporate_ifrs9_facility")["period"])
    assert facility == corporate
    # And no forward quarter has leaked in from anywhere.
    years = {int(p.split()[1]) for p in corporate}
    assert years == {2022, 2023, 2024, 2025, 2026}, sorted(years)


# --------------------------------------------------------------- Borrower 360

def test_borrower_360_agrees_with_the_canonical_ifrs9_book(borrowers, canonical):
    frame = _read("corporate_borrower_360")
    frame = frame[frame["period"] == PERIOD].set_index("borrower_id")
    for borrower in borrowers:
        row = frame.loc[borrower]
        want = canonical.loc[borrower]
        for shared, expected in (("stage", "stage"), ("ead", "ead"),
                                 ("final_ecl", "final_ecl"), ("lgd", "lgd")):
            if shared not in row.index:
                continue
            assert float(row[shared]) == pytest.approx(
                float(want[expected]), rel=1e-6), (
                f"{borrower}: Borrower 360 {shared}={row[shared]} against "
                f"canonical {want[expected]}")


# ------------------------------------------------- the facility-grain identity

def test_facility_ifrs9_reconciles_to_the_obligor_book():
    from backend.corporate import ifrs9_facility as derive

    facility = _read("corporate_ifrs9_facility")
    obligor = _read("corporate_ifrs9")
    breaks = derive.reconciles(facility, obligor, tolerance=1e-9)
    assert breaks.empty, (
        f"{len(breaks)} borrower-quarter(s) where the facility book does not "
        f"sum back to the obligor book:\n{breaks.head().to_string()}")


def test_every_facility_belongs_to_a_canonical_borrower():
    facility = _read("corporate_ifrs9_facility")
    known = set(_read("corporate_ifrs9")["borrower_id"])
    orphans = sorted(set(facility["borrower_id"]) - known)
    assert not orphans, orphans[:5]
