"""Three methods, one confirmed scenario, one cohort, one baseline.

UNIT. No model, no provider, no database. `run.py` composes what P3 and P4
built; what this module asserts is the composition — that the methods stay
alternative ANSWERS to one question and never become factors of one.

The D-series requirements covered:

* **D02** the full frozen cohort is used, never the displayed rows and never
  the top contributors, and every row is in the total including the ones
  nothing touched.
* **D06** one baseline, read once, and every method starts from it.
* **D07** methods are shown side by side and never composed. The ML estimate
  is not multiplied by the Delta factor.
* **D08** where the methods cover different populations the run discloses it
  and publishes a like-for-like comparison over the rows all of them
  reached.
* **D09** an unavailable method carries its reason and NO number.
* **D10** an unconfirmed scenario does not execute, and neither does one
  confirmed against a different book.
* **D11** a missing user assumption is resolved BEFORE the run, not
  discovered halfway through it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import errors as err
from backend.cockpit_v4.scenario import run as rn
from backend.cockpit_v4.scenario import spec as sp
from tests.cockpit_v4.test_whatif_spec import cohort, confirmed, draft, pd_up

D = Decimal


def rows(count: int = 6, *, sector: str = "Construction",
         ecl: str = "100") -> list[dict]:
    """A cohort with something for each disposition to land on."""
    out = []
    for i in range(count):
        out.append({
            "facility_id": f"F{i}",
            "sector": sector if i % 2 == 0 else "Energy",
            "stage": 1 if i < count - 1 else 2,
            "ecl_sar_mn": D(ecl) + i,
            "pd_pit_12m": D("0.03"),
            "pd_lifetime": D("0.06"),
            "lgd_pct": D("45"),
            "ead_sar_mn": D("1000"),
        })
    return out


def spec_for(**over) -> sp.ScenarioSpec:
    body = {"methods": (sp.DELTA,)}
    body.update(over)
    return confirmed(**body)


def plan_for(spec: sp.ScenarioSpec) -> dl.Plan:
    return dl.plan(spec)


class _Anchored:
    """A stand-in for `infer.Anchored`, so this module needs no model."""

    def __init__(self, total: float) -> None:
        self.anchored_total = total

    def as_facts(self) -> dict:
        return {"anchored_total_ecl": self.anchored_total,
                "anchoring": "ML_change = P1 - P0"}


# ==========================================================================
# D06 / D02 -- one baseline, the whole cohort
# ==========================================================================

def test_d06_every_method_starts_from_the_same_baseline() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "10",
                                     "stated_as": "10% higher"})
    book = rows()
    got = rn.execute(spec, book, key="facility_id", ecl_column="ecl_sar_mn",
                     plan=plan_for(spec))
    baselines = {o.baseline for o in got.outcomes.values()}
    assert len(baselines) == 1
    assert baselines.pop() == sum(r["ecl_sar_mn"] for r in book)


def test_d02_every_cohort_row_is_in_the_total_including_the_untouched():
    """An unaffected row contributes exactly zero and stays in the sum."""
    spec = spec_for(shocks=(pd_up("20", where={"sector": "Energy"}),))
    book = rows()
    got = rn.execute(spec, book, key="facility_id", ecl_column="ecl_sar_mn",
                     plan=plan_for(spec))
    assert got.cohort_size == len(book)
    assert len(got.outcomes[sp.DELTA].covered) == len(book)
    ledger = got.ledgers[sp.DELTA]
    assert len(ledger.lines) == len(book)
    untouched = [line for line in ledger.lines
                 if line.disposition == dl.UNAFFECTED]
    assert untouched
    assert all(line.scenario == line.baseline for line in untouched)


def test_d02_an_empty_cohort_is_refused_not_answered_with_zero() -> None:
    spec = spec_for()
    with pytest.raises(err.ScenarioError) as raised:
        rn.execute(spec, [], key="facility_id", ecl_column="ecl_sar_mn",
                   plan=plan_for(spec))
    assert "not a result of zero" in str(raised.value)


# ==========================================================================
# D10 -- confirmation and the book
# ==========================================================================

def test_d10_an_unconfirmed_scenario_does_not_execute() -> None:
    spec = draft(methods=(sp.DELTA,))
    with pytest.raises(err.ScenarioError) as raised:
        rn.execute(spec, rows(), key="facility_id",
                   ecl_column="ecl_sar_mn", plan=plan_for(spec))
    assert raised.value.code == err.CONFIRMATION_STALE
    assert "has not been confirmed" in str(raised.value)


def test_d10_a_revised_scenario_loses_its_confirmation() -> None:
    """Nobody has to remember: `revise` drops it."""
    spec = spec_for().revise(shocks=(pd_up("50"),))
    assert not spec.is_confirmed()
    with pytest.raises(err.ScenarioError):
        rn.execute(spec, rows(), key="facility_id",
                   ecl_column="ecl_sar_mn", plan=plan_for(spec))


def test_d10_a_scenario_confirmed_against_another_book_is_refused() -> None:
    spec = spec_for()
    rn.require_same_book(spec, release_id=spec.source.release_id)
    with pytest.raises(err.ScenarioError) as raised:
        rn.require_same_book(spec, release_id="v4-whatif-corporate-20q-s1")
    assert raised.value.code == err.MODEL_NOT_READY
    assert "set of identifiers in the other release" in str(raised.value)


def test_d10_the_same_id_republished_is_caught_by_the_fingerprint() -> None:
    spec = spec_for()
    with pytest.raises(err.ScenarioError) as raised:
        rn.require_same_book(spec, release_id=spec.source.release_id,
                             release_fingerprint="ffffffffffff0000")
    assert "republished under the same id" in str(raised.value)


# ==========================================================================
# D09 / D11 -- an unavailable method says so
# ==========================================================================

def test_d09_a_missing_emulator_carries_a_reason_and_no_number() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec),
                     anchored=None,
                     ml_unavailable="No emulator is published for this book.")
    outcome = got.outcomes[sp.ML]
    assert outcome.status == rn.UNAVAILABLE
    assert outcome.scenario is None
    assert outcome.change is None
    assert outcome.covered == ()
    assert "No emulator" in outcome.reason
    assert got.unavailable == (sp.ML,)
    assert got.ran == (sp.DELTA,)


def test_d09_an_unavailable_method_is_never_given_another_methods_answer():
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    delta = got.outcomes[sp.DELTA]
    assert delta.scenario is not None
    assert got.outcomes[sp.ML].scenario is None
    comparison = got.compare()
    ml_row = [r for r in comparison["own_population"]
              if r["method"] == sp.ML][0]
    assert ml_row["scenario"] is None
    assert ml_row["change"] is None
    assert ml_row["status"] == rn.UNAVAILABLE


def test_d11_a_missing_assumption_is_reported_before_the_run() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.USER_DEFINED))
    outstanding = rn.unresolved_assumptions(spec)
    assert outstanding
    assert "relative move" in outstanding[0]
    assert rn.unresolved_assumptions(spec_for(methods=(sp.DELTA,))) == []


def test_d11_a_scenario_with_no_assumption_does_not_invent_one() -> None:
    spec = spec_for(methods=(sp.USER_DEFINED,))
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    outcome = got.outcomes[sp.USER_DEFINED]
    assert outcome.status == rn.UNAVAILABLE
    assert outcome.scenario is None
    assert "does not supply one" in outcome.reason
    assert "State the ECL change you want to assume" in outcome.reason


def test_a_stated_assumption_runs_and_is_labelled_as_one() -> None:
    spec = spec_for(methods=(sp.USER_DEFINED,),
                    user_assumption={
                        "form": "relative", "value": "10",
                        "stated_as": "assume ECL is 10% higher"})
    book = rows()
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    outcome = got.outcomes[sp.USER_DEFINED]
    assert outcome.status == rn.AVAILABLE
    baseline = sum(r["ecl_sar_mn"] for r in book)
    assert outcome.scenario == baseline * D("1.10")
    assert outcome.facts["label"] == "USER_ASSUMPTION"
    assert "10% higher" in outcome.facts["stated_by_the_reader"]


def test_a_scenario_naming_no_method_is_refused() -> None:
    spec = spec_for(methods=())
    with pytest.raises(err.ScenarioError) as raised:
        rn.execute(spec, rows(), key="facility_id",
                   ecl_column="ecl_sar_mn", plan=plan_for(spec))
    assert "names no method" in str(raised.value)


# ==========================================================================
# D07 -- side by side, never composed
# ==========================================================================

def test_d07_the_comparison_shows_the_methods_and_composes_nothing() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.ML, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "5",
                                     "stated_as": "5% higher"})
    book = rows()
    baseline = sum(r["ecl_sar_mn"] for r in book)
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec),
                     anchored=_Anchored(float(baseline) * 1.08))
    comparison = got.compare()
    assert len(comparison["own_population"]) == 3
    assert "not multiplied by the Delta factor" in \
        comparison["never_composed"]
    assert "averaged" in comparison["never_composed"]
    # Three separate scenario totals, none of them a product of the others.
    totals = [D(r["scenario"]) for r in comparison["own_population"]]
    assert len(set(totals)) == 3


def test_d07_the_disagreement_is_explained_rather_than_averaged() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "40",
                                     "stated_as": "40% higher"})
    book = rows()
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    words = got.disagreement()
    assert "differ by" in words
    assert "shown side by side" in words
    assert "average" not in words.lower()


def test_one_method_alone_has_no_disagreement_to_explain() -> None:
    spec = spec_for()
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    assert got.disagreement() == ""


# ==========================================================================
# D08 -- coverage, and the like-for-like comparison
# ==========================================================================

def test_d08_identical_coverage_needs_no_like_for_like_comparison() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "10",
                                     "stated_as": "10% higher"})
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    assert got.coverage.uniform
    assert got.compare()["like_for_like_needed"] is False
    assert "covered the same" in got.coverage.describe()


def test_d08_different_coverage_is_disclosed_and_compared_like_for_like():
    coverage = rn.Coverage(
        cohort=("F0", "F1", "F2", "F3"),
        by_method={sp.DELTA: ("F0", "F1", "F2", "F3"),
                   sp.ML: ("F0", "F1")})
    assert not coverage.uniform
    assert coverage.shared == ("F0", "F1")
    assert coverage.gaps() == {sp.ML: ("F2", "F3")}
    words = coverage.describe()
    assert "different populations" in words
    assert "mostly population" in words


def test_d08_the_like_for_like_rows_say_what_they_are() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    book = rows()
    baseline = sum(r["ecl_sar_mn"] for r in book)
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec),
                     anchored=_Anchored(float(baseline) * 1.05))
    # Both methods covered the whole cohort here, so no second table.
    assert got.coverage.uniform
    # Construct the uneven case directly.
    uneven = rn.Coverage(cohort=("A", "B", "C"),
                         by_method={sp.DELTA: ("A", "B", "C"),
                                    sp.ML: ("A",)})
    patched = rn.Run(spec=got.spec, period=got.period,
                     membership_hash=got.membership_hash,
                     cohort_size=3, book_baseline=D(0),
                     outcomes=got.outcomes, coverage=uneven)
    comparison = patched.compare()
    assert comparison["like_for_like_needed"] is True
    assert comparison["like_for_like"]
    for row in comparison["like_for_like"]:
        assert row["rows_covered"] == 1
        assert "method rather than population" in row["note"]


def test_a_method_that_covered_nothing_is_not_in_the_shared_set() -> None:
    coverage = rn.Coverage(cohort=("A", "B"),
                           by_method={sp.DELTA: ("A", "B"), sp.ML: ()})
    assert coverage.shared == ("A", "B")
    assert coverage.uniform


# ==========================================================================
# Delta's own reporting inside the run
# ==========================================================================

def test_a_field_delta_cannot_express_makes_the_answer_partial() -> None:
    """Section 10: reporting a Delta total that ignored part of the request
    is worse than saying which part."""
    plan = dl.Plan(domain_id="corporate", submode=sp.PROPORTIONAL,
                   factors=(), unhandled=("limit_sar_mn",))
    spec = spec_for()
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan)
    outcome = got.outcomes[sp.DELTA]
    assert outcome.status == rn.PARTIAL
    assert "limit_sar_mn" in outcome.reason
    assert "not in this number" in outcome.reason


def test_the_delta_ledger_reconciles_to_the_outcome() -> None:
    spec = spec_for()
    book = rows()
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    ledger = got.ledgers[sp.DELTA]
    outcome = got.outcomes[sp.DELTA]
    assert ledger.baseline == outcome.baseline
    assert ledger.scenario == outcome.scenario


def test_the_outcome_sentence_carries_all_three_numbers() -> None:
    spec = spec_for()
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    words = got.outcomes[sp.DELTA].describe()
    assert " to " in words
    assert "a change of" in words
    assert "%" in words
    assert "rows" in words


def test_an_unavailable_outcome_describes_itself_as_unavailable() -> None:
    """The verdict a READER sees is "NOT READY"; the status the code branches
    on is still `UNAVAILABLE`.

    `describe()` writes copy, so it writes `run.VERDICTS[status]`. The word
    changed deliberately: "UNAVAILABLE" beside two working methods reads as a
    product fault, where the truth is that this method's model exists and has
    not passed its predeclared validation gates. The state machine is
    untouched -- the assertion on `outcome.status` below is what pins that.
    """
    outcome = rn.Outcome(method=sp.ML, status=rn.UNAVAILABLE,
                         baseline=D("100"), scenario=None, covered=(),
                         reason="No emulator is published.")
    words = outcome.describe()
    assert words.startswith("Emulator: NOT READY")
    assert outcome.status == rn.UNAVAILABLE
    assert rn.VERDICTS[rn.UNAVAILABLE] == "NOT READY"
    assert "No emulator is published." in words
    assert "0" not in words.replace("No emulator is published.", "")


def test_a_zero_baseline_has_no_percentage_rather_than_infinity() -> None:
    outcome = rn.Outcome(method=sp.DELTA, status=rn.AVAILABLE,
                         baseline=D("0"), scenario=D("5"), covered=("A",))
    assert "not defined from a zero baseline" in outcome.describe()


def test_the_cohort_reference_is_carried_not_recomputed() -> None:
    """The run reports the membership hash the confirmation was bound to."""
    spec = spec_for(cohort=cohort(membership_hash="b" * 64, entity_count=6))
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    assert got.membership_hash == "b" * 64
    assert got.ledgers[sp.DELTA].membership_hash == "b" * 64


# ==========================================================================
# A model that ran and missed a gate is not shown as if it had passed
# ==========================================================================

class _Loaded:
    """A stand-in for `infer.Loaded`, carrying gate outcomes."""

    def __init__(self, gates: dict) -> None:
        self.gates = gates

    @property
    def passed_every_gate(self) -> bool:
        return all(g["passed"] for g in self.gates.values())

    def failures(self) -> list[str]:
        return [f"{name}: {g['what']} measured {g['measured']:.4f} against "
                f"{g['threshold']:.4f}"
                for name, g in sorted(self.gates.items())
                if not g["passed"]]


def test_a_model_that_missed_a_gate_carries_the_gate_with_its_number():
    """Section 11.5. Three figures with nothing to distinguish them read as
    three equally reliable figures."""
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    book = rows()
    baseline = sum(r["ecl_sar_mn"] for r in book)
    missed = _Loaded({
        "G1": {"what": "out-of-time currency WAPE", "threshold": 0.10,
               "measured": 0.02, "passed": True},
        "G4": {"what": "worst material-group WAPE", "threshold": 0.15,
               "measured": 0.3802, "passed": False}})
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec),
                     anchored=_Anchored(float(baseline) * 1.05),
                     loaded=missed)
    outcome = got.outcomes[sp.ML]
    # It ran, so it has a number.
    assert outcome.status == rn.AVAILABLE
    assert outcome.scenario is not None
    # And the number arrives with the gate it missed.
    assert outcome.limitations
    assert "MISSED a predeclared acceptance gate" in outcome.limitations[0]
    assert "worst material-group WAPE" in outcome.limitations[0]
    assert "0.3802" in outcome.limitations[0]
    assert "was not relaxed to accommodate it" in outcome.limitations[0]
    assert "MISSED a predeclared acceptance gate" in outcome.describe()
    row = [r for r in got.compare()["own_population"]
           if r["method"] == sp.ML][0]
    assert row["limitations"]


def test_a_model_that_passed_every_gate_carries_no_limitation() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    book = rows()
    baseline = sum(r["ecl_sar_mn"] for r in book)
    clean = _Loaded({
        "G1": {"what": "out-of-time currency WAPE", "threshold": 0.10,
               "measured": 0.02, "passed": True}})
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec),
                     anchored=_Anchored(float(baseline) * 1.05),
                     loaded=clean)
    assert got.outcomes[sp.ML].limitations == ()
    assert "MISSED" not in got.outcomes[sp.ML].describe()


# ==========================================================================
# P8b -- one contract, stated once, and a verdict line that names a refusal
# ==========================================================================

def test_p8b_the_comparison_states_the_one_contract_it_compared_over() -> None:
    """Section 6: comparable means one book, period, release, cohort,
    revision, approval and baseline. Each of those was enforced somewhere and
    published nowhere, so a reader comparing two figures had to take the
    comparability on trust."""
    spec = spec_for(methods=(sp.DELTA, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "10",
                                     "stated_as": "10% higher"})
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    contract = got.compare()["contract"]
    assert contract["book"] == spec.source.domain_id
    assert contract["release_id"] == spec.source.release_id
    assert contract["release_fingerprint"] == spec.source.release_fingerprint
    assert contract["reporting_period"] == spec.source.reporting_period
    assert contract["cohort_id"] == spec.cohort.cohort_id
    assert contract["membership_hash"] == got.membership_hash
    assert contract["scenario_id"] == spec.scenario_id
    assert contract["scenario_version"] == spec.version
    assert contract["confirmed_digest"] == spec.confirmed_digest
    assert contract["cohort_size"] == got.cohort_size


def test_p8b_identical_baselines_are_checked_rather_than_asserted() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "10",
                                     "stated_as": "10% higher"})
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    comparison = got.compare()
    assert comparison["baselines_identical"] is True
    baselines = {r["baseline"] for r in comparison["own_population"]}
    assert len(baselines) == 1


def test_p8b_the_status_line_names_every_method_and_its_verdict() -> None:
    spec = spec_for(methods=(sp.DELTA, sp.ML, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "5",
                                     "stated_as": "5% higher"})
    book = rows()
    baseline = sum(r["ecl_sar_mn"] for r in book)
    got = rn.execute(spec, book, key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec),
                     anchored=_Anchored(float(baseline) * 1.08))
    line = got.status_line()
    for method in (sp.DELTA, sp.ML, sp.USER_DEFINED):
        assert rn.LABELS[method] in line
    assert line.count(";") == 2


def test_p8b_a_refused_method_carries_its_reason_into_the_status_line():
    """Section 6: do not insert zero and do not silently substitute another
    model. An unavailable method must be VISIBLE in the line, with why."""
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec),
                     ml_unavailable="G4 material-group WAPE 34.36% > 15%")
    line = got.status_line()
    assert rn.LABELS[sp.ML] in line
    assert "G4" in line and "34.36%" in line
    assert got.outcomes[sp.ML].scenario is None
    # Never a zero standing in for the estimate that was not produced.
    assert "0" not in [r["scenario"] for r in got.compare()["own_population"]]
    assert None in [r["scenario"] for r in got.compare()["own_population"]]


def test_p8b_the_status_line_lists_the_methods_in_the_declared_order() -> None:
    spec = spec_for(methods=(sp.USER_DEFINED, sp.DELTA),
                    user_assumption={"form": "relative", "value": "10",
                                     "stated_as": "10% higher"})
    got = rn.execute(spec, rows(), key="facility_id",
                     ecl_column="ecl_sar_mn", plan=plan_for(spec))
    line = got.status_line()
    assert line.index(rn.LABELS[sp.DELTA]) < \
        line.index(rn.LABELS[sp.USER_DEFINED]), (
            "the line follows run.ORDER, so a reader sees the same sequence "
            "whatever order the request happened to name the methods in")
