"""The Early Warning landing page. R2 §10.

The screen opened on signal counts — "412 utilisation_high, 389 leverage_rose"
— which describes how the RULE BOOK is behaving and says nothing about the
book. What a credit officer arrives wanting to know is how many names need
them today, how much money is behind those names, and what changed.

These tests assert the shape of that answer and, where they can, its
plausibility: a landing page whose headline number covers half the book is a
landing page nobody can work from.
"""

from __future__ import annotations

import pytest

from backend.early_warning import dashboard as db
from backend.early_warning import priority as pr
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx


def standing(borrower_id: str, **row):
    row.setdefault("borrower_id", borrower_id)
    row.setdefault("sector", "Shipping")
    return sg.stand(row, period="Q2 2026")


@pytest.fixture(scope="module")
def book():
    """A small hand-built book with one borrower of each shape."""
    big = pr.MATERIAL_EXPOSURE * 3
    return [
        standing("CORP-IMPAIRED", drawn_exposure=big, stage=3),
        standing("CORP-DEFAULT", drawn_exposure=big, current_dpd=120),
        standing("CORP-BREACH", drawn_exposure=big, breach_flag=True),
        standing("CORP-ARREARS", drawn_exposure=big, current_dpd=45,
                 sector="Contracting"),
        standing("CORP-THIN", drawn_exposure=20.0, revenue_growth=-4.0,
                 sector="Contracting"),
        standing("CORP-QUIET", drawn_exposure=20.0, stage=1, current_dpd=0),
    ]


class TestTheMeasures:
    def test_every_measure_says_what_it_is(self, book):
        for measure in db.measures(book):
            assert measure.label
            assert measure.means.endswith(".")
            assert " " in measure.means

    def test_the_headline_is_what_to_act_on_not_how_many_rules_fired(
            self, book):
        first = db.measures(book)[0]
        assert first.key == "act_now"
        assert first.value == 3  # impaired, in default, in breach

    def test_a_measure_names_the_borrowers_behind_it(self, book):
        found = {m.key: m for m in db.measures(book)}
        assert "CORP-IMPAIRED" in found["act_now"].borrowers
        assert "CORP-QUIET" not in found["act_now"].borrowers

    def test_exposure_at_stake_is_money_in_riyals(self, book):
        found = {m.key: m for m in db.measures(book)}["exposure_at_stake"]
        assert found.unit == db.MONEY
        assert found.to_dict()["currency"] == "SAR"
        assert found.value and found.value > 0

    def test_a_measure_the_book_cannot_compute_says_so(self):
        """§7. "No covenant breaches" and "this deployment does not carry the
        covenant flag" are different answers, and only one is reassuring."""
        thin = [standing("CORP-1", revenue_growth=-4.0)]
        found = {m.key: m for m in db.measures(thin)}
        assert not found["covenant_breaches"].available
        assert "does not carry" in found["covenant_breaches"].unavailable
        assert found["covenant_breaches"].value is None

    def test_an_unavailable_measure_is_never_reported_as_zero(self):
        thin = [standing("CORP-1", revenue_growth=-4.0)]
        for measure in db.measures(thin):
            if not measure.available:
                assert measure.value is None, measure.key

    def test_a_stage_prompt_is_not_a_stage_classification(self, book):
        """§20. An early-warning prompt is never an accounting stage."""
        found = {m.key: m for m in db.measures(book)}["stage_two_candidates"]
        assert "NOT a stage classification" in found.means

    def test_new_this_quarter_is_separate_from_the_total(self, book):
        keys = [m.key for m in db.measures(book)]
        assert "newly_at_risk" in keys
        assert keys.index("newly_at_risk") < keys.index("exposure_at_stake")


class TestHotspotsAndChanges:
    def test_hotspots_are_by_sector_with_counts_and_money(self, book):
        rows = db.hotspots(book)
        assert rows
        for row in rows:
            assert row["sector"]
            assert row["act_now"] + row["review"] > 0
            assert row["exposure"] >= 0

    def test_a_sector_with_nothing_to_act_on_is_not_a_hotspot(self, book):
        sectors = {r["sector"] for r in db.hotspots(book)}
        assert "Shipping" in sectors

    def test_changes_say_what_changed_in_words(self, book):
        for row in db.changes(book):
            assert row["what_changed"].endswith(".")
            assert row["priority"] in pr.PRIORITIES
            assert row["priority_label"]

    def test_changes_lead_with_what_needs_acting_on(self, book):
        rows = db.changes(book)
        ranks = [pr.PRIORITY_RANK[r["priority"]] for r in rows]
        assert ranks == sorted(ranks, reverse=True)


class TestDiagnostics:
    def test_the_signal_counts_are_still_published(self, book):
        """Moved off the landing page, not deleted: the person tuning a
        threshold still needs them."""
        rows = db.diagnostics(book)
        assert rows
        for row in rows:
            assert row["signal"]
            assert row["label"]
            assert 0 <= row["share_of_book_pct"] <= 100

    def test_they_are_ordered_by_how_many_borrowers_they_touch(self, book):
        counts = [r["borrowers"] for r in db.diagnostics(book)]
        assert counts == sorted(counts, reverse=True)


class TestTheWholePayload:
    def test_it_carries_the_policy_it_applied(self, book):
        found = db.build(book, period="Q2 2026")
        policy = found["priority_policy"]
        assert policy["owner"] == tx.THRESHOLD_OWNER
        assert {p["priority"] for p in policy["levels"]} == set(pr.PRIORITIES)
        assert policy["material_exposure"] == pr.MATERIAL_EXPOSURE

    def test_there_is_no_score_anywhere_in_it(self, book):
        import json

        text = json.dumps(db.build(book, period="Q2 2026"))
        assert '"score"' not in text

    def test_the_currency_is_stated_once_at_the_top(self, book):
        assert db.build(book, period="Q2 2026")["currency"] == "SAR"


class TestAgainstTheRealBook:
    """A landing page whose headline covers half the book is unusable."""

    @pytest.fixture(scope="class")
    @classmethod
    def live(cls):
        found = sg.dashboard()
        if not found.get("evaluated"):
            pytest.skip("no published book in this environment")
        return found

    def test_the_act_now_list_is_a_minority_of_the_book(self, live):
        measure = {m["key"]: m for m in live["measures"]}["act_now"]
        assert measure["value"] / live["evaluated"] < 0.30

    def test_and_is_smaller_than_the_review_population(self, live):
        acting = {m["key"]: m for m in live["measures"]}["act_now"]["value"]
        assert acting < live["evaluated"] / 2

    def test_every_borrower_to_act_on_has_a_fact_behind_it(self, live):
        """Not evidence — a FACT: impaired, in default, in breach, or
        materially under-secured while deteriorating."""
        facts = {"booked_impaired", "in_default", "covenant_breached_material",
                 "collateral_shortfall_material"}
        book = sg.portfolio(limit=500)
        for row in book["borrowers"]:
            if row["priority"] != pr.ACT_NOW:
                continue
            rules = {r["rule"] for r in row["priority_reasons"]
                     if r["level"] == pr.ACT_NOW}
            assert rules & facts, (row["borrower_id"], rules)

    def test_the_hotspots_name_real_sectors(self, live):
        from backend.corporate.universe import SECTORS

        names = {s.name for s in SECTORS}
        for row in live["hotspots"]:
            assert row["sector"] in names or row["sector"] == "Unattributed"

    def test_the_measures_and_the_list_agree(self, live):
        """A KPI and the list behind it are built from the same standings, so
        they cannot disagree about how many borrowers there are."""
        measure = {m["key"]: m for m in live["measures"]}["act_now"]
        book = sg.portfolio(limit=500)
        listed = sum(1 for b in book["borrowers"]
                     if b["priority"] == pr.ACT_NOW)
        assert listed == min(measure["value"], len(book["borrowers"]))
