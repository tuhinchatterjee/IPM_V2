"""
The Arab National Bank card demonstration: the finding, and the five answers.

These are acceptance gates for a LIVE DEMONSTRATION, so they check the two
things a demonstration actually fails on.

The first is severity. A movement that is real but subtle is invisible in a
room: the presenter says a bucket doubled and the audience sees a flat line
with a bend in it. So the gates below assert the calibration targets the
demonstration was built to — the size of the migration, its concentration in
one sub-bucket, the behavioural-band shift, the utilisation move and the
programme concentration — and they assert them on the SHIPPED book, because a
target met only in a fixture is not met.

The second is coherence. Every figure in this story is quoted at least twice:
on the card, in the drawer, and again in an answer three questions later. A
demonstration where the card says the bucket doubled and the third answer
implies it rose by a third is worse than one that shows nothing, because the
audience cannot tell which figure is wrong and has to assume both might be. So
the gates trace the same numbers through every surface that shows them and
require them to be identical rather than close.

Nothing here asserts a hard-coded figure from the specification. The targets
are ranges and relationships, because the book is regenerated from a seed and a
test that pins a decimal fails the first time anybody improves the generator —
and passes forever if the story quietly stops being true.

Every figure the demonstration shows is SYNTHETIC. Alpha Card is a
demonstration product.
"""

from __future__ import annotations

import pytest

from backend.retail import anb_answers as answers
from backend.retail import anb_demo as anb
from backend.retail import taxonomy as tax


@pytest.fixture(scope="module")
def book(retail_book):
    """Point the demo reader at the shipped lake for the whole module."""
    import backend.retail.anb_demo as module

    original = module._analytics_dir
    module._analytics_dir = lambda: str(retail_book.analytics_dir)
    anb.reset_cache()
    yield retail_book
    module._analytics_dir = original
    anb.reset_cache()


# ------------------------------------------------------ the data is there

class TestTheBookSupportsTheStory:

    def test_alpha_card_is_one_programme_among_several(self, book):
        latest = book.month(book.months()[-1],
                            ["product_code", "product_subsegment"])
        cards = latest[latest.product_code == "CREDIT_CARD"]
        found = set(cards.product_subsegment.dropna().unique())
        assert "ALPHA" in found, "Alpha Card is not in the book"
        assert found <= set(tax.CARD_PROGRAMMES), f"unknown programmes: {found}"
        assert len(found) >= 3, (
            "Alpha Card is the whole card book. It is meant to be one "
            "proposition inside it, not a rename of the product.")
        share = (cards.product_subsegment == "ALPHA").mean()
        assert 0.15 <= share <= 0.35, (
            f"Alpha Card is {share:.0%} of card accounts. Outside 15-35% it is "
            "either too small to carry the finding or too large for the "
            "finding to be a concentration.")

    def test_no_other_product_gained_a_card_programme(self, book):
        latest = book.month(book.months()[-1],
                            ["product_code", "product_subsegment"])
        others = latest[latest.product_code != "CREDIT_CARD"]
        leaked = set(others.product_subsegment.dropna().unique()) & set(
            tax.CARD_PROGRAMMES)
        assert not leaked, f"card programmes leaked onto other products: {leaked}"

    def test_origination_bands_are_fixed_at_origination(self, book):
        """A band that moves is not a band, it is a behavioural measure."""
        months = book.months()
        early = book.month(months[-4], ["facility_id", "origination_score_band"])
        late = book.month(months[-1], ["facility_id", "origination_score_band"])
        both = early.merge(late, on="facility_id", suffixes=("_a", "_b"))
        moved = (both.origination_score_band_a.fillna("")
                 != both.origination_score_band_b.fillna("")).sum()
        assert moved == 0, f"{moved} accounts changed origination band"

    def test_the_baseline_months_are_quiet(self, book):
        """Four or five boring periods, then a break. Not a slow ramp."""
        trend = anb.bucket_trend()
        early = [float(r["1-29 DPD"]) for r in trend["rows"][:-1]]
        spread = max(early) - min(early)
        assert spread < 3.0, (
            f"the months before the break move by {spread:.1f} points between "
            "themselves. A baseline that wanders gives the audience nothing to "
            "read the break against.")


# ------------------------------------------- the finding, and its severity

class TestTheFinding:

    def test_a_case_is_raised_and_it_is_not_about_defaults(self, book):
        from backend.retail import review

        draft = review._early_delinquency(anb.latest_month())
        assert draft is not None, "no early-delinquency case was raised"
        assert "1-29" in draft.title
        for forbidden in ("default rate", "increased default", "defaults"):
            assert forbidden not in draft.title.lower(), (
                f"the card title says {forbidden!r}. This finding is a "
                "population migration, and calling it a default problem is the "
                "one thing the specification forbids.")
        from backend.agentic import severity as sv

        assert sv.ORDER[draft.score.band] >= sv.ORDER[sv.HIGH], (
            f"the card is {draft.score.band} severity. A near-doubling of the "
            "early bucket that nobody notices in the list is a finding the "
            "presenter has to go looking for.")

    def test_the_early_bucket_roughly_doubles(self, book):
        found = anb.early_delinquency()
        early = found["early"]
        assert found["baseline_multiple"] >= 1.8, (
            f"1-29 DPD is {found['baseline_multiple']:.2f}x its baseline. The "
            "demonstration needs roughly a doubling.")
        assert early.change >= 5.0, (
            f"1-29 DPD rose {early.change:.2f} points. Below five the audience "
            "reads it as noise.")

    def test_the_current_population_fell_by_a_matching_amount(self, book):
        found = anb.early_delinquency()
        rise, fall = found["early"].change, -found["current"].change
        assert fall >= rise * 0.7, (
            f"1-29 rose {rise:.2f} points but 0 DPD only fell {fall:.2f}. "
            "Without a matching fall this is a book that grew, not a migration.")

    def test_the_later_buckets_did_not_move(self, book):
        found = anb.early_delinquency()
        for move in found["later"]:
            assert abs(move.change) < 1.5, (
                f"{move.label} moved {move.change:+.2f} points. The finding is "
                "that later delinquency has NOT moved with the early bucket.")

    def test_the_case_says_which_way_it_weighted_the_ladder(self, book):
        """Two cards about one product must not read as contradicting each other.

        The portfolio review also raises a deterioration case on the card book,
        and that one weights the delinquency ladder by BALANCE. On a book whose
        balances are growing — which this one's are, because the cohort is
        drawing down its limits — the two measures diverge: the 30+ population
        is flat while the 30+ share of balance climbs.

        Both are right. Side by side on a Cockpit with nothing to distinguish
        them, one of them reads as wrong. So this case states which quantity it
        counted and why the other one moved.
        """
        from backend.retail import review

        found = anb.early_delinquency()
        weighted = found["later_by_balance"]
        balances = found["balances"]
        if weighted.change <= 0.2 or balances.now <= balances.before:
            pytest.skip("the two measures agree on this book; nothing to explain")

        draft = review._early_delinquency(anb.latest_month())
        text = draft.conclusion.lower()
        assert "balance" in text, (
            "the case claims later delinquency is flat and does not mention "
            "that the balance-weighted measure moved. The deterioration case "
            "beside it says exactly that, and the reader has to decide which "
            "of the two is lying.")
        assert "customer" in text or "account" in text, (
            "the case does not say which quantity its own figures count")

    def test_the_drawer_chart_travels_on_the_case(self, book):
        from backend.retail import review

        draft = review._early_delinquency(anb.latest_month())
        chart = draft.evidence.get("chart") or {}
        assert chart.get("rows"), "the case carries no chart for the drawer"
        assert len(chart["rows"]) >= 6, "too few months to show a baseline"
        assert "0 DPD" in chart["series"]
        assert "0 DPD" not in chart["focus"], (
            "0 DPD is in the drawn series. At roughly 85% it flattens every "
            "bucket the case is about onto the floor of the axis.")


# ------------------------------------------------- question 1: the split

class TestTheSplit:

    def test_the_deterioration_is_in_the_last_ten_days(self, book):
        found = anb.sub_bucket_trend()
        focus = found["focus"]
        assert found["focus_share_of_early"] > 50.0, (
            f"20-29 DPD is {found['focus_share_of_early']:.0f}% of the 1-29 "
            "population. The story is that it dominates it.")
        assert focus["baseline_multiple"] >= 3.0, (
            f"20-29 DPD is {focus['baseline_multiple']:.1f}x its baseline.")

    def test_the_first_two_weeks_barely_moved(self, book):
        found = anb.sub_bucket_trend()
        for entry in found["moves"]:
            if entry["move"].label == anb.FOCUS:
                continue
            assert entry["baseline_multiple"] < 2.0, (
                f"{entry['move'].label} is {entry['baseline_multiple']:.1f}x its "
                "baseline. If every sub-bucket moves, the split proves nothing.")

    def test_the_sub_buckets_add_up_to_the_early_bucket(self, book):
        """The split and the card are readings of one book, not two."""
        split = anb.sub_bucket_trend()
        ladder = anb.early_delinquency()
        assert split["early_now"] == pytest.approx(ladder["early"].now, abs=0.05)


# --------------------------------------------- question 2: the score move

class TestTheBehaviouralMove:

    def test_the_cohort_is_large_enough_to_mean_something(self, book):
        found = anb.behaviour_distribution()
        assert found["cohort"] >= 200, (
            f"{found['cohort']} accounts. A distribution over a handful of "
            "customers is not evidence of anything.")
        assert found["traced"] >= found["cohort"] * 0.7, (
            "most of the cohort could not be traced to the baseline month")

    def test_weak_bands_take_over_the_cohort(self, book):
        found = anb.behaviour_distribution()
        assert found["weak_now"] > 60.0, (
            f"weak and very weak hold {found['weak_now']:.0f}% of the cohort.")
        assert found["weak_change"] >= 25.0, (
            f"the weak bands moved {found['weak_change']:+.0f} points.")

    def test_the_comparison_is_the_same_accounts(self, book):
        """Not the same BAND at two dates, which would be two populations."""
        found = anb.behaviour_distribution()
        now = sum(o["count"] for o in found["now"])
        before = sum(o["count"] for o in found["before"])
        assert now == before == found["traced"]


# ----------------------------------------- question 3: what moved the score

class TestTheDecomposition:

    def test_delinquency_does_not_explain_most_of_it(self, book):
        found = anb.score_decomposition()
        assert found["non_delinquency_share"] > 50.0, (
            f"only {found['non_delinquency_share']:.0f}% of the fall comes from "
            "variables carrying no arrears information. The presenter's whole "
            "argument at this point is that the score is not simply reacting "
            "to the DPD.")

    def test_drawing_and_repayment_are_the_two_signals(self, book):
        found = anb.score_decomposition()
        assert found["two_signal_share"] > 50.0
        assert found["drawing_share"] > 0 and found["repayment_share"] > 0

    def test_the_score_had_already_fallen_before_any_arrears(self, book):
        found = anb.score_decomposition()
        ahead = found["before_arrears"]
        assert ahead, "no pre-arrears window was computed"
        assert ahead["points"] < 0, (
            "the cohort's score had not fallen before it missed a payment. "
            "Without that, the timing argument in this answer is not available.")

    def test_the_contributions_reconcile_with_the_score(self, book):
        """The decomposition is arithmetic. It has to add up, not approximately."""
        found = anb.score_decomposition()
        total = sum(v["points"] for v in found["variables"])
        assert total == pytest.approx(found["score"].change, abs=0.5), (
            f"the variable contributions sum to {total:.1f} but the score moved "
            f"{found['score'].change:.1f}. One of them is not what it says.")
        assert abs(found["residual"]) < 0.5, (
            f"a residual of {found['residual']:.2f} points is unexplained. The "
            "answer claims the split is arithmetic, so it has to be.")

    def test_utilisation_and_repayment_moved_in_the_real_units(self, book):
        found = anb.score_decomposition()
        by = {m.label: m for m in found["metrics"]}
        util = by["Average card utilisation"]
        assert util.change >= 20.0, (
            f"utilisation moved {util.change:+.1f} points.")
        assert util.now >= 80.0, (
            f"the cohort is at {util.now:.0f}% utilisation. The story is that "
            "it has run out of headroom.")
        pay = by["Payments received against amounts due, 3 months"]
        assert pay.now < pay.before, "repayment did not weaken"


# ---------------------------------------- question 4: where it is concentrated

class TestTheConcentration:

    def test_alpha_card_carries_the_problem_and_not_the_book(self, book):
        found = anb.concentration()
        lead = found["lead"]
        assert lead["programme"] == "ALPHA", (
            f"{lead['label']} leads the new cases, not Alpha Card.")
        assert lead["exposure_share"] <= 30.0, (
            f"Alpha Card is {lead['exposure_share']:.0f}% of the book. Above a "
            "third it is not a concentration, it is the book.")
        assert lead["problem_share"] >= 60.0, (
            f"Alpha Card is {lead['problem_share']:.0f}% of the new cases.")

    def test_the_established_programmes_are_quiet(self, book):
        found = anb.concentration()
        for programme in found["programmes"]:
            if programme["programme"] == "ALPHA":
                continue
            assert programme["rate"] < found["lead"]["rate"] / 3, (
                f"{programme['label']} is entering 20-29 DPD at "
                f"{programme['rate']:.1f}%. If the established programmes moved "
                "too, this is a card book under pressure and not one product.")

    def test_the_score_band_gradient_is_steep_and_monotone(self, book):
        found = anb.concentration()
        bands = [b for b in found["bands"] if b["accounts"] >= 50]
        rates = [b["rate"] for b in bands]
        assert rates == sorted(rates, reverse=True), (
            f"the gradient is not monotone: {[(b['band'], b['rate']) for b in bands]}")
        assert found["gradient"] >= 5.0, (
            f"the steepest band is {found['gradient']:.1f}x the shallowest.")

    def test_the_opened_bands_are_a_minority_that_causes_a_majority(self, book):
        found = anb.concentration()
        assert found["opened_share"] < found["opened_case_share"], (
            "the bands opened below the established floor do not carry a "
            "disproportionate share of the cases, so there is no finding here.")
        assert found["opened_case_share"] >= 60.0

    def test_the_policy_context_is_on_the_answer(self, book):
        found = anb.concentration()
        assert found["expansion_floor"] < found["established_floor"]
        assert "demonstration" in found["expansion_context"].lower()
        for forbidden in ("rejected elsewhere", "declined elsewhere",
                          "subprime", "arab national bank's policy"):
            assert forbidden not in found["expansion_context"].lower()


# ------------------------------------------------ question 5: what to do

class TestTheActions:

    def test_only_the_opened_bands_are_acted_on(self, book):
        found = anb.actions()
        for row in found["rows"]:
            if row["band"] in anb.OPENED_BANDS:
                continue
            assert row["reduction"] == 0.0, (
                f"{row['band']} is proposed a {row['reduction']}% reduction. A "
                "blanket tightening is the recommendation this answer exists "
                "to argue against.")

    def test_every_reduction_is_derived_from_its_own_row(self, book):
        found = anb.actions()
        for row in found["rows"]:
            if not row["reduction"]:
                continue
            expected = min((row["excess"] - 1.0) * found["damping"],
                           found["cap"] / 100.0) * 100
            assert row["reduction"] == pytest.approx(expected, abs=0.1), (
                f"{row['band']}'s reduction is not what its own excess implies. "
                "A recommendation nobody can check against the row beside it is "
                "a number somebody chose.")

    def test_the_reductions_are_graded_and_capped(self, book):
        found = anb.actions()
        acting = [r for r in found["rows"] if r["reduction"]]
        assert len(acting) >= 2
        assert all(r["reduction"] <= found["cap"] for r in acting)
        rates = [r["rate"] for r in acting]
        cuts = [r["reduction"] for r in acting]
        assert rates == sorted(rates, reverse=True)
        assert cuts == sorted(cuts, reverse=True), (
            "a worse band is proposed a smaller reduction than a better one")

    def test_limits_are_in_saudi_riyals_and_round(self, book):
        found = anb.actions()
        for row in found["rows"]:
            assert row["proposed_limit"] % 500 == 0, (
                f"{row['band']} proposes SAR {row['proposed_limit']}, which is "
                "an arithmetic result rather than a limit anybody would publish.")
            assert row["proposed_limit"] <= row["current_limit"]


# ------------------------------------------------------- the whole thread

class TestTheThreadHoldsTogether:

    QUESTIONS = [
        "Can you split the 1-29 DPD population into 1-9, 10-19 and 20-29 DPD "
        "and show me the trend?",
        "How is the behavioural score distribution for these 20-29 DPD "
        "customers? Show me how it has moved.",
        "But the behavioural score may simply be worse because these customers "
        "are already 20-29 DPD. Can you decompose the deterioration by the "
        "behavioural-model variables and tell me what is really driving it?",
        "Okay, what is causing this? Where is this stress concentrated?",
        "What should we do about it?",
    ]
    CONTEXT = {"risk_case": {"about": answers.ABOUT}}

    def test_every_question_is_read_and_answered(self, book):
        seen = []
        for question in self.QUESTIONS:
            reading = answers.read(question, context=self.CONTEXT)
            assert reading is not None, f"unread: {question}"
            result = answers.answer(reading)
            assert result is not None, f"unanswered: {question}"
            assert result.answer.strip(), f"empty answer: {question}"
            assert result.rows, f"no figures: {question}"
            seen.append(reading.kind)
        assert seen == [answers.SPLIT, answers.BEHAVIOUR, answers.DECOMPOSE,
                        answers.CONCENTRATION, answers.ACTIONS]

    def test_the_generic_questions_are_declined_outside_the_thread(self, book):
        for question in ("What should we do about it?",
                         "Okay, what is causing this?",
                         "What do you recommend?"):
            assert answers.read(question, context={}) is None, (
                f"{question!r} was answered from the card book outside the card "
                "investigation. Nobody has said what 'it' is.")

    def test_unrelated_questions_are_left_to_the_planner(self, book):
        for question in ("What is total ECL for the home finance book?",
                         "List the datasets you hold.",
                         "How many auto finance accounts are in Stage 2?",
                         "Show me the personal finance arrears trend."):
            assert answers.read(question, context=self.CONTEXT) is None, (
                f"{question!r} was hijacked by the card investigation route.")

    def test_no_answer_leaks_implementation_detail(self, book):
        forbidden = ("parquet", "select ", "dataframe", "retail_facility_month",
                     "handlerresult", "beh_", "dpd_bucket", "np.", "pd.")
        for question in self.QUESTIONS:
            result = answers.answer(answers.read(question, context=self.CONTEXT))
            text = " ".join([
                result.answer,
                " ".join(str(v) for v in result.detail.get("observations", [])),
                str(result.detail.get("definition", "")),
            ]).lower()
            for word in forbidden:
                assert word not in text, (
                    f"{word!r} reached the user-visible answer to {question!r}")

    def test_the_answers_agree_with_the_card(self, book):
        """One computation read twice, not two that happen to be close."""
        from backend.retail import review

        draft = review._early_delinquency(anb.latest_month())
        card = {m["label"]: m["value"] for m in draft.metrics}

        split = answers.answer(answers.read(self.QUESTIONS[0], context=self.CONTEXT))
        assert split.values["20-29 DPD now"] == anb.early_delinquency()["focus_now"]

        ladder = anb.early_delinquency()
        assert card["1-29 DPD population"] == ladder["early"].now
        assert card["Card accounts"] == ladder["accounts"]

        cohort = answers.answer(
            answers.read(self.QUESTIONS[1], context=self.CONTEXT))
        concentration = anb.concentration()
        assert cohort.values["Accounts in the cohort"] == len(anb.cohort())
        assert concentration["new_cases"] <= len(anb.cohort()), (
            "more accounts entered 20-29 DPD this month than are in it")

    def test_the_orchestrator_route_actually_runs(self, book):
        """Through `orchestrator.answer`, not through the builders directly.

        THIS IS THE GATE THE OTHERS DID NOT COVER, AND IT IS WHY IT EXISTS.

        Every test above calls `answers.read` and `answers.answer`, which is
        most of the work and none of the wiring. The route that connects them
        to the product sits in the orchestrator, and it referred to a
        conversation-action constant that does not exist. Both functions were
        perfectly correct; every question in the live demonstration came back
        as "CreditProbe could not complete that request", and only running the
        thing end to end found it.

        So this asks the orchestrator, the way the API does, and checks that a
        result came back from THIS route rather than from the planner
        happening to answer something.
        """
        from backend.orchestration import orchestrator
        from backend.orchestration import conversation as cv

        for question in self.QUESTIONS:
            state = cv.ConversationState()
            state.thread_context = dict(self.CONTEXT)
            answered = orchestrator.answer(question, state=state)
            assert answered.failure in (None, "", False), (
                f"the orchestrator failed on {question!r}: {answered.failure}")
            assert answered.result is not None, (
                f"the orchestrator returned no result for {question!r}")
            assert answered.reading.source == "retail_card_investigation", (
                f"{question!r} was answered by {answered.reading.source}, not "
                "by the card investigation route")
            assert answered.result.rows, f"no figures for {question!r}"

    def test_the_route_stands_aside_outside_the_thread(self, book):
        """The same call, with no thread context, must reach the planner."""
        from backend.orchestration import orchestrator
        from backend.orchestration import conversation as cv

        for question in ("What should we do about it?",
                         "Okay, what is causing this?"):
            state = cv.ConversationState()
            answered = orchestrator.answer(question, state=state)
            source = getattr(answered.reading, "source", "")
            assert source != "retail_card_investigation", (
                f"{question!r} was answered from the card book with no card "
                "investigation open around it.")

    def test_asking_twice_gives_the_same_answer(self, book):
        """A live demonstration is run more than once."""
        for question in self.QUESTIONS:
            reading = answers.read(question, context=self.CONTEXT)
            first = answers.answer(reading)
            anb.reset_cache()
            second = answers.answer(answers.read(question, context=self.CONTEXT))
            assert first.answer == second.answer, f"drifted: {question}"
            assert first.rows == second.rows, f"figures drifted: {question}"
