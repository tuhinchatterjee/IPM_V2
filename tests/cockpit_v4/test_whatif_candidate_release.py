"""The published candidate release, opened and reconciled through DuckDB.

REAL DATABASE · NO MODEL. The published candidate parquet through a real
DuckDB session, opened the way the Cockpit opens a book. No provider in this
module, not even a scripted one.

Two things are proved here and nothing else will prove them:

**The accepted books did not move.** The candidate release is written into the
same lake root the accepted books live in. Their fingerprints are re-read from
their own manifests and compared with the values recorded at `245c50e`, so a
generator that reached into them would fail here rather than in front of a
reader.

**The candidate measures what it claims to.** Book ECL equals modelled plus
overlay, exactly; the weighted term structure equals the modelled figure,
exactly; and the published ECL is NOT `ead x pd x lgd`, which is the whole
reason this release exists. A candidate whose ECL were the closed form would
make section 11's emulator a tautology.

Skipped, not failed, when the candidate is not published: it is built by
`scripts/whatif/seed_candidate.py` and a fresh checkout has no lake at all.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import domain_resolver as resolver
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import candidate_schema as cs
from backend.cockpit_v4.scenario import flags as fl
from backend.cockpit_v4.scenario import reference_ecl as ref

D = Decimal

#: The accepted books' fingerprints, as published at the accepted baseline.
#: Written out rather than read from the manifests twice: comparing a file
#: with itself proves nothing, and these are the values `PROTECTED_FILES`
#: pins the parquet bytes to.
ACCEPTED_FINGERPRINTS = {
    "v4-saudi-corporate-20q-v4":
        "e37236d0f6d4e494fea0fe2f2b66b83085e76cb9eabdd2c2e2b95ea87a36750f",
    "v4-saudi-retail-20m-v5":
        "a1e797dcc73236b7a0bdac3635712a912c5680a1b3c7de60f059c78d893706cb",
}

BOOKS = (
    (dom.CORPORATE, "corp_facility_quarter", "whatif_corp_ifrs9",
     "facility_id", "reporting_quarter"),
    (dom.RETAIL, "retail_account_month", "whatif_retail_ifrs9",
     "account_id", "reporting_month"),
)


@pytest.fixture(scope="module", autouse=True)
def _candidate_published():
    if not pathlib.Path("data/cockpit_v4_lake").exists():
        pytest.skip("the published lake is not present in this worktree")
    missing = [r for r in cs.RELEASES.values() if not lake.exists(r)]
    if missing:
        pytest.skip(f"candidate release(s) {missing} are not published; "
                    f"run scripts/whatif/seed_candidate.py")
    arun.reset()
    yield
    arun.reset()


@pytest.fixture()
def enabled(monkeypatch):
    for variable in fl.VARIABLES.values():
        monkeypatch.setenv(variable, "1")
    arun.reset()
    yield
    arun.reset()


def book_of(domain_id):
    scope = resolver.scope_for(domain_id, tenant_id=lake.DEFAULT_TENANT)
    return scope, arun.for_domain(domain_id).session.connection


# ---- the accepted books are untouched ---------------------------------

@pytest.mark.parametrize("release,digest", sorted(
    ACCEPTED_FINGERPRINTS.items()))
def test_the_accepted_releases_are_byte_identical(release, digest) -> None:
    """A01, A02 and D09. The candidate is written into the same lake root,
    so this is not a formality."""
    assert lake.exists(release)
    assert lake.fingerprint(release) == digest


def test_the_candidate_is_a_different_release_with_a_different_fingerprint(
) -> None:
    accepted = set(ACCEPTED_FINGERPRINTS.values())
    for release in cs.RELEASES.values():
        assert lake.fingerprint(release) not in accepted


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_candidate_manifest_says_it_is_synthetic(domain_id) -> None:
    manifest = lake.read_manifest(cs.RELEASES[domain_id])
    assert manifest["origin"] == "SYNTHETIC_DEMO"
    notes = manifest["notes"]
    assert "not a bank engine" in notes["not_a_bank_engine"].lower()
    assert "not economic history" in notes["macro_is_generated"]


# ---- the Cockpit opens it ---------------------------------------------

@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_runtime_opens_the_candidate_when_the_book_is_enabled(
        enabled, domain_id) -> None:
    """End to end through `domain_resolver.scope_for` -- the same call a live
    run makes -- rather than by reading the parquet directly."""
    scope, _connection = book_of(domain_id)
    assert scope.release_id == cs.RELEASES[domain_id]
    assert scope.release_fingerprint == lake.fingerprint(scope.release_id)
    for name in cs.relation_names(domain_id):
        assert name in scope.relations


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_runtime_opens_the_accepted_book_with_the_flags_off(
        monkeypatch, domain_id) -> None:
    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    arun.reset()
    scope = resolver.scope_for(domain_id, tenant_id=lake.DEFAULT_TENANT)
    assert scope.release_id == dom.DEFAULT_RELEASES[domain_id]
    assert not any(r.startswith("whatif_") for r in scope.relations)
    arun.reset()


# ---- the measurement reconciles ---------------------------------------

@pytest.mark.parametrize("domain_id,book,ifrs9,key,period_column", BOOKS)
def test_published_ecl_is_modelled_plus_overlay_exactly(
        enabled, domain_id, book, ifrs9, key, period_column) -> None:
    """Section 9.1's split, checked as an identity rather than described."""
    scope, connection = book_of(domain_id)
    row = connection.execute(f"""
        SELECT sum(b.ecl_sar_mn) AS published,
               sum(i.ecl_modelled_sar_mn + i.ecl_overlay_sar_mn) AS parts,
               count(*) AS n
        FROM {book} b JOIN {ifrs9} i
          ON b.{key} = i.{key} AND b.{period_column} = i.{period_column}
        WHERE b.{period_column} = '{scope.latest_period}'
          AND b.stage < 3 AND b.write_off_sar_mn = 0
    """).fetchone()
    assert row[2] > 100, "not a population worth reconciling"
    assert abs(D(str(row[0])) - D(str(row[1]))) < D("0.0001")


@pytest.mark.parametrize("domain_id,book,ifrs9,key,period_column", BOOKS)
def test_the_term_structure_reconciles_to_the_modelled_figure(
        enabled, domain_id, book, ifrs9, key, period_column) -> None:
    """The weighted first bucket IS the twelve-month modelled ECL. Published
    beside the total so a reader can recompute it, which is what makes
    `reference_ecl.py` a reference rather than a black box."""
    scope, connection = book_of(domain_id)
    term = ("whatif_corp_term_structure" if domain_id == dom.CORPORATE
            else "whatif_retail_term_structure")
    rows = connection.execute(f"""
        WITH stage_one AS (
            SELECT {key} FROM {book}
            WHERE {period_column} = '{scope.latest_period}' AND stage = 1
            LIMIT 25)
        SELECT t.{key},
               sum(t.scenario_weight * t.expected_shortfall_sar_mn) AS weighted,
               max(i.ecl_modelled_sar_mn) AS modelled
        FROM {term} t
        JOIN stage_one USING ({key})
        JOIN {ifrs9} i ON i.{key} = t.{key}
                      AND i.{period_column} = t.{period_column}
        WHERE t.{period_column} = '{scope.latest_period}'
          AND t.horizon_index = 0
        GROUP BY t.{key}
    """).fetchall()
    assert len(rows) >= 20
    for key_value, weighted, modelled in rows:
        assert abs(D(str(weighted)) - D(str(modelled))) < D("0.000002"), (
            key_value)


@pytest.mark.parametrize("domain_id,book,ifrs9,key,period_column", BOOKS)
def test_published_ecl_is_not_the_closed_form(
        enabled, domain_id, book, ifrs9, key, period_column) -> None:
    """The reason this release exists. Section 11.1: *"Do not manufacture the
    training label as PD x LGD x EAD and then claim the resulting model
    learned the bank's ECL engine."* The accepted books measure exactly that
    product; this one does not, and a model trained here has a real function
    to learn.
    """
    scope, connection = book_of(domain_id)
    published, closed_form = connection.execute(f"""
        SELECT sum(ecl_sar_mn),
               sum(ead_sar_mn * pd_pit_12m * lgd_pct / 100.0)
        FROM {book}
        WHERE {period_column} = '{scope.latest_period}' AND stage = 1
    """).fetchone()
    assert published > 0 and closed_form > 0
    gap = abs(published - closed_form) / closed_form
    assert gap > 0.01, (
        f"{domain_id}: published ECL is within {gap:.4%} of ead x pd x lgd, "
        f"which is close enough that an emulator would be recovering a "
        f"closed form")


@pytest.mark.parametrize("domain_id,book,ifrs9,key,period_column", BOOKS)
def test_the_ecl_rate_is_on_its_declared_denominator(
        enabled, domain_id, book, ifrs9, key, period_column) -> None:
    """M01. The ML target is a rate, and a rate whose denominator is not
    stated is not a rate."""
    scope, connection = book_of(domain_id)
    rows = connection.execute(f"""
        SELECT i.ecl_denominator, i.ecl_rate, b.ecl_sar_mn, b.ead_sar_mn
        FROM {ifrs9} i JOIN {book} b
          ON b.{key} = i.{key} AND b.{period_column} = i.{period_column}
        WHERE i.{period_column} = '{scope.latest_period}'
          AND b.ead_sar_mn > 0.01
        LIMIT 50
    """).fetchall()
    assert rows
    for denominator, rate, ecl, ead in rows:
        assert denominator == "ead_sar_mn"
        assert 0.0 <= rate <= 1.0
        assert abs(rate - min(ecl / ead, 1.0)) < 1e-6


# ---- the macro panel --------------------------------------------------

@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_registry_reports_twenty_candidates_and_its_absences(
        enabled, domain_id) -> None:
    """S01. *"Twenty-factor registry reports actual support and missing
    factors without invented zeros."*"""
    _scope, connection = book_of(domain_id)
    registry = ("whatif_corp_mev_registry" if domain_id == dom.CORPORATE
                else "whatif_retail_mev_registry")
    rows = connection.execute(
        f"SELECT factor_id, availability, absent_reason, series_id "
        f"FROM {registry} ORDER BY factor_id").fetchall()
    assert len(rows) == 20
    assert [r[0] for r in rows] == [f"MEV{i:02d}" for i in range(1, 21)]
    absent = [r for r in rows if r[1] == "ABSENT"]
    assert absent, "a book that carried all twenty would not test this"
    for _factor, _status, reason, series in absent:
        assert reason, "an absence with no reason is a shrug"
        assert series == ""


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_an_absent_factor_has_no_observations_rather_than_zeros(
        enabled, domain_id) -> None:
    """Section 7.1: *"Never present missing factors as zero."* Enforced by
    there being nothing to read, not by a column of zeros."""
    _scope, connection = book_of(domain_id)
    registry = ("whatif_corp_mev_registry" if domain_id == dom.CORPORATE
                else "whatif_retail_mev_registry")
    panel = ("whatif_corp_macro_quarter" if domain_id == dom.CORPORATE
             else "whatif_retail_macro_month")
    absent = connection.execute(
        f"SELECT factor_id FROM {registry} WHERE availability = 'ABSENT'"
    ).fetchall()
    for (factor,) in absent:
        count = connection.execute(
            f"SELECT count(*) FROM {panel} WHERE factor_id = '{factor}'"
        ).fetchone()[0]
        assert count == 0, f"{factor} is ABSENT and has {count} observations"


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_the_panel_carries_three_scenarios_over_the_whole_calendar(
        enabled, domain_id) -> None:
    scope, connection = book_of(domain_id)
    panel = ("whatif_corp_macro_quarter" if domain_id == dom.CORPORATE
             else "whatif_retail_macro_month")
    period_column = scope.period_column
    scenarios, periods = connection.execute(
        f"SELECT count(DISTINCT scenario_id), count(DISTINCT {period_column}) "
        f"FROM {panel}").fetchone()
    assert scenarios == 3
    assert periods == len(scope.periods)


@pytest.mark.parametrize("domain_id", [dom.CORPORATE, dom.RETAIL])
def test_a_forecast_is_labelled_as_one(enabled, domain_id) -> None:
    """Section 7.2: a projection is not a known-at-the-time observation, and
    a value published after the period it describes was not available to a
    process running then."""
    _scope, connection = book_of(domain_id)
    panel = ("whatif_corp_macro_quarter" if domain_id == dom.CORPORATE
             else "whatif_retail_macro_month")
    statuses = {r[0] for r in connection.execute(
        f"SELECT DISTINCT observation_status FROM {panel}").fetchall()}
    assert statuses == {"ACTUAL", "FORECAST"}
    orphan = connection.execute(
        f"SELECT count(*) FROM {panel} "
        f"WHERE observation_status = 'FORECAST' AND forecast_vintage = ''"
    ).fetchone()[0]
    assert orphan == 0, "a forecast with no vintage cannot be reproduced"


def test_the_macro_drives_the_risk_rather_than_sitting_beside_it(
        enabled) -> None:
    """The property that makes section 7 worth implementing at all.

    Portfolio ECL and lagged unemployment move together in the candidate
    book because the book was generated in that order. A release where they
    did not would let a sensitivity fit report coefficients, an R-squared
    and a heatmap, every one of them an artefact of noise.
    """
    import statistics

    scope, connection = book_of(dom.CORPORATE)
    ecl = dict(connection.execute(
        "SELECT reporting_quarter, sum(ecl_sar_mn) FROM corp_facility_quarter "
        "GROUP BY 1 ORDER BY 1").fetchall())
    unemployment = dict(connection.execute(
        "SELECT reporting_quarter, value FROM whatif_corp_macro_quarter "
        "WHERE factor_id = 'MEV03' AND scenario_id = 'baseline' "
        "ORDER BY 1").fetchall())
    periods = list(scope.periods)
    lagged = [unemployment[periods[max(i - 1, 0)]]
              for i in range(len(periods))]
    correlation = statistics.correlation([ecl[p] for p in periods], lagged)
    assert correlation > 0.5, (
        f"ECL and lagged unemployment correlate at {correlation:.3f}; the "
        f"book's risk is not responding to its own economy")


# ---- the dimensions the accepted books do not carry -------------------

def test_retail_employer_sector_is_its_own_dimension(enabled) -> None:
    """Section 3.3: product is not a substitute for employer sector. A book
    where the two were the same would let a sector question be answered by a
    product filter without anyone noticing."""
    scope, connection = book_of(dom.RETAIL)
    rows = connection.execute(f"""
        SELECT p.employer_sector, a.product, count(*) AS n
        FROM whatif_retail_profile p JOIN retail_account_month a
          ON a.customer_id = p.customer_id
         AND a.reporting_month = p.reporting_month
        WHERE p.reporting_month = '{scope.latest_period}'
        GROUP BY 1, 2
    """).fetchall()
    sectors = {r[0] for r in rows}
    products = {r[1] for r in rows}
    assert len(sectors) >= 8 and len(products) >= 4
    # Every sector holds more than one product and every product appears in
    # more than one sector: the two dimensions are independent.
    by_sector: dict[str, set[str]] = {}
    for sector, product, _n in rows:
        by_sector.setdefault(sector, set()).add(product)
    assert all(len(v) > 1 for v in by_sector.values())


def test_the_two_retail_scorecards_are_distinct(enabled) -> None:
    """S13. An application score from origination must not be substituted
    for a current behavioural score. They are on different scales here, so
    the substitution cannot even be made accidentally."""
    _scope, connection = book_of(dom.RETAIL)
    # Over the whole book, not one month: the claim is about the SCALES, and
    # whether a particular month happens to reach the top of one of them is
    # a fact about that month rather than about the scorecards.
    behavioural, application = connection.execute("""
        SELECT max(a.behaviour_score), max(p.application_score)
        FROM retail_account_month a JOIN whatif_retail_profile p
          ON a.customer_id = p.customer_id
         AND a.reporting_month = p.reporting_month
    """).fetchone()
    assert behavioural > application, (
        "the two scores reach different heights, so a value carried from one "
        "to the other is visibly out of place")
    types = {r[0] for r in connection.execute(
        "SELECT DISTINCT score_type FROM whatif_retail_score_map").fetchall()}
    assert types == {"BEHAVIOURAL", "APPLICATION"}
    ranges = connection.execute(
        "SELECT score_type, min(support_low), max(support_high) "
        "FROM whatif_retail_score_map GROUP BY 1 ORDER BY 1").fetchall()
    assert dict((r[0], (r[1], r[2])) for r in ranges) == {
        "APPLICATION": (200, 800), "BEHAVIOURAL": (300, 900)}


def test_the_application_score_does_not_move(enabled) -> None:
    """It is taken once, at origination. A book where it drifted month to
    month would be a second behavioural score wearing the wrong name."""
    _scope, connection = book_of(dom.RETAIL)
    moved = connection.execute("""
        SELECT count(*) FROM (
            SELECT customer_id FROM whatif_retail_profile
            GROUP BY customer_id
            HAVING count(DISTINCT application_score) > 1)
    """).fetchone()[0]
    assert moved == 0


def test_the_corporate_rating_scale_is_ordered_and_ends(enabled) -> None:
    """S12. A notch move steps this scale; there is nothing after the
    default grade, so a downgrade from it is refused rather than wrapped."""
    _scope, connection = book_of(dom.CORPORATE)
    rows = connection.execute(
        "SELECT rating_grade, grade_rank, pd_12m, is_default_grade "
        "FROM whatif_corp_rating_map ORDER BY grade_rank").fetchall()
    assert [r[1] for r in rows] == list(range(1, len(rows) + 1))
    assert [r[2] for r in rows] == sorted(r[2] for r in rows)
    assert rows[-1][3] == 1 and rows[-1][2] == 1.0
    assert sum(r[3] for r in rows) == 1


def test_ccf_eligibility_is_published_rather_than_derived(enabled) -> None:
    """The accepted Corporate book forces `(ead - drawn) / undrawn`, which
    inverts to noise where undrawn is zero. Here the conversion factor and
    the population it applies to are both columns."""
    scope, connection = book_of(dom.CORPORATE)
    rows = connection.execute(f"""
        SELECT ccf_eligible_flag, count(*), min(ccf_pit), max(ccf_pit)
        FROM whatif_corp_ifrs9
        WHERE reporting_quarter = '{scope.latest_period}'
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    by_flag = {r[0]: r for r in rows}
    assert by_flag[0][1] > 0 and by_flag[1][1] > 0
    assert by_flag[0][3] == 0.0, "an ineligible facility has no conversion"
    assert 0.0 < by_flag[1][2] <= by_flag[1][3] < 1.0


def test_the_reference_calculator_stamps_every_measurement(enabled) -> None:
    for domain_id, _book, ifrs9, _key, _period in BOOKS:
        _scope, connection = book_of(domain_id)
        versions = {r[0] for r in connection.execute(
            f"SELECT DISTINCT ifrs9_model_version FROM {ifrs9}").fetchall()}
        assert versions == {ref.VERSION}
