"""
Ask CreditProbe, evaluated against real questions.

Two suites in one file, deliberately.

**The deterministic suite** runs on every commit. It exercises the offline
semantic reader — the path a bank without a provider key actually gets — and
asserts what should HAPPEN: the capability routing, the shape of the plan, and
the invariants that must hold whatever route was taken. No network, no key, no
model.

**The live suite** runs only with `RUN_LIVE_LLM_EVALS=1` and a provider key. It
asserts the same expectations against a real model. It is separated because CI
has no key, because a model's answer varies, and because a suite that sometimes
passes teaches people to ignore it.

What is asserted is intent and behaviour, never "the endpoint returned 200".
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from backend.orchestration import capability as cap
from tests.conftest import database_available

CASES_PATH = pathlib.Path(__file__).parent / "ask_creditprobe_cases.json"

#: Below this share of cases routed correctly, the router has regressed.
#: Not 100%: a handful of the cases are deliberately ambiguous, and a router
#: that scored perfectly on them would be one that had stopped asking.
MIN_ROUTING_ACCURACY = 0.92


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text())["cases"]


CASES = load_cases()


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if not database_available():
        pytest.skip("needs the platform database")


# ------------------------------------------------------------ the case file


def test_the_case_file_is_large_enough_to_be_evidence():
    assert len(CASES) >= 200


def test_every_case_is_well_formed():
    for case in CASES:
        assert case["question"].strip()
        assert case["expected_intent"] in cap.ALL
        assert case["expected_behavior"]


def test_the_cases_cover_every_capability_that_can_be_asked_for():
    """A category with no cases is a category nobody is testing."""
    covered = {c["expected_intent"] for c in CASES}
    for intent in (cap.Capability.DATA_DISCOVERY, cap.Capability.DATA_DICTIONARY,
                   cap.Capability.DATA_QUALITY, cap.Capability.DATA_RELATIONSHIP,
                   cap.Capability.DATA_INSPECTION, cap.Capability.ANALYSIS,
                   cap.Capability.METHOD_DISCOVERY,
                   cap.Capability.METHOD_EXPLANATION):
        assert intent in covered, f"no case exercises {intent}"


def test_no_duplicate_questions():
    questions = [c["question"] for c in CASES]
    assert len(questions) == len(set(questions))


# ------------------------------------------------- deterministic routing


def _route(question: str) -> str:
    from backend.orchestration.capability import recognise

    return recognise(question)[0]


def test_the_offline_router_routes_the_corpus_correctly():
    """The whole corpus at once, so one regression is one failure with a list.

    Reported as a rate rather than case by case because the useful signal is
    "the router still works", and 227 separate failures would bury which ones
    actually moved.
    """
    wrong: list[str] = []
    for case in CASES:
        got = _route(case["question"])
        if got != case["expected_intent"]:
            wrong.append(f"{case['question']!r}: expected "
                         f"{case['expected_intent']}, got {got}")
    accuracy = 1 - len(wrong) / len(CASES)
    assert accuracy >= MIN_ROUTING_ACCURACY, (
        f"routing accuracy {accuracy:.1%} < {MIN_ROUTING_ACCURACY:.0%}\n"
        + "\n".join(wrong[:25]))


def test_a_data_question_never_routes_into_the_engine():
    """The failure that started this: a question about the catalogue answered
    with a portfolio statistic."""
    for case in CASES:
        if case["expected_intent"] not in cap.FROM_DATA_BUILDER:
            continue
        got = _route(case["question"])
        assert got in cap.FROM_DATA_BUILDER or got == cap.Capability.ANALYSIS
        if got == cap.Capability.ANALYSIS:
            # Allowed only where the question genuinely asks for a figure.
            assert any(word in case["question"].lower()
                       for word in ("how many", "total", "largest", "top")), (
                f"{case['question']!r} was routed into the engine")


def test_a_relationship_question_never_routes_into_the_engine():
    """"How is ratings connected to IFRS 9" must never compute a stage
    distribution, whatever else it does."""
    for case in CASES:
        if case["expected_intent"] != cap.Capability.DATA_RELATIONSHIP:
            continue
        assert _route(case["question"]) == cap.Capability.DATA_RELATIONSHIP, (
            case["question"])


# --------------------------------------------------------- end to end


@pytest.fixture(scope="module")
def answered():
    """Every ANALYSIS case, planned and run once."""
    from backend.orchestration.orchestrator import answer

    out = {}
    for case in CASES:
        if case["expected_intent"] != cap.Capability.ANALYSIS:
            continue
        try:
            out[case["question"]] = answer(case["question"])
        except Exception as e:  # noqa: BLE001 - recorded, asserted below
            out[case["question"]] = e
    return out


def test_no_analysis_question_raises(answered):
    """A question CreditProbe cannot answer must come back as a clarification,
    never as an exception."""
    broke = {q: repr(v) for q, v in answered.items() if isinstance(v, Exception)}
    assert broke == {}


def test_every_answer_is_either_computed_or_asked(answered):
    for question, result in answered.items():
        if isinstance(result, Exception):
            continue
        assert result.computed or result.clarification or result.result, (
            f"{question!r} produced neither an answer nor a question")


def test_a_forbidden_method_never_answers_its_case(answered):
    """A case naming a forbidden analysis is one where answering with it would
    be a correct figure for a question nobody asked."""
    by_question = {c["question"]: c for c in CASES}
    for question, result in answered.items():
        forbidden = by_question[question]["forbidden_methods"]
        if not forbidden or isinstance(result, Exception) or not result.computed:
            continue
        used = set(result.build.datasets)
        for name in forbidden:
            assert name not in used


# ------------------------------------------------------------- live evals


LIVE = os.environ.get("RUN_LIVE_LLM_EVALS") == "1"


@pytest.mark.skipif(not LIVE, reason="set RUN_LIVE_LLM_EVALS=1 to run these")
def test_the_live_model_routes_the_corpus_correctly():
    """The same corpus, against a real model.

    Opt-in: CI has no key, and a suite that sometimes passes is a suite people
    learn to ignore.
    """
    from backend.llm import is_configured
    from backend.orchestration.context import retrieve
    from backend.orchestration.router import read_request

    if not is_configured():
        pytest.skip("no AI provider key is configured")

    wrong: list[str] = []
    sample = CASES if os.environ.get("LIVE_EVAL_FULL") else CASES[::4]
    for case in sample:
        reading = read_request(case["question"],
                               context=retrieve(case["question"]))
        assert reading.source == "llm", (
            "the live eval must exercise the model, not the offline reader")
        if reading.intent != case["expected_intent"]:
            wrong.append(f"{case['question']!r}: expected "
                         f"{case['expected_intent']}, got {reading.intent}")
    accuracy = 1 - len(wrong) / len(sample)
    assert accuracy >= MIN_ROUTING_ACCURACY, (
        f"live routing accuracy {accuracy:.1%}\n" + "\n".join(wrong[:25]))
