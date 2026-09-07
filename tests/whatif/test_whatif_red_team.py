"""
Trying to make What-If say something it cannot support.

Every test here is an ATTACK. The question is not "does the feature work" but
"can a determined person get a confident wrong number out of it" — and the
answer has to be no, or the failure has to be a refusal in words rather than a
plausible figure.

Six shapes of attack, and each of them is something a real user does by
accident before anybody does it on purpose:

* **Ask for a book this engine does not read.** The corporate sector names
  share words with the retail, SME and card books.
* **State a scenario so extreme the arithmetic breaks.** A PD of ten thousand
  per cent, an LGD of minus fifty, a downgrade of ninety notches.
* **Ask a question that contains an instruction.** "Was any of this the rating
  downgrade?" is a question; reading it as a shock changes the number it asks
  about.
* **Narrow to nothing.** A filter nobody meets must say so, not return a
  confident zero.
* **Ask about a period, model or borrower that does not exist.**
* **Ask the same thing twice** and get the same answer, because a scenario
  engine that is not reproducible cannot be defended anywhere.
"""

from __future__ import annotations

import pytest

from backend.whatif import domain as dm
from backend.whatif import engine as wf
from backend.whatif import investigate as iv
from backend.whatif import language as lg
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
           kind: str = sc.PD) -> sp.ScenarioState:
    return sp.ScenarioState(
        period="", staging=st.default(), methodology="delta",
        steps=(sp.Step(kind=kind, shocks=tuple(shocks),
                       population=population or sc.Population(),
                       instruction="attack", interpreted="attack"),))


class TestAnotherBooksQuestion:
    @pytest.mark.parametrize("said", [
        "Downgrade the retail mortgage book by two notches.",
        "Increase PD by 20% on the credit card book.",
        "Stress the SME scorecard portfolio by one notch.",
        "Raise LGD by 5 points on the personal loan book.",
        "Downgrade the consumer lending portfolio two notches.",
        "Apply a 200bp shock to the auto loan book.",
    ])
    def test_it_is_refused_rather_than_mapped_onto_a_corporate_sector(
            self, said) -> None:
        read = lg.read(said)
        assert read.scenario is None, (
            f"{said!r} built a corporate scenario — a confident number about "
            "the wrong portfolio")
        assert any("different book" in note for note in read.notes)

    def test_the_domain_refuses_a_dataset_it_does_not_own(self) -> None:
        with pytest.raises(dm.DomainError) as raised:
            dm.read("portfolio_facility", "Q2 2026")
        assert "portfolio_facility" in str(raised.value)


@needs_lake
class TestAnAbsurdMagnitude:
    def test_a_pd_shock_of_ten_thousand_percent_stays_a_probability(self) -> None:
        result = rn.execute(
            _state(sc.Shock(kind=sc.PD, magnitude=10_000.0, unit=sc.RELATIVE)),
            requested="delta")
        frame = result.borrowers
        assert float(frame["pd_stressed"].max()) <= 100.0
        assert float(frame["pd_stressed"].min()) >= 0.0

    def test_a_negative_lgd_cannot_be_reached(self) -> None:
        result = rn.execute(
            _state(sc.Shock(kind=sc.LGD, magnitude=-500.0, unit=sc.ABSOLUTE_PP),
                   kind=sc.LGD), requested="delta")
        assert float(result.borrowers["lgd_stressed"].min()) >= 0.0

    def test_ninety_notches_stops_at_the_weakest_performing_grade(self) -> None:
        """A scenario does not manufacture a default out of arithmetic."""
        result = rn.execute(
            _state(sc.Shock(kind=sc.RATING, magnitude=90, unit=sc.NOTCHES),
                   kind=sc.RATING), requested="delta")
        frame = result.borrowers
        was_performing = frame["stage_baseline"] < 3
        assert (frame.loc[was_performing, "stressed_rating"] != "D").all()
        assert (frame.loc[was_performing, "stage_stressed"] < 3).all()

    def test_no_provision_exceeds_the_exposure_however_hard_it_is_shocked(
            self) -> None:
        result = rn.execute(
            _state(sc.Shock(kind=sc.PD, magnitude=10_000.0, unit=sc.RELATIVE),
                   sc.Shock(kind=sc.LGD, magnitude=95.0, unit=sc.ABSOLUTE_PP)),
            requested="delta")
        frame = result.borrowers
        over = frame[frame["ecl_stressed"] > frame["ead"] * 1.0001]
        assert over.empty, f"{len(over)} borrowers provisioned above exposure"

    def test_the_attribution_still_reconciles_at_the_clamps(self) -> None:
        """A shock that ran into a policy limit did not have the effect it
        asked for, and the difference is a NAMED driver rather than a gap."""
        result = rn.execute(
            _state(sc.Shock(kind=sc.PD, magnitude=10_000.0, unit=sc.RELATIVE)),
            requested="delta")
        assert result.attribution["reconciliation"]["reconciles"]


class TestAQuestionThatContainsAnInstruction:
    @pytest.mark.parametrize("said", [
        "Was any of this the rating downgrade?",
        "Which borrowers were downgraded in the last quarter?",
        "Why did the PD increase?",
        "Did the LGD move?",
        "How many borrowers migrated to Stage 2?",
        "Show me the top ten deteriorating borrowers.",
    ])
    def test_it_does_not_change_the_scenario(self, said) -> None:
        assert not iv.classify(said).changes_state, (
            f"{said!r} was read as an instruction")


@needs_lake
class TestNarrowingToNothing:
    def test_a_population_nobody_meets_says_so(self) -> None:
        scenario = sc.Scenario(
            key="attack", name="attack",
            shocks=(sc.Shock(kind=sc.PD, magnitude=20.0, unit=sc.RELATIVE),),
            population=sc.Population(
                sectors=("Contracting",),
                thresholds=(sc.Threshold(field="ead", operator="above",
                                         value=1e12, unit="SAR mn"),)))
        with pytest.raises(wf.EmptyPopulation) as raised:
            wf.run(scenario, staging=st.default())
        said = str(raised.value)
        assert "No borrowers match" in said
        assert "applied as stated" in said, (
            "the reader has to know the filter WORKED and nobody met it")

    def test_a_column_the_book_does_not_carry_is_named(self) -> None:
        scenario = sc.Scenario(
            key="attack", name="attack",
            shocks=(sc.Shock(kind=sc.PD, magnitude=20.0, unit=sc.RELATIVE),),
            population=sc.Population(thresholds=(
                sc.Threshold(field="not_a_column", operator="above",
                             value=1.0),)))
        with pytest.raises(wf.PopulationUnavailable) as raised:
            wf.run(scenario, staging=st.default())
        assert "not_a_column" in str(raised.value)


@needs_lake
class TestSomethingThatDoesNotExist:
    def test_a_period_the_book_does_not_have(self) -> None:
        with pytest.raises(dm.DomainError) as raised:
            dm.book("Q3 2099")
        assert "Q3 2099" in str(raised.value)

    def test_a_model_version_that_was_never_trained(self) -> None:
        from backend.whatif.ml import registry as rg

        with pytest.raises(rg.RegistryError):
            rg.load_booster("1999.01.01")

    def test_a_borrower_that_is_not_on_the_book(self) -> None:
        from backend.whatif import profiles as pf

        with pytest.raises(dm.DomainError):
            pf.borrower_history("CORP-999999")


@needs_lake
class TestItSaysTheSameThingTwice:
    def test_the_same_scenario_gives_the_same_figures(self) -> None:
        state = _state(sc.Shock(kind=sc.RATING, magnitude=2, unit=sc.NOTCHES),
                       kind=sc.RATING)
        first = rn.execute(state, requested="delta")
        second = rn.execute(state, requested="delta")
        for key in ("baseline_ecl", "stressed_ecl", "incremental_ecl"):
            assert first.summary[key] == pytest.approx(second.summary[key],
                                                       rel=1e-12), key

    def test_the_order_the_shocks_were_typed_in_does_not_change_the_answer(
            self) -> None:
        rating = sc.Shock(kind=sc.RATING, magnitude=1, unit=sc.NOTCHES)
        lgd = sc.Shock(kind=sc.LGD, magnitude=5.0, unit=sc.ABSOLUTE_PP)
        one = sp.ScenarioState(period="", staging=st.default(),
                               methodology="delta", steps=(
            sp.Step(kind=sc.RATING, shocks=(rating,), interpreted="a"),
            sp.Step(kind=sc.LGD, shocks=(lgd,), interpreted="b")))
        two = sp.ScenarioState(period="", staging=st.default(),
                               methodology="delta", steps=(
            sp.Step(kind=sc.LGD, shocks=(lgd,), interpreted="b"),
            sp.Step(kind=sc.RATING, shocks=(rating,), interpreted="a")))
        assert (rn.execute(one, requested="delta").summary["stressed_ecl"]
                == pytest.approx(
                    rn.execute(two, requested="delta").summary["stressed_ecl"],
                    rel=1e-12))

    def test_the_same_question_about_the_same_result_answers_the_same(self) -> None:
        result = rn.execute(
            _state(sc.Shock(kind=sc.PD, magnitude=25.0, unit=sc.RELATIVE)),
            requested="delta")
        reading = iv.classify("Why did the ECL increase?")
        assert (iv.answer(reading, result)["drivers"]
                == iv.answer(reading, result)["drivers"])


@needs_lake
class TestItNeverImprovesTheBook:
    @pytest.mark.parametrize("shock,kind", [
        (sc.Shock(kind=sc.RATING, magnitude=2, unit=sc.NOTCHES), sc.RATING),
        (sc.Shock(kind=sc.PD, magnitude=50.0, unit=sc.RELATIVE), sc.PD),
        (sc.Shock(kind=sc.LGD, magnitude=10.0, unit=sc.ABSOLUTE_PP), sc.LGD),
        (sc.Shock(kind=sc.COLLATERAL, magnitude=-20.0, unit=sc.RELATIVE),
         sc.COLLATERAL),
    ])
    def test_an_adverse_shock_never_reduces_the_provision(self, shock, kind) -> None:
        result = rn.execute(_state(shock, kind=kind), requested="delta")
        assert result.summary["incremental_ecl"] >= -0.01, (
            "an adverse scenario that releases provision is describing a "
            "different book")

    def test_no_scenario_cures_a_stage(self) -> None:
        result = rn.execute(
            _state(sc.Shock(kind=sc.PD, magnitude=50.0, unit=sc.RELATIVE)),
            requested="delta")
        frame = result.borrowers
        assert (frame["stage_stressed"] >= frame["stage_baseline"]).all()

    def test_the_reported_book_is_never_touched(self) -> None:
        """The baseline column is the accounts. A scenario that moved it would
        be restating the financial statements."""
        before, _ = dm.book("")
        rn.execute(_state(sc.Shock(kind=sc.RATING, magnitude=4,
                                   unit=sc.NOTCHES), kind=sc.RATING),
                   requested="delta")
        after, _ = dm.book("")
        assert float(before["final_ecl"].sum()) == pytest.approx(
            float(after["final_ecl"].sum()), rel=1e-12)
        assert (before["stage"].to_numpy() == after["stage"].to_numpy()).all()
