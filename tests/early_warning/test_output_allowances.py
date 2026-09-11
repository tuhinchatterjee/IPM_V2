"""
Whether a healthy model answer fits in the room CreditProbe gives it.

The defect this suite exists for
--------------------------------
A live run reached every stage on real models and then wrote its answer
deterministically anyway:

    opus_sufficiency_review     cut off at the 1000-token output limit
    opus_final_interpretation   cut off at the 1600-token output limit

Both replies were well formed. Both were thrown away. The architecture, the
routing, the executable registry and the domain locks all worked, and the
product still fell back — to its own output caps.

The caps were sized for the document. That is the mistake: on Opus 5 thinking
is on by default and its tokens come out of the SAME `max_tokens` allowance, so
a two-hundred-token verdict can be cut off at a thousand. A ceiling has to cover
the document AND the reasoning that produces it.

Two halves, then. The documents are now bounded and told to be short — a
sufficiency verdict is a list of labels, not an essay — and the two ceilings
that truncated are raised, per stage, to the smallest value that is safe on the
evidence. Nothing else moved: not the eight-call budget, not the reserve, not
the clocks, not the other six stages.
"""

from __future__ import annotations

import json

import pytest

from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import reading as reading_mod
from backend.early_warning.conversation import seam as seam_mod
from backend.early_warning.conversation import sufficiency as suff
from backend.llm.base import LLMError
from tests.early_warning.stub_provider import StubProvider, install

#: The live question, unchanged.
LIVE_QUESTION = ("Why has Contracting deteriorated over six months, and is it "
                 "concentrated in a handful of names?")

#: Roughly four characters to a token. Crude, and deliberately so: the point
#: is whether a realistic document is nowhere near the ceiling, not to
#: reproduce a tokeniser.
_CHARS_PER_TOKEN = 4


def _tokens(document: dict) -> int:
    return len(json.dumps(document)) // _CHARS_PER_TOKEN


#: A full sufficiency verdict — every field populated to its bound.
FULL_REVIEW = {
    "complete": False,
    "uncovered": ["concentration", "diagnosis", "movement", "grouping"],
    "unsupported_claims": [
        "that the deterioration is sector-wide",
        "that the largest obligor drives the move",
        "that the trend continues into the next quarter",
    ],
    "next_analysis": "concentration",
    "next_analysis_rationale": (
        "The request asked whether it sits in a handful of names and no "
        "concentration step ran."),
    "presentation": "table",
}

#: A full interpretation — a direct answer, two paragraphs, and every list at
#: its bound. Longer than a real one, which is the point.
FULL_READING = {
    "direct": ("Contracting is at 33.2 (low) across 30 obligors and "
               "SAR 6.5bn, with 11 at high or above."),
    "interpretation": (
        "The weakness is concentrated rather than broad-based: eleven of "
        "thirty obligors sit at high or above and carry the large majority of "
        "the segment's high-risk exposure. That distinction decides the "
        "response, because a concentrated position supports targeted borrower "
        "intervention while a broad one would call for a sector-level limit "
        "action, and the two commit very different amounts of the bank's "
        "capacity. Layer 1 internal behavioural is carrying the trigger side, "
        "which means the deterioration is showing in account conduct before "
        "it has reached the financials.\n\n"
        "Read the movement with the anchor rather than on its own. Where the "
        "score has fallen while the anchor has held, the notches moved and "
        "the obligor did not, and treating that as a recovery is the specific "
        "mistake this reading exists to prevent. The evidence here is "
        "corroborated across more than one feed for the names that matter, "
        "so the position is worth acting on rather than merely watching, but "
        "it remains a ranking of obligors and not a prediction about any of "
        "them."),
    "points": [
        "Eleven of thirty obligors are at high or above.",
        "The high-risk exposure is concentrated in the largest few names.",
        "Layer 1 internal behavioural leads the trigger side.",
    ],
    "drivers": [
        "L1.2 limit behaviour, the dominant node",
        "L1.1 deposit and cash flow, second",
        "L2.1 rating migration on a minority",
        "L4.3 guarantor deterioration on two names",
    ],
    "follow_ups": [
        "Which obligors carry the concentrated high-risk exposure?",
        "Show the evidence behind L1.2 for the weakest name.",
        "How does Contracting compare with the rest of the book?",
    ],
    "caveats": [
        "The model orders obligors; it does not predict them.",
        "Weights are a documented starting calibration, not fitted.",
        "Dominant driver is absent for obligors with no fired signal.",
    ],
}


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


def _engine(turn, stage: str) -> str:
    return turn.engines.get(stage, "")


def _reason(turn, stage: str) -> str:
    event = next(e for e in turn.events if e.stage == stage)
    return event.detail.get("model_call", {}).get("fallback_reason", "")


# ------------------------------------------- the allowances, and why they are


def test_the_two_stages_that_truncated_have_room_now():
    """The numbers, asserted at both ends.

    A floor, because these are the values the live run proved too small; and
    a ceiling, because "make it bigger" is not a fix and an unbounded
    allowance is a cost nobody chose.
    """
    review = seam_mod.STAGES[seam_mod.SUFFICIENCY]
    reading = seam_mod.STAGES[seam_mod.INTERPRETATION]

    assert 1600 <= review.max_tokens <= 2000, review.max_tokens
    assert 2400 <= reading.max_tokens <= 3000, reading.max_tokens
    assert review.max_tokens > 1000, "the review still has the cap that cut it"
    assert reading.max_tokens > 1600, "the reading still has the cap that cut it"


def test_no_other_stage_was_raised():
    """Not a global ceiling lift.

    These two were sized on their own documents and have never truncated, so
    a change that simply set every stage to one number fails here.

    The four stages this test used to pin at 700/1200/900/700 have since been
    raised, on their own evidence rather than as collateral: Sonnet 5 also
    runs adaptive thinking when the request omits `thinking`, so the two
    Sonnet stages shared the defect the Opus ones had, and the ownership gate
    was left sitting at 900 — BELOW the 1,000 that had already been proven to
    truncate on the same family. `test_output_allowances_floor.py` holds that
    line now, with a floor rather than a list of numbers, so the next stage
    added cannot quietly slip under it.
    """
    unchanged = {
        seam_mod.PLAN: 4000,
        seam_mod.REPAIR: 2500,
    }
    for key, expected in unchanged.items():
        assert seam_mod.STAGES[key].max_tokens == expected, (
            f"{key} was raised as collateral")
    # And the raise was not a levelling: the allowances are still distinct.
    assert len({s.max_tokens for s in seam_mod.STAGES.values()}) >= 4


def test_every_allowance_is_stage_specific():
    """One number for all eight would be either wasteful or too small."""
    allowances = {s.key: s.max_tokens for s in seam_mod.STAGES.values()}
    assert len(set(allowances.values())) >= 5, allowances


def test_a_list_over_its_bound_is_trimmed_rather_than_discarded():
    """Four points where three were asked for is not a bad reading.

    Trimming to the bound moves the value into what the schema already
    declares. Discarding the whole answer over the fourth point is the same
    papercut as refusing a plan for writing "25" instead of 25.
    """
    schema = {"type": "object",
              "properties": {"points": {"type": "array", "maxItems": 3,
                                        "items": {"type": "string"}}}}
    tidied = seam_mod._coerce({"points": ["a", "b", "c", "d", "e"]}, schema)
    assert tidied["points"] == ["a", "b", "c"]
    assert not seam_mod._conforms(tidied, schema)


# ----------------------------------------------- the documents are compact


def test_a_full_sufficiency_verdict_is_far_inside_its_allowance():
    """Every field at its bound, and still a fraction of the room.

    The headroom is not slack. On Opus 5 the model's own reasoning comes out
    of the same allowance, and that is what the old cap was spent on.
    """
    room = seam_mod.STAGES[seam_mod.SUFFICIENCY].max_tokens
    assert _tokens(FULL_REVIEW) < room // 4, (
        f"a full verdict is {_tokens(FULL_REVIEW)} tokens of {room}")


def test_a_full_interpretation_is_inside_its_allowance():
    room = seam_mod.STAGES[seam_mod.INTERPRETATION].max_tokens
    assert _tokens(FULL_READING) < room // 2, (
        f"a full reading is {_tokens(FULL_READING)} tokens of {room}")


def test_the_sufficiency_verdict_is_labels_rather_than_prose():
    """`uncovered` used to be free text, so a model wrote a sentence each.

    Which parts are missing is a choice from a closed set. Constraining it is
    what makes the verdict small enough to be a verdict.
    """
    uncovered = suff.SCHEMA["properties"]["uncovered"]
    assert uncovered["items"]["enum"], "uncovered is still free text"
    assert set(uncovered["items"]["enum"]) == set(suff.COVERED_BY)
    assert uncovered["maxItems"] <= 4

    claims = suff.SCHEMA["properties"]["unsupported_claims"]
    assert claims["maxItems"] <= 3


def test_the_interpretation_lists_are_bounded():
    bounds = reading_mod.SCHEMA["properties"]
    assert bounds["points"]["maxItems"] <= 4
    assert bounds["drivers"]["maxItems"] <= 4
    assert bounds["follow_ups"]["maxItems"] <= 4
    assert bounds["caveats"]["maxItems"] <= 4
    # Prose length is guidance in the prompt, not a hard constraint. A cap
    # cannot be enforced by trimming without cutting mid-word, and discarding
    # a good reading for being forty characters long is the failure this
    # whole suite is about.
    assert "maxLength" not in bounds["interpretation"]
    assert "maxLength" not in bounds["direct"]
    assert "LENGTH" in reading_mod.SYSTEM


@pytest.mark.parametrize("system,phrase", [
    (suff.SYSTEM, "no restating the request"),
    (suff.SYSTEM, "no repeating figures back"),
    (reading_mod.SYSTEM, "Do not restate the result packet back"),
])
def test_the_prompts_ask_for_the_fields_and_nothing_else(system, phrase):
    assert phrase in system, "the prompt does not say to be short"


def test_the_sufficiency_packet_does_not_carry_the_whole_result(monkeypatch):
    """It decides WHICH parts have evidence, not what the evidence says.

    It used to receive every figure the packet held and the coverage map's
    whole dictionary, including the proposed next step. A model shown the
    entire result is a model that restates it.
    """
    stub = install(monkeypatch, StubProvider())
    pipe.answer(LIVE_QUESTION)

    call = next(c for c in stub.calls if c["tool"] == "review_sufficiency")
    packet = call["packet"]
    assert "figures_produced" in packet, "the packet shape did not change"
    assert "figures" not in packet, "every figure is still being sent"
    assert "next_step" not in json.dumps(packet["coverage_map"])
    assert "model_call" not in json.dumps(packet["coverage_map"])


def test_the_interpretation_packet_does_not_send_the_evidence_twice(
        monkeypatch):
    """`fact_packs` and `figures` are the same numbers.

    Sent together, every value arrived twice and the rows a third time. A
    model shown the same evidence three ways spends its output reconciling
    the copies, and this stage's output is the answer.
    """
    stub = install(monkeypatch, StubProvider())
    pipe.answer(LIVE_QUESTION)

    call = next(c for c in stub.calls if c["tool"] == "interpret_the_result")
    packet = call["packet"]
    assert "fact_packs" not in packet, "the packs are still duplicating figures"
    assert "figures" in packet, "the figures themselves must still be there"
    assert len(packet.get("rows") or []) <= 10
    assert "deterministic_reading" in packet, (
        "the grounding baseline is what makes the figure check work")


# ------------------------------------------ a full answer still gets through


def test_a_full_sufficiency_verdict_is_accepted(monkeypatch):
    install(monkeypatch, StubProvider(replies={"review_sufficiency":
                                                FULL_REVIEW}))
    turn = pipe.answer(LIVE_QUESTION)
    assert _engine(turn, pipe.SUFFICIENCY_COMPLETE) == seam_mod.MODEL, (
        _reason(turn, pipe.SUFFICIENCY_COMPLETE))


#: Prose with no figures in it, to pad a reading out to its full length
#: without fighting the grounding check. Every sentence is one a credit
#: officer might actually write, because a padding string of "lorem ipsum"
#: would not be the length of a real answer.
_PADDING = (
    " Read the movement with the anchor rather than on its own: where the "
    "score has fallen while the anchor has held, the notches moved and the "
    "obligor did not, and treating that as a recovery is the specific "
    "mistake this reading exists to prevent. The evidence for the names that "
    "matter is corroborated across more than one feed, so the position is "
    "worth acting on rather than merely watching. It remains a ranking of "
    "obligors and not a prediction about any of them, and the weights behind "
    "it are a documented starting calibration rather than an estimate fitted "
    "to default data.")


def test_a_full_interpretation_is_accepted(monkeypatch):
    """A full-length reading, grounded, and accepted.

    Built from the deterministic answer the model is actually shown, then
    padded with figure-free prose to the length a real Opus reading reaches.
    Written by hand with invented figures it would be discarded — correctly,
    by the grounding check — and this test is about the ALLOWANCE, so the
    figures are the real ones and the length is the fixture's contribution.
    """
    floor = install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)
    grounded = turn.answer
    del floor

    reading = {
        "direct": grounded["direct"],
        "interpretation": grounded["interpretation"] + _PADDING,
        "points": [str(p) for p in (grounded.get("points") or [])][:3],
        "drivers": [str(d) for d in (grounded.get("drivers") or [])][:4],
        "follow_ups": [str(f) for f in (grounded.get("follow_ups") or [])][:3],
        "caveats": [
            "The model orders obligors; it does not predict them.",
            "Weights are a documented starting calibration, not fitted.",
        ],
    }
    assert _tokens(reading) < seam_mod.STAGES[
        seam_mod.INTERPRETATION].max_tokens, "the fixture is over the ceiling"

    install(monkeypatch, StubProvider(
        replies={"interpret_the_result": reading}))
    second = pipe.answer(LIVE_QUESTION)

    final = next(e for e in second.events if e.stage == pipe.FINAL_ANSWER)
    assert not final.detail.get("ungrounded_figures"), (
        final.detail["ungrounded_figures"])
    assert _engine(second, pipe.FINAL_ANSWER) == seam_mod.MODEL, (
        _reason(second, pipe.FINAL_ANSWER))
    assert _PADDING.strip()[:40] in second.answer["interpretation"], (
        "the model's longer reading was not the one used")


# ------------------------------------- truncation is still detected as such


def test_truncation_is_still_detected_and_named():
    from backend.llm import anthropic_provider as provider_mod

    class _Truncated:
        stop_reason = "max_tokens"
        content: list = []

    with pytest.raises(LLMError) as raised:
        provider_mod._refuse_if_truncated(_Truncated(), "review_sufficiency",
                                          2000)
    assert "cut off" in str(raised.value)
    assert "2000" in str(raised.value)


def test_a_truncated_reply_is_not_called_malformed(monkeypatch):
    """The misclassification the brief singles out.

    A partial document is not a malformed one, and calling it malformed
    sends whoever is debugging it to look at a schema that is fine.
    """
    install(monkeypatch, StubProvider(
        replies={"interpret_the_result": LLMError(
            "The interpret_the_result reply was cut off at the 3000-token "
            "limit before it finished")}))
    turn = pipe.answer(LIVE_QUESTION)

    reason = _reason(turn, pipe.FINAL_ANSWER)
    assert "cut off" in reason, reason
    assert "did not conform" not in reason
    assert turn.answer["answered"] is True, (
        "the deterministic reading must still answer")


def test_a_truncated_reply_is_not_retried():
    """It would be cut off again in exactly the same place."""
    from backend.llm import anthropic_provider as provider_mod

    truncated = LLMError("The review_sufficiency reply was cut off at the "
                         "2000-token limit before it finished")
    assert not provider_mod._worth_retrying(truncated)


def test_a_truncation_costs_one_call_and_not_the_reserve(monkeypatch):
    """No extra retries, and the closing stages still run.

    A truncated review is charged once — the call happened — and the answer
    is still written by a model, which is the whole point of the reserve.
    """
    install(monkeypatch, StubProvider(
        replies={"review_sufficiency": LLMError(
            "The review_sufficiency reply was cut off at the 2000-token "
            "limit before it finished")}))
    turn = pipe.answer(LIVE_QUESTION)

    charged = [a for a in turn.model_attempts
               if a["stage"] == pipe.SUFFICIENCY_COMPLETE]
    assert len(charged) == 1, f"{len(charged)} attempts at one stage"
    assert charged[0]["ok"] is False
    assert turn.budget["model_calls_failed"] == 1
    assert _engine(turn, pipe.FINAL_ANSWER) == seam_mod.MODEL
    assert _engine(turn, pipe.SUMMARY_UPDATED) == seam_mod.MODEL


# --------------------------------------------- nothing else moved


def test_the_budget_architecture_is_untouched():
    standard = budget_mod.CEILINGS[budget_mod.STANDARD]
    assert standard["model_calls"] == 8
    assert budget_mod.RESERVED_MODEL_CALLS == 2
    assert standard["wall_clock_seconds"] == 120
    assert standard["hard_wall_clock_seconds"] == 240


def test_the_families_are_unchanged():
    assert seam_mod.STAGES[seam_mod.SUFFICIENCY].family == seam_mod.OPUS
    assert seam_mod.STAGES[seam_mod.INTERPRETATION].family == seam_mod.OPUS
    assert seam_mod.STAGES[seam_mod.SUMMARY].family == seam_mod.SONNET
    assert seam_mod.STAGES[seam_mod.INTERPRETATION].closing
    assert seam_mod.STAGES[seam_mod.SUMMARY].closing
    assert not seam_mod.STAGES[seam_mod.SUFFICIENCY].closing


# ---------------------------------------------------- the acceptance target


def test_the_live_acceptance_target(monkeypatch):
    """7 charged, 7 succeeded, 3 Sonnet and 4 Opus, every stage on a model."""
    install(monkeypatch, StubProvider())
    turn = pipe.answer(LIVE_QUESTION)

    budget = turn.budget
    assert budget["model_calls_charged"] == 7, budget
    assert budget["model_calls_succeeded"] == 7, budget
    assert budget["model_calls_failed"] == 0, budget
    assert budget["spent"]["sonnet_calls"] == 3
    assert budget["spent"]["opus_calls"] == 4
    assert budget["spent"]["revisions"] == 0

    for stage in (pipe.SONNET_PASS_1, pipe.SONNET_PASS_2,
                  pipe.FUNCTIONALITY_SELECTED, pipe.PLAN_CREATED,
                  pipe.SUFFICIENCY_COMPLETE, pipe.FINAL_ANSWER,
                  pipe.SUMMARY_UPDATED):
        assert _engine(turn, stage) == seam_mod.MODEL, (
            f"{stage}: {_reason(turn, stage)}")


def test_the_what_if_redirect_is_unchanged(monkeypatch):
    """4 of 4 successful, nothing executed, still routed to What-If."""
    install(monkeypatch, StubProvider())
    turn = pipe.answer("What happens to ECL if oil falls 30%?")

    assert turn.selection["selected_functionality"] == "what_if"
    assert turn.budget["model_calls_charged"] == 4
    assert turn.budget["model_calls_succeeded"] == 4
    assert turn.budget["spent"]["executions"] == 0
    assert not (set(turn.stages) & pipe.ANALYTICAL_STAGES)
    assert turn.answer["answered"] is False
