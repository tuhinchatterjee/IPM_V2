"""The two denominations, and the five things that must be true of them.

The first candidate release divided every amount by a million and declared
itself denominated in millions. Read at portfolio grain it was right; read at
facility grain every monetary figure published as `SAR 0 million`, because
the frozen money policy writes an amount with no decimal places and a
facility is a small fraction of a million riyals.

The release now publishes both denominations. `*_sar_mn` is genuinely in
millions and is what the frozen engine's own SQL sums; `*_sar` is the source
book's own riyal figure, declared `unit="SAR"` so the policy renders it in
riyals whatever the release scale says. These tests are the gate on that
pair: that it reconciles to the source, that the manifest tells the truth
about it, that an account-level figure survives rendering, that a portfolio
total survives the engine, and that nothing the engine reads by name broke.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from backend.retail_cockpit_adapter import gates
from backend.retail_cockpit_adapter import semantic_map as sm

ROOT = Path(__file__).resolve().parents[2]

#: The release this correction produced. Named as a literal: a test that
#: followed the configured release id would pass against the defective one.
RELEASE = "cockpitdata-r1.2.0-c1.0.0-s20260910-p5"

#: The reconciliation the Mac reported, to the precision a float sum is
#: reproducible to across machines. The EXACT equality that matters is
#: source-to-projection on ONE machine, which `test_riyals_are_the_source`
#: asserts; a literal pinned to the last bit would fail on the other one for
#: reasons that have nothing to do with the denomination.
LATEST_MONTH = "2026-08"
EXPECTED_TOTALS = {
    "ead_sar": 6_425_968_606.8348,
    "ecl_sar": 58_608_354.4360,
    "balance_sar": 6_388_268_768.9000,
}
RELATIVE = 1e-12


def _manifest() -> dict:
    import json

    from backend.cockpit_v4 import lake

    path = Path(lake.root()) / RELEASE / "manifest.json"
    if not path.exists():
        pytest.skip(f"{RELEASE} is not published in this runtime. Publish it "
                    f"with scripts/retail_cockpit/publish_release.py "
                    f"--revision 5")
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot():
    from backend.retail_cockpit_adapter.source import SnapshotUnavailable, open_snapshot

    for analytics, metadata in (
            (ROOT / "data" / "retail" / "analytics", ROOT / "metadata"
             / "retail"),
            (ROOT / "var" / "retail-candidate-book" / "analytics",
             ROOT / "var" / "retail-candidate-book" / "metadata")):
        try:
            snapshot = open_snapshot(analytics, metadata)
        except SnapshotUnavailable:
            continue
        # The manifest is committed and the 400 MB of Parquet beside it is
        # not, so a readable catalogue does not mean a readable book.
        if snapshot.part_path(snapshot.latest_period).exists():
            return snapshot
    pytest.skip("the Cockpit Data snapshot is not readable in this runtime")


def _session(monkeypatch, tmp_path):
    from backend.cockpit_v4 import catalog as cat

    monkeypatch.setenv("COCKPIT_V4_RUNTIME_DIR", str(tmp_path / "runtime"))
    _manifest()
    cat.reset_sessions()
    catalog = cat.build(domain_id="retail", release_id=RELEASE,
                        tenant_id="demo-tenant")
    return catalog, cat.open_session(catalog=catalog, reuse=False)


# ---- the pair is declared at all ---------------------------------------

def test_every_money_column_is_published_in_both_denominations():
    for relation, mappings in sm.MAPS.items():
        declared = {m.column for m in mappings}
        for mapping in mappings:
            if mapping.unit != "rcy":
                continue
            twin = sm.riyal_name(mapping.column)
            assert twin in declared, (
                f"{relation}.{mapping.column} is denominated in the "
                f"reporting currency and has no riyal twin")
            assert sm.millions_name(twin) == mapping.column


def test_the_twin_carries_the_same_source_and_never_divides():
    for mappings in sm.MAPS.values():
        by_name = {m.column: m for m in mappings}
        for mapping in mappings:
            if mapping.unit != "rcy":
                continue
            twin = by_name[sm.riyal_name(mapping.column)]
            assert twin.unit == sm.UNIT_SAR
            assert twin.source == mapping.source
            assert twin.group == mapping.group
            assert twin.aggregation == mapping.aggregation
            assert "1,000,000" not in twin.lineage
            assert twin.reads == mapping.reads


def test_a_derived_money_column_without_a_riyal_rule_is_refused():
    base = sm.Mapping(relation=sm.ACCOUNT, column="invented_sar_mn",
                      unit="rcy", derive=lambda frame: frame,
                      needs=("dpd",))
    with pytest.raises(ValueError) as raised:
        sm.riyal_twin(base)
    assert "RIYAL_DERIVE" in str(raised.value)


# ---- G1: the riyal columns ARE the source ------------------------------

def test_riyals_are_the_source_book_exactly():
    from backend.retail_cockpit_adapter.projection import project_month

    snapshot = _snapshot()
    month = snapshot.months[-1]
    projected = project_month(snapshot, month.reporting_month,
                              tenant_id="demo-tenant", release_id=RELEASE,
                              domain_id="retail")
    assert gates.check_source_totals(snapshot, projected, month) == []


def test_the_two_denominations_are_one_quantity():
    from backend.retail_cockpit_adapter.projection import project_month

    snapshot = _snapshot()
    month = snapshot.months[-1]
    projected = project_month(snapshot, month.reporting_month,
                              tenant_id="demo-tenant", release_id=RELEASE,
                              domain_id="retail")
    assert gates._denomination(projected.frames, month) == []


def test_the_defect_this_release_corrects_would_be_caught():
    """A riyal column that was divided is a finding, not a rounding note."""
    from backend.retail_cockpit_adapter.projection import project_month

    snapshot = _snapshot()
    month = snapshot.months[-1]
    projected = project_month(snapshot, month.reporting_month,
                              tenant_id="demo-tenant", release_id=RELEASE,
                              domain_id="retail")
    frames = dict(projected.frames)
    broken = frames[sm.ACCOUNT].copy()
    broken["ead_sar"] = broken["ead_sar"] / sm.SAR_PER_MILLION
    frames[sm.ACCOUNT] = broken
    findings = gates._denomination(frames, month)
    assert [f for f in findings if "ead_sar" in f.problem]


# ---- G2: the manifest tells the truth ----------------------------------

def test_the_manifest_declares_a_scale_and_a_unit_per_column():
    manifest = _manifest()
    assert manifest["reporting_currency"] == sm.CURRENCY
    assert manifest["amount_scale"] == sm.AMOUNT_SCALE == "million"
    seen = 0
    for relation in manifest["relations"]:
        for field in relation["fields"]:
            name = str(field["name"])
            if name.endswith("_sar_mn"):
                assert field["unit"] == "rcy", name
                seen += 1
            elif name.endswith("_sar"):
                assert field["unit"] == sm.UNIT_SAR, name
                seen += 1
    assert seen == 2 * sum(len(p) for p in sm.MONEY_PAIRS.values())


def test_each_denomination_names_the_other_in_its_own_definition():
    manifest = _manifest()
    described = {f["name"]: str(f["description"])
                 for relation in manifest["relations"]
                 for f in relation["fields"]}
    for pairs in sm.MONEY_PAIRS.values():
        for millions, riyals in pairs:
            assert riyals in described[millions]
            assert millions in described[riyals]


def test_the_release_header_is_not_unverified():
    from backend.cockpit_v4 import release as release_mod

    manifest = _manifest()
    header = release_mod.header(release_id=RELEASE, release_summary=manifest,
                                tenant_id="demo-tenant")
    assert header.unverified == ()
    assert header.money_unit == "SAR million"


# ---- G3: an account-level figure survives rendering --------------------

def test_an_account_level_amount_does_not_render_as_zero(monkeypatch,
                                                         tmp_path):
    from backend.cockpit_v4 import display as disp

    catalog, session = _session(monkeypatch, tmp_path)
    try:
        rows = session.connection.execute(
            "SELECT balance_sar, balance_sar_mn, ead_sar, ead_sar_mn "
            "FROM retail_account_month "
            f"WHERE reporting_month = '{LATEST_MONTH}' "
            "AND balance_sar > 0 AND ead_sar > 0 "
            "ORDER BY account_id LIMIT 200").fetchall()
        assert rows
        riyal_unit = disp.unit_for_field(catalog, sm.ACCOUNT, "balance_sar")
        million_unit = disp.unit_for_field(catalog, sm.ACCOUNT,
                                           "balance_sar_mn")
        assert riyal_unit == "SAR"
        assert million_unit == "SAR million"
        collapsed = 0
        for balance, balance_mn, ead, ead_mn in rows:
            for value, unit in ((balance, riyal_unit), (ead, riyal_unit)):
                shown = disp.format_value(Decimal(str(value)), unit)
                assert shown.startswith("SAR ")
                assert "million" not in shown
                assert any(ch in "123456789" for ch in shown), shown
            for value in (balance_mn, ead_mn):
                if disp.format_value(Decimal(str(value)),
                                     million_unit) == "SAR 0 million":
                    collapsed += 1
        # The reason the riyal column exists, asserted rather than assumed:
        # at this grain the millions column is the one that rounds away.
        assert collapsed > 0
    finally:
        session.close()


# ---- G4: a portfolio total survives the engine -------------------------

def test_portfolio_totals_reconcile_through_the_session(monkeypatch,
                                                        tmp_path):
    _, session = _session(monkeypatch, tmp_path)
    try:
        for column, expected in EXPECTED_TOTALS.items():
            riyals, millions = session.connection.execute(
                f"SELECT SUM({column}), SUM({sm.millions_name(column)}) "
                "FROM retail_account_month "
                f"WHERE reporting_month = '{LATEST_MONTH}'").fetchone()
            assert abs(riyals - expected) <= abs(expected) * RELATIVE, column
            assert abs(millions - riyals / sm.SAR_PER_MILLION) <= (
                abs(riyals / sm.SAR_PER_MILLION) * RELATIVE), column
    finally:
        session.close()


def test_the_customer_roll_up_is_the_facilities_in_both_denominations(
        monkeypatch, tmp_path):
    _, session = _session(monkeypatch, tmp_path)
    try:
        rolled, summed = session.connection.execute(
            "SELECT (SELECT SUM(total_ead_sar) FROM retail_customer_month "
            f"        WHERE reporting_month = '{LATEST_MONTH}'), "
            "       (SELECT SUM(ead_sar) FROM retail_account_month "
            f"        WHERE reporting_month = '{LATEST_MONTH}')").fetchone()
        assert abs(rolled - summed) <= abs(summed) * RELATIVE
    finally:
        session.close()


# ---- G5: nothing the frozen engine reads by name broke -----------------

def test_the_ecl_panel_still_reads_its_own_columns(monkeypatch, tmp_path):
    from backend.cockpit_v4 import ecl as ecl_mod

    catalog, session = _session(monkeypatch, tmp_path)
    try:
        scope = _scope(catalog)
        profile = ecl_mod.stage_profile(session=session, scope=scope)
        assert profile["stages"]
        assert scope.money_unit == "SAR million"
        movement = ecl_mod.decompose(session=session, scope=scope)
        assert movement.money_unit == "SAR million"
    finally:
        session.close()


#: The one retail attention family this book cannot serve, and why. It reads
#: `retail_customer_month.score_migration`; the source publishes a
#: behavioural score at FACILITY grain and no customer-level migration, so
#: the projection has no column to put there. Nothing to do with the
#: denomination, and present in every revision including the first.
UNSERVED_FAMILY = "segment_score_decline"


def _referenced(expression: str) -> set[str]:
    import re

    return {name for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
            if name.islower() and "_" in name}


def test_every_money_column_the_attention_feed_reads_is_published(
        monkeypatch, tmp_path):
    """The feed's money SQL is the point: it sums `*_sar_mn` by name."""
    from backend.cockpit_v4 import attention_v2 as att

    catalog, session = _session(monkeypatch, tmp_path)
    try:
        served = 0
        for family in att.FAMILIES["retail"]:
            if family.key == UNSERVED_FAMILY:
                continue
            columns = set(catalog.columns(family.relation))
            missing = (_referenced(family.expression)
                       | _referenced(family.size_expression)) - columns
            assert not missing, (family.key, sorted(missing))
            for sql in (family.expression, family.size_expression):
                session.connection.execute(
                    f"SELECT {sql} FROM {family.relation}").fetchone()
            served += 1
        assert served == len(att.FAMILIES["retail"]) - 1
    finally:
        session.close()


@pytest.mark.xfail(strict=True, reason=(
    "retail_customer_month.score_migration is not published by this book, "
    "so attention_v2.compute raises on the segment_score_decline family and "
    "the whole Home feed is unavailable. Recorded, not worked around. When "
    "the gap is closed this test XPASSes and must be promoted."))
def test_the_whole_retail_attention_feed_computes(monkeypatch, tmp_path):
    from backend.cockpit_v4 import attention_v2 as att

    catalog, session = _session(monkeypatch, tmp_path)
    try:
        from backend.cockpit_v4 import domain_resolver

        scope = domain_resolver.scope_for("retail", tenant_id="demo-tenant",
                                          release_id=RELEASE)
        feed = att.compute(session=session, scope=scope)
        assert feed["segments_requiring_attention"]
    finally:
        session.close()


def test_the_compact_packet_still_carries_every_money_measure(monkeypatch,
                                                              tmp_path):
    from backend.cockpit_v4 import semantics as sem

    catalog, session = _session(monkeypatch, tmp_path)
    try:
        resolved = {entry["field"] for entry in sem.measures(catalog)}
        for expected in ("ead_sar_mn", "ecl_sar_mn", "limit_sar_mn",
                         "balance_sar_mn", "write_off_sar_mn",
                         "recovery_sar_mn"):
            assert expected in resolved, expected
    finally:
        session.close()


def _scope(catalog):
    from backend.cockpit_v4 import domain_resolver

    return domain_resolver.scope_for("retail", tenant_id="demo-tenant",
                                     release_id=RELEASE)
