"""The field dictionary must agree with the parquet, or it is a wish list.

REAL DATA. Reads both published books. No model, no provider call.

Section 3.2 wants a field dictionary; section 3.1 wants primary-key
uniqueness, join cardinality and before/after checks. A dictionary written
from a schema comment would pass its own review and fail the first scenario,
so every claim here is checked against the bytes.

Three measured facts drive the eligibility rules, and each has a test that
would fail if the book changed under them:

  D-identity   published ECL is `ead x pd x lgd`, and on Corporate the
               aggregate difference is -0.3343 on 7,075,662 SAR mn
  D-stage3     Stage 3 carries PD exactly 1.0, so a PD shock is meaningless
  D-floor      1,837 written-off Retail accounts carry a floor worth
               53.04 SAR mn, 1.97% of that book

Covers D01, D04, D06, D07 and D11 of section 16.2.
"""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal

import duckdb
import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import ScenarioError

LAKE = pathlib.Path("data/cockpit_v4_lake")
RELEASES = {dom.CORPORATE: "v4-saudi-corporate-20q-v4",
            dom.RETAIL: "v4-saudi-retail-20m-v5"}
GRAIN = {dom.CORPORATE: ("corp_facility_quarter", "facility_id",
                         "reporting_quarter"),
         dom.RETAIL: ("retail_account_month", "account_id",
                      "reporting_month")}


@pytest.fixture(scope="module")
def con():
    if not LAKE.exists():
        pytest.skip("the published lake is not present in this worktree; "
                    "copy or publish it (see BASELINE_AND_EXTENSION_MAP.md)")
    return duckdb.connect()


def table(domain_id: str) -> str:
    relation, _, _ = GRAIN[domain_id]
    return str(LAKE / RELEASES[domain_id] / f"{relation}.parquet")


def one(con, sql: str):
    return con.execute(sql).fetchone()


BOOKS = [dom.CORPORATE, dom.RETAIL]


# ---- D01: the declared grain is the actual grain -----------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_d01_the_ecl_relation_is_unique_on_its_declared_key(con,
                                                            domain_id) -> None:
    _, key, period = GRAIN[domain_id]
    rows, keys = one(con, f"""
        SELECT COUNT(*), COUNT(DISTINCT ({key} || '|' || {period}))
        FROM '{table(domain_id)}'""")
    assert rows == keys, (
        f"{domain_id}: {rows:,} rows over {keys:,} distinct "
        f"({key}, {period}) pairs -- the grain is not what it says")


@pytest.mark.parametrize("domain_id", BOOKS)
def test_d04_the_latest_period_comes_from_the_data(con, domain_id) -> None:
    """Section 3.1: the latest COMPLETE approved period, not the wall clock."""
    _, _, period = GRAIN[domain_id]
    count, newest = one(con, f"""
        SELECT COUNT(DISTINCT {period}), MAX({period})
        FROM '{table(domain_id)}'""")
    assert count == 20, f"{domain_id} has {count} periods, not 20"
    manifest = json.loads(
        (LAKE / RELEASES[domain_id] / "manifest.json").read_text())
    assert newest == manifest["reporting_periods"][-1]
    assert newest in ("2026Q2", "2026-08")


# ---- every dictionary entry is real ------------------------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_published_field_is_a_real_column(con, domain_id) -> None:
    columns = {r[0] for r in
               con.execute(f"DESCRIBE SELECT * FROM '{table(domain_id)}'"
                           ).fetchall()}
    for entry in fd.BY_DOMAIN[domain_id]:
        if entry.availability != fd.PUBLISHED:
            continue
        if entry.relation != GRAIN[domain_id][0]:
            continue  # borrower-grain fields live in another parquet
        assert entry.field_id in columns, (
            f"{domain_id}.{entry.field_id} is declared PUBLISHED and is not "
            f"a column of {entry.relation}")


@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_absent_field_really_is_absent(con, domain_id) -> None:
    """The harder half. A field wrongly marked ABSENT hides a capability."""
    columns = {r[0] for r in
               con.execute(f"DESCRIBE SELECT * FROM '{table(domain_id)}'"
                           ).fetchall()}
    for entry in fd.absent(domain_id):
        assert entry.field_id not in columns, (
            f"{domain_id}.{entry.field_id} is declared ABSENT and the column "
            f"exists -- the dictionary is hiding something the book has")
        assert len(entry.absent_note) > 60, entry.field_id


# ---- D-identity: why proportional Delta is sound here ------------------

def _identity_sql(domain_id: str) -> str:
    return f"""
    WITH x AS (SELECT *, ead_sar_mn *
                 (CASE WHEN stage = 1 THEN pd_pit_12m ELSE pd_lifetime END)
                 * lgd_pct/100.0 AS implied FROM '{table(domain_id)}')
    SELECT SUM(ecl_sar_mn), SUM(implied), MAX(ABS(ecl_sar_mn - implied))
    FROM x"""


def test_the_corporate_ecl_identity_is_exact_in_aggregate(con) -> None:
    """D-identity. This is the measurement proportional Delta rests on: if
    ECL is linear in PD, a 20% PD rise really is a 20% ECL rise."""
    published, implied, worst = one(con, _identity_sql(dom.CORPORATE))
    assert abs(published - implied) < Decimal("1"), (
        f"identity off by {published - implied:,.4f} SAR mn")
    assert abs(published - implied) / published < 1e-7
    assert worst < 0.02, f"worst single row off by {worst}"


def test_the_retail_identity_breaks_only_on_the_write_off_floor(con) -> None:
    """D-floor. 1.97% of the Retail book, entirely from written-off accounts.

    Quantified rather than waved at, because it is exactly the population the
    dictionary excludes from proportional Delta.
    """
    published, implied, _ = one(con, _identity_sql(dom.RETAIL))
    gap = published - implied
    assert gap > 0, "the floor can only raise ECL"
    assert 1.5 < gap / published * 100 < 2.5, f"{gap / published * 100:.2f}%"

    floor_rows, floor_gap = one(con, f"""
        WITH x AS (SELECT *, ead_sar_mn*pd_lifetime*lgd_pct/100.0 AS implied
                   FROM '{table(dom.RETAIL)}'
                   WHERE stage = 3 AND write_off_sar_mn > 0)
        SELECT COUNT(*), SUM(ecl_sar_mn - implied) FROM x""")
    assert floor_rows > 0
    assert abs(floor_gap - gap) < Decimal("0.01"), (
        f"the whole {gap:,.4f} gap should be the floor, and the written-off "
        f"rows account for {floor_gap:,.4f}")


# ---- D-stage3: the exclusion that is not an opinion --------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_stage_three_carries_a_pd_of_exactly_one(con, domain_id) -> None:
    rows, lo, hi = one(con, f"""
        SELECT COUNT(*), MIN(pd_pit_12m), MAX(pd_pit_12m)
        FROM '{table(domain_id)}' WHERE stage = 3""")
    assert rows > 0
    assert lo == 1.0 and hi == 1.0, (
        f"{domain_id} Stage 3 PD spans [{lo}, {hi}] -- the exclusion rule "
        f"assumes it is exactly 1.0")


@pytest.mark.parametrize("domain_id", BOOKS)
@pytest.mark.parametrize("field_id", ["pd_pit_12m", "pd_lifetime"])
def test_a_pd_shock_excludes_stage_three_with_its_reason(domain_id,
                                                         field_id) -> None:
    predicate, reason = fd.sql_ineligibility(domain_id, field_id)
    assert predicate == "stage = 3"
    assert "already one" in reason
    assert "excluded" in reason and "scaled" in reason


def test_the_predicate_selects_what_it_says(con) -> None:
    """The reason is prose; the predicate is what actually runs."""
    predicate, _ = fd.sql_ineligibility(dom.CORPORATE, "pd_pit_12m")
    excluded, total = one(con, f"""
        SELECT SUM(CASE WHEN {predicate} THEN 1 ELSE 0 END), COUNT(*)
        FROM '{table(dom.CORPORATE)}'""")
    stage3 = one(con, f"SELECT COUNT(*) FROM '{table(dom.CORPORATE)}' "
                      f"WHERE stage = 3")[0]
    assert excluded == stage3 > 0
    assert excluded < total, "a shock that excludes everything is not a shock"


def test_retail_proportional_delta_excludes_the_floored_rows() -> None:
    for field_id in ("lgd_pct", "ead_sar_mn"):
        predicate, reason = fd.sql_ineligibility(dom.RETAIL, field_id)
        assert predicate == "write_off_sar_mn > 0"
        assert "not a function of PD, LGD or EAD" in reason


def test_corporate_lgd_excludes_nothing() -> None:
    """The floor is a Retail generator rule. Corporate has no equivalent, and
    inventing a symmetric exclusion would cost real rows for tidiness."""
    predicate, reason = fd.sql_ineligibility(dom.CORPORATE, "lgd_pct")
    assert predicate == ""
    assert "every row" in fd.eligibility_note(dom.CORPORATE, "lgd_pct")
    assert reason == ""


# ---- the derived CCF ---------------------------------------------------

def test_the_derived_ccf_reconstructs_ead_exactly(con) -> None:
    worst, undefined = one(con, f"""
        SELECT MAX(ABS(ead_sar_mn - (drawn_sar_mn + undrawn_sar_mn *
                   ((ead_sar_mn - drawn_sar_mn)
                    / NULLIF(undrawn_sar_mn, 0))))),
               SUM(CASE WHEN undrawn_sar_mn = 0 THEN 1 ELSE 0 END)
        FROM '{table(dom.CORPORATE)}'""")
    assert worst < 1e-9, f"CCF does not invert EAD: worst {worst}"
    assert undefined > 0, "there should be facilities with no undrawn"


def test_ccf_is_labelled_derived_and_says_how(con) -> None:
    """Section 3.3: a derivation may not be passed off as a source fact."""
    entry = fd.lookup(dom.CORPORATE, "ccf")
    assert entry.availability == fd.DERIVED
    assert "(ead_sar_mn - drawn_sar_mn) / undrawn_sar_mn" in entry.derivation
    assert fd.derived(dom.CORPORATE) == (entry,)


def test_a_zero_undrawn_facility_has_no_ccf_sensitivity() -> None:
    predicate, reason = fd.sql_ineligibility(dom.CORPORATE, "ccf")
    assert predicate == "undrawn_sar_mn = 0"
    assert "no CCF to convert" in reason


def test_retail_has_no_ccf_at_all() -> None:
    """Not derivable either: ead = balance on four of five products, and the
    fifth uses a constant that lives in the generator."""
    entry = fd.lookup(dom.RETAIL, "ccf")
    assert entry.availability == fd.ABSENT
    assert "0.45" in entry.absent_note
    predicate, reason = fd.sql_ineligibility(dom.RETAIL, "ccf")
    assert predicate == "TRUE", "every Retail row is ineligible"
    assert "nothing to act on" in reason


# ---- D07, D11: distinctions the dictionary must keep -------------------

def test_d07_a_missing_value_is_not_a_zero_value() -> None:
    for domain_id, field_id in ((dom.RETAIL, "behaviour_score"),
                                (dom.CORPORATE, "ccf"),
                                (dom.CORPORATE, "rating_current")):
        note = fd.lookup(domain_id, field_id).missing_means
        assert note, f"{domain_id}.{field_id} does not say what missing means"
        assert "not" in note.lower()


def test_d11_retail_product_is_not_a_sector() -> None:
    """Section 3.3 names this substitution and forbids it."""
    sector = fd.lookup(dom.RETAIL, "sector")
    assert sector.availability == fd.ABSENT
    assert "product is not a substitute" in sector.absent_note
    assert fd.lookup(dom.RETAIL, "product").availability == fd.PUBLISHED


def test_an_application_score_is_not_a_behavioural_one() -> None:
    """Section 8: an origination score must not be substituted."""
    application = fd.lookup(dom.RETAIL, "application_score")
    assert application.availability == fd.ABSENT
    assert "must not be substituted" in application.absent_note
    assert fd.lookup(dom.RETAIL, "behaviour_score").availability == (
        fd.PUBLISHED)


def test_the_two_pd_horizons_are_kept_apart() -> None:
    """Section 9.2: PD12 and lifetime PD are distinct measurement concepts."""
    for domain_id in BOOKS:
        twelve = fd.lookup(domain_id, "pd_pit_12m")
        life = fd.lookup(domain_id, "pd_lifetime")
        assert twelve.horizon == "12 months"
        assert "lifetime" in life.horizon
        assert "not published" in life.horizon, (
            "the lifetime horizon length is genuinely absent and the "
            "dictionary must not imply otherwise")


def test_d06_probabilities_are_fractions_and_percents_are_percents() -> None:
    """Section 3.2's internal convention, per column rather than per name."""
    for domain_id in BOOKS:
        assert fd.lookup(domain_id, "pd_pit_12m").storage == un.FRACTION
        assert fd.lookup(domain_id, "lgd_pct").storage == un.PERCENT
        assert fd.lookup(domain_id, "ead_sar_mn").storage == un.MONEY


@pytest.mark.parametrize("domain_id", BOOKS)
def test_the_declared_ranges_hold_in_the_data(con, domain_id) -> None:
    for entry in fd.BY_DOMAIN[domain_id]:
        if entry.availability != fd.PUBLISHED or entry.low is None:
            continue
        if entry.relation != GRAIN[domain_id][0]:
            continue
        lo, hi = one(con, f"SELECT MIN({entry.field_id}), "
                          f"MAX({entry.field_id}) FROM '{table(domain_id)}'")
        assert Decimal(str(lo)) >= entry.low, f"{entry.field_id} min {lo}"
        if entry.high is not None:
            assert Decimal(str(hi)) <= entry.high, (
                f"{entry.field_id} max {hi} exceeds {entry.high}")


# ---- what the dictionary refuses ---------------------------------------

def test_an_unknown_field_names_what_the_book_has() -> None:
    with pytest.raises(ScenarioError, match="not a field") as caught:
        fd.lookup(dom.CORPORATE, "probability_of_doom")
    assert caught.value.code == "MAPPING_UNAVAILABLE"
    assert "pd_pit_12m" in str(caught.value), "say what IS available"


def test_an_immutable_field_says_what_to_move_instead() -> None:
    with pytest.raises(ScenarioError, match="not something a scenario") as e:
        fd.mutable(dom.CORPORATE, "ecl_sar_mn")
    assert e.value.detail["affects"] == []


def test_an_absent_field_is_refused_with_its_reason() -> None:
    with pytest.raises(ScenarioError, match="not in the retail book") as e:
        fd.mutable(dom.RETAIL, "sector")
    assert "product is not a substitute" in str(e.value)


def test_a_utilisation_shock_is_redirected_to_its_drivers() -> None:
    """Utilisation is drawn over limit. Moving it directly would be moving a
    quotient and hoping the numerator followed."""
    with pytest.raises(ScenarioError) as caught:
        fd.mutable(dom.CORPORATE, "utilisation_pct")
    assert "Move what drives it" in str(caught.value)


def test_stage_is_movable_but_only_by_a_user_assumption() -> None:
    """Section 8: stages frozen by default; an explicit migration needs an
    approved rule, a horizon conversion and method support -- none of which
    this book has, so Delta is not offered for it."""
    from backend.cockpit_v4.scenario import spec as sp

    entry = fd.mutable(dom.CORPORATE, "stage")
    assert entry.mutable is True
    assert entry.methods == (sp.USER_DEFINED,)
    assert sp.DELTA not in entry.methods
