"""The compiled SQL must mean what the Python means, and must not sample.

REAL DATABASE · NO MODEL. The published Corporate and Retail books through
DuckDB. No provider in this module, not even a scripted one.

Two risks live here and this module exists for both.

**Drift.** The unit algebra now exists twice -- `units.apply` and
`sql.moved_value` -- and two implementations of one rule diverge unless
something holds them together. `test_every_operation_means_the_same_thing_in_
both` walks every operation-and-storage pair over a grid of baselines and
compares the engine's answer to the Decimal one, exactly. It is the only
thing standing between a future edit to one of them and a wrong published
number.

**Sampling.** Section 9.1: *"never present a sampled total as a full-
population result."* A `LIMIT` in the generated SQL would do exactly that
and would look right, because a sampled total is a plausible number. So the
generated SQL is asserted to carry no limiting clause, and O12 runs a real
cohort above the display cap and checks the engine's total against one
computed independently, row by row, in Decimal.

**The zero-baseline branch is unreachable against the real books.** Neither
book has a single row with `pd_pit_12m = 0` -- measured, not assumed, and
asserted below -- so the case section 10.3 cares most about cannot be
exercised by any cohort of real facilities. A mutation that made a zero
baseline divide anyway therefore passed every real-data test here. It does
not any more: section 17.1's four hand-calculable rows are loaded into the
engine as a fixture relation and the SAME generated SQL is run over them, so
the branch is covered in the database rather than only in Python.

Covers O12 of section 17.1, and the reachable parts of E12, E13 and R01.
"""

from __future__ import annotations

import pathlib
import re
from decimal import Decimal
from typing import Any

import pytest

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import contracts, lake
from backend.cockpit_v4 import domain_resolver as resolver
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import preview as pv
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import sql as sq
from backend.cockpit_v4.scenario import units as un

D = Decimal


@pytest.fixture(scope="module", autouse=True)
def _lake_present():
    if not pathlib.Path("data/cockpit_v4_lake").exists():
        pytest.skip("the published lake is not present in this worktree")
    arun.reset()
    yield
    arun.reset()


@pytest.fixture(scope="module")
def corporate():
    return arun.for_domain(dom.CORPORATE)


@pytest.fixture(scope="module")
def frozen(corporate):
    scope = resolver.scope_for(dom.CORPORATE, tenant_id=lake.DEFAULT_TENANT)
    return ch.freeze(session=corporate.session, scope=scope,
                     predicate="stage = 1",
                     described_as="every performing facility")


def spec_for(frozen, *shocks: sp.Shock, **over) -> sp.ScenarioSpec:
    body = {
        "scenario_id": "sc-1", "version": 1, "name": "SQL compilation",
        "source": sp.SourceRef(
            domain_id=frozen.domain_id, release_id=frozen.release_id,
            release_fingerprint=frozen.release_fingerprint,
            reporting_period=frozen.period),
        "cohort": frozen.ref, "shocks": shocks,
    }
    body.update(over)
    return sp.ScenarioSpec(**body)


def shock(field_id: str, value: str, operation: str = un.RELATIVE) -> sp.Shock:
    return sp.Shock(field_id=field_id,
                    amount=un.parse(value, operation,
                                    raw=f"{field_id} {value}"),
                    origin=f"move {field_id} by {value}")


def confirmed(frozen, *shocks: sp.Shock) -> sp.ScenarioSpec:
    """A spec that has been through the preview and been approved.

    `confirm()` refuses from DRAFT on purpose -- section 6.2 -- so the only
    way to a confirmed scenario is the one a reader takes.
    """
    spec = spec_for(frozen, *shocks)
    return pv.confirm(pv.build(spec=spec, frozen=frozen,
                               readiness=pv.readiness(spec)), "yes")


def evaluate(session: Any, expression: str) -> Decimal:
    """One scalar out of the engine, as an exact Decimal."""
    value = session.connection.execute(f"SELECT {expression}").fetchone()[0]
    return D(str(value))


# ---- the two implementations of one rule -------------------------------

#: Every pair the `units.ALLOWED` matrix permits, with a baseline that is
#: meaningful for that storage.
GRID: list[tuple[str, str, list[str]]] = [
    (un.FRACTION, un.RELATIVE, ["0.02", "0.5", "0.999"]),
    (un.FRACTION, un.MULTIPLY, ["0.02", "0.5"]),
    (un.FRACTION, un.ABSOLUTE_PP, ["0.02", "0.5"]),
    (un.FRACTION, un.BASIS_POINTS, ["0.02", "0.5"]),
    (un.FRACTION, un.SET_TO, ["0.02"]),
    (un.PERCENT, un.RELATIVE, ["40", "62.5"]),
    (un.PERCENT, un.MULTIPLY, ["40"]),
    (un.PERCENT, un.ABSOLUTE_PP, ["40", "62.5"]),
    (un.PERCENT, un.BASIS_POINTS, ["40"]),
    (un.PERCENT, un.SET_TO, ["40"]),
    (un.MONEY, un.RELATIVE, ["1250.75", "0"]),
    (un.MONEY, un.MULTIPLY, ["1250.75"]),
    (un.MONEY, un.ABSOLUTE_AMOUNT, ["1250.75"]),
    (un.MONEY, un.SET_TO, ["1250.75"]),
    (un.INDEX, un.RELATIVE, ["720"]),
    (un.INDEX, un.MULTIPLY, ["720"]),
    (un.INDEX, un.POINTS, ["720"]),
    (un.INDEX, un.SET_TO, ["720"]),
]

AMOUNTS = ["20", "-20", "0", "2.5"]


@pytest.mark.parametrize("storage,operation,baselines", GRID,
                         ids=[f"{s}-{o}" for s, o, _ in GRID])
def test_every_operation_means_the_same_thing_in_both(
        corporate, storage, operation, baselines) -> None:
    """The engine and the Decimal algebra, compared value for value.

    Exactly, not approximately: both sides are given terminating decimals,
    so a difference here is a difference in meaning rather than in
    precision.
    """
    for raw in baselines:
        for amount_text in AMOUNTS:
            if operation in un.DISCRETE_OPERATIONS and "." in amount_text:
                continue
            amount = un.parse(amount_text, operation)
            expected = un.apply(D(raw), amount, storage=storage)
            expression = sq.moved_value("baseline", amount, storage=storage)
            got = evaluate(corporate.session,
                           expression.replace("baseline", f"({raw})"))
            assert got == expected, (
                f"{storage}/{operation} on {raw} by {amount_text}: "
                f"SQL {got}, Decimal {expected}")


def test_an_operation_with_no_sql_form_raises_rather_than_guessing() -> None:
    """A future operation added to `units` and not here would otherwise
    silently fall through to whatever the last branch did."""
    amount = un.Amount(value=D("1"), operation=un.NOTCHES)
    with pytest.raises(un.UnitError, match="no SQL form"):
        sq.moved_value("rating_current", amount, storage=un.ORDINAL)


def test_a_decimal_reaches_the_engine_in_plain_notation() -> None:
    """`1E-8` is read back as a float by some engines and `0.00000001` is
    read as exact numeric by all of them."""
    assert sq.literal(D("0.00000001")) == "0.00000001"
    assert "E" not in sq.literal(D("1e-8")).upper()
    assert sq.literal(D("20.00")) == "20"


def test_a_derived_field_reads_as_its_derivation() -> None:
    assert sq.column("ccf") == "((ead_sar_mn - drawn_sar_mn) / undrawn_sar_mn)"
    assert sq.column("pd_pit_12m") == "pd_pit_12m"


# ---- no sampling -------------------------------------------------------

LIMITING = re.compile(r"\b(LIMIT|TABLESAMPLE|USING\s+SAMPLE|FETCH\s+FIRST)\b",
                      re.IGNORECASE)


def test_the_generated_sql_carries_no_limiting_clause(frozen) -> None:
    spec = spec_for(frozen, shock("pd_pit_12m", "20"))
    plan = dl.plan(spec)
    for statement in (sq.row_ledger_sql(spec, plan, frozen=frozen),
                      sq.book_totals_sql(spec, frozen=frozen)):
        assert not LIMITING.search(statement), statement


def test_the_ledger_returns_one_row_per_cohort_member(corporate,
                                                      frozen) -> None:
    spec = spec_for(frozen, shock("pd_pit_12m", "20"))
    statement = sq.row_ledger_sql(spec, dl.plan(spec), frozen=frozen)
    rows = corporate.session.connection.execute(statement).fetchall()
    assert len(rows) == frozen.ref.entity_count
    assert len({r[0] for r in rows}) == len(rows), "one row per facility"


# ---- O12 ---------------------------------------------------------------

def test_o12_a_cohort_above_the_display_cap_totals_exactly(corporate,
                                                           frozen) -> None:
    """Section 17.1's O12, and section 9.1's full-population rule.

    The cohort is every performing Corporate facility at the latest quarter,
    which is far above any display or query-detail cap. The expected total is
    built independently: the raw EAD, PD and LGD columns are read out and the
    scenario ECL is computed in Decimal per row, owing nothing to the CASE
    expression under test.
    """
    assert frozen.ref.entity_count > 1000, "not a population worth the name"

    spec = spec_for(frozen, shock("pd_pit_12m", "20"))
    plan = dl.plan(spec)
    statement = sq.row_ledger_sql(spec, plan, frozen=frozen)
    rows = corporate.session.connection.execute(statement).fetchall()
    engine_total = sum((D(str(r[2])) for r in rows), D(0))

    raw = corporate.session.connection.execute(
        f"SELECT facility_id, ecl_sar_mn, pd_pit_12m "
        f"FROM corp_facility_quarter "
        f"WHERE reporting_quarter = '{frozen.period}' AND stage = 1"
    ).fetchall()
    independent = sum(
        (D(str(ecl)) * (D(str(pd)) * D("1.2") / D(str(pd))) if D(str(pd))
         else D(str(ecl)) for _, ecl, pd in raw), D(0))

    assert len(raw) == len(rows)
    assert abs(engine_total - independent) < D("0.0001"), (
        f"engine {engine_total}, independent {independent}")


def test_o12_the_book_total_splits_into_the_cohort_and_the_rest(corporate,
                                                                frozen):
    """Section 13.1's identity, measured on the same relation and period as
    the cohort -- checking it against a different population would prove
    nothing at all."""
    statement = sq.book_totals_sql(spec_for(frozen), frozen=frozen)
    book, inside, outside, count = corporate.session.connection.execute(
        statement).fetchone()
    assert abs(D(str(inside)) + D(str(outside)) - D(str(book))) < D("0.0001")
    assert abs(D(str(inside)) - D(frozen.ref.baseline_ecl)) < D("0.0001")
    assert count > frozen.ref.entity_count, "the book is bigger than the cohort"


# ---- the SQL and the row walker agree ----------------------------------

def test_the_engine_and_the_row_walker_agree_row_for_row(corporate,
                                                         frozen) -> None:
    """`delta.scale_row` is the preview's worked example and the oracles'
    arithmetic; the SQL is what actually runs. A reader shown one and paid on
    the other is the failure this prevents."""
    spec = spec_for(frozen, shock("pd_pit_12m", "20"),
                    shock("lgd_pct", "5", un.ABSOLUTE_PP))
    plan = dl.plan(spec)
    statement = sq.row_ledger_sql(spec, plan, frozen=frozen)
    engine = {r[0]: (D(str(r[2])), r[3]) for r in
              corporate.session.connection.execute(statement).fetchall()}

    raw = corporate.session.connection.execute(
        f"SELECT facility_id, ecl_sar_mn, pd_pit_12m, lgd_pct, stage, "
        f"       undrawn_sar_mn, write_off_sar_mn "
        f"FROM corp_facility_quarter "
        f"WHERE reporting_quarter = '{frozen.period}' AND stage = 1 "
        f"ORDER BY facility_id"
    ).fetchall()

    for key, ecl, pd, lgd, stage, undrawn, written_off in raw[:400]:
        walked = dl.scale_row(plan, {
            "ecl_sar_mn": D(str(ecl)), "pd_pit_12m": D(str(pd)),
            "lgd_pct": D(str(lgd)), "stage": D(str(stage)),
            "undrawn_sar_mn": D(str(undrawn)),
            "write_off_sar_mn": D(str(written_off))})
        engine_value, disposition = engine[key]
        assert disposition == walked.disposition, key
        assert abs(engine_value - walked.scenario_ecl) < D("0.0000001"), key


def test_a_stage_two_cohort_is_untouched_by_a_twelve_month_pd_shock(
        corporate) -> None:
    """Not approximately untouched: the disposition says UNAFFECTED and the
    figure is the baseline, because ECL at Stage 2 uses the lifetime PD.

    This is the case a reader most needs told. A silent zero change here
    reads as "the stress did nothing", when what happened is that the
    scenario moved a parameter this population's ECL does not use.
    """
    scope = resolver.scope_for(dom.CORPORATE, tenant_id=lake.DEFAULT_TENANT)
    stage_two = ch.freeze(session=corporate.session, scope=scope,
                          predicate="stage = 2", described_as="Stage 2")
    spec = spec_for(stage_two, shock("pd_pit_12m", "20"))
    statement = sq.row_ledger_sql(spec, dl.plan(spec), frozen=stage_two)
    rows = corporate.session.connection.execute(statement).fetchall()
    assert rows and {r[3] for r in rows} == {dl.UNAFFECTED}
    assert all(D(str(r[1])) == D(str(r[2])) for r in rows)


def test_stage_three_is_reason_coded_ineligible_for_a_pd_shock(
        corporate) -> None:
    """Its PD is exactly 1.0 and its ECL is EAD x LGD, so a relative PD
    shock on it is meaningless rather than small."""
    scope = resolver.scope_for(dom.CORPORATE, tenant_id=lake.DEFAULT_TENANT)
    stage_three = ch.freeze(session=corporate.session, scope=scope,
                            predicate="stage = 3", described_as="Stage 3")
    spec = spec_for(stage_three, shock("pd_lifetime", "20"))
    statement = sq.row_ledger_sql(spec, dl.plan(spec), frozen=stage_three)
    rows = corporate.session.connection.execute(statement).fetchall()
    assert rows and {r[3] for r in rows} == {dl.INELIGIBLE}
    assert all(D(str(r[1])) == D(str(r[2])) for r in rows), (
        "an ineligible row keeps its baseline; it does not become zero")


def test_the_retail_write_off_floor_is_excluded_with_its_reason(
        frozen) -> None:
    retail = arun.for_domain(dom.RETAIL)
    scope = resolver.scope_for(dom.RETAIL, tenant_id=lake.DEFAULT_TENANT)
    cohort = ch.freeze(session=retail.session, scope=scope,
                       predicate="stage = 3", described_as="Retail Stage 3")
    spec = spec_for(cohort, shock("lgd_pct", "10"))
    plan = dl.plan(spec)
    assert "write_off_sar_mn > 0" in sq.ineligible_sql(plan)

    statement = sq.row_ledger_sql(spec, plan, frozen=cohort)
    rows = retail.session.connection.execute(statement).fetchall()
    assert dl.INELIGIBLE in {r[3] for r in rows}
    for _, base, scen, disposition in rows:
        if disposition == dl.INELIGIBLE:
            assert D(str(base)) == D(str(scen))


# ---- the submission the analyst sends ----------------------------------

def test_the_submission_is_accepted_by_the_existing_contract(frozen) -> None:
    """Nothing here is a second execution path. The payload this module
    builds goes through `contracts.parse_execution` exactly as any analyst's
    would, and producing one that it rejects is a bug in this module."""
    spec = confirmed(frozen, shock("pd_pit_12m", "20"))
    payload = sq.submission(spec, dl.plan(spec), frozen=frozen)
    payload["intent"] = {
        "query_mode": contracts.DATA_ANALYSIS,
        "owner": "WHAT_IF",
        "understood_request": "What happens to ECL if PD rises 20%?",
    }
    for step in payload["steps"]:
        step.setdefault("purpose", "scenario")

    parsed = contracts.parse_execution(payload, max_steps=8)
    assert len(parsed.steps) == 2
    assert {s.language for s in parsed.steps} == {"sql"}
    assert parsed.expected_output_grain == "row"
    assert parsed.intent.owner == "WHAT_IF"


def test_the_accepted_contract_already_names_this_owner() -> None:
    """WHAT_IF is in `contracts.OWNERS` at the accepted baseline, so a
    scenario turn declares an owner the runtime already knows. That is one
    fewer protected-file change than this capability might have needed, and
    it is worth a test so a future edit cannot quietly take it away."""
    assert "WHAT_IF" in contracts.OWNERS


def test_an_unconfirmed_scenario_produces_no_submission(frozen) -> None:
    """Section 6.2: the preview is confirmed before anything is calculated,
    and the compiler is the last place that can still say no."""
    from backend.cockpit_v4.scenario.errors import ScenarioError

    spec = spec_for(frozen, shock("pd_pit_12m", "20"))
    with pytest.raises(ScenarioError, match="has not been confirmed"):
        sq.submission(spec, dl.plan(spec), frozen=frozen)


def test_the_submission_carries_the_scenario_and_cohort_identity(
        frozen) -> None:
    """So a published artifact can be traced back to exactly which scenario
    over exactly which rows produced it."""
    spec = confirmed(frozen, shock("pd_pit_12m", "20"))
    scope = sq.submission(spec, dl.plan(spec), frozen=frozen)["scope"]
    assert scope["membership_hash"] == frozen.ref.membership_hash
    assert scope["scenario_digest"] == spec.digest()
    assert scope["release_id"] == frozen.release_id


def test_a_derived_input_is_visible_as_derived(frozen) -> None:
    """Section 3.3 forbids passing a derivation off as a source fact, so the
    preview needs to be able to say which inputs were reconstructed."""
    published = spec_for(frozen, shock("pd_pit_12m", "20"))
    derived = spec_for(frozen, shock("ccf", "20"))
    assert sq.reads_only_published(dl.plan(published),
                                  domain_id=dom.CORPORATE)
    assert not sq.reads_only_published(dl.plan(derived),
                                       domain_id=dom.CORPORATE)


# ---- the hand fixture, run through the engine --------------------------
#
# Section 17.1's four rows, loaded into DuckDB under the relation name the
# compiler emits, so the generated SQL can be run over numbers whose answers
# are known by hand. This is what covers Z: neither published book has a
# zero-PD row, so the branch section 10.3 is most concerned with has no real
# facility to exercise it.

FIXTURE_ROWS = [
    # facility_id, ecl, pd_pit_12m, lgd_pct, stage, drawn, undrawn, ead,
    # write_off
    ("A", "8000", "0.02", "40", 1, "1000000", "0", "1000000", "0"),
    ("B", "10000", "0.04", "50", 1, "500000", "0", "500000", "0"),
    ("C", "1800", "0.05", "40", 1, "80000", "20000", "90000", "0"),
    ("Z", "0", "0", "40", 1, "100000", "0", "100000", "0"),
]


@pytest.fixture()
def fixture_book():
    """A throwaway in-engine relation shaped like a Corporate book."""
    import duckdb

    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE corp_facility_quarter ("
        " facility_id VARCHAR, borrower_id VARCHAR, reporting_quarter VARCHAR,"
        " ecl_sar_mn DOUBLE, pd_pit_12m DOUBLE, pd_lifetime DOUBLE,"
        " lgd_pct DOUBLE, stage BIGINT, drawn_sar_mn DOUBLE,"
        " undrawn_sar_mn DOUBLE, ead_sar_mn DOUBLE, write_off_sar_mn DOUBLE)")
    for key, ecl, pd, lgd, stage, drawn, undrawn, ead, written in FIXTURE_ROWS:
        connection.execute(
            "INSERT INTO corp_facility_quarter VALUES "
            "(?, ?, '2026Q2', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [key, f"BR-{key}", float(ecl), float(pd), float(pd), float(lgd),
             stage, float(drawn), float(undrawn), float(ead), float(written)])
    yield connection
    connection.close()


def fixture_frozen(period: str = "2026Q2") -> ch.Frozen:
    return ch.Frozen(
        ref=sp.CohortRef(cohort_id="fx", membership_hash="0" * 64,
                         grain="facility", entity_count=4,
                         baseline_ead="1690000", baseline_ecl="19800"),
        domain_id=dom.CORPORATE, release_id="fixture",
        release_fingerprint="0" * 16, period=period, predicate="",
        selection=ch.BY_ROW, owner_count=4,
        described_as="section 17.1's hand fixture")


def fixture_results(connection, *shocks: sp.Shock) -> dict[str, tuple]:
    frozen = fixture_frozen()
    spec = spec_for(frozen, *shocks)
    statement = sq.row_ledger_sql(spec, dl.plan(spec), frozen=frozen)
    return {r[0]: (D(str(r[1])), D(str(r[2])), r[3])
            for r in connection.execute(statement).fetchall()}


def test_neither_published_book_has_a_zero_pd_row(corporate) -> None:
    """Which is why the fixture relation below exists. Measured here so that
    a future book with one turns this into a prompt to cover it for real."""
    retail = arun.for_domain(dom.RETAIL)
    for session, relation in ((corporate.session, "corp_facility_quarter"),
                              (retail.session, "retail_account_month")):
        found = session.connection.execute(
            f"SELECT count(*) FROM {relation} WHERE pd_pit_12m = 0"
        ).fetchone()[0]
        assert found == 0


def test_the_fixture_totals_19800_in_the_engine(fixture_book) -> None:
    total = fixture_book.execute(
        "SELECT sum(ecl_sar_mn) FROM corp_facility_quarter").fetchone()[0]
    assert D(str(total)) == D("19800")


def test_o01_through_the_engine(fixture_book) -> None:
    """The generated SQL over the hand fixture: 23,760, up 3,960."""
    got = fixture_results(fixture_book, shock("pd_pit_12m", "20"))
    assert sum((v[1] for v in got.values()), D(0)) == D("23760")
    assert got["A"][1] == D("9600")
    assert got["C"][1] == D("2160")


def test_o11_through_the_engine_a_zero_pd_cannot_be_set_positive(
        fixture_book) -> None:
    """Z's PD from 0% to 1% in SQL: unsupported, keeping its baseline.

    This is the case no real facility in either book can reach, and the one
    an epsilon denominator would turn into an invented number.
    """
    got = fixture_results(fixture_book,
                          shock("pd_pit_12m", "1", un.SET_TO))
    assert got["Z"][2] == dl.UNSUPPORTED
    assert got["Z"][1] == D("0"), "its baseline, not an invention"
    assert got["A"][2] == dl.SCALED


def test_o01_through_the_engine_a_zero_to_zero_move_is_neutral(
        fixture_book) -> None:
    """Z under a RELATIVE shock stays zero and is scaled, not unsupported:
    zero-to-zero has a ratio of one. The two zero cases are different and
    the engine tells them apart."""
    got = fixture_results(fixture_book, shock("pd_pit_12m", "20"))
    assert got["Z"][2] == dl.SCALED
    assert got["Z"][1] == D("0")


def test_the_engine_and_the_oracle_agree_on_every_fixture_row(
        fixture_book) -> None:
    """The same four rows, the same shock, through the SQL and through the
    row walker. Hand-calculable numbers on both sides."""
    shocks = (shock("pd_pit_12m", "20"), shock("lgd_pct", "10"))
    got = fixture_results(fixture_book, *shocks)
    plan = dl.plan(spec_for(fixture_frozen(), *shocks))
    for key, ecl, pd, lgd, stage, _drawn, undrawn, _ead, written in (
            FIXTURE_ROWS):
        walked = dl.scale_row(plan, {
            "ecl_sar_mn": D(ecl), "pd_pit_12m": D(pd), "lgd_pct": D(lgd),
            "stage": D(stage), "undrawn_sar_mn": D(undrawn),
            "write_off_sar_mn": D(written)})
        assert got[key][2] == walked.disposition, key
        assert got[key][1] == walked.scenario_ecl, key
    assert got["A"][1] == D("10560"), "O03, end to end"


# ---- one unsupported factor must not leave the others scaling ----------
#
# A separate relation, deliberately: section 17.1's four rows stay exactly
# the four the specification gives, and this case needs a fifth that it does
# not have.
#
# Y has drawn 100,000, undrawn 50,000 and EAD 100,000, so its DERIVED CCF is
# (100,000 - 100,000) / 50,000 = 0 while its ECL is a real 2,000. That makes
# it the one shape where the zero-baseline branch changes a published number
# rather than merely a label: on a parameter whose zero does NOT force ECL to
# zero. For PD, LGD and EAD it does -- ECL is their product -- which is why a
# mutation of the NULL to a 1 is invisible on those three and visible here.


@pytest.fixture()
def partial_book():
    import duckdb

    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE corp_facility_quarter ("
        " facility_id VARCHAR, reporting_quarter VARCHAR,"
        " ecl_sar_mn DOUBLE, pd_pit_12m DOUBLE, pd_lifetime DOUBLE,"
        " lgd_pct DOUBLE, stage BIGINT, drawn_sar_mn DOUBLE,"
        " undrawn_sar_mn DOUBLE, ead_sar_mn DOUBLE, write_off_sar_mn DOUBLE)")
    connection.execute(
        "INSERT INTO corp_facility_quarter VALUES "
        "('Y', '2026Q2', 2000, 0.05, 0.05, 40, 1, 100000, 50000, 100000, 0)")
    yield connection
    connection.close()


def test_the_fixture_y_has_a_zero_ccf_and_a_real_ecl(partial_book) -> None:
    ccf, ecl = partial_book.execute(
        f"SELECT {sq.column('ccf')}, ecl_sar_mn FROM corp_facility_quarter"
    ).fetchone()
    assert D(str(ccf)) == D("0")
    assert D(str(ecl)) == D("2000")


def test_an_unsupported_factor_stops_the_whole_row_not_just_itself(
        partial_book) -> None:
    """A CCF that cannot be moved and an LGD that can, on one row.

    The row is UNSUPPORTED and keeps its 2,000. Scaling it by the LGD alone
    would give 2,200 and would be published as though the whole scenario had
    applied, when one of its two instructions could not be carried out --
    section 9.1's hidden partial, wearing a complete answer's clothes.
    """
    got = fixture_results(partial_book,
                          shock("ccf", "60", un.SET_TO),
                          shock("lgd_pct", "10"))
    assert got["Y"][2] == dl.UNSUPPORTED
    assert got["Y"][1] == D("2000")
    assert got["Y"][1] != D("2200"), "the LGD must not scale it on its own"


def test_the_row_walker_stops_on_the_same_row(partial_book) -> None:
    shocks = (shock("ccf", "60", un.SET_TO), shock("lgd_pct", "10"))
    plan = dl.plan(spec_for(fixture_frozen(), *shocks))
    walked = dl.scale_row(plan, {
        "ecl_sar_mn": D("2000"), "ccf": D("0"), "lgd_pct": D("40"),
        "pd_pit_12m": D("0.05"), "stage": D(1),
        "undrawn_sar_mn": D("50000"), "write_off_sar_mn": D("0")})
    assert walked.disposition == dl.UNSUPPORTED
    assert walked.scenario_ecl == D("2000")


def test_a_declared_elasticity_is_refused_rather_than_ignored() -> None:
    """`Factor` can carry one and `Factor.contribution` raises the ratio to
    it; this compiler has no form for it.

    Emitting the bare ratio instead would make the population run and the
    preview's worked example disagree about the same scenario -- the exact
    drift this module exists to prevent, arriving through a field rather
    than through an edit.
    """
    from backend.cockpit_v4.scenario.errors import ScenarioError

    base = dl.plan(spec_for(fixture_frozen(),
                            shock("pd_pit_12m", "20"))).factors[0]
    declared = dl.Factor(field_id=base.field_id, shock=base.shock,
                         elasticity=D(2), applies_when=base.applies_when,
                         storage=base.storage)
    with pytest.raises(ScenarioError, match="no form in this compiler"):
        sq.factor_sql(declared)


@pytest.fixture()
def stage_two_zero_book():
    """One Stage 2 facility whose 12-month PD is zero.

    Contrived, and it has to be: neither published book has a zero-PD row at
    any stage. It separates two things that both look like "nothing
    happened" -- a parameter that cannot be moved, and a parameter that does
    not enter this row's ECL at all.
    """
    import duckdb

    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE corp_facility_quarter ("
        " facility_id VARCHAR, reporting_quarter VARCHAR,"
        " ecl_sar_mn DOUBLE, pd_pit_12m DOUBLE, pd_lifetime DOUBLE,"
        " lgd_pct DOUBLE, stage BIGINT, drawn_sar_mn DOUBLE,"
        " undrawn_sar_mn DOUBLE, ead_sar_mn DOUBLE, write_off_sar_mn DOUBLE)")
    connection.execute(
        "INSERT INTO corp_facility_quarter VALUES "
        "('S2', '2026Q2', 600, 0, 0.12, 40, 2, 5000, 0, 5000, 0)")
    yield connection
    connection.close()


def test_a_parameter_outside_this_row_s_ecl_is_unaffected_not_unsupported(
        stage_two_zero_book) -> None:
    """Both read as "nothing happened" and they are different facts.

    UNSUPPORTED says the engine could not answer the question asked.
    UNAFFECTED says the question does not bear on this row -- its ECL uses
    the lifetime PD, so the 12-month one being zero is not a failure to move
    it. Labelling the second as the first would put a coverage gap in a
    report that has none.
    """
    got = fixture_results(stage_two_zero_book,
                          shock("pd_pit_12m", "1", un.SET_TO))
    assert got["S2"][2] == dl.UNAFFECTED
    assert got["S2"][1] == D("600")


def test_the_row_walker_agrees_that_it_is_unaffected() -> None:
    plan = dl.plan(spec_for(fixture_frozen(),
                            shock("pd_pit_12m", "1", un.SET_TO)))
    walked = dl.scale_row(plan, {
        "ecl_sar_mn": D("600"), "pd_pit_12m": D("0"), "pd_lifetime": D("0.12"),
        "lgd_pct": D("40"), "stage": D(2), "undrawn_sar_mn": D("0"),
        "write_off_sar_mn": D("0")})
    assert walked.disposition == dl.UNAFFECTED
    assert walked.scenario_ecl == D("600")


def test_the_same_row_at_stage_one_would_be_unsupported(fixture_book) -> None:
    """The control: Z is Stage 1 with a zero 12-month PD, and the same shock
    on it is genuinely unanswerable."""
    got = fixture_results(fixture_book, shock("pd_pit_12m", "1", un.SET_TO))
    assert got["Z"][2] == dl.UNSUPPORTED
