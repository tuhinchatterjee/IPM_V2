"""Why is this borrower High Risk? Sections 11E-11H.

The defect
----------
Overall risk was the number of signals firing, which is a fact about the RULE
BOOK rather than about the borrower. Six stale-valuation observations outranked
one covenant breach with thirty days past due, because six is more than three.

The first attempt at a fix replaced the count with eight rules and took the
worst of them. On the live book that made 88% of names High, because on a
stressed portfolio most of those rules hold for most borrowers most of the
time — breadth of two families is the MEDIAN. A High list holding seven names
in eight is not a list anybody works, so it is the same defect wearing better
prose.

What is tested here
-------------------
That gravity and corroboration are BOTH required and neither substitutes for
the other; that the framework can come back down; that the level is not a
function of how many signals fired; and that every level comes with sentences
naming the evidence rather than with a number.
"""

from __future__ import annotations

import pytest

from backend.early_warning import assessment as ea
from backend.early_warning import classifiers as cls
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

BIG = ea.MATERIAL_EXPOSURE * 4


def standing(previous=None, **row):
    row.setdefault("borrower_id", "CORP-1")
    return sg.stand(row, previous, period="Q2 2026",
                    previous_period="Q1 2026")


def assess(previous=None, **row):
    return ea.assess(standing(previous, **row))


def fired_keys(found: ea.Assessment) -> set[str]:
    return set(found.new) | set(found.persistent) | set(found.worsening) \
        | set(found.improving)


# ------------------------------------------------------------ the rule itself


class TestGravityAndCorroboration:
    """Section 11G. Both, or it is not High."""

    def test_a_quiet_borrower_is_low(self):
        found = assess(drawn_exposure=BIG, ead=BIG)
        assert found.level == ea.LOW
        assert found.primary_concern == "Nothing beyond routine observations."

    def test_a_severe_credit_event_alone_is_not_high(self):
        # A covenant breach on a name whose every other measure is within
        # threshold is a covenant breach: serious, and a conversation, not a
        # crisis. Escalating it to High is how the High list fills with names
        # nobody can act on.
        found = assess(ead=BIG, breach_flag=True)
        assert found.level == ea.MEDIUM
        assert any(r.rule == "not_corroborated" for r in found.reasons)

    def test_the_same_event_corroborated_is_high(self):
        found = assess(ead=BIG, breach_flag=True,
                       stage=2, sicr_flag=True,          # ifrs9
                       interest_coverage=1.2)            # leverage
        assert found.level == ea.HIGH
        assert any(r.rule == "severe_credit_event" for r in found.reasons)

    def test_corroboration_excludes_the_family_the_gravity_sits_in(self):
        # Two covenant conditions are one observation told twice. The rule
        # counts families OTHER than the one carrying the gravity, so a second
        # covenant signal cannot corroborate a covenant breach.
        found = assess(ead=BIG, breach_flag=True, minimum_headroom_pct=2.0)
        assert tx.COVENANT not in found.corroborating
        assert found.level == ea.MEDIUM

    def test_corroboration_without_gravity_is_not_high(self):
        # Five families of mild evidence and nothing established. This is the
        # exact shape the median borrower has, and calling it High is what
        # made 88% of the book High.
        found = assess(ead=BIG,
                       revenue_growth=-1.0,           # financial
                       interest_coverage=1.5,         # leverage
                       rating_change_notches=-1.0,    # rating
                       watchlist_flag=True,
                       network_risk_score=30.0)       # network
        assert len(found.families) >= ea.BREADTH_FAMILIES
        assert found.level != ea.HIGH

    def test_a_severe_condition_that_persisted_is_gravity(self):
        # One quarter is a reading; two is a direction. Leverage above 4x in
        # both periods, corroborated in liquidity and financial.
        previous = {"debt_to_equity": 5.0}
        found = assess(previous, ead=BIG, debt_to_equity=6.0,
                       cash=1.0, drawn_exposure=100.0,
                       revenue_growth=-3.0)
        assert any(r.rule == "severe_persistent" for r in found.reasons)
        assert found.level == ea.HIGH

    def test_the_same_severe_condition_new_is_not_yet_gravity(self):
        previous = {"debt_to_equity": 1.0}
        found = assess(previous, ead=BIG, debt_to_equity=6.0,
                       cash=1.0, drawn_exposure=100.0,
                       revenue_growth=-3.0)
        assert any(r.rule == "severe_new" for r in found.reasons)
        assert found.level == ea.MEDIUM


class TestItIsNotACount:
    """Section 11G's headline prohibition."""

    def test_many_mild_signals_do_not_beat_one_serious_one(self):
        many = assess(ead=BIG,
                      revenue_growth=-1.0, ebitda_margin=1.0,
                      interest_coverage=1.9, debt_to_equity=3.9,
                      rating_change_notches=-1.0, watchlist_flag=True,
                      network_risk_score=30.0, connected_group_size=20.0,
                      rating_outlook="Stable")
        serious = assess(ead=BIG, breach_flag=True, stage=2, sicr_flag=True,
                         interest_coverage=1.2)
        assert len(fired_keys(many)) > len(fired_keys(serious))
        assert ea.LEVEL_RANK[serious.level] > ea.LEVEL_RANK[many.level], (
            "the borrower with more signals outranked the one in breach, "
            "which is the defect this module exists to fix")

    def test_signal_count_is_named_as_something_not_used(self):
        excluded = {entry["input"] for entry in ea.describe()["not_used"]}
        assert "Signal count" in excluded

    def test_exposure_does_not_decide_the_level(self):
        # A small facility can be in as much trouble as a large one. Exposure
        # decides who reads the warning, not how serious it is.
        big = assess(ead=BIG, breach_flag=True, stage=2, sicr_flag=True,
                     interest_coverage=1.2)
        small = assess(ead=1.0, breach_flag=True, stage=2, sicr_flag=True,
                       interest_coverage=1.2)
        assert big.level == small.level == ea.HIGH


class TestItCanComeBackDown:
    """A framework that can only escalate is one nobody trusts."""

    def test_a_cured_warning_is_recorded_as_mitigating(self):
        # The field has to be PRESENT and false now. A field missing from the
        # current row is untested, not cured, and the two must not be confused.
        previous = {"watchlist_flag": True}
        found = assess(previous, ead=BIG, watchlist_flag=False)
        assert found.resolved
        assert any(r.rule == "resolved" for r in found.mitigating)

    def test_a_borrower_recovering_on_balance_comes_back_down(self):
        # Corroborated across families and one measure still drifting the
        # wrong way — which is a Medium — but three conditions have come back
        # within threshold since the last period. A name with one measure
        # drifting and three recovering is recovering.
        previous = {"watchlist_flag": True, "current_dpd": 5,
                    "rating_outlook": "Negative", "interest_coverage": 1.9,
                    "network_risk_score": 30.0}
        found = assess(previous, ead=BIG, watchlist_flag=False, current_dpd=0,
                       rating_outlook="Stable", interest_coverage=1.0,
                       network_risk_score=30.0, connected_group_size=20.0)
        assert found.worsening, "nothing is drifting, so nothing to come down"
        assert len(found.corroborating) >= ea.BREADTH_FAMILIES
        assert len(found.resolved) + len(found.improving) > len(found.worsening)
        assert found.level == ea.LOW
        assert any(r.rule == "mitigated" for r in found.mitigating)

    def test_it_does_not_come_down_while_more_is_worsening_than_healing(self):
        previous = {"watchlist_flag": True, "interest_coverage": 1.9,
                    "debt_to_equity": 3.0, "revenue_growth": 1.0}
        found = assess(previous, ead=BIG, watchlist_flag=False,
                       interest_coverage=1.0, debt_to_equity=3.9,
                       revenue_growth=-4.0)
        assert found.worsening
        assert not any(r.rule == "mitigated" for r in found.mitigating)

    def test_de_escalation_never_overrides_a_severe_condition(self):
        # The first version of this rule dropped a name carrying a two-notch
        # downgrade and a material collateral shortfall to Low because three
        # unrelated warnings had cured. Severe evidence is not cancelled by
        # unrelated good news.
        previous = {"watchlist_flag": True, "sicr_flag": True,
                    "rating_outlook": "Negative"}
        found = assess(previous, ead=BIG, watchlist_flag=False,
                       sicr_flag=False, rating_outlook="Stable",
                       rating_change_notches=-2.0,
                       collateral_shortfall=40.0, drawn_exposure=100.0)
        assert found.mitigating
        assert found.level != ea.LOW

    def test_improving_is_not_recorded_while_something_worsens(self):
        previous = {"debt_to_equity": 4.5, "interest_coverage": 1.5}
        found = assess(previous, ead=BIG, debt_to_equity=6.0,
                       interest_coverage=1.9)
        assert found.worsening
        assert not any(r.rule == "improving" for r in found.mitigating)


class TestTheEvidenceIsReadable:
    """Every level comes with sentences, never with a number."""

    def test_every_reason_is_a_sentence_naming_evidence(self):
        found = assess(ead=BIG, breach_flag=True, stage=2, sicr_flag=True,
                       interest_coverage=1.2)
        assert found.reasons
        for reason in found.reasons:
            assert reason.says.endswith((".", "?")), reason.says
            assert len(reason.says.split()) >= 5
            assert reason.rule and reason.pushes in ea.LEVELS

    def test_there_is_no_score(self):
        found = assess(ead=BIG, breach_flag=True).to_dict()
        for forbidden in ("score", "points", "weight", "weighted"):
            assert forbidden not in found, (
                f"the assessment publishes {forbidden!r}, which is a number "
                "nobody can argue with")

    def test_the_primary_concern_prefers_the_serious_event(self):
        found = assess(ead=BIG, breach_flag=True, watchlist_flag=True,
                       stage=2, sicr_flag=True)
        assert found.primary_concern == tx.BY_KEY["covenant_breached"].label

    def test_why_now_separates_new_from_merely_true(self):
        previous = {"breach_flag": True, "stage": 2, "sicr_flag": True,
                    "interest_coverage": 1.2}
        found = assess(previous, ead=BIG, breach_flag=True, stage=2,
                       sicr_flag=True, interest_coverage=1.2)
        assert "Nothing new" in found.why_now

    def test_the_family_labels_are_business_language(self):
        found = assess(ead=BIG, breach_flag=True, stage=2).to_dict()
        assert found["family_labels"]
        for label in found["family_labels"]:
            assert label and label[0].isupper()


# --------------------------------------------------------------- section 11H


class TestWarningStates:
    """Section 11H. What the BORROWER is doing, in credit language."""

    @pytest.mark.parametrize("state", ea.STATES)
    def test_every_state_says_which_periods_it_compares(self, state):
        means = ea.STATE_MEANS[state].lower()
        assert "observation period" in means, (
            f"{state!r} does not say which periods it is comparing, so a "
            "reader cannot tell what changed")

    def test_a_severe_condition_reads_as_high_concern(self):
        found = standing(ead=BIG, breach_flag=True)
        breach = next(o for o in found.fired
                      if o.signal == "covenant_breached")
        assert ea.state_of(breach) == ea.HIGH_CONCERN

    def test_a_cured_condition_reads_as_resolved(self):
        found = standing({"watchlist_flag": True}, ead=BIG,
                         watchlist_flag=False)
        cured = next(o for o in found.cured if o.signal == "on_watchlist")
        assert ea.state_of(cured) == ea.RESOLVED

    def test_a_condition_within_threshold_reads_as_healthy(self):
        observations = sg.evaluate({"ead": BIG, "revenue_growth": 5.0})
        within = next(o for o in observations
                      if o.signal == "revenue_fell" and not o.fired)
        assert ea.state_of(within) == ea.HEALTHY

    def test_the_states_are_distinct(self):
        assert len(set(ea.STATE_MEANS.values())) == len(ea.STATES)


# --------------------------------------------------------------- section 11E


class TestTacInTheAssessment:
    def test_credit_events_come_from_the_taxonomy_not_a_list(self):
        # A signal cannot be an event here and a threshold there.
        for key in ea.CREDIT_EVENTS:
            assert tx.BY_KEY[key].tac == tx.ACTION_BASED

    def test_grave_events_are_the_severe_subset(self):
        assert ea.GRAVE_EVENTS
        for key in ea.GRAVE_EVENTS:
            assert tx.BY_KEY[key].severity == tx.SEVERE

    def test_the_tac_split_is_published_per_borrower(self):
        found = assess(ead=BIG, breach_flag=True, stage=2, sicr_flag=True,
                       interest_coverage=1.2, cash=1.0, drawn_exposure=100.0)
        counts = found.tac_counts
        assert set(counts) == set(tx.TAC_TYPES)
        assert counts[tx.ACTION_BASED] >= 1

    def test_a_classifier_is_counted_as_a_pattern_not_as_signals(self):
        found = assess(ead=BIG, cash=1.0, drawn_exposure=100.0,
                       maturing_0_3m=200.0, minimum_headroom_pct=2.0)
        assert found.tac_counts[tx.CLASSIFIER_BASED] == sum(
            1 for m in found.patterns if m.fired)


class TestClassifiers:
    """Section 11E: do not claim a classifier exists if it is not configured."""

    def test_every_component_binds_to_a_governed_signal(self):
        assert cls.unknown_components() == ()

    def test_every_classifier_needs_more_than_one_component(self):
        for entry in cls.CLASSIFIERS:
            assert 2 <= entry.needs <= len(entry.signals), (
                f"{entry.key} fires on {entry.needs} of {len(entry.signals)}, "
                "which is not a pattern")

    def test_a_classifier_that_does_not_fire_says_nothing(self):
        for match in cls.classify(set()):
            assert not match.fired
            assert match.why() == ""

    def test_a_fired_classifier_names_what_matched(self):
        found = cls.fired_for({"cash_thin", "liquidity_buffer_thin",
                               "near_maturity_uncovered"})
        assert found
        for match in found:
            for key in match.matched:
                assert tx.BY_KEY[key].label in match.why()

    def test_untested_components_are_declared_rather_than_ignored(self):
        # A pattern resting partly on evidence this deployment cannot test is
        # reported as such. Silently not matching would read as an all-clear.
        entry = cls.BY_KEY["liquidity_stress"]
        matched = set(entry.signals[:entry.needs])
        found = cls.classify(matched, tested=matched)
        match = next(m for m in found if m.classifier.key == entry.key)
        assert match.untested
        assert "could not be tested" in match.why()


class TestTheMethodologyIsInspectable:
    def test_describe_states_both_halves_of_the_rule(self):
        rule = ea.describe()["rule"]
        assert "gravity" in rule and "corroboration" in rule
        assert "AND" in rule["high"]

    def test_every_level_has_a_meaning(self):
        for level in ea.LEVELS:
            assert ea.LEVEL_MEANS[level].endswith(".")

    def test_the_classifier_count_is_read_from_the_configuration(self):
        entry = next(e for e in ea.describe()["inputs"]
                     if e["input"] == "Recognised patterns")
        assert str(len(cls.CLASSIFIERS)) in entry["rule"]


# -------------------------------------------------- against the real book


class TestTheLiveBook:
    """The numbers this actually produces at Q2 2026.

    A rule that is defensible on four hand-made rows and puts 88% of a real
    book into High is not defensible. These assertions are deliberately loose
    — they are asking whether the distribution is credible, not pinning it.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def levels(cls):
        book = sg._book("")
        ranked = book.get("_ranked") or []
        assert ranked, "no borrowers to assess"
        counts = dict.fromkeys(ea.LEVELS, 0)
        for standing_ in ranked:
            counts[ea.assess(standing_).level] += 1
        return counts, len(ranked)

    def test_high_risk_is_a_minority_of_the_book(self, levels):
        counts, total = levels
        share = counts[ea.HIGH] / total
        assert share < 0.40, (
            f"{share:.0%} of the book is High Risk, which is a list nobody "
            "works down")

    def test_high_risk_is_not_empty_either(self, levels):
        # This book carries covenant breaches, arrears and stage 3 exposures.
        # A framework that finds nothing serious in it is miscalibrated the
        # other way.
        counts, _ = levels
        assert counts[ea.HIGH] > 0

    def test_every_level_is_populated(self, levels):
        counts, _ = levels
        for level in ea.LEVELS:
            assert counts[level] > 0, f"no borrower is {level}"

    def test_every_high_risk_borrower_can_say_why(self):
        book = sg._book("")
        checked = 0
        for standing_ in (book.get("_ranked") or [])[:200]:
            found = ea.assess(standing_)
            if found.level != ea.HIGH:
                continue
            checked += 1
            assert found.because(), f"{standing_.borrower_id} is High in silence"
            assert found.corroborating, (
                f"{standing_.borrower_id} is High without corroboration")
        assert checked, "no High Risk borrower in the first two hundred"

    def test_the_dashboard_publishes_the_split(self):
        found = sg.dashboard("")["risk_levels"]
        assert {entry["level"] for entry in found["levels"]} == set(ea.LEVELS)
        assert sum(entry["borrowers"] for entry in found["levels"]) > 0
        assert "never by how many signals fired" in found["statement"]
