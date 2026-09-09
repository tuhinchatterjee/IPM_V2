"""The domain boundary, tested against the real engine.
Specification sections 6.4, 10.1 and 14.4.

Section 14.4 requires these to be validated "with the real database and
sandbox, not only mocked validation functions", so every test here runs against
a genuine DuckDB session built exactly as the runtime builds it.
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.cockpit_agentic import catalog as C
from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic import generate as G
from backend.cockpit_agentic import scope as S
from backend.cockpit_agentic import sql, store
from backend.cockpit_agentic.contracts import (
    OUT_OF_SCOPE_ACCESS,
    PERMISSION_DENIED,
    RESOURCE_LIMIT,
    SYNTAX_ERROR,
    TYPE_MISMATCH,
    UNRESOLVED_FIELD,
    UNSAFE_OPERATION,
)

RELEASE = "test-sec-20q"


class Principal:
    user_id = 1
    tenant_id = G.TENANT


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    """A real published release, in an isolated namespace."""
    from backend import config

    base = tmp_path_factory.mktemp("lake")
    original = config.settings
    config.settings = dataclasses.replace(
        original, cockpit_agentic_v3=True, analytics_dir=base / "analytics")
    release = G.build_release(dataset_release_id=RELEASE, borrowers=25,
                              facilities=50)
    G.conform(release)
    store.write(release, overwrite=True)
    yield release
    sql.clear_sessions()
    config.settings = original


@pytest.fixture()
def session(published):
    scope = S.for_principal(Principal(), dataset_release_id=RELEASE)
    catalog = C.build(dataset_release_id=RELEASE,
                      calendar=published.calendar)
    return sql.open_session(scope=scope, catalog=catalog, reuse=False)


def run(statement: str, session) -> sql.SqlResult:
    sql.check_structure(statement)
    sql.bind(statement, session)
    return sql.execute(statement, session, deadline_seconds=15)


def rejected(statement: str, session) -> sql.SqlRejected:
    with pytest.raises(sql.SqlRejected) as e:
        run(statement, session)
    return e.value


# ---- the happy path -------------------------------------------------------

def test_a_legitimate_analytical_query_runs(session):
    result = run("SELECT reporting_quarter, count(*) AS n, "
                 "sum(ecl_reported) AS ecl FROM cockpit_facility_quarter "
                 "GROUP BY 1 ORDER BY 1", session)
    assert result.row_count == 20
    assert {c["name"] for c in result.columns} == {"reporting_quarter", "n",
                                                   "ecl"}
    assert all(row["n"] > 0 for row in result.rows)


def test_window_functions_ctes_and_statistics_are_permitted(session):
    """Section 10.1: allow legitimate analytic constructs."""
    result = run("""
        WITH q AS (
            SELECT reporting_quarter, borrower_id, avg(pd_pit_12m) AS pd
            FROM cockpit_facility_quarter GROUP BY 1, 2)
        SELECT reporting_quarter, median(pd) AS median_pd,
               stddev_samp(pd) AS sd,
               rank() OVER (ORDER BY avg(pd) DESC) AS r
        FROM q GROUP BY 1 ORDER BY 1 LIMIT 5
    """, session)
    assert result.row_count == 5


def test_a_join_across_grains_runs_and_the_catalog_warned_about_it(session):
    result = run("SELECT f.reporting_quarter, count(*) AS rows_after_join "
                 "FROM cockpit_facility_quarter f "
                 "JOIN cockpit_borrower_financial_quarter b "
                 "ON f.borrower_id = b.borrower_id "
                 "AND f.reporting_quarter = b.reporting_quarter "
                 "GROUP BY 1 ORDER BY 1 LIMIT 3", session)
    assert result.row_count == 3
    warning = next(j for j in F.JOINS
                   if j["right"] == F.BORROWER_FINANCIAL)["warning"]
    assert "once per facility" in warning


# ---- the boundary ---------------------------------------------------------

def test_another_module_is_not_reachable(session):
    for relation in ("ews_alerts", "early_warning_signals", "scorecard_runs",
                     "stress_scenarios", "lenses_documents", "credit_scores"):
        error = rejected(f"SELECT * FROM {relation}", session)
        assert error.category == OUT_OF_SCOPE_ACCESS
        assert "twenty-quarter corporate domain only" in str(error)


def test_a_refusal_does_not_disclose_what_lies_beyond(session):
    known = rejected("SELECT * FROM ews_alerts", session)
    unknown = rejected("SELECT * FROM zzz_does_not_exist_anywhere", session)
    assert known.category == unknown.category == OUT_OF_SCOPE_ACCESS
    for message in (str(known), str(unknown)):
        for leak in ("scorecard", "lens", "stress", "early_warning",
                     "parquet", "/home/", "/tmp/"):
            assert leak not in message.lower()


def test_file_access_is_impossible_from_generated_sql(session):
    for statement in (
            "SELECT * FROM read_parquet('/etc/hostname')",
            "SELECT * FROM read_csv_auto('/etc/passwd')",
            "SELECT * FROM read_json_auto('/etc/hosts')",
            "SELECT * FROM glob('/**')",
            "SELECT * FROM read_text('/etc/passwd')"):
        assert rejected(statement, session).category == UNSAFE_OPERATION


def test_the_engine_blocks_file_access_even_past_the_validator(session):
    """The regex is a courtesy. The engine is the boundary.

    This calls the connection DIRECTLY, bypassing check_structure entirely, to
    prove that the security property does not depend on the validator -- which
    is exactly what section 10.1 means by "a keyword check alone is not a
    sandbox".
    """
    import duckdb

    for statement in ("SELECT * FROM read_csv_auto('/etc/passwd')",
                      "COPY (SELECT 1) TO '/tmp/escape.csv'",
                      "ATTACH '/tmp/escape.db'",
                      "INSTALL httpfs",
                      "SET enable_external_access = true"):
        with pytest.raises((duckdb.PermissionException, duckdb.IOException,
                            duckdb.InvalidInputException,
                            duckdb.HTTPException, duckdb.CatalogException)):
            session.connection.execute(statement)


def test_writes_schema_changes_and_data_movement_are_refused(session):
    for statement in (
            "DROP TABLE cockpit_facility_quarter",
            "DELETE FROM cockpit_facility_quarter",
            "UPDATE cockpit_facility_quarter SET ecl_reported = 0",
            "INSERT INTO cockpit_facility_quarter VALUES (1)",
            "CREATE TABLE evil AS SELECT 1",
            "ALTER TABLE cockpit_facility_quarter RENAME TO x",
            "TRUNCATE cockpit_facility_quarter",
            "COPY (SELECT 1) TO '/tmp/out.csv'",
            "ATTACH '/tmp/other.db'",
            "INSTALL httpfs",
            "PRAGMA database_list",
            "SET memory_limit='16GB'"):
        assert rejected(statement, session).category == UNSAFE_OPERATION


def test_multi_statement_injection_is_refused(session):
    error = rejected("SELECT 1; DROP TABLE cockpit_facility_quarter", session)
    assert error.category == UNSAFE_OPERATION
    assert "Exactly one SELECT" in str(error)
    # ...and the table is still there.
    assert run("SELECT count(*) AS n FROM cockpit_facility_quarter",
               session).rows[0]["n"] > 0


def test_a_cross_tenant_session_is_refused_rather_than_returning_nothing(
        published):
    """A zero-row result is not proof the portfolio is empty (section 7.7)."""
    class Other:
        tenant_id = "some-other-bank"

    scope = S.for_principal(Other(), dataset_release_id=RELEASE)
    catalog = C.build(dataset_release_id=RELEASE, calendar=published.calendar)
    with pytest.raises(sql.SqlRejected) as e:
        sql.open_session(scope=scope, catalog=catalog, reuse=False)
    assert e.value.category == PERMISSION_DENIED
    assert "not an empty portfolio" in str(e.value)


def test_the_tenant_filter_is_in_the_table_not_in_the_model_s_query(session):
    """Section 10.1: do not rely on Opus including the correct WHERE
    tenant_id. A query that omits it still sees only this tenant."""
    result = run("SELECT DISTINCT tenant_id FROM cockpit_facility_quarter",
                 session)
    assert [row["tenant_id"] for row in result.rows] == [G.TENANT]


def test_a_principal_narrowed_to_fewer_relations_sees_fewer(published):
    class Narrow:
        tenant_id = G.TENANT
        cockpit_relations = ("cockpit_facility_quarter",)

    scope = S.for_principal(Narrow(), dataset_release_id=RELEASE)
    catalog = C.build(dataset_release_id=RELEASE, calendar=published.calendar)
    narrow = sql.open_session(scope=scope, catalog=catalog, reuse=False)
    assert narrow.relations == ("cockpit_facility_quarter",)
    error = rejected("SELECT * FROM cockpit_covenant_quarter", narrow)
    assert error.category == OUT_OF_SCOPE_ACCESS


def test_the_session_cache_key_carries_tenant_and_release(published):
    catalog = C.build(dataset_release_id=RELEASE, calendar=published.calendar)
    first = sql.open_session(
        scope=S.for_principal(Principal(), dataset_release_id=RELEASE),
        catalog=catalog)
    again = sql.open_session(
        scope=S.for_principal(Principal(), dataset_release_id=RELEASE),
        catalog=catalog)
    assert again is first, "a session is reused for the same tenant and release"
    assert first.key == (G.TENANT, RELEASE)
    sql.clear_sessions()


# ---- the twenty-quarter window --------------------------------------------

def test_no_query_can_reach_a_twenty_first_quarter(session):
    result = run("SELECT DISTINCT reporting_quarter FROM "
                 "cockpit_facility_quarter ORDER BY 1", session)
    quarters = [row["reporting_quarter"] for row in result.rows]
    assert len(quarters) == 20
    assert quarters[0] == "2021Q3" and quarters[-1] == "2026Q2"
    outside = run("SELECT count(*) AS n FROM cockpit_facility_quarter "
                  "WHERE reporting_quarter < '2021Q3'", session)
    assert outside.rows[0]["n"] == 0


def test_an_empty_result_is_not_a_failure(session):
    result = run("SELECT * FROM cockpit_facility_quarter "
                 "WHERE sector_name = 'Aerospace'", session)
    assert result.row_count == 0
    assert result.truncated is False


def test_an_unavailable_filter_value_can_be_answered_with_the_real_ones(session):
    """Section 7.6: an unsupported value returns the available permitted
    choices rather than secretly substituting another."""
    values = sql.filter_values("cockpit_facility_quarter", "sector_name",
                               session)
    assert len(values) >= 5
    assert "Aerospace" not in values
    assert "Construction" in values


# ---- diagnostics for the failure packet -----------------------------------

def test_an_unresolved_column_is_diagnosed_with_the_name_it_used(session):
    error = rejected("SELECT pd_12_month FROM cockpit_facility_quarter",
                     session)
    assert error.category == UNRESOLVED_FIELD
    assert error.unresolved == "pd_12_month"


def test_a_syntax_error_is_told_apart_from_a_missing_column(session):
    assert rejected("SELCT 1 FROM cockpit_facility_quarter",
                    session).category in (SYNTAX_ERROR, UNSAFE_OPERATION)
    assert rejected("SELECT nope FROM cockpit_facility_quarter",
                    session).category == UNRESOLVED_FIELD


def test_a_type_mismatch_is_categorized(session):
    error = rejected("SELECT * FROM cockpit_facility_quarter "
                     "WHERE pd_pit_12m > 'not a number'", session)
    assert error.category in (TYPE_MISMATCH, UNRESOLVED_FIELD)


def test_error_messages_never_leak_a_path_or_another_schema(session):
    for statement in ("SELECT nope FROM cockpit_facility_quarter",
                      "SELECT * FROM read_parquet('/etc/hostname')",
                      "SELECT * FROM ews_alerts",
                      "SELECT * FROM cockpit_facility_quarter WHERE x = 1"):
        message = str(rejected(statement, session))
        for leak in (".parquet", "/home/", "/tmp/", "/etc/", "analytics"):
            assert leak not in message, f"{statement} leaked {leak}"


# ---- resource control -----------------------------------------------------

def test_binding_does_not_execute(session):
    """EXPLAIN resolves the query without doing the work."""
    import time

    heavy = ("SELECT a.facility_id FROM cockpit_facility_quarter a, "
             "cockpit_facility_quarter b, cockpit_facility_quarter c")
    started = time.monotonic()
    sql.bind(heavy, session)
    assert time.monotonic() - started < 2.0, (
        "binding took long enough that it probably executed")


def test_a_runaway_query_is_cancelled_at_the_deadline(session):
    """A row limit does not make a query cheap. The deadline is the control."""
    import time

    heavy = ("SELECT count(*) FROM cockpit_facility_quarter a, "
             "cockpit_facility_quarter b, cockpit_facility_quarter c, "
             "cockpit_qualitative_quarter d")
    sql.check_structure(heavy)
    started = time.monotonic()
    with pytest.raises(sql.SqlRejected) as e:
        sql.execute(heavy, session, deadline_seconds=1.0)
    elapsed = time.monotonic() - started
    assert e.value.category == RESOURCE_LIMIT
    assert elapsed < 12.0, f"cancellation took {elapsed:.1f}s"
    # ...and the session is still usable afterwards.
    assert run("SELECT 1 AS ok", session).rows == [{"ok": 1}]


def test_a_clipped_table_says_it_is_clipped(session):
    result = sql.execute(
        "SELECT facility_id, reporting_quarter FROM cockpit_facility_quarter",
        session, deadline_seconds=15, max_rows=5)
    assert result.truncated is True
    assert len(result.rows) == 5
    assert result.row_count > 5
    assert "CLIPPED" in result.warnings[0]
    assert "do not read a total off it" in result.warnings[0]


# ---- samples --------------------------------------------------------------

def test_samples_are_bounded_ordered_and_labelled(session):
    sample = sql.sample_rows(F.FACILITY_QUARTER, session, limit=10)
    assert len(sample["rows"]) == 10
    assert sample["ordering"][0] == "reporting_quarter"
    assert "do not establish a total" in sample["limitation"]
    again = sql.sample_rows(F.FACILITY_QUARTER, session, limit=10)
    assert [r["facility_id"] for r in again["rows"]] == \
           [r["facility_id"] for r in sample["rows"]], "samples reproducible"


def test_a_sample_of_an_unauthorized_relation_is_refused(session):
    with pytest.raises(S.OutOfScope):
        sql.sample_rows("ews_alerts", session)
