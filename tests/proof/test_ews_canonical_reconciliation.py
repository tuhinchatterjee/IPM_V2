"""Early Warning reads the canonical book, and this proves it still does.

The integration's ruling is that there is ONE canonical Corporate identity and
one IFRS 9 history: `CORP-1NNNNN` borrowers over sixteen quarters, Q3 2022 to
Q2 2026. Early Warning keeps its own domain — signals, classifiers, triggers,
persistence, scores — but every borrower it reports on must be a borrower the
canonical book has, and the IFRS 9 fields it carries must be reads of that book
rather than a second opinion about it.

That is already true by construction: `scripts/build_early_warning_v2.py` calls
`corp._load(corp.SNAPSHOT)` and refuses to run without it, then selects its
population from borrowers present in every needed quarter. What was missing is
anything that would notice if it stopped being true — a later change to either
generator, a reseeded universe, a different sample.

One wrinkle this pins deliberately. Early Warning writes the canonical
`CORP-` values under the column name `customer_id`, not `borrower_id`. Same
values, different name, which is a join waiting to be got wrong: a reader who
assumes the names match finds nothing, and a reader who assumes different names
mean different populations concludes the books disagree. The tests below assert
the VALUES reconcile and say plainly which column carries them.
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "analytics"
EWS = LAKE / "early_warning_borrower_month"
CORPORATE = LAKE / "corporate_borrower_360"

#: Early Warning's identity column. Named here once so a rename is a one-line
#: change in this file rather than a hunt, and so the asymmetry is documented
#: where it is asserted.
EWS_IDENTITY_COLUMN = "customer_id"


def _con():
    duckdb = pytest.importorskip("duckdb")
    if not EWS.exists() or not CORPORATE.exists():
        pytest.skip("the Early Warning or canonical lake is not built here")
    return duckdb.connect()


class TestEveryEarlyWarningBorrowerIsACanonicalBorrower:

    def test_no_early_warning_borrower_is_unknown_to_the_canonical_book(self):
        con = _con()
        orphans = con.execute(f"""
            SELECT DISTINCT e.{EWS_IDENTITY_COLUMN}
            FROM read_parquet('{EWS}/**/*.parquet') e
            WHERE e.{EWS_IDENTITY_COLUMN} NOT IN (
                SELECT borrower_id FROM read_parquet('{CORPORATE}/**/*.parquet'))
        """).fetchall()
        assert orphans == [], (
            "Early Warning reports on borrowers the canonical book does not "
            f"have, so the two populations have diverged: {orphans[:10]}")

    def test_the_population_is_not_empty_so_the_check_above_means_something(self):
        con = _con()
        n = con.execute(
            f"SELECT COUNT(DISTINCT {EWS_IDENTITY_COLUMN}) "
            f"FROM read_parquet('{EWS}/**/*.parquet')").fetchone()[0]
        assert n > 0, "no Early Warning borrowers at all"

    def test_the_identifiers_are_canonical_in_shape_as_well_as_membership(self):
        """Membership could pass on an empty-ish overlap; the prefix cannot."""
        con = _con()
        rows = con.execute(
            f"SELECT DISTINCT {EWS_IDENTITY_COLUMN} "
            f"FROM read_parquet('{EWS}/**/*.parquet') LIMIT 2000").fetchall()
        strays = [r[0] for r in rows if not str(r[0]).startswith("CORP-")]
        assert strays == [], f"non-canonical identifiers in Early Warning: {strays[:10]}"


class TestEarlyWarningAddsToTheBookRatherThanRedefiningIt:

    def test_early_warning_is_a_subset_not_a_second_universe(self):
        """It samples the canonical population; it must never exceed it."""
        con = _con()
        ews = con.execute(
            f"SELECT COUNT(DISTINCT {EWS_IDENTITY_COLUMN}) "
            f"FROM read_parquet('{EWS}/**/*.parquet')").fetchone()[0]
        canon = con.execute(
            f"SELECT COUNT(DISTINCT borrower_id) "
            f"FROM read_parquet('{CORPORATE}/**/*.parquet')").fetchone()[0]
        assert ews <= canon, (
            f"Early Warning reports {ews} borrowers where the canonical book "
            f"has {canon} — it cannot be a subset of it")

    def test_early_warning_months_do_not_widen_the_canonical_quarters(self):
        """EWS publishes month-ends and the canonical book publishes quarters.

        Two calendars are legitimate; a month outside the canonical span is
        not, because it would be Early Warning asserting history the
        authoritative book does not have.
        """
        con = _con()
        months = [str(r[0]) for r in con.execute(
            f"SELECT DISTINCT snapshot_month "
            f"FROM read_parquet('{EWS}/**/*.parquet') ORDER BY 1").fetchall()]
        assert months, "no Early Warning months"
        # The canonical book ends Q2 2026 — June 2026. Nothing may sit beyond it.
        assert max(months) <= "2026-06", (
            f"Early Warning publishes {max(months)}, beyond the canonical "
            "book's final quarter Q2 2026")
