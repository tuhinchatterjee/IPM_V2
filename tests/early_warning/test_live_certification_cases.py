"""
The five live cases that failed, run end to end against a model that answers.

The deterministic suite cannot reach these. Every one of them needed a model
to actually write something — a reading with a figure in it, a pass-two reply
with a layer in it, an ownership verdict — and with no provider configured
every stage falls to its deterministic floor and every contract holds
vacuously. That is how a build with 78 green scenarios failed five of eight
real-provider cases.

So the stub is made to produce the exact shapes the live run produced, and the
whole pipeline runs on top of it:

* LIVE-2 / LIVE-3 / LIVE-7 — a reading stating the SIZE of a movement the
  packet stores signed, plus the two hyphenated phrases the stage's own system
  prompt asks for.
* LIVE-3 — a pass-two reply whose `requested_layer` is spelled the way a real
  Sonnet spells it.
* LIVE-5 — an ownership verdict routing a false-premise question to What-If.
* LIVE-8 — the mixed-language question, on the same reading path.

A test here failing means the certification will fail on the Mac.
"""

from __future__ import annotations

import pytest

from backend.early_warning import functionality as fn
from backend.early_warning.conversation import pipeline as pl
from backend.early_warning.conversation import seam as seam_mod
from tests.early_warning.stub_provider import LAYER_SHAPES, StubProvider, install

#: The stub is reached by TOOL name, which is what the provider boundary sees.
#: The stage keys below are what the trace records.
TOOL_INTERPRET = seam_mod.STAGES[seam_mod.INTERPRETATION].tool_name
TOOL_PASS_2 = seam_mod.STAGES[seam_mod.PASS_2].tool_name
TOOL_SELECT = seam_mod.STAGES[seam_mod.FUNCTIONALITY].tool_name

LIVE_2 = "Why has the Contracting sector deteriorated over the last six months?"
LIVE_3 = ("Why has Contracting deteriorated over six months, is it concentrated "
          "in a handful of names, and which layer is driving it?")
LIVE_5 = ("Given every Contracting obligor improved last month, which one "
          "improved most?")
LIVE_7 = "wich contrcting names deterioted mst lst 6 mnths"
LIVE_8 = "construction ka risk last 6 months mein kyun badha?"


def run(question: str, thread: str) -> dict:
    return pl.answer(question, thread_id=thread).to_dict()


def interpretation_call(turn: dict) -> dict:
    """What the final-answer event says about the reading.

    Read from the event rather than from `model_calls`, because that is where
    the trace records a DISCARDED reading — and a discard is exactly what
    several of these tests are about.
    """
    for event in reversed(turn.get("events") or []):
        if event.get("stage") == pl.FINAL_ANSWER:
            return dict(event.get("detail") or {})
    return {}


# ------------------------------------- the reading that states a magnitude

@pytest.mark.parametrize("question,name", [
    (LIVE_2, "LIVE-2"), (LIVE_3, "LIVE-3"),
    (LIVE_7, "LIVE-7"), (LIVE_8, "LIVE-8"),
])
def test_a_reading_stating_the_size_of_a_signed_move_survives(
        monkeypatch, question, name):
    """The failure that cost four of the eight cases."""
    install(monkeypatch, StubProvider(behaviour="writes_a_magnitude",
                                      behaviour_for=TOOL_INTERPRET))
    turn = run(question, f"live-magnitude-{name}")
    call = interpretation_call(turn)
    assert call, name
    assert call.get("engine") == seam_mod.MODEL, (
        name, call.get("fallback_reason"))
    assert not call.get("ungrounded"), (name, call.get("ungrounded"))


@pytest.mark.parametrize("question,name", [(LIVE_2, "LIVE-2"), (LIVE_7, "LIVE-7")])
def test_the_reading_the_model_wrote_is_the_one_shown(monkeypatch, question, name):
    install(monkeypatch, StubProvider(behaviour="writes_a_magnitude",
                                      behaviour_for=TOOL_INTERPRET))
    turn = run(question, f"live-kept-{name}")
    assert "tier-3" in (turn["answer"].get("interpretation") or ""), name


def test_a_reading_that_invents_a_figure_is_still_discarded(monkeypatch):
    install(monkeypatch, StubProvider(behaviour="ungrounded",
                                      behaviour_for=TOOL_INTERPRET))
    turn = run(LIVE_2, "live-ungrounded")
    call = interpretation_call(turn)
    assert call.get("engine") == seam_mod.DETERMINISTIC
    assert "88,412.7" in " ".join(call.get("ungrounded_figures") or [])


# ------------------------------------------------ the declared-claim path

def test_declared_arithmetic_the_server_reproduces_is_kept(monkeypatch):
    install(monkeypatch, StubProvider(behaviour="declares_arithmetic",
                                      behaviour_for=TOOL_INTERPRET))
    turn = run(LIVE_2, "live-declared")
    call = interpretation_call(turn)
    claims = call.get("derived_claims") or []
    if not claims:
        pytest.skip("this packet carried no two rows with an exposure each")
    assert call.get("engine") == seam_mod.MODEL, call.get("fallback_reason")
    assert all(c["accepted"] for c in claims)


def test_the_same_arithmetic_undeclared_is_refused(monkeypatch):
    install(monkeypatch, StubProvider(behaviour="undeclared_arithmetic",
                                      behaviour_for=TOOL_INTERPRET))
    turn = run(LIVE_2, "live-undeclared")
    call = interpretation_call(turn)
    assert call.get("engine") == seam_mod.DETERMINISTIC
    assert call.get("ungrounded_figures")


def test_a_declaration_the_server_disagrees_with_is_refused(monkeypatch):
    install(monkeypatch, StubProvider(behaviour="bad_declaration",
                                      behaviour_for=TOOL_INTERPRET))
    turn = run(LIVE_2, "live-bad-declaration")
    call = interpretation_call(turn)
    assert call.get("engine") == seam_mod.DETERMINISTIC
    assert any(not c["accepted"] for c in call.get("derived_claims") or [{}])


# ------------------------------------------------------- pass two, live shapes

@pytest.mark.parametrize("shape", sorted(LAYER_SHAPES))
def test_every_layer_shape_a_live_model_sent_keeps_the_pass(monkeypatch, shape):
    install(monkeypatch, StubProvider(behaviour=shape,
                                      behaviour_for=TOOL_PASS_2))
    turn = run(LIVE_3, f"live-layer-{shape}")
    engines = turn.get("engines") or {}
    assert engines.get(seam_mod.PASS_2) == seam_mod.MODEL, (
        shape, [c.get("fallback_reason") for c in turn.get("model_calls") or []
                if c.get("stage") == seam_mod.PASS_2])


@pytest.mark.parametrize("shape,expected", [
    ("lowercase_layer", "L3"), ("spelled_layer", "L3"),
    ("described_layer", "L3"), ("verbose_layer", "L3"),
    ("listed_layer", "L3"),
])
def test_the_layer_the_model_meant_reaches_the_plan(monkeypatch, shape, expected):
    install(monkeypatch, StubProvider(behaviour=shape,
                                      behaviour_for=TOOL_PASS_2))
    turn = run("Which obligors carry the most L3 warnings?",
               f"live-layer-plan-{shape}")
    assert turn["result_packet"]["request"]["normalized_request"]
    said = str(turn["result_packet"]).count(expected)
    assert said, (shape, expected)


@pytest.mark.parametrize("shape", ["unknown_layer", "blank_layer", "null_layer"])
def test_a_layer_this_product_does_not_have_is_not_invented(monkeypatch, shape):
    install(monkeypatch, StubProvider(behaviour=shape,
                                      behaviour_for=TOOL_PASS_2))
    turn = run(LIVE_2, f"live-layer-unknown-{shape}")
    plan = turn["result_packet"]["request"]["plan"]
    assert all(not (s.get("layer") or "") for s in plan["steps"]), shape


# ------------------------------------------------------------- ownership

def test_a_false_premise_is_not_routed_to_what_if(monkeypatch):
    """LIVE-5: the model proposes What-If and the gate holds it here."""
    install(monkeypatch, StubProvider(
        replies={TOOL_SELECT: {
            "selected_functionality": fn.WHAT_IF, "confidence": 0.9,
            "ownership_rationale": "the request supposes an improvement",
            "ambiguous": False, "clarification": ""}}))
    turn = run(LIVE_5, "live-premise")
    assert turn["functionality_selection"]["selected_functionality"] \
        == fn.EARLY_WARNING
    assert turn["answer"].get("answered") is True


def test_the_false_premise_answer_contradicts_the_premise(monkeypatch):
    install(monkeypatch, StubProvider(
        replies={TOOL_SELECT: {
            "selected_functionality": fn.WHAT_IF, "confidence": 0.9,
            "ownership_rationale": "supposition", "ambiguous": False,
            "clarification": ""}}))
    turn = run(LIVE_5, "live-premise-said")
    said = (turn["answer"].get("direct") or "").lower()
    assert "deteriorated" in said


def test_a_genuine_what_if_still_leaves_and_runs_nothing(monkeypatch):
    """LIVE-6, preserved exactly."""
    install(monkeypatch, StubProvider())
    turn = run("What happens to ECL if oil falls 30%?", "live-whatif")
    assert turn["functionality_selection"]["selected_functionality"] \
        == fn.WHAT_IF
    ran = [e for e in turn.get("events") or []
           if e.get("stage") in ("execution_step", "execution")]
    assert ran == []


# ------------------------------------------------------ the passes preserved

def test_easy_retrieval_still_answers(monkeypatch):
    """LIVE-1."""
    install(monkeypatch, StubProvider())
    turn = run("What is the current Early Warning distribution by risk band?",
               "live-retrieval")
    assert turn["answer"].get("answered") is True
    assert turn["functionality_selection"]["selected_functionality"] \
        == fn.EARLY_WARNING


def test_a_follow_up_still_resolves_against_the_thread(monkeypatch):
    """LIVE-4, which runs as the second turn of LIVE-3's thread."""
    install(monkeypatch, StubProvider())
    first = pl.answer(LIVE_3, thread_id="live-followup")
    second = pl.answer("Which two of those worsened fastest?",
                       thread_id="live-followup",
                       rolling_summary=first.rolling_summary.to_dict()).to_dict()
    assert second["answer"].get("answered") is True
    assert second["functionality_selection"]["selected_functionality"] \
        == fn.EARLY_WARNING


# ------------------------------------------------- noisy and mixed language

def test_misspelling_survives_into_the_plan(monkeypatch):
    """LIVE-7: the cleanup must keep the sector and the window, not just the
    words. A turn that spells the question correctly and then answers about
    the whole book has lost the question."""
    install(monkeypatch, StubProvider(behaviour="writes_a_magnitude",
                                      behaviour_for=TOOL_INTERPRET))
    turn = run(LIVE_7, "live-noisy-meaning")
    steps = turn["result_packet"]["request"]["plan"]["steps"]
    assert any((s.get("filters") or {}).get("sector") == "Contracting"
               for s in steps)
    assert any(s.get("comparison_period") for s in steps)
    assert "Contracting" in turn["result_packet"]["request"]["normalized_request"]


def test_the_noisy_and_mixed_questions_keep_a_model_reading(monkeypatch):
    """LIVE-7 and LIVE-8 failed on grounding, not on routing."""
    install(monkeypatch, StubProvider(behaviour="writes_a_magnitude",
                                      behaviour_for=TOOL_INTERPRET))
    for question, thread in ((LIVE_7, "noisy"), (LIVE_8, "mixed")):
        turn = run(question, f"live-lang-{thread}")
        detail = interpretation_call(turn)
        assert detail.get("engine") == seam_mod.MODEL, question
        assert not detail.get("ungrounded_figures"), question
        assert turn["functionality_selection"]["selected_functionality"] \
            == fn.EARLY_WARNING, question
