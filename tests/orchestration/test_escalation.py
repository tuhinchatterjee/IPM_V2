"""
§22-§29 — model roles, the Opus route, and never substituting silently.

The sentence the whole group turns on
--------------------------------------
    "Never silently downgrade from configured Opus-class role."

Everything here is a way of making that hold when something goes wrong: the
complex planner is its own configured role so it can be named; a direct signal
routes to it on its own so the threshold cannot miss it; the cascade caps the
attempts so a failure cannot loop into one; the unavailable policy makes every
branch carry a sentence, so a degraded answer cannot look like an ordinary one.
"""

from __future__ import annotations

import pytest

from backend.llm import roles
from backend.orchestration import routing as rt


class _Provider:
    name = "anthropic"
    supported_models = ("m-router", "m-planner", "m-complex")
    supports_structured_output = True
    context_tokens = 200000


@pytest.fixture
def env(monkeypatch):
    for name, _ in roles._ENV.values():
        monkeypatch.delenv(name, raising=False)
    for _, effort in roles._ENV.values():
        monkeypatch.delenv(effort, raising=False)
    monkeypatch.delenv(rt.POLICY_ENV, raising=False)
    return monkeypatch


# ============================================================ §22 the roles


def test_the_complex_planner_is_a_role_of_its_own():
    """An administrator who wants a stronger model for forensic work should
    not have to pay for it on every "what is total EAD by sector"."""
    assert roles.COMPLEX_PLANNER in roles.ROLES
    assert roles._ENV[roles.COMPLEX_PLANNER][0] == "AI_COMPLEX_PLANNER_MODEL"
    assert rt.ROLE_OF[rt.COMPLEX] == roles.COMPLEX_PLANNER


def test_every_role_has_its_own_model_and_effort_variable():
    models = {v[0] for v in roles._ENV.values()}
    efforts = {v[1] for v in roles._ENV.values()}
    assert len(models) == len(roles.ROLES)
    assert len(efforts) == len(roles.ROLES)
    assert all(name.startswith("AI_") for name in models | efforts)


def test_a_deployment_configured_before_the_split_still_works(env):
    """§22 asks for backward compatibility. Without the fallback the upgrade
    would move complex planning onto the shared default — which is the silent
    substitution §23 forbids, arriving through the back door."""
    env.setenv("AI_PLANNER_MODEL", "m-planner")
    assert roles.role(roles.COMPLEX_PLANNER).model == "m-planner"
    assert roles.role(roles.COMPLEX_PLANNER).inherited is True


def test_an_explicit_complex_model_wins_over_the_fallback(env):
    env.setenv("AI_PLANNER_MODEL", "m-planner")
    env.setenv("AI_COMPLEX_PLANNER_MODEL", "m-complex")
    configured = roles.role(roles.COMPLEX_PLANNER)
    assert configured.model == "m-complex"
    assert configured.inherited is False


def test_translation_is_declared_but_not_counted_as_active():
    """§22 lists it as optional and §49 does not need it yet. Reporting it as
    unconfigured would report a gap that is not one."""
    assert roles.TRANSLATION in roles.ROLES
    assert roles.TRANSLATION not in roles.ACTIVE_ROLES
    assert len(roles.all_roles()) == len(roles.ACTIVE_ROLES)


def test_no_model_id_is_written_into_the_code():
    """§23: "Do not embed these IDs as fixed behavior." The recommendation
    lives in .env.example and nowhere else."""
    import inspect

    for module in (roles, rt):
        source = inspect.getsource(module)
        assert "claude-" not in source, module.__name__


# ================================================== §29 provider validation


def test_a_configured_model_the_provider_does_not_list_blocks_preflight(env):
    env.setenv("AI_COMPLEX_PLANNER_MODEL", "m-nope")
    report = roles.preflight(_Provider())
    row = next(r for r in report["roles"]
               if r["role"] == roles.COMPLEX_PLANNER)
    assert row["state"] == roles.UNAVAILABLE
    assert not report["ok"]
    assert any("m-nope" in p for p in report["problems"])


def test_a_configured_model_the_provider_lists_passes(env):
    env.setenv("AI_ROUTER_MODEL", "m-router")
    report = roles.preflight(_Provider())
    row = next(r for r in report["roles"] if r["role"] == roles.ROUTER)
    assert row["state"] == roles.OK


def test_an_unconfigured_role_is_not_a_failure(env):
    """CreditProbe runs offline by design. A preflight that refused an
    unconfigured deployment would be refusing the supported way to run it."""
    report = roles.preflight(_Provider())
    assert report["ok"]
    assert {r["state"] for r in report["roles"]} == {roles.UNCONFIGURED}


def test_a_provider_that_publishes_no_model_list_leaves_ids_unverified(env):
    """Reporting that honestly beats either guessing they are fine or
    refusing to start."""
    class _Silent:
        name = "anthropic"
        supported_models = ()

    env.setenv("AI_ROUTER_MODEL", "whatever")
    report = roles.preflight(_Silent())
    row = next(r for r in report["roles"] if r["role"] == roles.ROUTER)
    assert row["state"] == roles.UNVERIFIED
    assert report["ok"]


def test_preflight_reports_effort_and_structured_output_support(env):
    env.setenv("AI_ROUTER_MODEL", "m-router")
    env.setenv("AI_ROUTER_EFFORT", "high")
    report = roles.preflight(_Provider())
    row = next(r for r in report["roles"] if r["role"] == roles.ROUTER)
    assert row["effort_supported"] is True
    assert row["structured_output"] is True
    assert row["context_tokens"] == 200000


# ====================================================== §24 the direct route


@pytest.mark.parametrize("question", [
    "Decompose the change in ECL in Contracting over the latest year.",
    "Show me the stage migration matrix for the last two quarters.",
    "What happens to ECL under the severe downside scenario?",
    "Give me a full review of the Contracting book.",
    "Attribute the movement order-neutrally across the drivers.",
    "We need to change the methodology for concentration.",
])
def test_a_direct_signal_routes_to_the_complex_planner_on_its_own(question):
    """§24. Not because these are worth many points — because a threshold
    reachable by three cheap signals could also be missed by one expensive
    one."""
    decision = rt.decide(question)
    assert decision.route == rt.COMPLEX
    assert decision.direct is True


def test_an_ordinary_question_stays_on_the_routine_route():
    decision = rt.decide("What is total EAD by sector in the latest quarter?")
    assert decision.route == rt.ROUTINE
    assert decision.direct is False


@pytest.mark.parametrize("situation,signal", [
    (rt.Situation(relationships=3), "relationships"),
    (rt.Situation(grains=2), "grains"),
    (rt.Situation(agents=3), "agents"),
    (rt.Situation(conflicting_findings=True), "conflict"),
    (rt.Situation(plan_rejected=True), "plan_rejected"),
    (rt.Situation(validation_failed=True), "validation_failed"),
    (rt.Situation(critical_case=True), "critical_case"),
    (rt.Situation(high_materiality=True), "materiality"),
])
def test_the_caller_can_force_the_complex_route_with_what_it_knows(situation,
                                                                   signal):
    """These are facts the router cannot read off the text, and a router that
    inferred "the previous plan failed" from wording would be inferring the
    one thing it must never get wrong."""
    decision = rt.decide("What is total EAD by sector?", situation=situation)
    assert decision.route == rt.COMPLEX
    assert signal in [s.id for s in decision.signals if s.direct]


def test_an_exhausted_budget_holds_the_complex_route_and_says_so():
    """§25 lists cost budget among the routing inputs. An answer planned by
    the routine model because the budget ran out is a different answer, and
    the Trace has to say so."""
    decision = rt.decide(
        "Decompose the change in ECL in Contracting.",
        situation=rt.Situation(cost_budget=1.0, cost_spent=1.0))
    assert decision.route == rt.ROUTINE
    assert decision.degraded == "budget"
    assert "budget" in decision.reason


def test_an_unset_budget_does_not_read_as_an_exhausted_one():
    assert not rt.Situation().budget_exhausted
    assert rt.Situation(cost_budget=2.0, cost_spent=0.5).budget_exhausted \
        is False


# ==================================================== §25 the routing record


def test_the_record_carries_everything_section_25_persists():
    decision = rt.decide("Decompose the change in ECL in Contracting.")
    record = decision.record()
    assert set(record) >= {
        "initial_route", "final_route", "route_score", "route_reasons",
        "model_role", "configured_model", "served_model", "effort",
        "escalation", "escalation_reason", "teaching_cases", "latency_ms",
        "input_tokens", "output_tokens", "cost_estimate"}


def test_the_initial_route_survives_every_escalation():
    """A turn that began routine and ended at the critic is a different fact
    from one that went straight to the complex planner, and an evaluation that
    cannot tell them apart cannot tune the threshold."""
    first = rt.decide("What is total EAD by sector?")
    assert first.route == rt.ROUTINE

    replanned = rt.escalate(first, "the validator rejected the plan")
    repaired = rt.escalate(replanned, "still rejected", to=rt.CRITIC)

    assert repaired.record()["initial_route"] == rt.ROUTINE
    assert repaired.record()["final_route"] == rt.CRITIC
    assert repaired.record()["escalation"] == rt.COMPLEX
    assert repaired.repairs == 2


def test_a_substituted_model_is_detected_rather_than_assumed_impossible():
    """§23 forbids substituting silently. It does not forbid a provider
    falling back on its own side, so the honest thing is to detect it."""
    decision = rt.Decision(configured_model="m-complex",
                           served_model="m-routine")
    assert decision.substituted
    assert decision.record()["substituted"] is True

    matched = rt.Decision(configured_model="m", served_model="m")
    assert not matched.substituted


# ======================================================== §27 the cascade


def test_the_cascade_permits_one_of_each_attempt():
    cascade = rt.Cascade()
    cascade.attempt(rt.ROUTINE)
    cascade.attempt(rt.COMPLEX)
    cascade.attempt(rt.CRITIC)
    cascade.repair_interpretation()
    assert cascade.model_calls == 4
    assert cascade.exhausted


@pytest.mark.parametrize("route", [rt.ROUTINE, rt.COMPLEX, rt.CRITIC])
def test_a_second_attempt_on_a_route_is_refused(route):
    """Every cap is a LOOP if it is not enforced: a critic that can be
    re-invoked on its own failure will be, and the failure that made the first
    pass necessary is usually still there on the fourth."""
    cascade = rt.Cascade()
    cascade.attempt(route)
    with pytest.raises(rt.CascadeExhausted):
        cascade.attempt(route)


def test_a_second_interpretation_repair_is_refused():
    cascade = rt.Cascade()
    cascade.repair_interpretation()
    with pytest.raises(rt.CascadeExhausted):
        cascade.repair_interpretation()


def test_the_cascade_records_the_path_it_took():
    """§45 shows this. A Trace that says "the critic ran" without saying why
    is a Trace that cannot be argued with."""
    cascade = rt.Cascade()
    cascade.note(rt.READ)
    cascade.note(rt.RETRIEVE, why="3 cases")
    cascade.attempt(rt.ROUTINE, why="first plan")
    cascade.attempt(rt.COMPLEX, why="validator rejected the join")
    steps = cascade.to_dict()["steps"]
    assert [s["stage"] for s in steps][:2] == [rt.READ, rt.RETRIEVE]
    assert "validator rejected the join" in [s["why"] for s in steps]


def test_the_stages_cover_section_27s_ladder():
    assert set(rt.STAGES) == {
        "reading", "teaching_retrieval", "plan", "plan_validation",
        "execute", "result_invariants", "interpretation",
        "interpretation_rubric", "present"}


# ============================== §28 what happens when the complex role fails


def test_the_default_policy_refuses_rather_than_downgrades(env):
    degraded = rt.when_complex_unavailable("rate limited")
    assert degraded.policy == rt.FAIL_SAFE
    assert not degraded.answerable
    assert "will not answer it with a different model" in degraded.message


def test_the_routine_fallback_is_marked_and_validated_more_strictly(env):
    """A weaker planner checked no harder is exactly the silent downgrade §28
    forbids, so the branch that allows an answer also demands stricter
    validation and a sentence on screen."""
    degraded = rt.when_complex_unavailable("unavailable",
                                           policy=rt.ROUTINE_WITH_WARNING)
    assert degraded.answerable
    assert degraded.route == rt.ROUTINE
    assert degraded.stricter_validation
    assert "provisional" in degraded.message


def test_the_queue_policy_does_not_answer(env):
    degraded = rt.when_complex_unavailable("unavailable",
                                           policy=rt.QUEUE_FOR_REVIEW)
    assert degraded.queue
    assert not degraded.answerable


def test_every_branch_carries_a_sentence(env):
    """An empty message is what a silent downgrade looks like from here."""
    for policy in rt.POLICIES:
        assert rt.when_complex_unavailable("x", policy=policy).message


def test_demo_safe_mode_forces_fail_safe_over_anything_configured(env):
    """The one place a degraded answer costs most is the room where nobody
    can tell."""
    env.setenv(rt.POLICY_ENV, rt.ROUTINE_WITH_WARNING)
    assert rt.unavailable_policy(demo_safe=True) == rt.FAIL_SAFE
    assert rt.when_complex_unavailable(
        "x", demo_safe=True, policy=rt.ROUTINE_WITH_WARNING).policy == \
        rt.FAIL_SAFE


def test_an_unrecognised_policy_falls_back_to_the_safe_one(env):
    env.setenv(rt.POLICY_ENV, "JUST_ANSWER_ANYWAY")
    assert rt.unavailable_policy() == rt.FAIL_SAFE


def test_a_configured_policy_is_honoured(env):
    env.setenv(rt.POLICY_ENV, rt.QUEUE_FOR_REVIEW)
    assert rt.unavailable_policy() == rt.QUEUE_FOR_REVIEW


# ============================ §26 officer level and model role are separate


def test_the_officer_level_and_the_model_role_are_different_things():
    """§26: "Do not equate Chief Orchestrator with Opus." One reflects
    business complexity, the other computational routing, and a request can
    be level 4 and answered without a model at all."""
    deterministic = rt.decide("Show it as a chart.", deterministic=True)
    assert deterministic.route == rt.DETERMINISTIC
    assert not deterministic.uses_model
    assert deterministic.role == ""


def test_the_env_example_documents_every_variable_the_code_reads():
    """§22: do not modify the user's .env — update .env.example. A variable
    the code reads and the example does not name is one nobody can set."""
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / ".env.example"
    text = example.read_text()
    for model_var, effort_var in roles._ENV.values():
        assert f"{model_var}=" in text
        assert f"{effort_var}=" in text
    assert f"{rt.POLICY_ENV}=" in text
