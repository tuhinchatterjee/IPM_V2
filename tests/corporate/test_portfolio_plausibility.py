"""Is this a book a credit officer would recognise?

R2 §24 asked for the portfolio generator to be recalibrated and for
plausibility tests to hold it there — "do not make everything healthy". Four
things it named were wrong, and each is asserted here from BOTH ends:

* **The sector mix.** Financial Services carried 3% of the book and was
  nonetheless the headline story the AI reached for. Two sectors a Gulf
  corporate bank cannot be without — Oil & Gas and Shipping — did not exist at
  all, and the external-intelligence domain was publishing shipping events
  against a sector no borrower belonged to.
* **The covenant book.** A third of borrowers were in breach of something,
  because thresholds were anchored to a 2022 statement and never reset. A bank
  whose covenants are breached by a third of its book is not a bank with a
  covenant problem, it is a bank with a covenant policy that does not work.
* **Delinquency.** Every defaulted borrower was floored at exactly 91 days, so
  eighty-eight names shared that value — more than held any other number above
  ninety.
* **The stage distribution.** Stage 2 has to mean something, so it needs to be
  neither empty nor half the book, and it must be concentrated where the risk
  is rather than spread evenly or, worse, inverted.

Bands, not point values. A generator asserted to two decimal places is a
generator nobody can ever tune again; a generator asserted only from below is
one that passes by making everything healthy.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend import scenarios
from backend.corporate.universe import SECTORS


@pytest.fixture(scope="module")
def latest(snapshot):
    """The most recent quarter, which is what every screen opens on."""
    period = sorted(snapshot["period"].unique(),
                    key=lambda p: (p.split()[-1], p.split()[0]))[-1]
    return snapshot.loc[snapshot["period"] == period]


class TestTheSectorMix:
    def test_every_declared_sector_has_borrowers_in_it(self, latest):
        present = set(latest["sector"].unique())
        assert {s.name for s in SECTORS} <= present

    def test_the_two_missing_gulf_sectors_are_now_material(self, latest):
        """Oil & Gas and Shipping, without which this is not a Gulf book."""
        share = latest["sector"].value_counts(normalize=True)
        assert share["Oil & Gas"] > 0.03
        assert share["Shipping"] > 0.02

    def test_financial_services_is_a_line_not_a_rounding(self, latest):
        """3% was too small to be anybody's headline story."""
        share = latest["sector"].value_counts(normalize=True)
        assert 0.04 <= share["Financial Services"] <= 0.12

    def test_no_sector_dominates_the_book(self, latest):
        share = latest["sector"].value_counts(normalize=True)
        assert share.max() <= 0.16, share.head(3).to_dict()

    def test_the_mix_is_not_flat_either(self, latest):
        """A bank concentrates. Equal weights would be a different defect."""
        share = latest["sector"].value_counts(normalize=True)
        assert share.max() / share.min() >= 2.5


class TestTheStageDistribution:
    def test_stage_one_is_most_but_not_all_of_the_book(self, latest):
        share = latest["stage"].value_counts(normalize=True)
        assert 0.68 <= share.get(1, 0.0) <= 0.92

    def test_stage_two_is_neither_empty_nor_half_the_book(self, latest):
        share = latest["stage"].value_counts(normalize=True)
        assert 0.05 <= share.get(2, 0.0) <= 0.20

    def test_stage_three_is_a_real_but_small_population(self, latest):
        share = latest["stage"].value_counts(normalize=True)
        assert 0.005 <= share.get(3, 0.0) <= 0.09

    def test_stage_two_is_not_inverted_across_sectors(self, latest):
        """The defect this test exists for.

        The core book's three-notch SICR trigger had no grade floor, so it
        fired hardest on the STRONGEST sectors: a grade-1 borrower drifting to
        grade 4 tripped it while a grade-8 one could not fall three notches at
        all. Education and Healthcare came out with more Stage 2 than
        Contracting, which is backwards, and a sector answer built on it would
        have sent an officer to the wrong names.
        """
        quality = {s.name: s.quality for s in SECTORS}
        rate = (latest.assign(two=latest["stage"] == 2)
                .groupby("sector")["two"].mean())
        ranked = sorted(rate.index, key=lambda name: quality[name])
        weakest = rate[ranked[:4]].mean()
        strongest = rate[ranked[-4:]].mean()
        assert weakest > strongest * 1.5, {
            "weakest": ranked[:4], "rate": round(float(weakest), 3),
            "strongest": ranked[-4:], "their rate": round(float(strongest), 3)}

    def test_some_sector_is_bad_enough_to_be_worth_a_question(self, latest):
        """"Do not make everything healthy." There has to be a story."""
        rate = (latest.assign(two=latest["stage"] == 2)
                .groupby("sector")["two"].mean())
        assert rate.max() >= 0.15


class TestTheCovenantBook:
    def test_breaches_are_a_minority_of_the_book(self, latest):
        """The one-third artefact. Thresholds now reset at annual review."""
        breached = (latest["covenants_breached"] > 0).mean()
        assert breached <= 0.15, round(float(breached), 3)

    def test_but_breaches_do_happen(self, latest):
        breached = (latest["covenants_breached"] > 0).mean()
        assert breached >= 0.015, round(float(breached), 3)

    def test_a_borrower_is_not_tested_on_everything(self, latest):
        """"Covenants tested" has to be a fact, not a constant."""
        tested = latest["covenants_tested"]
        assert tested.nunique() > 1
        assert tested.max() <= len(SECTORS)

    def test_a_breach_never_exceeds_the_tests_that_were_run(self, latest):
        assert (latest["covenants_breached"]
                <= latest["covenants_tested"]).all()


class TestDelinquency:
    def test_most_of_the_book_is_current(self, latest):
        assert (latest["current_dpd"] > 0).mean() <= 0.25

    def test_but_arrears_exist(self, latest):
        assert (latest["current_dpd"] > 0).mean() >= 0.02

    def test_no_single_arrears_value_is_a_spike(self, latest):
        """The 91-day artefact: every defaulted borrower floored at the same
        number, which put more names on 91 than on any other value above
        ninety. The floor is drawn now, so the distribution is a distribution.
        """
        deep = latest.loc[latest["current_dpd"] >= 90, "current_dpd"]
        assert deep.size >= 20, "need a population to say anything about it"
        counts = np.bincount(deep.to_numpy())
        assert counts.max() / deep.size <= 0.20, (
            f"{counts.argmax()} days holds {counts.max()} of {deep.size}")

    def test_arrears_do_not_run_past_a_workout_horizon(self, latest):
        assert latest["current_dpd"].max() <= 640


class TestTheShippingScenario:
    """R2 §8 and §26. "Why did Shipping deteriorate this quarter?" has to have
    an answer in the data, or the external-intelligence events beside it are
    an invitation to invent one."""

    @staticmethod
    def _rate(snapshot, sector, period):
        part = snapshot.loc[(snapshot["sector"] == sector)
                            & (snapshot["period"] == period)]
        return float((part["stage"] == 2).mean()), len(part)

    @pytest.fixture(scope="class")
    @classmethod
    def window(cls, snapshot):
        periods = sorted(snapshot["period"].unique(),
                         key=lambda p: (p.split()[-1], p.split()[0]))
        return periods[-len(scenarios.RAMP) - 1], periods[-1]

    def test_shipping_deteriorated_over_the_scenario_window(
            self, snapshot, window):
        before, after = window
        was, _ = self._rate(snapshot, "Shipping", before)
        now, count = self._rate(snapshot, "Shipping", after)
        assert count >= 80, "too few names to call it a sector story"
        assert now > was + 0.05, (was, now)

    def test_an_unaffected_sector_did_not(self, snapshot, window):
        """So the story is about Shipping and not about the quarter."""
        before, after = window
        assert "Healthcare" not in scenarios.SECTOR_IMPACT
        was, _ = self._rate(snapshot, "Healthcare", before)
        now, _ = self._rate(snapshot, "Healthcare", after)
        assert now < was + 0.05, (was, now)

    def test_shipping_is_worse_than_the_sectors_it_touches(
            self, snapshot, window):
        """The transmission has an order: the carrier before the cargo."""
        _, after = window
        shipping, _ = self._rate(snapshot, "Shipping", after)
        secondary, _ = self._rate(snapshot, "Transport & Logistics", after)
        assert shipping > secondary

    def test_the_scenario_does_not_reach_sectors_it_should_not(self):
        """A scenario that touches everything explains nothing."""
        touched = set(scenarios.SECTOR_IMPACT)
        assert touched < {s.name for s in SECTORS}
        assert len(touched) <= len(SECTORS) // 2
