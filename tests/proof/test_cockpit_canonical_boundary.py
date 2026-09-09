"""The Cockpit's own book must never be mistaken for the canonical one.

Cockpit Agentic V3 arrived with a private synthetic universe — `BRW0001`
borrowers, `FAC00001` facilities, twenty quarters, INR crore — and the
integration's ruling is that the canonical Corporate book is the single
authority for reported actuals: `CORP-1NNNNN` over sixteen quarters,
Q3 2022 to Q2 2026, in SAR millions.

Repointing the Cockpit onto that book is deferred (see
docs/cockpit_repoint/FIELD_MAPPING.md and the integration ledger): only 50 of
the Cockpit's 791 declared fields share even a NAME with canonical, so the
"compatibility layer" is the whole mapping, and doing it quickly would mean
guessing at what several hundred numbers mean.

Deferring it is safe ONLY while the two books cannot reach each other, and
that is what this file holds to the fire. The feature branches each test their
own side; neither owns the boundary between them, which is exactly why it went
untested and why it belongs here.

The guarantee is structural rather than procedural: the Cockpit writes to its
own root and refuses the canonical directories, and its datasets are absent
from the governed catalogue — so a canonical consumer cannot read Cockpit data
even by mistake, because there is nothing there to name.
"""

from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Every identifier shape the Cockpit's private universes mint. If one of these
#: appears in a canonical dataset, the two books have merged and the canonical
#: claim is false.
COCKPIT_ID_PREFIXES = ("BRW", "FAC0", "GRP0", "CKB-", "CKG-")


def _catalogue() -> list[dict]:
    path = ROOT / "metadata" / "catalog.json"
    if not path.exists():
        pytest.skip("no governed catalogue built in this environment")
    doc = json.loads(path.read_text())
    return doc["datasets"] if isinstance(doc, dict) else doc


class TestTheCockpitIsNotInTheGovernedCatalogue:
    """A dataset the catalogue does not name cannot be read by a governed
    plan, whatever a model asks for."""

    def test_no_cockpit_dataset_is_governed(self):
        named = [d["name"] for d in _catalogue()
                 if str(d.get("name", "")).startswith("cockpit")]
        assert named == [], (
            "Cockpit datasets have entered the governed catalogue, so a "
            f"canonical consumer can now reach them: {named}")

    def test_the_catalogue_still_holds_the_canonical_book(self):
        """The other half of the same claim. An empty catalogue would pass the
        test above for the wrong reason."""
        names = {d["name"] for d in _catalogue()}
        assert "corporate_ifrs9" in names
        assert "corporate_borrower_360" in names


class TestTheCockpitWritesOutsideTheCanonicalDirectories:

    def test_the_cockpit_root_is_not_the_analytics_lake(self):
        from backend.cockpit_agentic import store
        from backend.config import settings

        root = pathlib.Path(store.root()).resolve()
        analytics = pathlib.Path(settings.analytics_dir).resolve()
        metadata = pathlib.Path(settings.metadata_dir).resolve()
        assert root != analytics
        assert analytics not in root.parents and root not in analytics.parents
        assert metadata not in root.parents

    def test_the_canonical_directories_are_refused_by_name(self):
        from backend.cockpit_agentic import store

        for forbidden in ("data/analytics", "metadata"):
            assert forbidden in store.FORBIDDEN


class TestNoCockpitIdentifierReachesTheCanonicalBook:
    """The strongest form of the claim, asserted against the Parquet itself
    rather than against a declaration about it."""

    def test_canonical_borrowers_are_all_canonical(self):
        duckdb = pytest.importorskip("duckdb")
        lake = ROOT / "data" / "analytics" / "corporate_borrower_360"
        if not lake.exists():
            pytest.skip("the canonical lake is not built in this environment")
        con = duckdb.connect()
        rows = con.execute(
            f"SELECT DISTINCT borrower_id "
            f"FROM read_parquet('{lake}/**/*.parquet') LIMIT 5000").fetchall()
        strays = [r[0] for r in rows
                  if str(r[0]).startswith(COCKPIT_ID_PREFIXES)]
        assert strays == [], f"Cockpit identifiers in the canonical book: {strays[:10]}"
        assert rows, "the canonical book is empty, so this proves nothing"
        assert all(str(r[0]).startswith("CORP-") for r in rows)


class TestTheCanonicalPeriodSetIsUnchanged:
    """Sixteen quarters, and the Cockpit's twenty must not have widened it."""

    def test_whatif_sees_exactly_the_canonical_sixteen(self):
        duckdb = pytest.importorskip("duckdb")
        lake = ROOT / "data" / "analytics" / "corporate_ifrs9"
        if not lake.exists():
            pytest.skip("the canonical lake is not built in this environment")
        con = duckdb.connect()
        periods = [r[0] for r in con.execute(
            f"SELECT DISTINCT period FROM read_parquet('{lake}/**/*.parquet')"
        ).fetchall()]
        assert len(periods) == 16, f"expected 16 canonical quarters, got {len(periods)}"
        assert "Q3 2022" in periods and "Q2 2026" in periods
        # 2021 is Cockpit's calendar, not the canonical one; a forecast target
        # beyond Q2 2026 would mean a projection had become a reported period.
        assert not [p for p in periods if "2021" in str(p) or "2027" in str(p)
                    or "2030" in str(p)]
