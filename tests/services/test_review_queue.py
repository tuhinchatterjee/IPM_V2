"""
P0.14 and P0.15 — model routing honesty, and learning that goes through a person.

    "If all roles inherit one model, report that honestly."
    "No automatic production self-training."

Both sentences are about not letting an architecture diagram stand in for what
the product does.
"""

from __future__ import annotations

import pytest

from backend.llm import roles
from backend.orchestration import routing as rt

# ---------------------------------------------------------------------------
# P0.14 — model routing and the critic
# ---------------------------------------------------------------------------


def test_no_provider_or_model_name_is_hard_coded_in_the_routing():
    """P0.14: do not hard-code a provider/model name. Routes name ROLES, and a
    role resolves to whatever an administrator configured."""
    for route, role_name in rt.ROLE_OF.items():
        assert route in rt.ROUTES
        assert role_name in roles.ROLES


def test_every_role_is_configurable_by_its_own_variable():
    """Four roles in a settings page imply four models. Each has to be
    separately settable or the page is describing something that cannot
    happen."""
    for name in roles.ROLES:
        model_var, effort_var = roles._ENV[name]
        assert model_var.startswith("AI_")
        assert effort_var.startswith("AI_")
    assert len({v[0] for v in roles._ENV.values()}) == len(roles.ROLES)


def test_a_complex_request_routes_to_the_planner_and_a_repair_to_the_critic():
    """P0.14: complex multi-domain / multi-objective requests must use the
    complex planner and critic routes where configured."""
    # §22: the complex planner is a role of its own. An administrator who
    # wants a stronger model for forensic work should not have to pay for it
    # on every "what is total EAD by sector".
    assert rt.ROLE_OF[rt.COMPLEX] == roles.COMPLEX_PLANNER
    assert rt.ROLE_OF[rt.CRITIC] == roles.CRITIC

    decision = rt.decide(
        "For every sector, calculate Stage 2 EAD divided by total sector EAD, "
        "compare it with four quarters ago, rank sectors by the change, and "
        "say which borrowers drove it.")
    assert decision.route == rt.COMPLEX, decision.reason


def test_the_router_counts_objectives_with_the_decomposer_not_a_pattern():
    """Two places counting the same thing is one too many, and the pattern was
    the worse of the two: it wanted ", and <wh-word>", so a request ending
    ", and SAY which borrowers drove it" scored as one objective and took the
    routine route."""
    found = rt.signals(
        "Calculate total ECL, rank the borrowers by exposure, and say which "
        "of them moved the most.")
    objectives = next((s for s in found if s.id == "objectives"), None)
    assert objectives is not None
    assert objectives.weight >= 3


def test_the_router_counts_more_liberally_than_the_answer_does():
    """The two consumers have opposite tolerances. Over-routing a simple
    question costs a second; under-routing a compound one produces a confident
    wrong answer in front of a client — so the router may split where the
    decomposer that governs the ANSWER deliberately does not."""
    from backend.orchestration import objectives as ob

    question = ("For every sector, calculate the Stage 2 share, compare it "
                "with last year, and rank sectors by the change.")
    assert len(ob.read(question).objectives) < rt._objective_count(question)


def test_a_plain_question_gains_no_objectives_signal():
    """A liberal count that fires on everything would route every question to
    the expensive model, which is the same as having no router."""
    for question in ("What is total ECL?", "Show me ECL by sector.",
                     "How many customers are in Stage 2?",
                     "Show the top 10 borrowers by exposure at default."):
        assert rt.decide(question).score == 0, question


def test_a_simple_request_does_not_pay_for_the_complex_route():
    decision = rt.decide("What is total ECL?")
    assert decision.route in (rt.DETERMINISTIC, rt.ROUTINE)


def test_escalation_records_why():
    """P0.14: record routing/escalation in the Trace. A route that changed
    with no reason recorded is a route nobody can review."""
    first = rt.decide("What is total ECL by sector?")
    escalated = rt.escalate(first, "The first plan failed validation: no join")
    assert escalated.route == rt.COMPLEX
    assert "failed validation" in escalated.reason
    assert escalated.repairs > first.repairs


def test_the_roles_report_says_plainly_when_they_all_resolve_to_one_model():
    """The ordinary case: three of four variables are blank. Four role names
    beside four percentages implies four models, and saying so when it is one
    is the difference between an honest report and an architecture diagram."""
    described = roles.describe()
    assert set(described) >= {"roles", "all_inherited", "distinct_models",
                              "differentiated", "summary"}
    # The active roles, not every declared one: TRANSLATION is declared for
    # §49 and unused until Arabic exists, and reporting it as unconfigured
    # would report a gap that is not one.
    assert len(described["roles"]) == len(roles.ACTIVE_ROLES)
    if described["all_inherited"]:
        assert described["differentiated"] is False
        # Whatever the wording, the summary must say the roles are not
        # differentiated — either they inherit one id, or none is configured
        # and the provider's own default serves every stage.
        said = described["summary"].lower()
        assert "inherit" in said or "no model id is configured" in said
        assert "routing" in said


def test_the_roles_report_never_carries_a_key():
    """A settings page that shows model configuration must not show what
    authorises it."""
    import json

    text = json.dumps(roles.describe()).lower()
    for secret in ("sk-", "api_key", "anthropic_api_key", "bearer"):
        assert secret not in text


# ---------------------------------------------------------------------------
# P0.15 — the Intelligence Review Queue
# ---------------------------------------------------------------------------

from tests.conftest import database_available  # noqa: E402

db = pytest.mark.skipif(not database_available(),
                        reason="needs the platform database")

if database_available():
    from sqlalchemy import text  # noqa: E402

    from backend.db.engine import SessionLocal  # noqa: E402
    from backend.services import review_queue as rq  # noqa: E402


@pytest.fixture
def session():
    s = SessionLocal()
    s.execute(text("DELETE FROM review_queue_items"))
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        s.execute(text("DELETE FROM review_queue_items"))
        s.commit()
        s.close()


def _spec() -> dict[str, object]:
    return {"capability": "ANALYSIS",
            "concepts": ["expected credit loss"],
            "invariants": ["filter_equality"],
            "forbidden": ["whole_portfolio"]}


@db
def test_a_failure_is_captured_with_what_the_product_did(session):
    """Capture is deliberately cheap and deliberately incomplete: it takes what
    the product already knows, and the correction is what a reviewer adds. A
    capture step that demanded the correction up front would be a form, and
    nobody fills in a form at the moment they find a bug."""
    item = rq.capture(session, question="Show me Stage 2 customers",
                      failure_layer="same_turn_referent",
                      observed_problem="answered about the whole book",
                      source="cockpit")
    session.commit()
    assert item.status == rq.CAPTURED
    assert item.regression_status == rq.NOT_TESTED
    assert item.corrected_reading == {}
    assert item in rq.pending(session)


@db
def test_an_item_cannot_be_approved_without_being_reviewed(session):
    """A state machine rather than a free status column: 'approved' arrived at
    by any path is a claim about a review that no review happened."""
    item = rq.capture(session, question="q")
    session.commit()
    with pytest.raises(rq.NotPermitted, match="cannot become"):
        rq.approve(session, item.id, corrected_reading={"intent": "ANALYSIS"},
                   corrected_expectations=_spec(), note="looks right")


@db
def test_an_approval_needs_the_corrected_reading_and_a_reason(session):
    """Each argument refuses something. An approval with no reasoning is a
    click, and the curriculum inherits it for as long as the case survives."""
    item = rq.capture(session, question="q")
    rq.start_review(session, item.id)
    session.commit()

    with pytest.raises(rq.NotPermitted, match="corrected reading"):
        rq.approve(session, item.id, corrected_reading={},
                   corrected_expectations=_spec(), note="fine")
    with pytest.raises(rq.NotPermitted, match="corrected expectations"):
        rq.approve(session, item.id, corrected_reading={"intent": "ANALYSIS"},
                   corrected_expectations={}, note="fine")
    with pytest.raises(rq.NotPermitted, match="reason"):
        rq.approve(session, item.id, corrected_reading={"intent": "ANALYSIS"},
                   corrected_expectations=_spec(), note="   ")


@db
def test_an_approved_item_becomes_a_curriculum_case(session):
    """The whole point of the queue: an approved failure becomes something the
    evaluator RUNS, in the same shape as every other case, rather than a
    paragraph somebody has to read and reinterpret.

    The service returns plain data and the FACTORY builds the case. The
    dependency runs factory to backend and never the other way: a backend
    module that can import the curriculum can reach the sealed holdout in one
    more line."""
    item = rq.capture(session, question="Show me Stage 2 customers and "
                                        "which of them are in Contracting")
    rq.start_review(session, item.id)
    rq.approve(session, item.id,
               corrected_reading={"intent": "ANALYSIS",
                                  "concepts": ["expected credit loss"]},
               corrected_expectations=_spec(),
               note="the second clause is about the first clause's cohort",
               user_id=None)
    session.commit()

    from intelligence_factory import reviewed

    built = reviewed.case(rq.specification(item))
    assert built.id == item.curriculum_case_id
    assert built.turns[0].question == item.question
    assert built.turns[0].capability == "ANALYSIS"
    assert "whole_portfolio" in built.turns[0].forbidden
    assert built in reviewed.cases(rq.specifications(session))


@db
def test_an_unapproved_item_is_not_a_case(session):
    """An unadjudicated failure in the curriculum is the product learning from
    its own mistakes, which is how a wrong answer becomes the standard."""
    from intelligence_factory import reviewed

    item = rq.capture(session, question="q")
    session.commit()
    with pytest.raises(rq.NotPermitted, match="Only an approved item"):
        rq.specification(item)
    assert reviewed.cases(rq.specifications(session)) == []


@db
def test_an_approved_item_has_not_been_shown_to_pass(session):
    """NOT_TESTED is not PASSING. An approved correction nobody has run is a
    description of an intention."""
    item = rq.capture(session, question="q")
    rq.start_review(session, item.id)
    rq.approve(session, item.id, corrected_reading={"intent": "ANALYSIS"},
               corrected_expectations=_spec(), note="because")
    session.commit()
    assert item.regression_status == rq.NOT_TESTED
    assert rq.summary(session)["approved_but_never_run"] == 1


@db
def test_a_regression_result_only_exists_once_there_is_something_to_run(session):
    item = rq.capture(session, question="q")
    session.commit()
    with pytest.raises(rq.NotPermitted, match="approved"):
        rq.record_regression(session, item.id, status=rq.PASSING)

    rq.start_review(session, item.id)
    rq.approve(session, item.id, corrected_reading={"intent": "ANALYSIS"},
               corrected_expectations=_spec(), note="because")
    rq.record_regression(session, item.id, status=rq.FAILING)
    session.commit()
    assert item.regression_status == rq.FAILING
    assert item.regression_checked_at is not None


@db
def test_an_approved_item_is_settled(session):
    """Terminal by design: an approved case lives in the curriculum, and
    changing it there is a change to the curriculum rather than a re-decision
    in the queue."""
    item = rq.capture(session, question="q")
    rq.start_review(session, item.id)
    rq.approve(session, item.id, corrected_reading={"intent": "ANALYSIS"},
               corrected_expectations=_spec(), note="because")
    session.commit()
    with pytest.raises(rq.NotPermitted, match="settled"):
        rq.reject(session, item.id, note="changed my mind")


@db
def test_a_rejection_needs_a_reason_and_can_be_reopened(session):
    """A rejection nobody explained is one somebody re-files next month."""
    item = rq.capture(session, question="q")
    session.commit()
    with pytest.raises(rq.NotPermitted, match="reason"):
        rq.reject(session, item.id, note="")
    rq.reject(session, item.id, note="working as designed: the filter was ours")
    session.commit()
    assert item.status == rq.REJECTED
    rq.start_review(session, item.id)
    assert item.status == rq.UNDER_REVIEW


@db
def test_the_summary_says_nothing_trains_a_model(session):
    """P0.15: no automatic production self-training. Said in the summary the
    operations screen reads, because the alternative is a reader assuming the
    ordinary thing."""
    rq.capture(session, question="q")
    session.commit()
    shown = rq.summary(session)
    assert shown["self_training"] is False
    assert "trains a model" in shown["rule"]
    assert shown["awaiting_review"] == 1
    assert shown["in_curriculum"] == 0


@db
def test_capture_from_an_answer_records_what_the_user_was_looking_at(session):
    """Reads the same objects the answer surface reads, so what lands in the
    queue is what was on screen rather than a reconstruction of it."""
    class Gate:
        verdict = "WITHHOLD"
        why = "a computed figure contradicts what was asked"

    class Build:
        summary = "expected credit loss by sector"
        shape = "aggregate"
        datasets = ["ifrs9_staging"]
        filters = [("sector", "Contracting")]
        period = "Q2 2026"

    class Runtime:
        row_count = 12
        warnings = ["4 borrowers excluded"]
        run_id = "run-1"

    class Answered:
        question = "What is ECL in Contracting?"
        reading = None
        build = Build()
        runtime = Runtime()
        gate = Gate()
        failure_kind = ""

    item = rq.from_answer(session, Answered(), problem="wrong sector",
                          layer="plan")
    session.commit()
    assert item.observed_plan["shape"] == "aggregate"
    assert item.observed_result["presentability"] == "WITHHOLD"
    assert item.observed_result["row_count"] == 12
    assert item.run_id == "run-1"
    assert item.status == rq.CAPTURED
