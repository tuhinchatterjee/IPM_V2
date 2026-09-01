"""
The Investigation Factory: the Part B engines, composed into one run.

Why this module exists
----------------------
Everything else in this package is a part. A blueprint library that nothing
compiles, a DAG nothing executes, a contradiction diagnostic nothing calls and
a completion rule nothing checks are eight good decisions that never meet, and
the failure they were each built to prevent happens in the gaps between them.

So this is the pipeline, in the order the brief puts it:

    select a blueprint (§69)
      -> compile it to a bounded DAG (§92)
        -> run the deterministic engines (§72-§77)
          -> detect and diagnose contradictions (§81-§84)
            -> raise the hypotheses and run the challenge pass (§70, §71)
              -> build the interpretation contract (§78)
                -> choose and critique the visualization (§86-§88)
                  -> score presentability (§94)
                    -> check the completion rules (§93)

Two properties matter more than the order
------------------------------------------
**Nothing is skipped quietly.** Each stage records what it did on the Run, and
the completion check reads the Run rather than being told. A pipeline where a
stage can be omitted and the completion check told it ran is a pipeline with
no completion check.

**A failure stops the polish, not the work.** A failed stage blocks what
depends on it and leaves everything else running, so a reader gets the
findings that did survive, labelled as findings. §93's "no polished answer
from a failed investigation" is about the POLISH; abandoning the analysis
would throw away work that was correct.

What this module does not do
-----------------------------
It does not call a provider, run SQL, or read the lake. Every engine is handed
its inputs and returns a structure. That makes the whole pipeline testable
offline, which is the only way the §97-§99 acceptance cases can run in CI —
and it means the integration in Part D is a matter of supplying real inputs
rather than of re-implementing any of this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.judgment import blueprints as bp
from backend.judgment import contradictions as cd
from backend.judgment import evidence as ev
from backend.judgment import hypotheses as hy
from backend.judgment import interpretation as it
from backend.judgment import observations as ob
from backend.judgment import presentability as pb
from backend.judgment import task_dag as td
from backend.judgment import visual_critic as vc
from backend.judgment import visual_grammar as vg

FACTORY_VERSION = "1.0.0"

# The stages, named so a Trace and the Studio can list them and a reader can
# see which one an investigation stopped at.
SELECT = "SELECT_BLUEPRINT"
COMPILE = "COMPILE_DAG"
EXECUTE = "RUN_ENGINES"
DIAGNOSE = "DIAGNOSE_CONTRADICTIONS"
CHALLENGE = "CHALLENGE_PASS"
INTERPRET = "BUILD_INTERPRETATION"
VISUALISE = "CHOOSE_VISUALIZATION"
PRESENT = "SCORE_PRESENTABILITY"
COMPLETE = "CHECK_COMPLETION"

STAGES: tuple[str, ...] = (SELECT, COMPILE, EXECUTE, DIAGNOSE, CHALLENGE,
                           INTERPRET, VISUALISE, PRESENT, COMPLETE)

STAGE_DOES: dict[str, str] = {
    SELECT: "Choose the blueprint a competent analyst would work from.",
    COMPILE: "Turn it into a bounded graph of tasks with their dependencies.",
    EXECUTE: "Run the deterministic engines and register their facts.",
    DIAGNOSE: "Find signals that disagree and run the fifteen diagnostics.",
    CHALLENGE: "Attack the conclusion before a reader does.",
    INTERPRET: "Decide which sections the evidence supports.",
    VISUALISE: "Choose a chart the shape supports and check it.",
    PRESENT: "Score the answer against the eighteen dimensions.",
    COMPLETE: "Decide whether this may be shown as an answer at all.",
}


@dataclass
class Stage:
    """What one stage of the pipeline did."""

    stage: str
    ran: bool = False
    detail: str = ""
    #: Anything the stage produced that a later one needs. Kept on the Run
    #: rather than passed along, so the completion check reads what happened
    #: instead of being told.
    output: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "does": STAGE_DOES.get(self.stage, ""),
                "ran": self.ran, "detail": self.detail}


@dataclass
class Inputs:
    """Everything the pipeline is handed. Nothing is fetched here.

    Deliberately explicit: a factory that could reach for its own data would
    be a factory whose behaviour depends on what happened to be in the lake
    when the test ran, and the §97-§99 acceptance cases could not run offline.
    """

    question: str = ""
    request: bp.Request | None = None
    graph: ev.Graph = field(default_factory=ev.Graph)
    observations: ob.Set = field(default_factory=ob.Set)
    signals: list[cd.Signal] = field(default_factory=list)
    #: check_id -> (outcome, detail), for the diagnostics that could run.
    diagnostics: dict[str, tuple[str, str]] = field(default_factory=dict)
    hypotheses: hy.Tree | None = None
    challenge: hy.Pass | None = None
    #: What each blueprint objective produced: objective id -> status.
    objective_results: dict[str, str] = field(default_factory=dict)
    #: Reasons for objectives that could not run.
    unavailable: dict[str, str] = field(default_factory=dict)
    visual_shape: str = ""
    visual_inputs: vg.Inputs | None = None
    built_charts: list[vc.Chart] = field(default_factory=list)
    table: vc.Table | None = None
    periods: int = 1
    question_is_open: bool = True
    narrative: str = ""
    #: Rubric outcomes the pipeline cannot compute itself — repetition,
    #: concision, actionability. Absent ones stay UNCHECKED, never PASS.
    rubric: dict[str, str] = field(default_factory=dict)
    trace_consistent: bool = False
    validations_passed: bool = False


@dataclass
class Run:
    """One investigation, and everything it did."""

    question: str = ""
    stages: list[Stage] = field(default_factory=list)
    blueprint: bp.Selection | None = None
    dag: td.Dag | None = None
    contradictions: list[cd.Diagnosis] = field(default_factory=list)
    challenge: hy.Pass | None = None
    contract: it.Contract | None = None
    visual: vc.Rendered | None = None
    presentability: pb.Score | None = None
    completion: td.Completion | None = None

    def stage(self, name: str) -> Stage | None:
        return next((s for s in self.stages if s.stage == name), None)

    @property
    def ran(self) -> list[str]:
        return [s.stage for s in self.stages if s.ran]

    @property
    def stopped_at(self) -> str:
        """The first stage that did not run, or "" when all did."""
        return next((s.stage for s in self.stages if not s.ran), "")

    @property
    def shown_as_answer(self) -> bool:
        """§93 and §94 together: an answer, or findings.

        Both have to agree. A complete investigation whose narrative asserts
        an ungrounded figure is not presentable, and a presentable narrative
        over a half-failed investigation is the polished answer §93 forbids.
        """
        return bool(self.completion and self.completion.complete
                    and self.presentability
                    and self.presentability.verdict() == pb.SHOW)

    def sentence(self) -> str:
        if self.shown_as_answer:
            return "Shown as an answer."
        parts: list[str] = []
        if self.completion and not self.completion.complete:
            parts.append(self.completion.sentence())
        if self.presentability and self.presentability.verdict() != pb.SHOW:
            parts.append(self.presentability.sentence())
        if self.stopped_at:
            parts.append(
                f"The pipeline stopped at {self.stopped_at}: "
                + (self.stage(self.stopped_at).detail
                   if self.stage(self.stopped_at) else ""))
        return " ".join(parts) or "Shown as findings."

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FACTORY_VERSION,
            "question": self.question,
            "stages": [s.to_dict() for s in self.stages],
            "ran": self.ran,
            "stopped_at": self.stopped_at,
            "blueprint": self.blueprint.to_dict() if self.blueprint else None,
            "dag": self.dag.to_dict() if self.dag else None,
            "contradictions": [d.to_dict() for d in self.contradictions],
            "challenge": self.challenge.to_dict() if self.challenge else None,
            "contract": self.contract.to_dict() if self.contract else None,
            "visual": self.visual.to_dict() if self.visual else None,
            "presentability": (self.presentability.to_dict()
                               if self.presentability else None),
            "completion": (self.completion.to_dict() if self.completion
                           else None),
            "shown_as_answer": self.shown_as_answer,
            "sentence": self.sentence(),
        }


def _record(run: Run, stage: str, *, ran: bool, detail: str = "",
            output: Any = None) -> None:
    run.stages.append(Stage(stage=stage, ran=ran, detail=detail,
                            output=output))


def compile_dag(blueprint: bp.Blueprint, inputs: Inputs) -> td.Dag:
    """§92: a blueprint compiled to a bounded DAG.

    One SCOPE task, one DATA_AVAILABILITY task, then one task per objective,
    then the engines that depend on them, then the challenge and the
    synthesis. The shape is fixed because the DEPENDENCIES are what the DAG
    is for; a blueprint that could declare an arbitrary graph could declare
    one where the synthesis runs first.
    """
    dag = td.Dag(blueprint_id=blueprint.blueprint_id)

    dag.add(td.Task("scope", td.SCOPE, objective="pin the population, period "
                                                 "and grain",
                    method="scope_frame"))
    dag.add(td.Task("availability", td.DATA_AVAILABILITY,
                    objective="establish what data exists",
                    method="availability", dependencies=["scope"]))

    analysis_ids: list[str] = []
    for index, objective in enumerate(blueprint.objectives):
        task_id = f"obj-{index:02d}"
        dag.add(td.Task(task_id, td.ANALYSIS, objective=objective.statement,
                        method=objective.engine or f"objective_{index}",
                        dependencies=["availability"]))
        analysis_ids.append(task_id)

    if analysis_ids:
        dag.add(td.Task("drivers", td.DRIVER,
                        objective="decompose the movement into contributions",
                        method="driver_decomposition",
                        dependencies=analysis_ids))
        dag.add(td.Task("breadth", td.BREADTH,
                        objective="decide broad or concentrated",
                        method="breadth", dependencies=["drivers"]))
        dag.add(td.Task("persistence", td.PERSISTENCE,
                        objective="decide sustained or a spike",
                        method="persistence", dependencies=analysis_ids))
        dag.add(td.Task("contradiction", td.CONTRADICTION,
                        objective="diagnose signals that disagree",
                        method="contradiction_diagnostics",
                        dependencies=analysis_ids))
        dag.add(td.Task("validation", td.VALIDATION,
                        objective="check the mandatory invariants",
                        method="invariants", dependencies=analysis_ids))
        dag.add(td.Task("challenge", td.CHALLENGE,
                        objective="attack the conclusion",
                        method="challenge_pass",
                        dependencies=["drivers", "breadth", "persistence"],
                        differs_because="the challenge pass recomputes the "
                                        "decomposition on the matched "
                                        "population"))
        dag.add(td.Task("synthesis", td.SYNTHESIS,
                        objective="say what it means",
                        method="synthesis",
                        dependencies=["challenge", "contradiction",
                                      "validation"]))
        dag.add(td.Task("visualization", td.VISUALIZATION,
                        objective="choose and check the picture",
                        method="visual_grammar",
                        dependencies=["synthesis"]))
    return dag.seal()


def _run_dag(dag: td.Dag, inputs: Inputs) -> None:
    """Drive the graph to completion from the supplied results.

    `ready()` decides the order, so a stage cannot run before its inputs
    exist even if the caller supplied its result. That is the point of
    compiling a graph rather than a list.
    """
    objective_of = {t.task_id: t for t in dag.tasks}
    while True:
        available = dag.ready()
        if not available:
            break
        for task in available:
            key = task.task_id
            objective = objective_of[key].objective
            # The challenge node's status is whether a challenge pass
            # actually ran, not whether the caller listed it. A completed
            # node with no Pass behind it would satisfy §93's challenge
            # condition from an empty task.
            if key == "challenge" and not (inputs.challenge
                                           and inputs.challenge.complete):
                dag.record(key, td.FAILED,
                           note="the challenge pass did not run")
                continue
            if key in inputs.unavailable:
                dag.record(key, td.UNAVAILABLE, note=inputs.unavailable[key])
                continue
            status = inputs.objective_results.get(key, td.COMPLETED)
            if status == td.UNAVAILABLE:
                dag.record(key, td.UNAVAILABLE,
                           note=inputs.unavailable.get(
                               key, "the data this objective needs is not "
                                    "held"))
            elif status == td.FAILED:
                dag.record(key, td.FAILED, note=f"{objective} failed")
            else:
                dag.record(key, td.COMPLETED,
                           facts=sorted(inputs.graph.facts),
                           observations=[o.observation_id
                                         for o in inputs.observations.ordered()])


def investigate(inputs: Inputs) -> Run:
    """The whole pipeline. Every stage recorded, nothing skipped quietly."""
    run = Run(question=inputs.question)

    # ---- §69 select ----------------------------------------------------
    request = inputs.request or bp.Request(question=inputs.question)
    selection = bp.select(request)
    run.blueprint = selection
    # An unconfident match is not a selection. §69 already says to treat a
    # low-scoring blueprint's objective list as a starting point rather than
    # a fit; compiling a graph from it anyway would produce a complete,
    # coherent investigation of a question nobody asked.
    chosen = (bp.get(selection.selected_blueprint_id)
              if selection.confident else None)
    _record(run, SELECT, ran=chosen is not None,
            detail=(f"selected {chosen.business_name}" if chosen else
                    "no blueprint matched the request confidently: "
                    + "; ".join(selection.selection_reasons[:1])),
            output=selection)

    # ---- §92 compile ---------------------------------------------------
    if chosen is None:
        for stage in STAGES[1:]:
            _record(run, stage, ran=False,
                    detail="no blueprint was selected, so there was nothing "
                           "to compile")
        run.completion = td.completion(td.Dag())
        run.presentability = pb.score({})
        return run

    run.dag = compile_dag(chosen, inputs)
    _record(run, COMPILE, ran=True,
            detail=f"{len(run.dag.tasks)} tasks", output=run.dag)

    # ---- §72-§77 execute -----------------------------------------------
    _run_dag(run.dag, inputs)
    failed = run.dag.failed
    _record(run, EXECUTE, ran=not failed,
            detail=(f"{len(failed)} task(s) failed: "
                    + ", ".join(t.objective for t in failed))
            if failed else f"{len(run.dag.by_status(td.COMPLETED))} completed")

    # ---- §81-§84 diagnose ----------------------------------------------
    pairs = cd.detect(inputs.signals)
    for pair in pairs:
        diagnosis = cd.diagnose(pair)
        for check_id, (outcome, detail) in inputs.diagnostics.items():
            diagnosis.record(check_id, outcome, detail=detail)
        run.contradictions.append(cd.conclude(diagnosis))
    _record(run, DIAGNOSE, ran=True,
            detail=(f"{len(pairs)} contradiction(s): "
                    + ", ".join(d.outcome for d in run.contradictions))
            if pairs else "no signals disagreed")

    # ---- §70, §71 challenge --------------------------------------------
    run.challenge = inputs.challenge
    _record(run, CHALLENGE, ran=bool(run.challenge and run.challenge.complete),
            detail=(run.challenge.sentence() if run.challenge
                    else "the challenge pass did not run"))

    # ---- §78 interpret --------------------------------------------------
    run.contract = it.build(inputs.observations, periods=inputs.periods,
                            question_is_open=inputs.question_is_open)
    _record(run, INTERPRET, ran=not run.contract.abstain,
            detail=(run.contract.abstain_reason if run.contract.abstain
                    else f"{len(run.contract.present)} sections present"),
            output=run.contract)

    # ---- §86-§88 visualise ----------------------------------------------
    if inputs.built_charts:
        run.visual = vc.render(inputs.built_charts, inputs.table)
    elif inputs.visual_shape and inputs.visual_inputs:
        chosen = vg.select(inputs.visual_shape, inputs.visual_inputs)
        run.visual = vc.Rendered(chart=chosen.chosen)
    _record(run, VISUALISE, ran=bool(run.visual),
            detail=(run.visual.verdict.why() if run.visual
                    and run.visual.verdict else
                    (f"showing {run.visual.chart}" if run.visual
                     else "nothing was rendered")),
            output=run.visual)

    # ---- §94 present ----------------------------------------------------
    run.presentability = _score(run, inputs)
    _record(run, PRESENT,
            ran=run.presentability.verdict() == pb.SHOW,
            detail=run.presentability.sentence(), output=run.presentability)

    # ---- §93 complete ---------------------------------------------------
    run.completion = td.completion(
        run.dag,
        hypotheses_recorded=bool(inputs.hypotheses
                                 and inputs.hypotheses.hypotheses),
        validations_passed=inputs.validations_passed,
        facts=len(inputs.graph.usable()),
        grounded=run.presentability.get(pb.GROUNDING).outcome == pb.PASS,
        visual_approved=bool(run.visual and run.visual.verdict
                             and run.visual.verdict.approved),
        limitations=len(inputs.observations.by_type(ob.LIMITATION)),
        trace_consistent=inputs.trace_consistent)
    _record(run, COMPLETE, ran=run.completion.complete,
            detail=run.completion.sentence(), output=run.completion)
    return run


def _score(run: Run, inputs: Inputs) -> pb.Score:
    """§94's rubric, from what the pipeline actually produced.

    Everything the pipeline can determine, it determines. Everything it
    cannot — concision, repetition, actionability, which are properties of
    prose — is left to the caller, and absent means UNCHECKED. Filling them
    in with PASS would make the rubric report on dimensions nobody looked at.
    """
    outcomes: dict[str, str] = dict(inputs.rubric)
    details: dict[str, str] = {}

    def has_visual() -> bool:
        return bool(run.visual and run.visual.verdict)

    outcomes.setdefault(
        pb.DIRECTNESS,
        pb.PASS if run.contract and not run.contract.abstain else pb.FAIL)
    outcomes.setdefault(
        pb.OBJECTIVE_COMPLETENESS,
        pb.PASS if run.dag and not run.dag.outstanding else pb.FAIL)
    outcomes.setdefault(
        pb.MATERIALITY,
        pb.PASS if run.contract and run.contract.get(it.MATERIALITY)
        and run.contract.get(it.MATERIALITY).state == it.PRESENT
        else pb.NOT_APPLICABLE)
    outcomes.setdefault(
        pb.DRIVER_QUALITY,
        pb.PASS if run.dag and run.dag.get("drivers")
        and run.dag.get("drivers").satisfied else pb.UNCHECKED)
    outcomes.setdefault(
        pb.BREADTH_CONCENTRATION,
        pb.PASS if run.dag and run.dag.get("breadth")
        and run.dag.get("breadth").satisfied else pb.NOT_APPLICABLE)
    outcomes.setdefault(
        pb.PERSISTENCE,
        pb.PASS if inputs.periods >= 2 else pb.NOT_APPLICABLE)
    outcomes.setdefault(
        pb.EXCEPTIONS,
        pb.PASS if inputs.observations.by_type(ob.EXCEPTION)
        else pb.NOT_APPLICABLE)

    # A contradiction that reached a conclusion the diagnostics support
    # passes — including UNRESOLVED, which is a reported outcome and the
    # honest one when fifteen checks clear. DATA_INSUFFICIENT does not: it
    # means the contradiction was found and could not be diagnosed, and
    # showing the answer anyway is netting it away.
    diagnosed = all(d.outcome != cd.DATA_INSUFFICIENT
                    for d in run.contradictions)
    outcomes.setdefault(
        pb.CONTRADICTIONS,
        pb.PASS if diagnosed else pb.FAIL)
    if not diagnosed:
        details[pb.CONTRADICTIONS] = (
            "a contradiction was found and too few diagnostics could run to "
            "say anything about it")

    outcomes.setdefault(
        pb.VISUAL_VALIDITY,
        (pb.PASS if has_visual() and run.visual.verdict.approved else pb.FAIL)
        if run.visual else pb.NOT_APPLICABLE)
    if run.visual and has_visual() and not run.visual.verdict.approved:
        details[pb.VISUAL_VALIDITY] = run.visual.verdict.why()

    # Grounding is computed where a narrative exists and is UNCHECKED where
    # none does — never PASS. An answer nobody wrote has not been checked.
    if inputs.narrative:
        built = it.pack(inputs.question, inputs.observations, inputs.graph,
                        run.contract or it.Contract())
        grounding = it.check(inputs.narrative, built)
        outcomes.setdefault(pb.GROUNDING,
                            pb.PASS if grounding.ok else pb.FAIL)
        if not grounding.ok:
            details[pb.GROUNDING] = (
                "figures with no fact behind them: "
                + ", ".join(grounding.ungrounded)) if grounding.ungrounded \
                else "the narrative is over its length cap"

    outcomes.setdefault(pb.TRACE_CONSISTENCY,
                        pb.PASS if inputs.trace_consistent else pb.FAIL)
    outcomes.setdefault(
        pb.LIMITATIONS,
        pb.PASS if inputs.observations.by_type(ob.LIMITATION) else pb.FAIL)
    return pb.score(outcomes, details=details)


__all__ = ["CHALLENGE", "COMPILE", "COMPLETE", "DIAGNOSE", "EXECUTE",
           "FACTORY_VERSION", "INTERPRET", "Inputs", "PRESENT", "Run",
           "SELECT", "STAGES", "STAGE_DOES", "Stage", "VISUALISE",
           "compile_dag", "investigate"]
