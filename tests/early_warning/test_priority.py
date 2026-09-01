"""Severity is about the rule. Priority is about the borrower. R2 §25.

The acceptance run found Early Warning ranking borrowers by how many rules
fired. Two names with one severe signal each came out identical when one of
them was a SAR 412m exposure in covenant breach and a hundred and twenty days
past due, and the other was a SAR 3m facility whose statements were stale. An
officer working down that list works down it in the wrong order, which is the
whole failure: the list is the product.

Every rule here is a named condition that either holds or does not, and every
one that holds produces a sentence a credit officer can argue with. There is
no score, and these tests would fail if somebody introduced one — a weighted
number is not something a reader can disagree with.
"""

from __future__ import annotations

import pytest

from backend.early_warning import priority as pr
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

BIG = pr.MATERIAL_EXPOSURE * 4      # a material exposure
SMALL = pr.MATERIAL_EXPOSURE / 20   # one that is not


def standing(**row):
    row.setdefault("borrower_id", "CORP-1")
    return sg.stand(row, period="Q2 2026")


def verdict(**row):
    return standing(**row).verdict


class TestActNow:
    def test_an_impaired_exposure_is_not_a_watch_item(self):
        found = verdict(drawn_exposure=BIG, stage=3)
        assert found.priority == pr.ACT_NOW
        assert any("stage 3" in s for s in found.because())

    def test_ninety_days_past_due_is_a_fact_about_payment(self):
        found = verdict(drawn_exposure=BIG, current_dpd=120)
        assert found.priority == pr.ACT_NOW
        assert any("120 days past due" in s for s in found.because())

    def test_a_covenant_breach_on_a_material_exposure(self):
        found = verdict(drawn_exposure=BIG, breach_flag=True)
        assert found.priority == pr.ACT_NOW

    def test_a_collateral_shortfall_on_a_material_exposure(self):
        found = verdict(drawn_exposure=BIG, collateral_shortfall=25.0)
        assert found.priority == pr.ACT_NOW

    def test_the_same_breach_on_a_small_facility_is_a_review(self):
        """The defect this whole module exists for: size has to count."""
        found = verdict(drawn_exposure=SMALL, breach_flag=True)
        assert found.priority == pr.REVIEW
        assert not found.material

    def test_arrears_do_not_need_the_exposure_to_be_material(self):
        """An unpaid instalment is a fact whatever the facility is worth."""
        found = verdict(drawn_exposure=SMALL, current_dpd=95)
        assert found.priority == pr.ACT_NOW


class TestReview:
    def test_thirty_days_past_due_brings_the_review_forward(self):
        found = verdict(drawn_exposure=BIG, current_dpd=45)
        assert found.priority == pr.REVIEW

    def test_breadth_across_independent_families(self):
        found = verdict(drawn_exposure=SMALL, cash=1.0, drawn=0,
                        debt_to_equity=9.0, current_dpd=0,
                        collateral_coverage_pct=10.0, watchlist_flag=True)
        assert found.priority in (pr.REVIEW, pr.ACT_NOW)

    def test_stage_two_that_is_getting_worse(self):
        first = {"borrower_id": "CORP-1", "drawn_exposure": SMALL,
                 "stage": 2, "debt_to_equity": 3.0}
        now = dict(first)
        now["debt_to_equity"] = 9.0
        found = sg.stand(now, first, period="Q2 2026",
                         previous_period="Q1 2026").verdict
        assert found.priority == pr.REVIEW


class TestMonitorAndRoutine:
    def test_something_firing_on_a_small_exposure_is_monitored(self):
        found = verdict(drawn_exposure=SMALL, revenue_growth=-4.0)
        assert found.priority == pr.MONITOR

    def test_a_quiet_borrower_is_routine(self):
        found = verdict(drawn_exposure=SMALL, stage=1, current_dpd=0)
        assert found.priority == pr.ROUTINE

    def test_a_routine_borrower_still_has_a_sentence(self):
        """A caller that prints only the reasons must have something to
        print."""
        found = verdict(drawn_exposure=SMALL, stage=1, current_dpd=0)
        assert found.because()
        assert found.because()[0] == found.means


class TestItIsExplainedNotScored:
    def test_there_is_no_score(self):
        payload = verdict(drawn_exposure=BIG, stage=3).to_dict()
        assert not any("score" in key for key in payload)

    def test_every_reason_is_a_sentence_not_a_field_name(self):
        found = verdict(drawn_exposure=BIG, stage=3, current_dpd=120,
                        breach_flag=True)
        for said in found.because():
            assert said.endswith(".") or said.endswith("?")
            assert " " in said
            assert "_" not in said, said

    def test_money_is_written_as_money(self):
        """R2 §3: never a bare monetary number."""
        found = verdict(drawn_exposure=412.5, current_dpd=120)
        assert any("SAR 412.5m" in s for s in found.because())

    def test_a_large_exposure_reads_in_billions(self):
        found = verdict(drawn_exposure=2400.0, current_dpd=120)
        assert any("SAR 2.4bn" in s for s in found.because())

    def test_the_rules_that_did_not_decide_it_are_still_published(self):
        """A reader who disagrees with the level can see everything that
        held, not only the rules at the top."""
        found = verdict(drawn_exposure=BIG, stage=3, current_dpd=120)
        levels = {r.level for r in found.reasons}
        assert pr.ACT_NOW in levels
        assert pr.MONITOR in levels

    def test_the_policy_names_its_owner_and_its_version(self):
        payload = verdict(drawn_exposure=BIG, stage=3).to_dict()
        assert payload["priority_owner"] == tx.THRESHOLD_OWNER
        assert payload["priority_version"] == pr.PRIORITY_VERSION


class TestTheOrdering:
    def test_a_material_problem_outranks_a_broad_but_small_one(self):
        """The exact pair the acceptance run got backwards."""
        big = sg.stand({"borrower_id": "CORP-BIG", "drawn_exposure": 412.5,
                        "current_dpd": 120, "breach_flag": True},
                       period="Q2 2026")
        broad = sg.stand({"borrower_id": "CORP-SMALL", "drawn_exposure": 3.0,
                          "financial_statement_age_days": 400,
                          "valuation_age_days": 900, "revenue_growth": -4.0,
                          "debt_to_equity": 9.0, "cash": 0.01,
                          "collateral_coverage_pct": 10.0},
                         period="Q2 2026")
        assert sg.rank([broad, big])[0].borrower_id == "CORP-BIG"

    def test_within_a_priority_the_larger_exposure_comes_first(self):
        a = sg.stand({"borrower_id": "CORP-A", "drawn_exposure": 500.0,
                      "current_dpd": 120}, period="Q2 2026")
        b = sg.stand({"borrower_id": "CORP-B", "drawn_exposure": 900.0,
                      "current_dpd": 120}, period="Q2 2026")
        assert [s.borrower_id for s in sg.rank([a, b])] == ["CORP-B", "CORP-A"]

    def test_the_order_is_total_and_repeatable(self):
        book = [sg.stand({"borrower_id": f"CORP-{n}", "drawn_exposure": 200.0,
                          "current_dpd": 120}, period="Q2 2026")
                for n in range(6)]
        once = [s.borrower_id for s in sg.rank(list(book))]
        again = [s.borrower_id for s in sg.rank(list(reversed(book)))]
        assert once == again

    def test_a_routine_borrower_sorts_below_everything(self):
        quiet = sg.stand({"borrower_id": "CORP-Q", "drawn_exposure": 9000.0,
                          "stage": 1}, period="Q2 2026")
        noisy = sg.stand({"borrower_id": "CORP-N", "drawn_exposure": 1.0,
                          "revenue_growth": -4.0}, period="Q2 2026")
        assert sg.rank([quiet, noisy])[0].borrower_id == "CORP-N"


class TestTheStandingPublishesIt:
    @pytest.mark.parametrize("key", [
        "priority", "priority_label", "priority_means", "priority_because",
        "priority_reasons", "priority_owner", "priority_version",
        "exposure", "material"])
    def test_the_screen_gets_what_it_needs(self, key):
        assert key in standing(drawn_exposure=BIG, stage=3).to_dict()

    def test_severity_is_still_published_beside_it(self):
        """They answer different questions and both are worth having."""
        payload = standing(drawn_exposure=BIG, stage=3).to_dict()
        assert payload["severity"] in tx.SEVERITIES
        assert payload["priority"] in pr.PRIORITIES

    def test_every_priority_has_a_label_and_a_meaning(self):
        for level in pr.PRIORITIES:
            assert pr.PRIORITY_LABEL[level]
            assert pr.PRIORITY_MEANS[level]

    def test_a_missing_exposure_is_not_treated_as_zero_risk(self):
        """A deployment that does not carry the amount must not silently
        decide everything is immaterial and therefore fine."""
        found = verdict(current_dpd=120)
        assert found.priority == pr.ACT_NOW
        assert found.exposure is None
        assert any("does not carry" in s for s in found.because())
