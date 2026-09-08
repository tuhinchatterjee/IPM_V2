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

import json

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


# =========================================================================
# The surfaces added after the first six shapes of attack.
#
# Five more, and each is again something a real user does by accident before
# anybody does it on purpose:
#
# * **Make a user-defined assumption look governed.** The one thing an
#   override must never do is pass for the reference matrix.
# * **Get a figure into prose that was never computed.** The evidence check is
#   the only thing between a model and a quotable wrong number.
# * **Read somebody else's book.** A workbook carries the whole population at
#   borrower grain.
# * **Get a plausibility verdict to promise something.** A comparison against
#   history is not a forecast and must never read as one.
# * **Hand the integration check a broken book** and see whether it says so or
#   waves it through.
# =========================================================================


class TestAnOverrideCannotPassForGoverned:
    def test_a_user_relationship_is_labelled_wherever_it_appears(self) -> None:
        from backend.whatif import macrolab as ml

        own = ml.Sensitivity(
            variable="gdp_growth", source=ml.USER, name="GDP Growth Rate",
            pd_response_kind=ml.MULTIPLIER, pd_response=9.99,
            lgd_response_kind=ml.ABSOLUTE_PP, lgd_response=50.0)
        body = own.to_dict()
        said = body["description"] + " " + body["source_label"]
        assert "User-Defined" in said
        for word in ("required", "regulatory", "approved", "empirical",
                     "estimated", "governed", "reference sensitivity"):
            assert word not in said.lower().replace(
                "user-defined sensitivity", ""), word

    def test_an_override_cannot_claim_to_be_the_reference(self) -> None:
        """`source` is what the label is derived from, so a caller cannot set
        a user relationship and then have it announce itself as governed."""
        from backend.whatif import macrolab as ml

        lying = ml.Sensitivity.from_dict({
            "variable": "gdp_growth", "source": ml.USER,
            "source_label": "CreditProbe Reference Sensitivity",
            "pd_response_kind": ml.MULTIPLIER, "pd_response": 9.99,
            "lgd_response_kind": ml.ABSOLUTE_PP, "lgd_response": 50.0})
        assert lying.source == ml.USER
        assert "User-Defined" in lying.to_dict()["source_label"]

    @needs_lake
    def test_an_override_is_on_the_provenance_line_not_only_the_step(
            self) -> None:
        from backend.whatif import macrolab as ml
        from backend.whatif import methodology as me

        state = _state(sc.Shock(sc.MACRO, -1.0, sc.ABSOLUTE_PP,
                                target="gdp_growth"),
                       kind=sc.MACRO).with_sensitivity(ml.Sensitivity(
                           variable="gdp_growth", source=ml.USER,
                           name="GDP Growth Rate",
                           pd_response_kind=ml.MULTIPLIER, pd_response=1.9,
                           lgd_response_kind=ml.ABSOLUTE_PP,
                           lgd_response=3.0))
        context = rn.execute(state, requested=me.DELTA,
                             plausible=False).context()
        assert [s["source"] for s in context["sensitivities"]] == ["user"]
        assert "overridden for this thread" in context["sensitivity_note"]


class TestAFigureThatWasNeverComputed:
    """The evidence check is the only thing between a model and a quotable
    wrong number, so it is attacked directly."""

    PACKET = {"RESULT": {"whatif_ecl": 1631.2, "percentage_change": 31.49}}

    def test_an_invented_figure_is_caught(self) -> None:
        from backend.whatif import narrative as nr

        assert nr.check(
            ["Provisions reach SAR 1,631.2m, with 47 borrowers defaulting."],
            self.PACKET) == ["47"]

    def test_a_figure_hidden_in_a_larger_number_is_caught(self) -> None:
        from backend.whatif import narrative as nr

        found = nr.check(["Coverage moved to 8.44%."], self.PACKET)
        assert "8.44" in found

    def test_a_thousands_separator_does_not_smuggle_one_through(self) -> None:
        from backend.whatif import narrative as nr

        assert nr.check(["Exposure of SAR 12,345m."], self.PACKET) == ["12345"]

    def test_a_negative_of_a_known_figure_is_still_the_figure(self) -> None:
        from backend.whatif import narrative as nr

        assert nr.check(["A fall of 31.49%."], self.PACKET) == []

    def test_an_empty_packet_does_not_wave_everything_through(self) -> None:
        from backend.whatif import narrative as nr

        assert nr.check(["Provisions rose to SAR 4,120m."], {}) == ["4120"]

    @needs_lake
    def test_the_comparison_prose_is_checked_against_its_own_evidence(
            self) -> None:
        from backend.whatif import comparison as cp
        from backend.whatif import narrative as nr

        body = cp.compare(_state(sc.Shock(sc.PD, 20.0, sc.RELATIVE)))
        if not body.get("available"):
            pytest.skip("one methodology is unavailable")
        reading = cp.explain(body)
        assert nr.check([*reading["paragraphs"], reading["headline"]],
                        cp.packet(body)) == []


class TestSomebodyElsesBook:
    """A workbook carries the whole population at borrower grain, so who may
    have one is a security question."""

    def test_a_held_result_is_not_readable_by_another_owner(self) -> None:
        from backend.whatif import cache as ch

        run_id = ch.put(object(), owner=7)
        assert ch.get(run_id, owner=7) is not None
        assert ch.get(run_id, owner=8) is None
        assert ch.get(run_id, owner=None) is None

    def test_an_anonymous_result_is_not_readable_by_a_named_user(self) -> None:
        from backend.whatif import cache as ch

        run_id = ch.put(object(), owner=None)
        assert ch.get(run_id, owner=99) is None

    def test_a_guessed_run_id_returns_nothing(self) -> None:
        from backend.whatif import cache as ch

        for guess in ("", "  ", "0" * 32, "../../etc/passwd", "%2e%2e"):
            assert ch.get(guess, owner=1) is None

    def test_a_title_carrying_a_path_cannot_reach_the_filename(self) -> None:
        from backend.exports.contract import slug

        for nasty in ("../../etc/passwd", "a/b\\c:d", "con.aux",
                      "x" * 400, "..\\..\\windows"):
            cleaned = slug(nasty)
            for unsafe in ("..", "/", "\\", ":"):
                assert unsafe not in cleaned, (nasty, cleaned)

    @needs_lake
    def test_a_workbook_refuses_an_empty_population_rather_than_writing_one(
            self) -> None:
        import pandas as pd

        from backend.whatif import workbook as wb

        class Nobody:
            borrowers = pd.DataFrame()

        with pytest.raises(wb.WorkbookError):
            wb.build(Nobody())


class TestPlausibilityPromisesNothing:
    def test_no_verdict_reads_as_a_forecast(self) -> None:
        from backend.whatif import plausibility as pl

        for share, quarters in ((0.9, 12), (0.43, 9), (0.06, 3), (0.003, 2),
                                (0.0, 0)):
            body = pl.Evidence(measure="pd_12m", label="12-month PD",
                               proposed=20.0, unit="%")
            body.observations = 52880 if quarters else 0
            body.qoq_share = share
            body.quarters_seen = ["Q1 2024"] * quarters
            _, because = pl.verdict(body)
            said = because.lower()
            for promise in ("probability", "chance", "will happen", "expect",
                            "forecast", "predict", "likely to occur"):
                assert promise not in said, (promise, because)

    def test_a_bigger_shock_is_never_read_as_more_ordinary(self) -> None:
        """Monotonic by construction: severity cannot fall as a shock grows."""
        from backend.whatif import plausibility as pl

        order = [pl.CONSISTENT, pl.PLAUSIBLE, pl.POCKETS, pl.SEVERE_OBSERVED,
                 pl.SEVERE_RECENT, pl.OUTSIDE]
        seen = []
        for share in (0.9, 0.43, 0.06, 0.003, 0.0):
            body = pl.Evidence(measure="pd_12m", label="12-month PD",
                               proposed=20.0, unit="%")
            body.observations = 52880 if share else 0
            body.qoq_share = share
            body.quarters_seen = ["Q1 2024", "Q2 2024"] if share else []
            seen.append(order.index(pl.verdict(body)[0]))
        assert seen == sorted(seen), seen

    @needs_lake
    def test_a_history_that_cannot_be_built_costs_the_comparison_not_the_run(
            self) -> None:
        """A missing comparison is not a failed calculation."""
        from backend.whatif import methodology as me

        found = rn.execute(_state(sc.Shock(sc.PD, 20.0, sc.RELATIVE)),
                           requested=me.DELTA, plausible=True)
        assert found.summary["stressed_ecl"] > 0
        assert isinstance(found.plausibility, dict)


class TestABrokenBookIsSaidRatherThanWavedThrough:
    def test_a_dataset_that_is_not_there_blocks_and_says_what_it_costs(
            self) -> None:
        from backend.whatif import integration as itg

        body = itg.assess(snapshot="definitely_not_a_dataset")
        assert not body.ready
        assert body.blocked
        assert body.blocked[0].costs

    def test_it_never_raises_on_a_book_it_cannot_read(self) -> None:
        """The whole point is to SAY what is wrong. Raising says nothing."""
        from backend.whatif import integration as itg

        for name in ("", "  ", "../../etc", "a" * 200, "no_such_thing"):
            body = itg.assess(snapshot=name or "no_such_thing")
            assert isinstance(body.to_dict(), dict)

    def test_a_readiness_report_never_leaks_a_filesystem_path(self) -> None:
        """The endpoint is open to every analyst, and the underlying error
        names the directory it looked in."""
        from backend.whatif import integration as itg

        body = itg.assess(snapshot="no_such_thing").to_dict()
        said = json.dumps(body)
        assert "/home/" not in said
        assert "/data/analytics" not in said

    def test_a_finer_grain_book_is_blocked_not_warned(self) -> None:
        import pandas as pd

        from backend.whatif import integration as itg

        body = itg.Readiness(domain="t", snapshot="s", measurement="m")
        itg._check_grain(body, pd.DataFrame({
            "borrower_id": ["B1", "B1", "B1", "B2"]}), "Q2 2026")
        assert body.blocked
        assert not body.ready

    def test_a_parameter_in_the_wrong_unit_is_blocked(self) -> None:
        """A PD stored as a fraction rather than a percent divides every
        provision by a hundred, and every figure still looks reasonable."""
        import pandas as pd

        from backend.whatif import integration as itg

        body = itg.Readiness(domain="t", snapshot="s", measurement="m")
        itg._check_ranges(body, pd.DataFrame({"lgd": [45.0, 145.0]}))
        assert body.blocked
