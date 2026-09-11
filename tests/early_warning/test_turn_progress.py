"""
What the reader is shown while a turn runs, and whether it is true.

The defect this suite exists for
--------------------------------
An Early Warning turn takes fifteen to sixty seconds and the screen showed a
grey rectangle for all of it. A grey rectangle is indistinguishable from a
hang: the reader cannot tell whether CreditProbe is working, stuck, or about
to fail, so they wait through it or reload and pay for the turn twice.

The turn always knew what it was doing. Every stage emits an event. What was
missing was a way to read those events before the call returned, and a
vocabulary that a credit officer rather than an engineer could read.

What is asserted here
---------------------
Three things, and they are the three that make a progress panel worth having.

**It is true.** Every visible step comes from a real pipeline event. A step the
turn never ran never appears, the order on screen is the order the pipeline
ran in, and a turn that executed nothing reports no analyses. There is no
timer anywhere in the mapping, which is why `build` is a pure function of the
event list and these tests can hand it one.

**It says nothing it should not.** No stage name, model family, provider,
token count, schema error or budget counter reaches the reader. The vocabulary
endpoint publishes every sentence the panel can say, and a test reads all of
them looking for exactly that.

**It costs nothing.** No model call is made to produce a label, and observing
a turn does not change what the turn does — same answer, same ledger, same
executions, whether anybody is watching or not.
"""

from __future__ import annotations

import pytest

from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import execute as ex
from backend.early_warning.conversation import live as live_mod
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import progress as prog
from tests.early_warning.stub_provider import StubProvider, install

LIVE_QUESTION = ("Why has Contracting deteriorated over six months, and is it "
                 "concentrated in a handful of names?")
WHAT_IF = "What happens to ECL if oil falls 30%?"


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def period() -> str:
    from backend.early_warning import v2_service as svc

    return svc.latest_period()


def _seven_step_plan(period: str) -> dict:
    """Seven valid analyses under a six-execution ceiling.

    The same catalogue `test_execution_budget.py` uses, because a plan whose
    steps the validator rejects would exercise the repair path instead of the
    ceiling and quietly stop testing what this says it tests.
    """
    from backend.early_warning import v2_service as svc

    periods = list(svc.periods())
    earlier = periods[max(0, periods.index(period) - 6)]
    catalogue = [
        {"analysis": "population"},
        {"analysis": "movement", "comparison_period": earlier},
        {"analysis": "diagnosis"},
        {"analysis": "grouping", "group_by": "sector"},
        {"analysis": "concentration"},
        {"analysis": "ranking", "measures": ["ews_score"]},
        {"analysis": "comparison", "comparison_period": earlier,
         "group_by": "sector"},
    ]
    return {"intent": "diagnosis", "output_grain": "population_month",
            "steps": [dict({"domain": "early_warning", "period": period,
                            "rationale": "one of the planned analyses"}, **s)
                      for s in catalogue]}


def _panel(turn: pipe.Turn, *, active: bool = False) -> prog.Progress:
    return prog.build(turn.events, turn_id=turn.request_id, active=active)


def _keys(panel: prog.Progress) -> list[str]:
    return [s.key for s in panel.steps]


def _status(panel: prog.Progress, key: str) -> str:
    return next((s.status for s in panel.steps if s.key == key), "")


# ------------------------------------------------- the ordinary analytical turn


def test_the_panel_follows_the_pipeline_in_order(monkeypatch):
    """§32's ordering, as the reader sees it."""
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(LIVE_QUESTION))
    keys = _keys(panel)

    expected = [prog.UNDERSTANDING, prog.SCOPING, prog.EVIDENCE,
                prog.OWNERSHIP, prog.PLANNING, prog.VALIDATING,
                prog.ANALYSING, prog.CHECKING, prog.INTERPRETING,
                prog.CONTEXT, prog.COMPLETE]
    it = iter(keys)
    assert all(step in it for step in expected), keys


def test_every_visible_step_came_from_an_event(monkeypatch):
    """Nothing is on screen that the turn did not report.

    The defence against a progress panel that drifts into a storyboard: a
    step exists because an event produced it, so a step the pipeline stopped
    emitting would disappear rather than keep animating.
    """
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    panel = _panel(turn)

    produced = set()
    for event in turn.events:
        if event.stage == pipe.STAGE_STARTED:
            produced.add(str(event.detail.get("step")))
        elif event.stage in prog.EVENT_STEPS:
            produced.add(prog.EVENT_STEPS[event.stage])
    produced.add(prog.FALLBACK)  # derived from the interpretation's own engine

    assert set(_keys(panel)) <= produced, (
        set(_keys(panel)) - produced)


def test_the_analyses_that_ran_are_the_analyses_shown(monkeypatch):
    """§8, and its one prohibition: do not invent an analysis."""
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    panel = _panel(turn)
    step = next(s for s in panel.steps if s.key == prog.ANALYSING)

    ran = [e.detail["analysis"] for e in turn.events
           if e.stage == pipe.EXECUTION_STEP]
    reported = [s.key for s in step.substeps if s.status != prog.WAITING]
    assert sorted(reported) == sorted(ran), (reported, ran)
    assert all(s.label for s in step.substeps)


def test_each_analysis_carries_its_own_business_sentence(monkeypatch):
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(LIVE_QUESTION))
    step = next(s for s in panel.steps if s.key == prog.ANALYSING)

    for sub in step.substeps:
        assert sub.label != sub.key, "an analysis was shown by its type name"
        assert sub.label[0].isupper()


def test_a_step_reports_the_time_it_actually_took(monkeypatch):
    """Durations are measured, never estimated. §7."""
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    panel = _panel(turn)

    for step in panel.steps:
        if step.elapsed_ms is None:
            continue
        assert step.elapsed_ms >= 0
        assert step.started_ms is not None
        assert step.completed_ms is not None
        assert step.completed_ms <= turn.events[-1].at_ms


def test_the_completion_line_counts_the_real_analyses(monkeypatch):
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    panel = _panel(turn)
    ran = sum(1 for e in turn.events
              if e.stage == pipe.EXECUTION_STEP and e.detail.get("ok"))

    line = prog.completion_line(panel)
    assert line.startswith("Analysed in ")
    assert f"{ran} analys" in line, line
    assert "evidence checked" in line


# ------------------------------------------------------------- the live view


def test_a_stage_is_visible_while_it_runs_not_only_after(monkeypatch):
    """The whole point.

    The pipeline's stage events fire when a stage FINISHES. If that were the
    only signal, the panel would be empty for the first seconds of every turn
    — which is the dead state this feature exists to remove.
    """
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)

    begins = [e for e in turn.events if e.stage == pipe.STAGE_STARTED]
    assert begins, "no stage announced that it had begun"
    first = turn.events.index(begins[0])
    assert first <= 1, "the first stage announcement came too late to help"

    # Replayed at that moment, the panel already has a row, and it is running.
    panel = prog.build(turn.events[:first + 1], active=True)
    assert panel.steps
    assert panel.steps[-1].status == prog.ACTIVE


@pytest.mark.parametrize("upto", [2, 4, 8, 12])
def test_a_live_panel_has_exactly_one_running_step(monkeypatch, upto):
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    if len(turn.events) <= upto:
        pytest.skip("the turn was shorter than this prefix")
    panel = prog.build(turn.events[:upto], active=True)

    running = [s for s in panel.steps if s.status == prog.ACTIVE]
    assert len(running) <= 1, [s.key for s in running]


def test_nothing_is_still_running_once_the_turn_ends(monkeypatch):
    """§10: stop completely when the work is done."""
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(LIVE_QUESTION), active=False)

    assert not [s for s in panel.steps if s.status == prog.ACTIVE]
    assert panel.outcome == "complete"
    assert not panel.active


def test_the_live_panel_never_shows_a_step_the_turn_has_not_reached(
        monkeypatch):
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    panel = prog.build(turn.events[:6], active=True)

    assert prog.INTERPRETING not in _keys(panel)
    assert prog.COMPLETE not in _keys(panel)


# --------------------------------------------------------- cross-product §10


def test_a_redirect_shows_routing_and_no_analysis(monkeypatch):
    install(monkeypatch, StubProvider())
    turn = pipe.answer(WHAT_IF)
    panel = _panel(turn)
    keys = _keys(panel)

    assert prog.ROUTING in keys
    assert prog.PLANNING not in keys
    assert prog.VALIDATING not in keys
    assert prog.ANALYSING not in keys
    assert panel.outcome == "redirected"
    assert turn.budget["spent"]["executions"] == 0


def test_the_routing_step_names_the_product_in_business_language(monkeypatch):
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(WHAT_IF))
    routing = next(s for s in panel.steps if s.key == prog.ROUTING)

    assert routing.label == "Routing to What-If Analysis"
    assert routing.status == prog.DONE, "routing was shown as unfinished work"
    assert "what_if" not in routing.label


def test_the_redirect_completion_line_says_where_it_went(monkeypatch):
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(WHAT_IF))
    line = prog.completion_line(panel)

    assert "routed to What-If Analysis" in line
    assert "analys" not in line, "a redirect claimed to have run analyses"


# ------------------------------------------------- §11 the governed ceiling


def test_a_declined_drill_down_is_a_note_and_not_a_failure(monkeypatch,
                                                           period):
    """The execution ceiling must not read as an error."""
    install(monkeypatch, StubProvider(replies={
        "plan_the_analysis": _seven_step_plan(period)}))
    turn = pipe.answer(LIVE_QUESTION)
    panel = _panel(turn)

    assert pipe.EXECUTION_DECLINED in turn.stages
    assert _status(panel, prog.DEFERRED) == prog.NOTE
    assert _status(panel, prog.INTERPRETING) == prog.DONE, (
        "the turn stopped at the ceiling instead of answering with what ran")


def test_a_planned_analysis_that_never_ran_is_not_left_looking_pending(
        monkeypatch, period):
    """On a finished turn, "waiting" is a promise nothing will keep."""
    install(monkeypatch, StubProvider(replies={
        "plan_the_analysis": _seven_step_plan(period)}))
    panel = _panel(pipe.answer(LIVE_QUESTION))
    step = next(s for s in panel.steps if s.key == prog.ANALYSING)

    assert not [s for s in step.substeps if s.status == prog.WAITING], (
        "a declined analysis was still shown as about to run")
    never_ran = [s for s in step.substeps if s.completed_ms is None]
    assert never_ran, "this plan was meant to exceed the ceiling"
    assert all(s.status == prog.NOTE for s in never_ran)


def test_the_deferred_label_hides_the_budget_arithmetic(monkeypatch, period):
    """§11: "6 of 6" is not a sentence for a credit officer."""
    install(monkeypatch, StubProvider(replies={
        "plan_the_analysis": _seven_step_plan(period)}))
    panel = _panel(pipe.answer(LIVE_QUESTION))
    deferred = next(s for s in panel.steps if s.key == prog.DEFERRED)

    assert deferred.label == "Additional drill-down deferred"
    for forbidden in ("budget", "ceiling", "6 of 6", "executions", "spent"):
        assert forbidden not in deferred.label.lower()
    assert "additional drill-down deferred" in \
        prog.completion_line(panel).lower()


# ------------------------------------------------ §12 the deterministic reader


def test_the_governed_reader_is_named_when_it_wrote_the_answer(monkeypatch):
    """A provider that is unavailable is not an error the reader can act on."""
    install(monkeypatch, StubProvider(behaviour="error",
                                      behaviour_for="interpret_the_result"))
    panel = _panel(pipe.answer(LIVE_QUESTION))

    assert _status(panel, prog.FALLBACK) == prog.NOTE
    fallback = next(s for s in panel.steps if s.key == prog.FALLBACK)
    assert fallback.label == "Using governed Early Warning reader"
    assert "governed Early Warning reader" in prog.completion_line(panel)


def test_the_fallback_note_follows_the_interpretation(monkeypatch):
    install(monkeypatch, StubProvider(behaviour="error",
                                      behaviour_for="interpret_the_result"))
    keys = _keys(_panel(pipe.answer(LIVE_QUESTION)))

    assert keys.index(prog.FALLBACK) == keys.index(prog.INTERPRETING) + 1


def test_a_model_written_answer_carries_no_fallback_note(monkeypatch):
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    if turn.engines.get(pipe.FINAL_ANSWER) != "model":
        pytest.skip("the interpretation did not reach the stub provider")

    assert prog.FALLBACK not in _keys(_panel(turn))


# ------------------------------------------------------- §13 repair, §24 ask


def test_a_plan_repair_reads_as_refinement_not_as_an_error(monkeypatch,
                                                           period):
    install(monkeypatch, StubProvider(replies={"plan_the_analysis": {
        "intent": "diagnosis", "output_grain": "population_month",
        "steps": [{"analysis": "grouping", "domain": "early_warning",
                   "period": period, "group_by": "moon_phase",
                   "rationale": "a grouping the domain does not have"}]}}))
    turn = pipe.answer(LIVE_QUESTION)
    panel = _panel(turn)

    if pipe.REPAIR_ATTEMPTED not in turn.stages:
        pytest.skip("this plan did not need repairing")
    refining = next(s for s in panel.steps if s.key == prog.REFINING)
    assert refining.label == "Refining the investigation plan"
    assert refining.status == prog.NOTE
    for forbidden in ("schema", "json", "invalid", "error", "failed"):
        assert forbidden not in refining.label.lower()


def test_a_clarification_stops_the_panel_at_the_question(monkeypatch):
    """§24: no analysis is shown while the reader is being asked something."""
    events = [
        {"stage": "request_started", "detail": {"mode": "standard"}, "at_ms": 0},
        {"stage": "stage_started", "detail": {"step": prog.UNDERSTANDING},
         "at_ms": 1},
        {"stage": "sonnet_pass_1", "detail": {"engine": "model"}, "at_ms": 20},
        {"stage": "stage_started", "detail": {"step": prog.SCOPING}, "at_ms": 21},
        {"stage": "sonnet_pass_2", "detail": {"engine": "model"}, "at_ms": 40},
        {"stage": "stage_started", "detail": {"step": prog.CLARIFYING},
         "at_ms": 41},
        {"stage": "clarification_answer_created",
         "detail": {"reason": "ownership_ambiguous"}, "at_ms": 42},
    ]
    panel = prog.build(events, active=True)

    assert _status(panel, prog.CLARIFYING) == prog.ACTIVE
    assert prog.ANALYSING not in _keys(panel)
    assert prog.PLANNING not in _keys(panel)


def test_a_stopped_turn_is_marked_stopped(monkeypatch):
    events = [
        {"stage": "stage_started", "detail": {"step": prog.UNDERSTANDING},
         "at_ms": 0},
        {"stage": "sonnet_pass_1", "detail": {}, "at_ms": 10},
        {"stage": "stopped_honestly",
         "detail": {"reason": "request_names_another_domain"}, "at_ms": 12},
        {"stage": "sonnet_summary_update", "detail": {}, "at_ms": 13},
        {"stage": "thread_persisted", "detail": {}, "at_ms": 14},
    ]
    panel = prog.build(events, active=False)

    assert _status(panel, prog.STOPPED_STEP) == prog.STOPPED
    assert panel.outcome == "stopped"
    assert "stopped" in prog.completion_line(panel)


# ------------------------------------------- §4 and §22: what is never shown


FORBIDDEN = ("sonnet", "opus", "claude", "anthropic", "token", "max_tokens",
             "schema", "provider", "request_id", "budget", "ledger",
             "chain of thought", "prompt", "llm", "model")


def _sentences(panel: prog.Progress) -> list[str]:
    out: list[str] = [prog.completion_line(panel)]
    for step in panel.steps:
        out.append(step.label)
        out.extend(s.label for s in step.substeps)
    return [s for s in out if s]


@pytest.mark.parametrize("question", [LIVE_QUESTION, WHAT_IF])
def test_no_model_engineering_vocabulary_reaches_the_reader(monkeypatch,
                                                            question):
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(question))

    for sentence in _sentences(panel):
        low = sentence.lower()
        for word in FORBIDDEN:
            assert word not in low, f"{word!r} appeared in {sentence!r}"


def test_the_published_vocabulary_is_clean():
    """Every sentence the panel CAN say, not only the ones one turn said."""
    sentences = (list(prog.LABELS.values())
                 + list(prog.ANALYSIS_LABELS.values())
                 + list(prog.PRODUCTS.values()))

    for sentence in sentences:
        low = sentence.lower()
        for word in FORBIDDEN:
            assert word not in low, f"{word!r} appeared in {sentence!r}"


def test_the_detail_carries_no_engineering_fields(monkeypatch):
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(LIVE_QUESTION))

    allowed = {"product", "deferred"}
    for step in panel.steps:
        assert set(step.detail) <= allowed, step.detail
    assert set(panel.summary) <= {
        "mode", "functionality", "scope", "period", "analyses",
        "evidence_check", "deferred"}, panel.summary


def test_the_summary_never_carries_a_counter_the_reader_cannot_use(monkeypatch):
    install(monkeypatch, StubProvider())
    panel = _panel(pipe.answer(LIVE_QUESTION))

    assert "model_calls" not in panel.summary
    assert "executions" not in panel.summary
    assert panel.summary.get("mode") in ("Standard", "Deep")


# --------------------------------------------- §28: progress costs nothing


def test_watching_a_turn_does_not_change_it(monkeypatch):
    """An observer is an observer. Same answer, same ledger, either way."""
    install(monkeypatch, StubProvider())
    unwatched = pipe.answer(LIVE_QUESTION)

    install(monkeypatch, StubProvider())
    seen: list[pipe.Event] = []
    watched = pipe.answer(LIVE_QUESTION, on_event=seen.append)

    assert watched.stages == unwatched.stages
    assert watched.budget["model_calls_charged"] == \
        unwatched.budget["model_calls_charged"]
    assert watched.budget["spent"]["executions"] == \
        unwatched.budget["spent"]["executions"]
    assert len(seen) == len(watched.events)


def test_no_model_call_is_made_to_produce_a_label(monkeypatch):
    """§28: progress is orchestration metadata, not generated prose."""
    provider = StubProvider()
    install(monkeypatch, provider)
    turn = pipe.answer(LIVE_QUESTION)
    before = len(provider.calls)

    for _ in range(5):
        prog.build(turn.events, active=False)
    assert len(provider.calls) == before


def test_an_observer_that_raises_cannot_cost_the_answer(monkeypatch):
    install(monkeypatch, StubProvider())

    def explode(event):
        raise RuntimeError("the progress sink is broken")

    turn = pipe.answer(LIVE_QUESTION, on_event=explode)
    assert turn.answer["answered"] is True
    assert pipe.THREAD_PERSISTED in turn.stages


# ---------------------------------------------------------- the live registry


def test_the_registry_reads_back_what_the_turn_wrote(monkeypatch):
    class Caller:
        user_id = 7
        role = "analyst"

    live_mod.reset()
    key = live_mod.open_turn("turn-1", Caller())
    assert key == "turn-1"

    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION,
                       on_event=lambda e: live_mod.record(key, e))
    live_mod.close_turn(key)

    found = live_mod.read(key, Caller())
    assert found is not None
    assert found["active"] is False
    assert [s["key"] for s in found["steps"]] == \
        [s.key for s in _panel(turn).steps]


def test_another_caller_cannot_read_somebody_elses_turn():
    class Mine:
        user_id = 1
        role = "analyst"

    class Theirs:
        user_id = 2
        role = "analyst"

    live_mod.reset()
    live_mod.open_turn("turn-2", Mine())
    live_mod.record("turn-2", {"stage": "sonnet_pass_1", "detail": {},
                                "at_ms": 1})

    assert live_mod.read("turn-2", Mine()) is not None
    assert live_mod.read("turn-2", Theirs()) is None


def test_an_unknown_turn_is_not_an_error():
    live_mod.reset()

    class Caller:
        user_id = 1
        role = "analyst"

    assert live_mod.read("never-existed", Caller()) is None


@pytest.mark.parametrize("key,ok", [
    ("ews-abc-1", True),
    ("a" * 64, True),
    ("a" * 65, False),
    ("", False),
    ("../etc/passwd", False),
    ("has space", False),
])
def test_a_turn_key_is_checked_rather_than_trusted(key, ok):
    assert live_mod.valid_key(key) is ok


def test_the_registry_is_bounded():
    live_mod.reset()

    class Caller:
        user_id = 1
        role = "analyst"

    for i in range(live_mod.MAX_TURNS + 40):
        live_mod.open_turn(f"turn-{i}", Caller())
    assert live_mod.watching() <= live_mod.MAX_TURNS


# ------------------------------------------------------- §19 Standard vs Deep


def test_deep_mode_uses_the_same_panel(monkeypatch):
    install(monkeypatch, StubProvider())
    standard = _panel(pipe.answer(LIVE_QUESTION, mode="standard"))
    install(monkeypatch, StubProvider())
    deep = _panel(pipe.answer(LIVE_QUESTION, mode="deep"))

    assert standard.summary["mode"] == "Standard"
    assert deep.summary["mode"] == "Deep"
    # Same vocabulary, same shape. Deep may legitimately run more analyses;
    # it does not get a different visual language.
    assert set(_keys(deep)) <= set(prog.LABELS)
    assert set(_keys(standard)) <= set(prog.LABELS)


# -------------------------------------------------------------- the contract


def test_the_document_is_serialisable_and_versioned(monkeypatch):
    install(monkeypatch, StubProvider())
    document = _panel(pipe.answer(LIVE_QUESTION)).to_dict()

    assert document["version"] == prog.CONTRACT_VERSION
    assert isinstance(document["steps"], list)
    assert isinstance(document["completion_line"], str)
    for step in document["steps"]:
        assert set(step) == {"key", "label", "status", "started_ms",
                             "completed_ms", "elapsed_ms", "substeps",
                             "detail"}
        assert step["status"] in {prog.WAITING, prog.ACTIVE, prog.DONE,
                                  prog.NOTE, prog.STOPPED}


def test_every_step_key_has_a_governed_label():
    for key in prog.STEP_ORDER:
        assert prog.LABELS.get(key), key
    for key in prog.EVENT_STEPS.values():
        assert prog.LABELS.get(key), key


def test_the_analysis_vocabulary_covers_every_governed_analysis():
    from backend.early_warning.conversation import plan as plan_mod

    for analysis in plan_mod.ANALYSIS_TYPES:
        assert prog.ANALYSIS_LABELS.get(analysis), analysis


def test_an_unknown_analysis_is_named_rather_than_described():
    """§8: do not invent a description for something this map has not seen."""
    label = prog.analysis_label("brand_new_thing")
    assert "brand new thing" in label
    assert label != prog.ANALYSIS_LABELS["population"]


def test_a_node_grouping_says_so():
    assert prog.analysis_label("grouping", group_by="dominant_subcategory") == \
        "Identifying dominant warning sub-categories"
    assert prog.analysis_label("grouping", group_by="sector") == \
        "Identifying common warning characteristics"


def test_the_population_step_names_the_segment_when_the_plan_knew_it():
    assert prog.analysis_label("population", scope="Contracting") == \
        "Establishing the Contracting portfolio position"


# --------------------------------------------- §9: the progress must not judge


NEUTRAL_TRAPS = ("deteriorat", "improv", "worsen", "declin", "why ")


def test_no_analysis_label_pre_judges_the_answer():
    """§9.

    A turn is allowed to come back and say the premise was wrong. Progress
    text that already asserted the deterioration reads as a broken promise
    when it does.
    """
    for analysis, label in prog.ANALYSIS_LABELS.items():
        low = label.lower()
        for trap in NEUTRAL_TRAPS:
            assert trap not in low, f"{analysis}: {label!r}"


def test_no_step_label_pre_judges_the_answer():
    for key, label in prog.LABELS.items():
        low = label.lower()
        for trap in NEUTRAL_TRAPS:
            assert trap not in low, f"{key}: {label!r}"


def test_seconds_reads_the_way_a_person_would_say_it():
    assert prog.seconds(31_800) == "31.8s"
    assert prog.seconds(900) == "0.9s"
    assert prog.seconds(65_000) == "1m 5s"
    assert prog.seconds(120_000) == "2m"
    assert prog.seconds(0) == ""
    assert prog.seconds(None) == ""
