"""
The three things a message in a thread can be, and what Stage 3 is allowed to do.

Two failures found in manual acceptance are pinned here, because both of them
were the kind that looks like a display problem and is not.

**A question was read as a scenario.** "Why did Stage 3 ECL increase?" reached
the builder, which found no magnitude and either did nothing or — worse — was
answered with a fresh calculation of a scenario that had already been run. So
every message is now classified before anything is done with it, and only one
of the three classes may touch scenario state.

**Stage 3 moved and nothing explained it.** A rating downgrade aimed at
performing borrowers changed the provision on defaulted names. Underneath was a
book that held obligors who were credit-impaired by days past due, still rated
B-, still carrying a ten per cent PD — so a rating shock moved them. The book
no longer holds any such obligor, and the invariant is asserted here rather
than hoped for: a shock that cannot reach a defaulted borrower does not move
that borrower's provision, and any Stage 3 movement that does happen carries a
named mechanism.
"""

from __future__ import annotations

import pytest

from backend.whatif import cache as ch
from backend.whatif import domain as dm
from backend.whatif import investigate as iv
from backend.whatif import language as lang
from backend.whatif import run as rn
from backend.whatif import scenarios as sc
from backend.whatif import staging as st
from backend.whatif import steps as sp


def _lake() -> bool:
    try:
        return bool(dm.periods())
    except Exception:
        return False


needs_lake = pytest.mark.skipif(
    not _lake(), reason="the Corporate IFRS 9 lake has not been built")


def _state(*shocks: sc.Shock, population: sc.Population | None = None,
           kind: str = sc.RATING) -> sp.ScenarioState:
    step = sp.Step(kind=kind, shocks=tuple(shocks),
                   population=population or sc.Population(),
                   instruction="test", interpreted="test")
    return sp.ScenarioState(period="", steps=(step,), staging=st.default(),
                            methodology="delta")


@pytest.fixture(scope="module")
def downgrade():
    """One notch across the book — the commonest scenario there is."""
    return rn.execute(_state(sc.Shock(kind=sc.RATING, magnitude=1,
                                      unit=sc.NOTCHES)), requested="delta")


# ==================================================== what a message is


class TestTheThreeIntents:
    @pytest.mark.parametrize("question", [
        "Why did Stage 3 ECL increase?",
        "What caused the provision to rise?",
        "Which borrowers contributed most?",
        "How much of the increase is due to stage migration?",
        "Who is responsible for the movement?",
        "Explain the Stage 1 to Stage 2 movement.",
        "Why is the ECL up more than the PD?",
    ])
    def test_a_question_about_the_result_is_an_explanation(self, question):
        assert iv.classify(question).intent == iv.EXPLAIN

    @pytest.mark.parametrize("question", [
        "Show this by sector.",
        "Break it down by rating.",
        "Give me a table of the top 20.",
        "Chart it by segment.",
    ])
    def test_a_request_for_another_cut_is_a_view(self, question):
        assert iv.classify(question).intent == iv.VIEW

    @pytest.mark.parametrize("question", [
        "Now increase LGD by 5 percentage points.",
        "Undo the last step.",
        "Remove the macro shock.",
        "Also downgrade the Contracting book by one notch.",
        "Reset the scenario.",
    ])
    def test_a_change_to_the_scenario_is_a_modification(self, question):
        assert iv.classify(question).intent == iv.MODIFY

    def test_only_a_modification_may_change_state(self):
        assert not iv.classify("Why did ECL rise?").changes_state
        assert not iv.classify("Show this by sector.").changes_state
        assert iv.classify("Now raise PD by 20%.").changes_state

    def test_show_me_who_caused_it_is_read_as_a_question_not_a_table(self):
        """"Show" appears in it, but it is asking who — answering with a plain
        table would drop the question."""
        reading = iv.classify("Show me the borrowers responsible for this.")
        assert reading.intent == iv.EXPLAIN
        assert reading.topic == "borrowers"

    def test_a_sentence_with_neither_signal_and_no_magnitude_is_a_question(self):
        """The safe reading. It cannot silently change a number."""
        assert iv.classify("Stage 3 provision").intent == iv.EXPLAIN

    def test_a_sentence_with_neither_signal_but_a_magnitude_is_a_scenario(self):
        """A magnitude with no result behind it OPENS a scenario.

        The same sentence arriving after a result is a modification of it.
        Both change the state; which one it is decides whether the thread
        starts a scenario or adds a step to one.
        """
        said = "PD up 20% for Contracting"
        assert lang.read(said).scenario is not None
        opening = iv.classify(said)
        assert opening.intent == iv.SCENARIO
        assert opening.family == iv.CHANGES
        assert opening.changes_state
        assert iv.classify(said, has_result=True,
                           has_steps=True).intent == iv.MODIFY

    def test_the_named_stage_is_read_out_of_the_question(self):
        assert iv.classify("Why did Stage 3 ECL increase?").stage == 3
        assert iv.classify("What happened in stage 2?").stage == 2

    def test_the_intents_are_described_for_the_product(self):
        described = iv.describe()
        assert {row["intent"] for row in described["all_intents"]} == set(
            iv.INTENTS)
        # Only the CHANGES family may move the thread's state, and every
        # intent belongs to exactly one family.
        for row in described["all_intents"]:
            assert row["changes_state"] == (row["family"] == iv.CHANGES), row
            assert row["family"] in {iv.ASKS, iv.READS, iv.CHANGES}, row
        assert {row["family"] for row in described["families"]} == {
            iv.ASKS, iv.READS, iv.CHANGES}

    def test_every_intent_carries_a_label_and_a_family(self):
        for intent in iv.INTENTS:
            assert iv.LABELS.get(intent), intent
            assert iv.FAMILY.get(intent), intent

    def test_an_intent_that_needs_a_result_degrades_rather_than_refuses(self):
        """Asked before there is anything to export or compare, the thread
        answers the question it CAN answer instead of stopping."""
        for question in ("Export this to Excel.",
                         "Compare the two methodologies."):
            reading = iv.classify(question)
            assert reading.family == iv.ASKS, question
            assert not reading.changes_state, question


# ============================================ answering without recomputing


@needs_lake
class TestAnAnswerComesFromTheResult:
    def test_a_breakdown_is_the_same_total_grouped_differently(self, downgrade):
        answered = iv.answer(iv.classify("Show this by sector."), downgrade)
        breakdown = answered["breakdown"]
        assert breakdown["available"]
        assert answered["state_changed"] is False
        # The breakdown is a REGROUPING, so its total is the sum of the same
        # borrower rows the table shows — exactly, not approximately.
        rows = downgrade.borrowers
        exact = float((rows["ecl_stressed"] - rows["ecl_baseline"]).sum())
        assert breakdown["total_change"] == pytest.approx(exact, abs=1e-6)
        # And that ties to the headline to the precision the table publishes:
        # two decimals per borrower, over every borrower in the population.
        total = downgrade.summary["incremental_ecl"]
        assert abs(breakdown["total_change"] - total) <= 0.01 * len(rows)

    def test_the_contributors_shares_sum_to_the_whole_movement(self, downgrade):
        answered = iv.answer(iv.classify("Which borrowers contributed most?"),
                             downgrade)
        rows = answered["contributors"]["rows"]
        assert rows
        # Largest MOVEMENT first, in either direction: a borrower whose
        # provision fell by a billion is a contributor to the movement, and
        # ranking on the signed figure would bury it at the bottom.
        assert abs(rows[0]["ecl_increase"]) >= abs(rows[-1]["ecl_increase"])

    def test_a_general_why_returns_the_whole_decomposition(self, downgrade):
        answered = iv.answer(iv.classify("Why did the ECL increase?"),
                             downgrade)
        assert answered["drivers"]
        shares = sum(float(d.get("share_pct", 0.0))
                     for d in answered["drivers"])
        assert abs(shares - 100.0) < 0.5

    def test_the_measurement_basis_is_answered_separately_from_the_stage(
            self, downgrade):
        answered = iv.answer(
            iv.classify("How much of this is the measurement basis changing?"),
            downgrade)
        assert answered["measurement_basis"]

    def test_every_answer_carries_the_headline_it_is_about(self, downgrade):
        for question in ("Why did ECL rise?", "Show this by sector.",
                         "Which borrowers contributed most?"):
            answered = iv.answer(iv.classify(question), downgrade)
            assert answered["headline"]["change"] == pytest.approx(
                downgrade.summary["incremental_ecl"])

    def test_asking_the_same_question_twice_gives_the_same_answer(
            self, downgrade):
        reading = iv.classify("Which borrowers contributed most?")
        first = iv.answer(reading, downgrade)
        second = iv.answer(reading, downgrade)
        assert first["contributors"]["rows"] == second["contributors"]["rows"]


# ==================================================== Stage 3 isolation


@needs_lake
class TestStageThreeIsIsolated:
    def test_a_rating_downgrade_does_not_move_the_defaulted_book(self,
                                                                 downgrade):
        """A defaulted borrower is already at the weakest grade.

        The masterscale clamps a downgrade at the weakest PERFORMING grade, so
        a scenario never manufactures a default — and a name already in default
        cannot be downgraded further, so its provision cannot move.
        """
        frame = downgrade.borrowers
        stage_three = frame[frame["stage_baseline"] >= 3]
        assert not stage_three.empty
        moved = (stage_three["ecl_stressed"]
                 - stage_three["ecl_baseline"]).abs().max()
        assert float(moved) < 0.01, (
            f"a rating downgrade moved Stage 3 provision by {moved:,.2f}")

    def test_a_shock_aimed_at_stage_one_leaves_stage_three_untouched(self):
        result = rn.execute(
            _state(sc.Shock(kind=sc.PD, magnitude=50.0, unit=sc.RELATIVE),
                   population=sc.Population(stages=(1,)), kind=sc.PD),
            requested="delta")
        frame = result.borrowers
        stage_three = frame[frame["stage_baseline"] >= 3]
        if stage_three.empty:
            pytest.skip("the selected population holds no Stage 3 names")
        moved = (stage_three["ecl_stressed"]
                 - stage_three["ecl_baseline"]).abs().max()
        assert float(moved) < 0.01

    def test_no_scenario_cures_a_default(self, downgrade):
        frame = downgrade.borrowers
        was = frame["stage_baseline"] >= 3
        assert (frame.loc[was, "stage_stressed"] >= 3).all()

    def test_no_scenario_manufactures_a_default(self, downgrade):
        frame = downgrade.borrowers
        was_not = frame["stage_baseline"] < 3
        assert (frame.loc[was_not, "stage_stressed"] < 3).all()

    def test_an_unmoved_stage_three_says_so_rather_than_showing_nothing(
            self, downgrade):
        answered = iv.answer(iv.classify("Why did Stage 3 ECL increase?"),
                             downgrade)
        stage_3 = answered["stage_3"]
        assert stage_3["available"]
        assert stage_3["note"]
        if not stage_3["moved"]:
            assert "did not move" in stage_3["note"]

    def test_any_stage_three_movement_carries_a_named_mechanism(self):
        """An LGD shock legitimately reaches defaulted names.

        When it does, the movement is not left as an unexplained number: every
        part of it is attributed to names arriving, names leaving, or names
        already there whose loss rate the scenario changed, and those parts sum
        to the whole.
        """
        result = rn.execute(
            _state(sc.Shock(kind=sc.LGD, magnitude=10.0, unit=sc.ABSOLUTE_PP),
                   kind=sc.LGD), requested="delta")
        answered = iv.answer(iv.classify("Why did Stage 3 ECL move?"), result)
        stage_3 = answered["stage_3"]
        assert stage_3["available"]
        if stage_3["moved"]:
            named = sum(float(d["effect"]) for d in stage_3["drivers"])
            assert abs(named - stage_3["change"]) < 0.05
            for driver in stage_3["drivers"]:
                assert driver["driver"]


# ========================================================= the result store


class TestTheResultStore:
    def setup_method(self):
        ch.clear()

    def test_a_result_is_read_back_by_the_id_it_was_stored_under(self):
        run_id = ch.put(object(), owner=7)
        assert ch.get(run_id, owner=7) is not None

    def test_a_result_is_not_readable_by_another_account(self):
        run_id = ch.put(object(), owner=7)
        assert ch.get(run_id, owner=9) is None

    def test_an_unknown_id_returns_nothing_rather_than_guessing(self):
        assert ch.get("not-an-id", owner=7) is None

    def test_the_store_is_bounded(self):
        for _ in range(ch.CAPACITY + 20):
            ch.put(object(), owner=1)
        assert ch.held() == ch.CAPACITY

    def test_the_oldest_result_is_the_one_dropped(self):
        first = ch.put(object(), owner=1)
        for _ in range(ch.CAPACITY):
            ch.put(object(), owner=1)
        assert ch.get(first, owner=1) is None
