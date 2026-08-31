"""The governed early-warning taxonomy, held to what §19-§25 asked for.

Every assertion here is about a PROPERTY rather than a value, because the
values are synthetic and will change the next time the book is regenerated.
"How many borrowers show covenant pressure" is a fact about a fixture; "no
signal fires for every borrower" is a fact about whether the taxonomy carries
information, and only the second is worth a test.

The one thing this suite refuses hardest
-----------------------------------------
A score. §19: Early Warning "is NOT one opaque score". §25: "Do not introduce
arbitrary weighted black-box scores." A borrower's standing is a set of counts
a person can check, and if a weighted composite ever appears it has to arrive
with an owner, a methodology, a version and a validation — so a test that
fails the moment one appears without them is the cheapest way to keep that
true.
"""

from __future__ import annotations

import pytest

from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

# ------------------------------------------------------------ the taxonomy


class TestTheTaxonomyIsGoverned:

    def test_every_family_in_section_twenty_is_present(self):
        for family in (tx.FINANCIAL, tx.LEVERAGE, tx.LIQUIDITY,
                       tx.BEHAVIOURAL, tx.COVENANT, tx.COLLATERAL,
                       tx.RATING, tx.IFRS9):
            assert family in tx.FAMILIES
            assert tx.FAMILY_MEANS.get(family), f"{family} has no meaning"
            assert tx.in_family(family), f"{family} has no signals"

    @pytest.mark.parametrize("signal", tx.SIGNALS, ids=lambda s: s.key)
    def test_every_signal_is_bound_to_a_real_governed_field(self, signal):
        """A signal over a field that does not exist never fires, and a
        watchlist that is quietly incomplete is the worst failure this module
        can have."""
        from backend.data_access.catalog import get_catalog

        dataset = get_catalog().dataset(signal.dataset)
        for column in signal.columns:
            assert column in dataset.fields, (
                f"{signal.key} reads {signal.dataset}.{column}, which the "
                "catalogue does not publish")

    @pytest.mark.parametrize("signal", tx.SIGNALS, ids=lambda s: s.key)
    def test_every_signal_carries_its_governance(self, signal):
        payload = signal.to_dict()
        assert payload["owner"] == tx.THRESHOLD_OWNER
        assert payload["version"]
        assert payload["family"] in tx.FAMILIES
        assert payload["severity"] in tx.SEVERITIES
        assert payload["test"] in tx.TESTS
        assert payload["means"], "a signal nobody can read is a signal nobody acts on"
        assert payload["sentence"]

    @pytest.mark.parametrize("signal", tx.SIGNALS, ids=lambda s: s.key)
    def test_a_threshold_test_has_a_threshold(self, signal):
        if signal.test in (tx.TRUE, tx.CHANGED):
            return
        assert signal.threshold is not None, (
            f"{signal.key} tests {signal.test} against nothing")

    @pytest.mark.parametrize("signal", tx.SIGNALS, ids=lambda s: s.key)
    def test_a_movement_over_two_fields_names_both(self, signal):
        if signal.test in (tx.RATIO_ABOVE, tx.RATIO_ROSE_BY):
            assert signal.against, f"{signal.key} is a ratio with one field"

    def test_signal_keys_are_unique(self):
        keys = [s.key for s in tx.SIGNALS]
        assert len(keys) == len(set(keys))

    def test_the_ifrs9_family_marks_what_is_booked(self):
        """§20: never describe an early-warning prediction as an accounting
        stage classification. The only way to keep that straight in prose is
        to keep it straight in the data."""
        booked = {s.key for s in tx.in_family(tx.IFRS9) if s.booked_accounting}
        assert "stage_2" in booked
        assert "stage_3" in booked
        for signal in tx.SIGNALS:
            if signal.family != tx.IFRS9:
                assert not signal.booked_accounting, (
                    f"{signal.key} claims to be a booked accounting position")

    def test_what_cannot_be_watched_for_is_stated(self):
        """§7. An absent measure is a stated absence."""
        absent = tx.unavailable()
        assert absent
        for entry in absent:
            assert entry["family"] in tx.FAMILIES
            assert len(entry["means"]) > 20, "an absence with no reason"

    def test_the_description_is_whole(self):
        described = tx.describe()
        assert described["signal_count"] == len(tx.SIGNALS)
        assert len(described["families"]) == len(tx.FAMILIES)
        assert described["owner"] == tx.THRESHOLD_OWNER


# ------------------------------------------------------------ the evaluation


ROW = {
    "borrower_id": "CORP-1", "period": "Q2 2026",
    "revenue_growth": -5.0, "ebitda_margin": 10.0,
    "cash_flow_from_operations": 5.0, "free_cash_flow": -1.0,
    "cash": 2.0, "debt_to_equity": 5.0, "interest_coverage": 1.5,
    "drawn_exposure": 95.0, "total_limit": 100.0,
    "undrawn_commitment": 5.0, "single_name_utilisation_pct": 1.0,
    "current_dpd": 45, "max_dpd_12m": 45, "forbearance_flag": False,
    "breach_flag": True, "minimum_headroom_pct": 5.0,
    "average_headroom_pct": 20.0, "financial_statement_age_days": 200,
    "collateral_coverage_pct": 40.0, "collateral_shortfall": 50.0,
    "valuation_age_days": 400, "rating_change_notches": -1.0,
    "rating_override_flag": False, "watchlist_flag": True,
    "stage": 2, "pd_12m": 5.0, "ecl_coverage": 2.0, "sicr_flag": True,
}


class TestEvaluation:

    def test_every_signal_produces_an_observation(self):
        """Fired or not, available or not. A caller wanting only what fired
        filters; a caller wanting to know what was CHECKED has the answer
        without asking twice."""
        found = sg.evaluate(ROW, {}, period="Q2 2026")
        assert len(found) == len(tx.SIGNALS)
        assert {o.signal for o in found} == {s.key for s in tx.SIGNALS}

    @pytest.mark.parametrize("key,expected", [
        ("revenue_fell", True), ("interest_cover_weak", True),
        ("leverage_high", True), ("in_arrears", True), ("arrears_30", True),
        ("covenant_breached", True), ("covenant_headroom_tight", True),
        ("collateral_thin", True), ("collateral_shortfall", True),
        ("valuation_stale", False), ("rating_downgraded", True),
        ("on_watchlist", True), ("stage_2", True), ("sicr_flagged", True),
        ("utilisation_high", True), ("undrawn_thin", True),
        ("stage_3", False), ("restructured", False),
        ("rating_stale", False), ("large_exposure", False),
        ("cash_flow_negative", False),
    ])
    def test_a_signal_fires_when_its_condition_holds(self, key, expected):
        found = {o.signal: o for o in sg.evaluate(ROW, {}, period="Q2 2026")}
        assert found[key].fired is expected, found[key].to_dict()

    def test_a_missing_field_is_untested_rather_than_not_fired(self):
        """§7. "It did not fire" and "it could not be checked" are different
        answers, and only one of them is reassuring."""
        sparse = {"borrower_id": "CORP-2", "stage": 1}
        found = {o.signal: o for o in sg.evaluate(sparse, {})}
        assert found["collateral_thin"].unavailable
        assert found["collateral_thin"].lifecycle == sg.UNAVAILABLE
        assert found["collateral_thin"].fired is False
        assert "collateral_coverage_pct" in found["collateral_thin"].unavailable

    def test_a_movement_test_with_no_prior_period_is_untested(self):
        found = {o.signal: o for o in sg.evaluate(ROW, {})}
        assert found["ebitda_margin_fell"].unavailable
        assert "prior reporting date" in found["ebitda_margin_fell"].unavailable

    def test_an_observation_carries_everything_needed_to_defend_it(self):
        """§23's governed signal object."""
        found = {o.signal: o for o in sg.evaluate(ROW, {}, period="Q2 2026")}
        payload = found["covenant_headroom_tight"].to_dict()
        for key in ("signal", "family", "label", "fired", "lifecycle",
                    "severity", "value", "threshold", "threshold_version",
                    "threshold_owner", "dataset", "field", "test", "period",
                    "means"):
            assert key in payload, key
        assert payload["value"] == 5.0
        assert payload["threshold"] == 10.0
        assert payload["threshold_owner"] == tx.THRESHOLD_OWNER

    def test_a_ratio_signal_reports_the_ratio_not_the_numerator(self):
        found = {o.signal: o for o in sg.evaluate(ROW, {}, period="Q2 2026")}
        assert found["utilisation_high"].value == pytest.approx(95.0)


class TestLifecycle:
    """§24: one-period noise, persistent deterioration, acceleration, recovery."""

    def test_a_condition_not_present_before_is_new(self):
        before = {**ROW, "current_dpd": 0, "max_dpd_12m": 0}
        found = {o.signal: o for o in sg.evaluate(ROW, before)}
        assert found["in_arrears"].lifecycle == sg.NEW

    def test_a_condition_present_before_at_the_same_level_is_persisting(self):
        found = {o.signal: o for o in sg.evaluate(ROW, dict(ROW))}
        assert found["covenant_headroom_tight"].lifecycle == sg.PERSISTING

    def test_a_condition_that_has_moved_further_the_wrong_way_is_worsening(self):
        before = {**ROW, "minimum_headroom_pct": 9.0}
        found = {o.signal: o for o in sg.evaluate(ROW, before)}
        assert found["covenant_headroom_tight"].lifecycle == sg.WORSENING

    def test_a_condition_moving_back_towards_the_threshold_is_improving(self):
        before = {**ROW, "minimum_headroom_pct": 1.0}
        found = {o.signal: o for o in sg.evaluate(ROW, before)}
        assert found["covenant_headroom_tight"].lifecycle == sg.IMPROVING

    def test_a_condition_that_has_stopped_firing_is_cured(self):
        now = {**ROW, "breach_flag": False}
        found = {o.signal: o for o in sg.evaluate(now, ROW)}
        assert found["covenant_breached"].lifecycle == sg.CURED
        assert found["covenant_breached"].fired is False

    def test_a_movement_too_small_to_see_is_not_a_movement(self):
        """Without this, every signal on a continuous measure reports
        WORSENING or IMPROVING every quarter and the lifecycle stops carrying
        information."""
        # The threshold is 10; MATERIAL_MOVE is 5% of it, so a move of
        # 0.01 is well inside the noise floor.
        before = {**ROW, "minimum_headroom_pct": 5.01}
        found = {o.signal: o for o in sg.evaluate(ROW, before)}
        assert found["covenant_headroom_tight"].lifecycle == sg.PERSISTING

    @pytest.mark.parametrize("state", sg.LIFECYCLE)
    def test_every_lifecycle_state_says_what_it_means(self, state):
        assert len(sg.LIFECYCLE_MEANS.get(state, "")) > 20


class TestTheCompositeIsNotAScore:
    """§25, and the assertion this whole module exists to make possible."""

    def test_there_is_no_score_anywhere_in_the_result(self):
        standing = sg.stand(ROW, dict(ROW), period="Q2 2026")
        payload = standing.to_dict()
        for key in payload:
            assert "score" not in key.lower(), (
                f"a score appeared as {key!r}. §25 permits weights only with "
                "an owner, a methodology, a version and a validation.")

    def test_it_reports_the_six_measures_section_twenty_five_names(self):
        standing = sg.stand(ROW, dict(ROW), period="Q2 2026")
        payload = standing.to_dict()
        for key in ("breadth", "severity", "persistence", "worsening",
                    "agreement", "conflict"):
            assert key in payload, key

    def test_breadth_counts_families_not_signals(self):
        """Five liquidity conditions firing off one utilisation number is one
        fact told five ways. Counting it as five is the inflation a weighted
        score would also produce."""
        standing = sg.stand(ROW, {}, period="Q2 2026")
        assert standing.breadth == len({o.family for o in standing.fired})
        assert standing.breadth <= len(standing.fired)

    def test_severity_is_the_worst_that_fired_not_an_average(self):
        standing = sg.stand(ROW, {}, period="Q2 2026")
        worst = max((tx.SEVERITY_RANK[o.severity] for o in standing.fired),
                    default=0)
        assert tx.SEVERITY_RANK[standing.severity] == worst

    def test_contradictory_evidence_is_reported_rather_than_netted(self):
        """§26. A borrower with four deteriorating signals and two improving
        ones is a different situation from one with four and none."""
        now = {**ROW, "breach_flag": False}
        standing = sg.stand(now, ROW, period="Q2 2026")
        assert tx.COVENANT in standing.conflict
        assert standing.cured

    def test_the_booked_accounting_position_stays_separable(self):
        standing = sg.stand(ROW, {}, period="Q2 2026")
        assert "stage_2" in standing.booked_stage
        assert "in_arrears" not in standing.booked_stage

    def test_the_sentence_names_the_evidence_rather_than_a_number(self):
        standing = sg.stand(ROW, {}, period="Q2 2026")
        said = standing.sentence()
        assert "families" in said or "family" in said
        assert "governed signal" in said

    def test_a_borrower_with_nothing_firing_says_so(self):
        clean = {"borrower_id": "CORP-3", "period": "Q2 2026",
                 "stage": 1, "breach_flag": False, "watchlist_flag": False}
        standing = sg.stand(clean, {}, period="Q2 2026")
        assert standing.fired == []
        assert "No governed early-warning signal fires" in standing.sentence()


class TestTheRankingIsTotal:

    def _standings(self, count=40):
        out = []
        for index in range(count):
            row = dict(ROW)
            row["borrower_id"] = f"CORP-{index:03d}"
            row["current_dpd"] = 45 if index % 2 else 0
            row["max_dpd_12m"] = 45 if index % 2 else 0
            row["breach_flag"] = bool(index % 3)
            out.append(sg.stand(row, {}, borrower_id=row["borrower_id"],
                                period="Q2 2026"))
        return out

    def test_the_same_input_ranks_the_same_way_twice(self):
        standings = self._standings()
        first = [s.borrower_id for s in sg.rank(list(standings))]
        second = [s.borrower_id for s in sg.rank(list(reversed(standings)))]
        assert first == second

    def test_breadth_leads_the_ordering(self):
        ranked = sg.rank(self._standings())
        breadths = [s.breadth for s in ranked]
        assert breadths == sorted(breadths, reverse=True)

    def test_ties_are_broken_by_the_borrower_id(self):
        ranked = sg.rank(self._standings())
        for one, two in zip(ranked, ranked[1:], strict=False):
            same = (one.breadth == two.breadth
                    and one.severity == two.severity
                    and one.persistence == two.persistence
                    and one.worsening == two.worsening)
            if same:
                assert one.borrower_id <= two.borrower_id


class TestPeriodOrdering:
    """A string sort of quarter labels put Q4 2025 after Q2 2026."""

    @pytest.mark.parametrize("earlier,later", [
        ("Q4 2025", "Q1 2026"), ("Q1 2026", "Q2 2026"),
        ("Q4 2024", "Q1 2025"), ("Q3 2023", "Q4 2023"),
    ])
    def test_periods_order_chronologically_not_alphabetically(
            self, earlier, later):
        assert sg._period_key(earlier) < sg._period_key(later)

    def test_the_alphabetical_order_would_have_been_wrong(self):
        """The bug, stated. Without the key, this pair sorts backwards."""
        assert "Q4 2025" > "Q2 2026"          # what a string sort does
        assert sg._period_key("Q4 2025") < sg._period_key("Q2 2026")
