"""§8H: reading SQL well enough to refuse it.

Two kinds of test here and both matter. The refusals are the security
property. The ACCEPTANCES are what stops the guard from being turned off: a
validator that refuses `SELECT 'DROP TABLE x' AS note` is a validator somebody
will route around within a week.
"""

from __future__ import annotations

import pytest

from backend.metrics import sqlguard as guard

SAFE_RATIO = (
    "SELECT SUM(exposure) FILTER (WHERE ifrs9_stage = 2) / SUM(exposure) "
    "AS stage2_ratio FROM portfolio_facility WHERE period = ?")

SAFE_GROWTH = (
    "WITH cur AS (SELECT SUM(exposure) AS e FROM portfolio_facility "
    "WHERE period = ?),\n"
    "     prev AS (SELECT SUM(exposure) AS e FROM portfolio_facility "
    "WHERE period = ?)\n"
    "SELECT (cur.e / prev.e) - 1 AS qoq FROM cur CROSS JOIN prev")


# ------------------------------------------------------------- what is safe


@pytest.mark.parametrize("sql", [SAFE_RATIO, SAFE_GROWTH])
def test_ordinary_metric_sql_passes(sql):
    assert guard.statement_problems(sql) == []


def test_a_string_literal_is_not_a_statement():
    """`SELECT 'DROP TABLE x' AS note` is safe, and a regex for DROP rejects
    it. This is why the guard tokenises."""
    sql = "SELECT 'DROP TABLE portfolio_facility' AS note, SUM(exposure) " \
          "FROM portfolio_facility"
    assert guard.statement_problems(sql) == []


def test_an_escaped_quote_does_not_end_the_string():
    sql = "SELECT 'it''s fine; DROP TABLE x' AS note FROM portfolio_facility"
    assert guard.statement_problems(sql) == []


def test_a_trailing_semicolon_is_one_statement():
    assert guard.read("SELECT 1 FROM portfolio_facility;").statements == 1


# --------------------------------------------------------- what is refused


@pytest.mark.parametrize("sql,because", [
    ("SELECT 1 FROM portfolio_facility; DROP TABLE portfolio_facility",
     "statements"),
    ("SELECT/*safe*/ 1; DROP TABLE x", "statements"),
    ("DELETE FROM portfolio_facility", "SELECT or WITH"),
    ("UPDATE portfolio_facility SET exposure = 0", "SELECT or WITH"),
    ("INSERT INTO portfolio_facility VALUES (1)", "SELECT or WITH"),
    ("SELECT 1 FROM portfolio_facility; INSTALL httpfs", "statements"),
    ("GRANT SELECT ON portfolio_facility TO anybody", "SELECT or WITH"),
])
def test_writes_and_multiple_statements_are_refused(sql, because):
    problems = guard.statement_problems(sql)
    assert problems
    assert any(because in p for p in problems), problems


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_parquet('/etc/passwd')",
    "SELECT * FROM read_csv_auto('/tmp/anything.csv')",
    "WITH x AS (SELECT * FROM read_json('http://elsewhere/data')) "
    "SELECT * FROM x",
    "SELECT getenv('ANTHROPIC_API_KEY')",
])
def test_reaching_outside_the_governed_data_is_refused(sql):
    """This one found a hole in the guard's own first draft: a table function
    consumed the FROM target and was never recorded, so
    `read_parquet('/etc/passwd')` came back with no tables, no functions and
    no problems."""
    problems = guard.statement_problems(sql)
    assert problems
    assert any("outside the governed datasets" in p for p in problems), problems


def test_a_system_catalogue_is_refused():
    problems = guard.statement_problems(
        "SELECT * FROM information_schema.tables")
    assert any("system catalogues" in p for p in problems), problems


def test_a_schema_qualifier_is_refused_even_when_the_table_is_governed():
    """§8H's cross-tenant case. `other_tenant.portfolio_facility` names a real
    table somewhere this deployment did not put the data."""
    problems = guard.statement_problems(
        "SELECT * FROM other_tenant.portfolio_facility")
    assert any("schema" in p for p in problems), problems


# ------------------------------------------------------------------ reading


def test_tables_and_ctes_are_told_apart():
    reading = guard.read(SAFE_GROWTH)
    assert reading.tables == ["portfolio_facility", "portfolio_facility"]
    assert sorted(reading.cte_names) == ["cur", "prev"]


def test_aliases_are_not_mistaken_for_columns():
    reading = guard.read(
        "SELECT SUM(p.exposure) AS total FROM portfolio_facility p "
        "WHERE p.period = ?")
    assert "total" in reading.aliases
    assert "p" in reading.aliases
    assert ("p", "exposure") in reading.qualified_columns


def test_aggregations_are_recorded():
    assert "sum" in guard.read(SAFE_RATIO).aggregates


def test_scope_tells_a_real_join_from_two_separate_reads():
    """The distinction that keeps composite SQL from being refused. Two base
    tables in one FROM clause are joined; two in separate CTEs are two reads
    whose results are combined, and only the first carries fan-out risk."""
    composite = (
        "WITH numerator AS (SELECT SUM(exposure) AS value "
        "FROM portfolio_facility WHERE period = ?),\n"
        " denominator AS (SELECT SUM(total_ead) AS value "
        "FROM watchlist_register WHERE period = ?)\n"
        "SELECT numerator.value / denominator.value "
        "FROM numerator CROSS JOIN denominator")
    scopes = guard.read(composite).tables_by_scope
    assert scopes == {"numerator": ["portfolio_facility"],
                      "denominator": ["watchlist_register"]}

    joined = ("SELECT SUM(p.exposure) FROM portfolio_facility p "
              "JOIN watchlist_register w ON p.customer_id = w.customer_id")
    assert guard.read(joined).tables_by_scope == {
        "": ["portfolio_facility", "watchlist_register"]}


def test_a_join_inside_one_cte_is_still_a_join():
    sql = ("WITH x AS (SELECT p.exposure FROM portfolio_facility p "
           "JOIN ifrs9_staging s ON p.account_id = s.account_id) "
           "SELECT SUM(exposure) FROM x")
    assert guard.read(sql).tables_by_scope == {
        "x": ["portfolio_facility", "ifrs9_staging"]}


def test_empty_sql_is_refused_rather_than_passed():
    assert guard.statement_problems("") == ["There is no SQL to check."]
