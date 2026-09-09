"""
Whether what the planner is allowed to ask for is what the executor can do.

The defect this suite exists for
--------------------------------
A live `claude-opus-5` plan grouped by `dominant_subcategory`. It is a real
field: in the dictionary, on the wide view, and advertised by the grain package
as one of the eleven groupings a planner may use. The validator approved it.
The fact builder then raised `KeyError('dominant_subcategory')`, because
`facts.LEVEL_FIELDS` — a second, separate list — did not have it. The whole
conversational turn died: no answer, no partial answer, no explanation.

`dominant_subcategory` was not an Opus invention. It is a legitimate partition
of the book — it is exactly what "which sub-category is driving the high-risk
population?" needs — and it is now executable, which is the right resolution of
the three the brief names.

But the string was never the defect. Two registries for one capability was. So
this suite tests the contract rather than the field: everything advertised is
executable, everything executable is advertised, the validator checks the
executable registry rather than a description of the domain, and nothing raw
escapes execution even if all of that were somehow wrong.
"""

from __future__ import annotations

import pytest

from backend.early_warning import executable as ex
from backend.early_warning import facts as ff
from backend.early_warning import grain as grain_mod
from backend.early_warning.conversation import execute as ex_mod
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import seam as seam_mod
from backend.early_warning.conversation import validate as val
from tests.early_warning.stub_provider import StubProvider, install

#: The question from the live Sonnet 5 / Opus 5 run that crashed.
LIVE_QUESTION = ("Why has Contracting deteriorated over six months, and is it "
                 "concentrated in a handful of names?")


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def package():
    return grain_mod.build("x")


# ------------------------------------------------------- one registry, once


def test_one_registry_serves_every_surface():
    """The root cause, asserted directly.

    Two lists that agree today and drift tomorrow is the same defect waiting
    to happen again, so the test is that there is one list.
    """
    assert dict(ff.LEVEL_FIELDS) == dict(ex.GROUPINGS)
    assert dict(grain_mod.GROUPINGS) == dict(ex.GROUPINGS)


def test_every_advertised_grouping_actually_executes(package):
    """The test that would have caught it.

    Not "is the name in a list" — run every one of them and see.
    """
    for field_name in package.groupings:
        pack = ff.level(field_name)
        assert pack.rows, f"{field_name} produced no groups"
        assert pack.figures["obligors"] > 0


def test_a_grouping_never_loses_part_of_the_book(package):
    """`dominant_subcategory` is empty for an obligor with no fired signal.

    A groupby drops those rows silently, and the answer then describes a
    partition of the book that is not the book — a table that looks complete
    and quietly excludes most of the population.
    """
    from backend.early_warning import v2_service as svc

    total = len(svc.borrower_month())
    for field_name in package.groupings:
        pack = ff.level(field_name)
        counted = sum(int(row["obligors"]) for row in pack.rows)
        assert counted == total, (
            f"grouping by {field_name} accounted for {counted} of {total} "
            f"obligors")


def test_the_nullable_grouping_says_so_rather_than_dropping_rows():
    pack = ff.level("dominant_subcategory")
    values = {str(row["dominant_subcategory"]) for row in pack.rows}
    assert ex.NO_VALUE in values, (
        "obligors with no fired signal are not represented at all")


def test_an_unsupported_level_is_a_named_refusal_not_a_bare_key_error():
    with pytest.raises(ff.UnsupportedLevel) as raised:
        ff.level("customer_name")
    assert "customer_name" in str(raised.value)
    assert "partitioned by" in str(raised.value)
    # Still a KeyError, so nothing that used to catch one stops catching it.
    assert isinstance(raised.value, KeyError)


# ------------------------------------------------- the validator's own check


def test_the_validator_checks_the_executable_registry(package):
    """Being described is not being executable.

    `customer_name` and a signal score are both readable columns. Neither is
    a partition of three hundred obligors, and the validator has to know the
    difference — otherwise it approves a plan that produces one group per
    obligor, or one the executor cannot run at all.
    """
    for unsupported in ("customer_name", "ews_score", "exposure",
                        "sig042_covenant_breach_event_score"):
        step = plan_mod.Step(analysis=plan_mod.GROUPING,
                             group_by=unsupported,
                             period=package.current_period)
        result = val.check(plan_mod.Plan(steps=[step]), package)
        assert not result.ok, f"{unsupported} passed as a grouping"
        assert "ungroupable" in [f.code for f in result.failures]


def test_the_grouping_that_crashed_now_validates_and_runs(package):
    step = plan_mod.Step(analysis=plan_mod.GROUPING,
                         group_by="dominant_subcategory",
                         period=package.current_period,
                         measures=list(plan_mod.BASE_MEASURES))
    result = val.check(plan_mod.Plan(steps=[step]), package)
    assert result.ok, [f.message for f in result.failures]

    executed = ex_mod.run(step)
    assert executed.row_count > 0
    assert executed.grain == "group_month"


@pytest.mark.parametrize("role,name", [
    (ex.MEASURE, "ews_score"),
    (ex.MEASURE, "sig042_covenant_breach_event_score"),
    (ex.FILTER, "sector"),
    (ex.ORDER_BY, "exposure"),
])
def test_a_readable_field_is_usable_in_the_roles_that_read(role, name):
    assert ex.supports(name, role=role)


def test_the_validator_checks_every_role_separately(package):
    """group_by, measure, filter and sort are four different questions."""
    step = plan_mod.Step(
        analysis=plan_mod.RANKING, period=package.current_period,
        measures=["ews_score", "not_a_field"],
        filters={"also_not_a_field": "x"},
        order_by="still_not_a_field")
    result = val.check(plan_mod.Plan(steps=[step]), package)
    messages = " ".join(f.message for f in result.failures)
    assert "not_a_field" in messages
    assert "also_not_a_field" in messages
    assert "still_not_a_field" in messages


def test_an_analysis_that_needs_a_subject_and_has_none_is_refused(package):
    """A borrower step with no obligor used to reach the executor and fail."""
    step = plan_mod.Step(analysis=plan_mod.BORROWER,
                         period=package.current_period)
    result = val.check(plan_mod.Plan(steps=[step]), package)
    assert "missing_subject" in [f.code for f in result.failures]
    assert not result.repairable, (
        "which obligor is a question for the reader, not something to pick")


# --------------------------------------------- the governed semantic mapping


@pytest.mark.parametrize("written,means", [
    ("grade", "internal_rating"),
    ("rating", "internal_rating"),
    ("stage", "ifrs9_stage"),
    ("IFRS 9 stage", "ifrs9_stage"),
    ("industry", "sector"),
    ("rm", "relationship_manager"),
    ("sub_category", "dominant_subcategory"),
    ("dominant sub category", "dominant_subcategory"),
    ("layer", "dominant_layer"),
    ("severity", "ews_band"),
])
def test_a_canonical_alias_is_normalised_once_and_recorded(written, means,
                                                           package):
    step = plan_mod.Step(analysis=plan_mod.GROUPING, group_by=written,
                         period=package.current_period)
    result = val.check(plan_mod.Plan(steps=[step]), package)
    assert step.group_by == means
    assert result.ok, [f.message for f in result.failures]
    assert any(n["from"] == written and n["to"] == means
               for n in result.normalised), (
        "the rename is not on the trace, so the reader cannot reconcile the "
        "plan against their own question")


def test_the_same_word_means_different_things_in_different_roles():
    """"Group by utilisation" cannot mean the percentage.

    Three hundred obligors have three hundred utilisation percentages, so as
    a partition it means the band. As a measure it means the percentage.
    """
    assert ex.normalise("utilisation", role=ex.GROUP_BY) == "utilisation_band"
    assert ex.normalise("utilisation_pct", role=ex.MEASURE) == "utilisation_pct"


def test_an_unknown_name_is_not_guessed_at():
    """No fuzzy matching. A name the map does not know comes back unchanged,
    so the refusal names what the planner actually wrote."""
    assert ex.normalise("quantum_risk_index") == "quantum_risk_index"
    assert ex.normalise("band_of_brothers", role=ex.GROUP_BY) == \
        "band_of_brothers"


def test_the_substring_rule_is_gone(package):
    """It matched `band` to whichever field name happened to sort first."""
    assert plan_mod._resolve_grouping("sub", package) == ""
    assert plan_mod._resolve_grouping("rating_band_thing", package) == ""


# ----------------------------------------------------- the repair packet


def test_an_unsupported_grouping_returns_the_packet_the_brief_specifies(
        package):
    step = plan_mod.Step(analysis=plan_mod.GROUPING, group_by="customer_name",
                         period=package.current_period)
    plan = plan_mod.Plan(steps=[step])
    result = val.check(plan, package)
    packet = val.failure_packet(plan, result, package, question="x")

    unsupported = packet["unsupported"]
    assert unsupported
    entry = unsupported[0]
    assert entry["requested_grouping"] == "customer_name"
    assert entry["status"] == "unsupported"
    assert set(entry["allowed_groupings"]) == set(ex.GROUPINGS)
    assert entry["relevant_available_fields"]


def test_the_repair_packet_does_not_carry_two_thousand_field_names(package):
    """A repair prompt that is mostly a field list is a repair that costs
    more than the question did."""
    step = plan_mod.Step(analysis=plan_mod.RANKING,
                         period=package.current_period,
                         measures=["ews_rating"])
    plan = plan_mod.Plan(steps=[step])
    packet = val.failure_packet(plan, val.check(plan, package), package)
    assert len(packet["relevant_available_fields"]) <= 40
    assert packet["field_count"] > 2000, (
        "the packet should still say how large the domain is")


# ------------------------------------------- nothing raw escapes execution


def test_an_unsupported_grouping_reaching_execution_is_governed():
    """The last boundary.

    Validation is meant to catch this and now does. A control whose only
    guarantee is that the check upstream is complete is a control that ends
    a conversation the day the check is not.
    """
    step = plan_mod.Step(analysis=plan_mod.GROUPING, group_by="customer_name")
    with pytest.raises(ex_mod.ExecutionError) as raised:
        ex_mod.run(step)
    assert raised.value.code == "ungroupable"
    assert set(raised.value.offered) == set(ex.GROUPINGS)


def test_an_unexpected_failure_in_execution_is_governed(monkeypatch):
    def _explode(*_args, **_kwargs):
        raise ValueError("something nobody anticipated")

    monkeypatch.setattr(ex_mod.ff, "portfolio", _explode)
    step = plan_mod.Step(analysis=plan_mod.POPULATION)
    with pytest.raises(ex_mod.ExecutionError) as raised:
        ex_mod.run(step)
    assert raised.value.code in ("execution_failed", "no_data")


def test_a_turn_survives_a_failure_nothing_anticipated(monkeypatch):
    """No KeyError, no 500, and the thread still persists."""
    def _explode(*_args, **_kwargs):
        raise KeyError("dominant_subcategory")

    monkeypatch.setattr(ex_mod.ff, "level", _explode)
    monkeypatch.setattr(ex_mod.ff, "portfolio", _explode)
    monkeypatch.setattr(ex_mod.ff, "movement", _explode)
    monkeypatch.setattr(ex_mod.ff, "diagnosis", _explode)

    turn = pipe.answer(LIVE_QUESTION)
    assert pipe.THREAD_PERSISTED in turn.stages
    assert turn.rolling_summary is not None
    assert isinstance(turn.answer.get("direct"), str)
    assert turn.answer["direct"]


# ------------------------------------- the live question, end to end


def test_the_live_question_completes_every_stage(monkeypatch):
    """The exact question from the real-provider run that crashed."""
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)

    for stage in (pipe.REQUEST_STARTED, pipe.SONNET_PASS_1,
                  pipe.SONNET_PASS_2, pipe.CONTEXT_BUILT,
                  pipe.FUNCTIONALITY_SELECTED, pipe.PLAN_CREATED,
                  pipe.VALIDATION_PASSED, pipe.EXECUTION_COMPLETE,
                  pipe.RESULT_PACKET, pipe.SUFFICIENCY_COMPLETE,
                  pipe.FINAL_ANSWER, pipe.SUMMARY_UPDATED,
                  pipe.THREAD_PERSISTED):
        assert stage in turn.stages, f"{stage} never fired"

    assert turn.selection["selected_functionality"] == "early_warning"
    assert turn.answer["answered"] is True
    assert turn.packet is not None and turn.packet.steps
    # Every stage that can reach a model did, including the two closing ones.
    assert set(turn.engines.values()) == {seam_mod.MODEL}
    assert turn.engines[pipe.FINAL_ANSWER] == seam_mod.MODEL
    assert turn.engines[pipe.SUMMARY_UPDATED] == seam_mod.MODEL
    assert turn.budget["model_calls_failed"] == 0


def test_the_live_question_survives_a_plan_that_groups_by_the_crashing_field(
        monkeypatch):
    """The plan that killed the turn, run again.

    It is now executable, so the right outcome is that it simply runs.
    """
    from backend.early_warning import v2_service as svc

    period = svc.latest_period()
    install(monkeypatch, StubProvider(replies={"plan_the_analysis": {
        "intent": "diagnosis",
        "output_grain": "group_month",
        "steps": [
            {"analysis": "grouping", "domain": "early_warning",
             "group_by": "dominant_subcategory", "period": period,
             "measures": ["ews_score", "exposure"],
             "rationale": "which node is carrying it"},
            {"analysis": "concentration", "domain": "early_warning",
             "period": period, "filters": {"sector": "Contracting"},
             "rationale": "whether it is a handful of names"},
        ]}}))
    turn = pipe.answer(LIVE_QUESTION)

    assert turn.answer["answered"] is True
    ran = {step["analysis"] for step in turn.packet.steps}
    assert "grouping" in ran
    assert turn.budget["spent"]["repairs"] == 0, (
        "a plan that is now executable should not need repairing")


# ------------------------------------------------------- adversarial plans


def _planned(monkeypatch, step: dict) -> pipe.Turn:
    """One turn whose planner returns exactly this one step.

    The step carries a published period, because an unperiodised exposure sum
    is its own (correct) refusal and would mask the field under test.
    """
    from backend.early_warning import v2_service as svc

    install(monkeypatch, StubProvider(replies={"plan_the_analysis": {
        "output_grain": "population_month",
        "steps": [dict({"domain": "early_warning",
                        "period": svc.latest_period(),
                        "rationale": "the adversarial case"}, **step)]}}))
    return pipe.answer(LIVE_QUESTION)


@pytest.mark.parametrize("step,outcome", [
    ({"analysis": "grouping", "group_by": "moon_phase"}, "refused"),
    ({"analysis": "grouping", "group_by": "grade"}, "normalised"),
    ({"analysis": "ranking", "measures": ["quantum_risk_index"]}, "refused"),
    ({"analysis": "grouping", "group_by": "customer_name"}, "refused"),
    ({"analysis": "grouping", "group_by": "ews_score"}, "refused"),
    ({"analysis": "ranking", "filters": {"collateral_value": 1}}, "refused"),
    ({"analysis": "ranking", "measures": ["ead"]}, "normalised"),
], ids=["nonexistent_grouping", "aliased_real_field", "nonexistent_measure",
        "valid_field_wrong_type_for_grouping", "a_measure_as_a_partition",
        "source_domain_field_not_materialised", "aliased_measure"])
def test_an_adversarial_plan_is_normalised_or_repaired_before_execution(
        monkeypatch, step, outcome):
    """Each must be canonically normalised, or rejected and repaired.

    Never executed as written, and never a crash.
    """
    turn = _planned(monkeypatch, step)

    assert turn.answer["answered"] is True, "the turn did not survive"
    assert pipe.THREAD_PERSISTED in turn.stages

    if outcome == "normalised":
        assert not [e for e in turn.events
                    if e.stage == pipe.VALIDATION_FAILED], (
            "a governed alias should not need a repair")
    else:
        failed = [e for e in turn.events if e.stage == pipe.VALIDATION_FAILED]
        assert failed, "the unsupported field reached execution"
        assert pipe.REPAIR_ATTEMPTED in turn.stages

    # Whatever happened, only executable fields reached the executor.
    for planned in (turn.packet.plan or {}).get("steps", []):
        if planned.get("group_by"):
            assert planned["group_by"] in ex.GROUPINGS, planned["group_by"]
        for measure in planned.get("measures") or []:
            assert measure in ex.readable(), measure


def test_a_repair_spends_from_the_same_ledger(monkeypatch):
    turn = _planned(monkeypatch, {"analysis": "grouping",
                                   "group_by": "moon_phase"})
    assert turn.budget["spent"]["repairs"] >= 1
    assert turn.budget["model_calls_charged"] <= \
        turn.budget["ceilings"]["model_calls"]
    # And the closing stages still ran on a model.
    assert turn.engines[pipe.FINAL_ANSWER] == seam_mod.MODEL
    assert turn.engines[pipe.SUMMARY_UPDATED] == seam_mod.MODEL
