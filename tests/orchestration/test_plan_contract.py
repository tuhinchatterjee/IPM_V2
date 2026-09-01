"""
§20 and §21 — the strict planner document, and objective coverage.

    "Do not parse free-form prose into execution logic."
    "A final answer may not silently omit an objective."

Both sentences are about the same failure from different ends. A plan that
accepts prose where a list belongs will one day accept a condition disguised
as a dimension; a plan that loses an objective answers a question nobody
asked and looks complete doing it.
"""

from __future__ import annotations

import pytest

from backend.orchestration import objectives as ob
from backend.orchestration import plan_contract as pc


def _plan(**over) -> pc.Plan:
    base = dict(
        capability="ANALYSIS", conversation_action="NEW_REQUEST",
        objectives=[{"objective_id": "o1", "description": "total EAD",
                     "action": ob.AGGREGATE}],
        objective_coverage_plan={"o1": ob.PLANNED},
    )
    base.update(over)
    return pc.Plan(**base)


# ----------------------------------------------------------------- the shape


def test_the_document_carries_every_field_section_20_names():
    required = {
        "capability", "conversation_action", "same_turn_referents",
        "prior_context_referents", "objectives", "objective_coverage_plan",
        "concepts", "ambiguities", "entities", "cohorts", "metrics",
        "dimensions", "filters", "period", "grain", "population", "domains",
        "datasets", "relationships", "joins", "operations", "method",
        "analytical_plan", "invariants", "visualization", "clarification",
        "risk_flags", "confidence_components", "teaching_case_ids_used"}
    assert required == set(pc.FIELDS)
    assert required == set(pc.Plan().to_dict())


def test_the_schema_refuses_a_field_it_does_not_know():
    """A misspelled key is worse than a missing one: the field it was meant to
    be is silently empty, and the plan answers a slightly different question
    with complete confidence."""
    assert pc.SCHEMA["additionalProperties"] is False
    assert set(pc.SCHEMA["required"]) == set(pc.FIELDS)


def test_every_field_is_present_even_when_empty():
    """A caller reading `document.get("invariants")` and getting None cannot
    tell "no invariants apply" from "the planner forgot"."""
    empty = pc.Plan().to_dict()
    assert set(empty) == set(pc.FIELDS)
    assert all(name in empty for name in pc.FIELDS)


# ------------------------------------------------------------ strict reading


def test_prose_is_refused_where_a_list_belongs():
    """§20's sentence, at the point it is tempting to be helpful. Splitting
    "sector, segment" here is what makes "sector and segment where stage is 2"
    survive the next release."""
    _, problems = pc.read({name: [] for name in pc.FIELDS} |
                          {"dimensions": "sector, segment",
                           "capability": "ANALYSIS",
                           "conversation_action": "NEW_REQUEST",
                           "grain": ""})
    assert any(p.field == "dimensions" and "prose" in p.detail
               for p in problems)


def test_an_unknown_key_is_reported_rather_than_ignored():
    _, problems = pc.read({"capability": "ANALYSIS", "oops": 1})
    assert any(p.field == "oops" for p in problems)


def test_a_missing_field_is_reported():
    _, problems = pc.read({"capability": "ANALYSIS"})
    assert any(p.field == "objectives" and "missing" in p.detail
               for p in problems)


def test_a_reply_that_is_not_an_object_does_not_raise():
    """A planner returning something unusable is routine — the critic route
    exists for it — and an exception here turns a repairable reply into a
    failed request."""
    plan, problems = pc.read("I think you want total EAD by sector")
    assert plan == pc.Plan()
    assert problems


def test_a_well_formed_document_reads_back_unchanged():
    document = _plan(concepts=["exposure at default"],
                     dimensions=["sector"]).to_dict()
    plan, problems = pc.read(document)
    assert problems == []
    assert plan.to_dict() == document


# --------------------------------------------------------------- validation


def test_an_unknown_capability_is_refused():
    assert any(p.field == "capability"
               for p in pc.validate(_plan(capability="GUESS")))


def test_an_unknown_conversation_action_is_refused():
    assert any(p.field == "conversation_action"
               for p in pc.validate(_plan(conversation_action="MAYBE")))


def test_a_risk_flag_must_be_one_of_the_governed_ones():
    """A free-text flag cannot be counted, and §45 shows these on the
    Trace."""
    assert any(p.field == "risk_flags"
               for p in pc.validate(_plan(risk_flags=["SEEMS_ODD"])))
    assert pc.validate(_plan(risk_flags=["AMBIGUOUS_PERIOD"])) == []


def test_confidence_is_components_rather_than_a_number():
    """§20. One number cannot be argued with: a plan that is 0.4 because the
    period is ambiguous needs a different response from one that is 0.4
    because no governed method exists."""
    plan = _plan(confidence_components={"reading": 0.9,
                                        "referent_resolution": 0.2})
    assert pc.validate(plan) == []
    assert plan.confidence == 0.2


def test_confidence_is_the_weakest_component_and_never_the_mean():
    """A plan whose referent resolution is 0.2 and everything else is 1.0 is a
    plan about the wrong population. A mean would report it at 0.84."""
    plan = _plan(confidence_components={"reading": 1.0, "method_fit": 1.0,
                                        "data_availability": 1.0,
                                        "objective_coverage": 1.0,
                                        "referent_resolution": 0.2})
    assert plan.confidence == 0.2


def test_an_unknown_confidence_component_is_refused():
    assert any(p.field == "confidence_components"
               for p in pc.validate(_plan(confidence_components={"vibes": 1})))


def test_a_confidence_outside_zero_to_one_is_refused():
    assert any(p.field == "confidence_components"
               for p in pc.validate(_plan(confidence_components={
                   "reading": 1.5})))


def test_an_analysis_must_say_what_it_is_computing():
    assert any(p.field == "objectives"
               for p in pc.validate(_plan(objectives=[],
                                          objective_coverage_plan={})))


def test_a_clarifying_plan_must_say_what_it_asks():
    plan = _plan(conversation_action="CLARIFY")
    assert any(p.field == "clarification" for p in pc.validate(plan))


# ------------------------------------------------------- §21 coverage plan


def test_every_objective_needs_a_planned_coverage():
    """An objective with no planned status is one nothing will ever report
    on, which is the silent omission the validator exists to prevent."""
    plan = _plan(objectives=[
        {"objective_id": "o1", "description": "total", "action": ob.AGGREGATE},
        {"objective_id": "o2", "description": "rank", "action": ob.RANK}],
        objective_coverage_plan={"o1": ob.PLANNED})
    assert any(p.field == "objective_coverage_plan" and "o2" in p.detail
               for p in pc.validate(plan))


def test_a_coverage_entry_for_a_nonexistent_objective_is_refused():
    plan = _plan(objective_coverage_plan={"o1": ob.PLANNED,
                                          "ghost": ob.COMPLETE})
    assert any("ghost" in p.detail for p in pc.validate(plan))


def test_a_coverage_status_must_be_one_of_section_21s():
    plan = _plan(objective_coverage_plan={"o1": "PROBABLY"})
    assert any(p.field == "objective_coverage_plan" for p in pc.validate(plan))


def test_duplicate_objective_ids_are_refused():
    plan = _plan(objectives=[
        {"objective_id": "o1", "description": "a", "action": ob.AGGREGATE},
        {"objective_id": "o1", "description": "b", "action": ob.RANK}],
        objective_coverage_plan={"o1": ob.PLANNED})
    assert any(p.field == "objectives" and "duplicate" in p.detail
               for p in pc.validate(plan))


# ------------------------------------------------------ §21 the FAILED status


def test_failed_is_a_coverage_status_of_its_own():
    """Distinct from UNAVAILABLE, which means the data cannot answer it, and
    from PARTIAL, which means it was answered incompletely. Both of those read
    to a user as "we looked and this is what there is"."""
    assert ob.FAILED in ob.STATUSES
    assert ob.FAILED in ob.SETTLED


def test_a_failed_objective_is_reported_rather_than_hidden():
    """A failure that has been reported is not a silent omission. Hiding it
    would be."""
    reading = ob.read("What is total EAD by sector, and which sectors grew "
                      "fastest?")
    coverage = ob.coverage(reading)
    coverage.objectives[0].settle(ob.FAILED, note="the kernel refused")
    coverage.objectives[1].settle(ob.COMPLETE)

    assert coverage.presentable
    assert [o.objective_id for o in coverage.failed] == \
        [coverage.objectives[0].objective_id]
    assert "could not be completed" in coverage.sentence()
    assert "the kernel refused" in coverage.sentence()


def test_coverage_counts_by_status_rather_than_by_completeness():
    """§45 shows this table. The difference between an objective that failed
    and one the data cannot answer is the difference a reader needs."""
    reading = ob.read("What is total EAD by sector, and which sectors grew "
                      "fastest?")
    coverage = ob.coverage(reading)
    coverage.objectives[0].settle(ob.FAILED)
    counts = coverage.by_status()
    assert set(counts) == set(ob.STATUSES)
    assert counts[ob.FAILED] == 1
    assert counts[ob.PLANNED] == 1


def test_an_unsettled_objective_still_blocks_the_answer():
    reading = ob.read("What is total EAD by sector, and which sectors grew "
                      "fastest?")
    coverage = ob.coverage(reading)
    assert not coverage.presentable


# --------------------------------------------- §11 the decomposition itself


@pytest.mark.parametrize("question,expected", [
    # §11's own example. The semicolon separates two independent requests, and
    # read as one it can never be reported as partially answered.
    ("Decompose ECL change into exposure, Stage, PD, LGD and mix; show "
     "sector and customer contributors.", 2),
    # A serial instruction. Three verbs, three objectives.
    ("For Contracting, calculate total EAD, rank the borrowers by ECL, and "
     "say which moved most.", 3),
    ("What is total EAD by sector, and which sectors grew fastest?", 2),
])
def test_a_multi_objective_message_decomposes(question, expected):
    assert len(ob.read(question).objectives) == expected


@pytest.mark.parametrize("question", [
    # A fronted adverbial is not a boundary: "For every sector" is not an
    # objective anything could ever answer.
    "For every sector, calculate the Stage 2 EAD share.",
    # A list of measures inside one condition is one objective.
    "Which customers have worsening leverage and declining DSCR together "
    "with a rating downgrade?",
    "Show me the five largest Real Estate customers by EAD.",
])
def test_a_single_request_stays_one_objective(question):
    assert len(ob.read(question).objectives) == 1


# ------------------------------------------------------------- assembling it


def test_the_document_can_be_assembled_from_what_a_run_produced():
    """§45 and §46 show one document whether the model filled it or the
    deterministic reader did. A user comparing two runs is comparing like with
    like."""
    reading = ob.read("For Contracting, calculate total EAD, rank the "
                      "borrowers by ECL, and say which moved most.")
    plan = pc.from_run(coverage=ob.coverage(reading),
                       retrieved=["can-ecl-movement-000"],
                       invariants=["components_reconcile"],
                       confidence={"reading": 0.9,
                                   "objective_coverage": 0.6})
    assert len(plan.objectives) == 3
    assert set(plan.objective_coverage_plan.values()) == {ob.PLANNED}
    assert plan.teaching_case_ids_used == ["can-ecl-movement-000"]
    assert plan.confidence == 0.6
    assert pc.validate(plan) == []


def test_teaching_cases_appear_as_ids_and_never_as_content():
    """Repeating a pack inside the document would put a worked example in a
    Trace an ordinary user reads (§45)."""
    plan = pc.from_run(retrieved=["can-x-000", "mig-cx-y"])
    assert plan.teaching_case_ids_used == ["can-x-000", "mig-cx-y"]
    assert all(isinstance(v, str) for v in plan.teaching_case_ids_used)


def test_an_uncovered_objective_raises_its_own_risk_flag():
    reading = ob.read("What is total EAD by sector, and which sectors grew "
                      "fastest?")
    coverage = ob.coverage(reading)
    assert pc.coverage_flag(coverage) == ["OBJECTIVE_UNCOVERED"]
    for objective in coverage.objectives:
        objective.settle(ob.COMPLETE)
    assert pc.coverage_flag(coverage) == []


def test_an_ungoverned_risk_flag_is_dropped_on_assembly():
    plan = pc.from_run(risk_flags=["AMBIGUOUS_PERIOD", "SEEMS_ODD"])
    assert plan.risk_flags == ["AMBIGUOUS_PERIOD"]
