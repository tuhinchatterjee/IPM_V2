"""
P0.8 — "Do not display a polished but incomplete answer."

Two things are under test: the eight sections every complex answer has to
carry (Defect F), and the fourteen-check gate that refuses to show an answer
that is not client-presentable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import presentable as pg
from backend.orchestration import sections as sc

# ---------------------------------------------------------------- test doubles


@dataclass
class Obs:
    kind: str
    text: str
    facts: dict[str, Any] = field(default_factory=dict)


@dataclass
class Runtime:
    rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Filter:
    column: str
    values: list[str]


@dataclass
class Build:
    period: str = ""
    filters: list[Filter] = field(default_factory=list)
    executed: bool = False
    matches: list[Any] = field(default_factory=list)


@dataclass
class Written:
    headline: str = ""
    interpretation: str = ""
    notable: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)


@dataclass
class Invariants:
    checks: list[Any] = field(default_factory=list)
    failures: list[Any] = field(default_factory=list)


@dataclass
class Answered:
    question: str = ""
    build: Any = None
    runtime: Any = None
    written: Any = None
    invariants: Any = None
    scope: Any = None
    clarification: str = ""
    failure: str = ""
    failure_kind: str = ""
    result: Any = None

    @property
    def answered(self) -> bool:
        return self.result is not None or self.runtime is not None


def _ok() -> Answered:
    """An answer that should sail through every check."""
    return Answered(
        question="What is ECL by sector?",
        build=Build(period="Q2 2026"),
        runtime=Runtime(rows=[{"sector": "Contracting", "ecl": 100.0}]),
        written=Written(headline="ECL is USD 1.2bn.",
                        interpretation="Contracting is the largest sector."),
        invariants=Invariants(checks=[object()]),
    )


# ------------------------------------------------------------- the 8 sections


def test_every_answer_carries_all_eight_sections():
    """The defect was interpretations that were 'incomplete' and 'generic'.
    Prose with no required shape drifts toward the safe and the general."""
    reading = sc.compose(Build(), Runtime(rows=[{"a": 1}]),
                         [Obs("conclusion", "ECL rose to USD 1.2bn")])
    assert [s.key for s in reading.sections] == list(sc.ORDER)
    assert reading.complete is True
    assert reading.missing == []


def test_a_section_with_nothing_to_report_says_so_rather_than_vanishing():
    """A missing EXCEPTIONS section is an ambiguity: the reader cannot tell
    whether there were none or whether nobody looked. Same principle as
    'SKIPPED is not PASS'."""
    reading = sc.compose(Build(), Runtime(rows=[{"a": 1}]),
                         [Obs("conclusion", "ECL rose")])
    exceptions = reading.section(sc.EXCEPTIONS)
    assert exceptions.said is True
    assert exceptions.empty_finding is True
    assert "departs from the pattern" in exceptions.text
    assert reading.silent == []


def test_an_observation_feeds_exactly_one_section():
    """A driver observation appearing under both MAIN DRIVERS and MATERIALITY
    is how the same sentence ended up twice in one answer."""
    driver = Obs("driver", "Contracting accounts for USD 400mn")
    reading = sc.compose(Build(), Runtime(rows=[{"a": 1}]), [driver])
    holding = [s.key for s in reading.sections
               if "Contracting accounts" in s.text]
    assert holding == [sc.MAIN_DRIVERS]


def test_a_borrower_named_in_every_section_is_collapsed():
    """The repeated-name defect. Concentration, driver and exception all
    legitimately name the largest borrower; the repetition only exists once
    their sentences sit together, so it is fixed once, over the assembly."""
    name = "Al Rajhi Contracting"
    reading = sc.compose(
        Build(), Runtime(rows=[{"a": i} for i in range(9)]),
        [Obs("conclusion", f"{name} is the largest exposure"),
         Obs("concentration", f"{name} holds 31% of the total"),
         Obs("driver", f"{name} accounts for most of the increase"),
         Obs("exception", f"{name} sits well outside the pattern")])
    assert reading.deduplicated == [name]
    assert reading.prose().count(name) == sc.MAX_MENTIONS
    assert "the same borrower" in reading.prose()


def test_a_name_said_twice_is_left_alone():
    """Naming a borrower twice is English, not a bug. A de-duplication that
    fires on the second mention would strip information out of correct prose."""
    name = "Summit Power"
    reading = sc.compose(Build(), Runtime(rows=[{"a": 1}]),
                         [Obs("conclusion", f"{name} is the largest"),
                          Obs("driver", f"{name} drove the move")])
    assert reading.deduplicated == []
    assert reading.prose().count(name) == 2


def test_the_credit_risk_section_reads_the_governed_direction():
    """'Weak credit reasoning' in the defect list. A paragraph that treats
    every increase as a warning is not credit reasoning — ECL rising is bad
    news and ECL coverage rising is not, and the ontology already says which
    is which. Reading that field rather than keeping a second list here is the
    point: a duplicate opinion about the direction of deterioration is the one
    that inverts an answer, and it is not the one anybody thinks to check."""
    rising_ecl = sc.compose(
        *_governed("ecl"),
        [Obs("direction", "ECL rose over the quarter", {"change": 12.0})])
    risk = rising_ecl.section(sc.CREDIT_RISK)
    assert risk.facts["higher_is_worse"] is True
    assert risk.facts["deterioration"] is True
    assert "deterioration" in risk.text

    rising_coverage = sc.compose(
        *_governed("ecl_coverage"),
        [Obs("direction", "Coverage rose over the quarter", {"change": 3.0})])
    covered = rising_coverage.section(sc.CREDIT_RISK)
    assert covered.facts["higher_is_worse"] is False
    assert covered.facts["deterioration"] is False
    assert "improvement" in covered.text


def test_a_fall_in_a_higher_is_worse_measure_is_improvement():
    """The other half of the same rule. A gate that only got the rising case
    right would still invert every recovery."""
    reading = sc.compose(
        *_governed("ecl"),
        [Obs("direction", "ECL fell over the quarter", {"change": -8.0})])
    assert reading.section(sc.CREDIT_RISK).facts["deterioration"] is False


def test_the_credit_risk_section_asserts_nothing_when_no_concept_matched():
    """An honest silence. The alternative is a confident sentence about
    deterioration in a measure the ontology does not recognise, derived from
    what its column happens to be called."""
    reading = sc.compose(
        Build(), Runtime(rows=[{"headcount": 1.0}],
                         columns=[{"name": "headcount"}]),
        [Obs("direction", "Headcount rose", {"change": 4.0})])
    section = reading.section(sc.CREDIT_RISK)
    assert section.empty_finding is True
    assert "no deterioration is being asserted" in section.text


def test_a_position_with_no_movement_reports_no_deterioration():
    """A single-period result is a position, not a movement. Calling it either
    deterioration or improvement would be an assertion about a comparison that
    was never made."""
    reading = sc.compose(*_governed("ecl"),
                         [Obs("magnitude", "ECL is USD 1.2bn")])
    section = reading.section(sc.CREDIT_RISK)
    assert section.empty_finding is True
    assert "rather than a movement" in section.text


@dataclass
class Match:
    field: str
    concept: Any


def _governed(concept_id: str) -> tuple[Build, Runtime]:
    """A build and result for one real governed concept.

    Both are derived from the ontology rather than hand-written, so the column
    name, its semantic and its direction of deterioration all come from the
    same place the product reads them from. A hand-built schema here would test
    the test.
    """
    from backend.orchestration import concepts as cn

    concept = next(c for c in cn.CONCEPTS if c.id == concept_id)
    column = concept.default_candidate().field
    build = Build(matches=[Match(field=column, concept=concept)])
    runtime = Runtime(rows=[{column: 1.0}], columns=[{"name": column}])
    return build, runtime


def test_composing_survives_objects_it_does_not_understand():
    """A failure to write prose must never take the figures down with it. The
    passes read everything defensively, so an unrecognised build still yields
    the eight sections rather than an exception."""
    reading = sc.compose(object(), object(), [object()])  # type: ignore[arg-type]
    assert reading.complete is True


def test_a_reading_that_could_not_be_assembled_is_visibly_incomplete():
    """The fallback for a genuine assembly failure. It must not look like a
    complete answer — the gate downstream sees eight missing sections and
    refuses to call it presentable, which is the correct outcome."""
    reading = sc.Reading()
    assert reading.complete is False
    assert reading.missing == list(sc.ORDER)


# -------------------------------------------------------------------- the gate


def test_a_sound_answer_is_presentable():
    gate = pg.assess(_ok())
    assert gate.verdict == pg.SHOW
    assert gate.presentable is True
    assert gate.why == ""


def test_the_gate_runs_all_fourteen_checks():
    gate = pg.assess(_ok())
    assert [c.key for c in gate.checks] == list(pg.CHECKS)


def test_an_unsettled_objective_withholds_the_answer():
    """P0.3: 'Do not display a final answer while silently omitting
    objectives.' The coverage validator decides; the gate enforces."""
    from backend.orchestration import objectives as ob

    reading = ob.read("Which customers are in Stage 2, and what drove the "
                      "increase in their ECL?")
    coverage = ob.coverage(reading)
    gate = pg.assess(_ok(), coverage=coverage)
    assert gate.check(pg.OBJECTIVES).status == pg.FAIL
    assert gate.verdict == pg.WITHHOLD
    assert gate.presentable is False


def test_a_settled_objective_passes():
    from backend.orchestration import objectives as ob

    reading = ob.read("What is total ECL?")
    for objective in reading.objectives:
        objective.settle(ob.COMPLETE, result_reference="run-1")
    gate = pg.assess(_ok(), coverage=ob.coverage(reading))
    assert gate.check(pg.OBJECTIVES).status == pg.PASS


def test_ungrounded_prose_is_repaired_not_shown():
    """A figure the result does not contain is not a reason to hide correct
    figures — it is a reason to drop the sentence that invented one."""
    answer = _ok()
    answer.written.ungrounded = ["USD 4.4bn"]
    gate = pg.assess(answer)
    assert gate.check(pg.UNSUPPORTED).status == pg.FAIL
    assert gate.verdict == pg.REPAIR


def test_a_failing_invariant_withholds():
    answer = _ok()
    answer.invariants = Invariants(checks=[object()],
                                   failures=["ECL is negative for 3 rows"])
    gate = pg.assess(answer)
    assert gate.check(pg.CONTRADICTION).status == pg.FAIL
    assert gate.verdict == pg.WITHHOLD


def test_a_result_with_no_invariant_may_be_called_computed_but_not_validated():
    """SKIPPED is not PASS, applied to the answer. But an empty check list is a
    gap in the invariant library, not a broken figure — so it lowers the claim
    rather than hiding the result, the same shape as P0.9's assurance ceiling.
    """
    answer = _ok()
    answer.invariants = Invariants(checks=[])
    gate = pg.assess(answer)
    check = gate.check(pg.VALIDATIONS_REAL)
    assert check.status == pg.FAIL
    assert "not as validated" in check.detail
    assert gate.verdict == pg.REPAIR


def test_an_invariant_step_that_never_ran_withholds():
    """The other failure of the same check, and it is not the same thing: the
    pipeline did not complete, so the figures should not be shown."""
    answer = _ok()
    answer.invariants = None
    gate = pg.assess(answer)
    assert gate.check(pg.VALIDATIONS_REAL).status == pg.FAIL
    assert gate.verdict == pg.WITHHOLD


def test_a_check_can_lower_its_remedy_but_never_raise_it():
    """A ceiling, not a dial. A check that could escalate past what its key
    declares would make the remedy table a suggestion."""
    lowered = pg.Check(key=pg.CONTRADICTION, title="", status=pg.FAIL,
                       asks=pg.REPAIR)
    assert lowered.remedy == pg.REPAIR

    raised = pg.Check(key=pg.DECIMALS, title="", status=pg.FAIL,
                      asks=pg.WITHHOLD)
    assert raised.remedy == pg.REPAIR


def test_a_raw_float_in_prose_is_caught():
    """P0.12 caps display formatting at two decimals; prose has no formatter
    in front of it, which is how 2.6246841182876173 reached a sentence."""
    answer = _ok()
    answer.written.interpretation = "The share is 2.6246841182876173 per cent."
    gate = pg.assess(answer)
    assert gate.check(pg.DECIMALS).status == pg.FAIL
    assert gate.verdict == pg.REPAIR


def test_two_decimals_are_fine():
    answer = _ok()
    answer.written.interpretation = "The share is 2.62 per cent, up from 2.11."
    assert pg.assess(answer).check(pg.DECIMALS).status == pg.PASS


def test_a_version_string_is_not_a_raw_decimal():
    answer = _ok()
    answer.written.interpretation = "Computed under contract 1.4.2 at 09:30:15."
    assert pg.assess(answer).check(pg.DECIMALS).status == pg.PASS


def test_prose_naming_a_period_the_analysis_did_not_run_over_is_caught():
    answer = _ok()
    answer.build = Build(period="Q2 2026")
    answer.written.interpretation = "ECL rose sharply in Q4 2025."
    gate = pg.assess(answer)
    assert gate.check(pg.PERIOD).status == pg.FAIL
    assert "Q4 2025" in gate.check(pg.PERIOD).detail.replace("q4 2025", "Q4 2025")


def test_the_same_period_written_differently_is_the_same_period():
    """'2026-Q2' and 'Q2 2026' are one period. A check that failed on the
    spelling would fail every honest answer."""
    answer = _ok()
    answer.build = Build(period="2026-Q2")
    answer.written.interpretation = "ECL rose in Q2 2026."
    assert pg.assess(answer).check(pg.PERIOD).status == pg.PASS


def test_prose_discussing_a_sector_the_filter_excludes_is_caught():
    answer = _ok()
    answer.build = Build(period="Q2 2026",
                         filters=[Filter("sector", ["Contracting"])])
    answer.written.interpretation = "Real Estate drove most of the increase."
    gate = pg.assess(answer)
    assert gate.check(pg.POPULATION).status == pg.FAIL
    assert gate.verdict == pg.WITHHOLD


def test_a_terse_answer_that_does_not_restate_its_filters_is_not_wrong():
    """Only a positive contradiction fails. An answer that does not name its
    population is terse, not incorrect, and failing it would push the product
    toward padding."""
    answer = _ok()
    answer.build = Build(period="Q2 2026",
                         filters=[Filter("sector", ["Contracting"])])
    answer.written.interpretation = "The total rose over the quarter."
    assert pg.assess(answer).check(pg.POPULATION).status == pg.PASS


def test_an_unstated_material_limitation_is_caught():
    """An answer computed over a partial book that reads exactly like one
    computed over a whole one."""
    answer = _ok()
    answer.runtime = Runtime(rows=[{"a": 1}],
                             warnings=["4 borrowers excluded: missing ratings"])
    gate = pg.assess(answer)
    assert gate.check(pg.MISSING_STATED).status == pg.FAIL
    assert gate.verdict == pg.REPAIR


def test_a_stated_limitation_passes_even_when_reworded():
    """Requiring the warning verbatim would fail every honest answer."""
    answer = _ok()
    answer.runtime = Runtime(rows=[{"a": 1}],
                             warnings=["4 borrowers excluded: missing ratings"])
    answer.written.caveats = ["Four borrowers are excluded because their "
                              "ratings are missing."]
    assert pg.assess(answer).check(pg.MISSING_STATED).status == pg.PASS


def test_a_housekeeping_warning_does_not_have_to_be_narrated():
    answer = _ok()
    answer.runtime = Runtime(rows=[{"a": 1}], warnings=["query plan cached"])
    assert pg.assess(answer).check(pg.MISSING_STATED).status == pg.PASS


def test_an_invalid_chart_asks_for_a_repair():
    from backend.orchestration import viz_contract as vc

    verdict = vc.Verdict(ok=False, problems=[vc.Problem(
        check="axis_roles",
        detail="'Share Q2' is a measure and cannot be an axis")])
    gate = pg.assess(_ok(), visual_verdict=verdict)
    assert gate.check(pg.VISUALISATION).status == pg.FAIL
    assert gate.verdict == pg.REPAIR


def test_a_result_shown_with_no_plan_behind_it_withholds():
    answer = _ok()
    answer.build = None
    gate = pg.assess(answer)
    assert gate.check(pg.TRACE_AGREES).status == pg.FAIL
    assert gate.verdict == pg.WITHHOLD


def test_a_plan_that_claims_to_have_run_with_no_result_withholds():
    answer = _ok()
    answer.runtime = None
    answer.build = Build(executed=True)
    gate = pg.assess(answer)
    assert gate.check(pg.TRACE_AGREES).status == pg.FAIL


def test_an_uncategorised_failure_is_refused():
    """P0.10 gives ten categories. A failure with none of them is the
    anonymous 500 wearing a different coat."""
    answer = Answered(question="?", failure="Could not answer.")
    gate = pg.assess(answer)
    assert gate.check(pg.NO_UNEXPLAINED).status == pg.FAIL
    assert gate.verdict == pg.WITHHOLD


def test_a_categorised_failure_is_a_controlled_failure():
    answer = Answered(question="?", failure="The database is unreachable.",
                      failure_kind="PERSISTENCE")
    assert pg.assess(answer).check(pg.NO_UNEXPLAINED).status == pg.PASS


def test_an_answer_that_leads_with_no_figure_withholds():
    answer = _ok()
    answer.written = Written(headline="", interpretation="")
    gate = pg.assess(answer)
    assert gate.check(pg.DIRECT_ANSWER).status == pg.FAIL
    assert gate.verdict == pg.WITHHOLD


def test_a_clarification_is_itself_a_direct_answer():
    answer = Answered(question="?",
                      clarification="Which quarter did you mean?")
    assert pg.assess(answer).check(pg.DIRECT_ANSWER).status == pg.NOT_APPLICABLE


def test_repetition_is_advisory_and_never_withholds_a_correct_figure():
    """Repetition is ugly. It is not a reason to keep a correct figure from a
    credit officer, and a gate that treats it as one will be turned off."""
    answer = _ok()
    phrase = "the increase was driven largely by the contracting sector "
    answer.written.interpretation = phrase + phrase
    gate = pg.assess(answer)
    assert gate.check(pg.DUPLICATION).status == pg.FAIL
    assert gate.check(pg.DUPLICATION).mandatory is False
    assert gate.verdict == pg.SHOW


def test_the_worst_remedy_wins():
    answer = _ok()
    answer.written.ungrounded = ["USD 4.4bn"]          # REPAIR
    answer.invariants = Invariants(checks=[object()],
                                   failures=["negative ECL"])  # WITHHOLD
    assert pg.assess(answer).verdict == pg.WITHHOLD


def test_a_gate_that_cannot_run_withholds_rather_than_passing():
    """A gate that crashed has established nothing. Treating that as a pass is
    how a gate becomes decoration."""
    class Exploding:
        @property
        def written(self) -> Any:
            raise RuntimeError("boom")

    gate = pg.assess(Exploding())
    assert gate.error == "RuntimeError"
    assert gate.verdict == pg.WITHHOLD
    assert "could not confirm" in gate.why


def test_the_sentence_says_how_many_ran_not_only_how_many_passed():
    """A gate that skipped ten checks and passed four is not a gate that
    passed."""
    sentence = pg.assess(_ok()).sentence()
    assert "presentability checks passed" in sentence
    assert "did not apply" in sentence


def test_the_reason_is_written_for_a_reader():
    answer = _ok()
    answer.invariants = Invariants(checks=[object()],
                                   failures=["ECL is negative for 3 rows"])
    why = pg.assess(answer).why
    assert why
    assert "FAIL" not in why
    assert "no_contradictory_figures" not in why


def test_a_routine_join_warning_is_not_a_missing_limitation():
    """The gate reads the product's own judgement about which warnings a reader
    has to weigh. An as-of join carrying nulls appears under every joined
    answer; demanding a caveat for it would have the gate arguing with the
    answer rather than checking it — and would train readers to skip the
    warnings that matter."""
    answer = _ok()
    answer.runtime = Runtime(rows=[{"a": 1}], warnings=[
        "opening_asof_customer_ratings is an as-of join: each row takes the "
        "latest customer_ratings observation dated on or before its own "
        "period. Rows with no earlier observation carry nulls rather than "
        "being dropped."])
    assert pg.assess(answer).check(pg.MISSING_STATED).status == pg.PASS
