"""The evaluation bank's structure, so its coverage cannot quietly shrink.

These tests do not run any question. Nothing here can: the bank exists to be
run against real models, and a mock cannot answer any of it. What they hold is
that the bank still covers what was asked for -- every named category, every
redirect target, every language, the controlled behaviour cases -- and that no
entry claims a grade nobody gave it.
"""

from __future__ import annotations

import json
from pathlib import Path

BANK = Path(__file__).resolve().parents[2] / "tests" / "evals" / \
    "cockpit_agentic" / "question_bank.json"

REQUIRED_CATEGORIES = (
    "PD trend and history", "PIT versus TTC", "12-month versus lifetime",
    "ECL movement and decomposition", "Rating migration",
    "Covenant deterioration", "Collateral coverage and haircuts", "Liquidity",
    "Leverage", "Debt service", "Profitability",
    "Borrower financial statements", "Macro relationships",
    "Multi-quarter comparison", "Borrower ranking", "Portfolio segmentation",
    "Multi-part analytical", "Ambiguous, needs clarification",
    "Thread follow-up", "Hindi", "Bengali", "Arabic", "Hinglish",
    "Must redirect: Early Warning", "Must redirect: Credit Scoring",
    "Must redirect: What-if", "Must redirect: Scorecard Validation",
    "Must redirect: Lenses", "Unsupported data", "Adversarial cross-domain")

REQUIRED_CONTROLLED = (
    "First query succeeds", "One failure, then a successful repair",
    "Repeated invalid query, five-submission stop",
    "Three-round sufficiency stop", "Time-budget stop", "Token-budget stop",
    "User cancellation", "Thread summary continuity", "No unnecessary chart",
    "A chart when it is analytically useful")


def bank() -> dict:
    return json.loads(BANK.read_text())


def test_the_bank_exists_and_is_readable():
    assert BANK.exists(), (
        "regenerate with: python scripts/build_cockpit_question_bank.py")
    assert bank()["questions"]


def test_there_are_at_least_sixty_questions():
    assert len(bank()["questions"]) >= 60


def test_every_required_category_is_covered():
    present = {entry["category"] for entry in bank()["questions"]}
    missing = [c for c in REQUIRED_CATEGORIES if c not in present]
    assert missing == [], f"the bank no longer covers: {missing}"


def test_every_excluded_module_has_questions_that_must_redirect():
    """Five modules the Cockpit must not answer for. Each needs its own
    questions, because a bank that covered four would let the fifth rot."""
    for module in ("Early Warning", "Credit Scoring", "What-if",
                   "Scorecard Validation", "Lenses"):
        matching = [e for e in bank()["questions"]
                    if e["category"] == f"Must redirect: {module}"]
        assert len(matching) >= 2, module
        for entry in matching:
            assert entry["expected_behaviour"] == "refer_and_execute_nothing"


def test_all_four_languages_are_covered():
    languages = {entry["language"] for entry in bank()["questions"]}
    assert {"en", "hi", "bn", "ar", "hi-en"} <= languages


def test_the_non_english_questions_are_actually_in_those_scripts():
    """A bank that labelled an English question 'Hindi' would test nothing."""
    scripts = {"hi": range(0x0900, 0x0980),      # Devanagari
               "bn": range(0x0980, 0x0A00),      # Bengali
               "ar": range(0x0600, 0x0700)}      # Arabic
    for entry in bank()["questions"]:
        span = scripts.get(entry["language"])
        if span is None:
            continue
        assert any(ord(ch) in span for ch in entry["question"]), \
            f"{entry['id']} is labelled {entry['language']} and is not in it"


def test_every_controlled_behaviour_case_is_present():
    names = {case["name"] for case in bank()["controlled_cases"]}
    missing = [c for c in REQUIRED_CONTROLLED if c not in names]
    assert missing == [], f"controlled cases missing: {missing}"


def test_every_entry_says_what_to_check():
    """A question with no check is a question nobody can review."""
    for entry in bank()["questions"]:
        assert entry["what_to_check"].strip()
        assert entry["expected_behaviour"] in (
            "answer_from_cockpit", "ask_before_choosing",
            "refer_and_execute_nothing", "say_the_data_is_not_there",
            "refuse_the_other_domain")


def test_the_ids_are_unique():
    ids = [entry["id"] for entry in bank()["questions"]]
    assert len(ids) == len(set(ids))


def test_the_bank_carries_no_expected_answers():
    """Deliberate. For most of these there is no single right number, and a
    bank shipping one would grade the model against its author's belief."""
    for entry in bank()["questions"]:
        for forbidden in ("expected_answer", "correct_answer", "gold",
                          "score"):
            assert forbidden not in entry


def test_the_bank_does_not_claim_to_have_been_graded():
    blob = bank()
    assert blob["graded"] is False
    assert "mock cannot answer" in blob["grading_note"]
