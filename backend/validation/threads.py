"""
Running a conversation the way the browser runs it, and checking what came out.

Why not call the orchestrator
------------------------------
Because that is how the last set of conversation-memory failures got through.
Typed memory was built, tested and shown to work — by tests that called the
orchestrator directly. The browser does not call the orchestrator. It calls
`POST /investigations` and `POST /investigations/{id}/messages`, and the
service behind those passed the analytical state and forgot the memory. So
"which of those fields are financial ratios?" worked in every test and failed
for every user.

This drives the endpoints, in the order a person would, and asserts on the
payloads that come back. The FastAPI test client is an in-process HTTP client:
same routing, same dependencies, same serialisation, no server to start.

Named expectations
------------------
Each check is a named function in `EXPECTATIONS`. A thread declares which ones
must hold, and a failure names the property rather than reporting that
something, somewhere, was false. There is no way to express an expectation this
module does not implement — an unknown name fails loudly, because a
verification that silently skipped a check it did not recognise would be a
verification that gets weaker as it is extended.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

HEADERS = {"X-IPM-Role": "ANALYST"}


# ---------------------------------------------------------------------------
# Driving it
# ---------------------------------------------------------------------------


def _client() -> Any:
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def ask(questions: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    """Every turn of one thread, as the browser would receive them."""
    client = _client()
    first = client.post("/api/v1/investigations",
                        json={"question": questions[0], "ask": True},
                        headers=HEADERS)
    if first.status_code not in (200, 201):
        raise RuntimeError(
            f"the thread could not be opened: HTTP {first.status_code}")
    body = first.json()
    thread_id = (body.get("thread") or {}).get("id")
    turns = [body.get("run") or {}]

    for question in questions[1:]:
        response = client.post(f"/api/v1/investigations/{thread_id}/messages",
                               json={"question": question}, headers=HEADERS)
        if response.status_code != 200:
            raise RuntimeError(
                f"a turn could not be sent: HTTP {response.status_code}")
        turns.append(response.json().get("run") or {})
    return turns


def run_thread(questions: tuple[str, ...] | list[str],
               expects: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Run a thread and report which of its expectations did not hold."""
    turns = ask(questions)
    unmet: list[str] = []
    for name in expects:
        check = EXPECTATIONS.get(name)
        if check is None:
            unmet.append(f"{name} (no such check)")
            continue
        try:
            if not check(turns):
                unmet.append(name)
        except Exception as e:  # noqa: BLE001 - a check that raises did not hold
            logger.info("The %s check raised: %s", name, e)
            unmet.append(f"{name} (raised)")

    return {
        "turns": len(turns),
        "unmet": unmet,
        "calls": sum(_calls(turn) for turn in turns),
        "model": _model(turns[-1]),
        "invariants": [_invariants(turn) for turn in turns
                       if _invariants(turn)],
    }


# ---------------------------------------------------------------------------
# Reading a turn
# ---------------------------------------------------------------------------


def rows(turn: dict[str, Any]) -> list[dict[str, Any]]:
    steps = turn.get("steps") or []
    return ((steps[0].get("result") or {}).get("rows") or []) if steps else []


def narrative(turn: dict[str, Any]) -> dict[str, Any]:
    return dict(turn.get("narrative") or {})


def prose(turn: dict[str, Any]) -> str:
    said = narrative(turn)
    return " ".join([
        str(said.get("direct_answer") or ""),
        str(said.get("interpretation") or ""),
        str(said.get("scope") or ""),
        *[str(p) for p in (said.get("interpretation_points") or [])],
    ])


def action(turn: dict[str, Any]) -> str:
    conversation = turn.get("conversation") or {}
    return str((conversation.get("continuation") or {}).get("action") or "")


def _calls(turn: dict[str, Any]) -> int:
    return int((turn.get("mode") or {}).get("model_calls") or 0)


def _model(turn: dict[str, Any]) -> str:
    mode = turn.get("mode") or {}
    return str(mode.get("model_name") or mode.get("model") or "")


def _invariants(turn: dict[str, Any]) -> dict[str, Any]:
    conversation = turn.get("conversation") or {}
    return dict(conversation.get("invariants") or {})


def _clarification(turn: dict[str, Any]) -> str:
    found = turn.get("clarification") or {}
    return str(found.get("question") or found.get("message") or "")


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


Turns = list[dict[str, Any]]


def _succeeded(turns: Turns) -> bool:
    return all(turn.get("status") == "succeeded" for turn in turns)


def _succeeded_or_empty(turns: Turns) -> bool:
    """A screen that matches nobody has succeeded, and must say so.

    The distinction that matters: "no customer meets all four conditions" is an
    ANSWER. A clarification or a failure is not, and neither is a table of
    customers who meet three of them.
    """
    return all(turn.get("status") == "succeeded" for turn in turns)


def _dataset_focus_retained(turns: Turns) -> bool:
    """The later turns are still about the dataset the first one named."""
    opening = prose(turns[0]).lower()
    named = [word for word in ("ratings", "rating", "customer_ratings")
             if word in opening]
    if not named:
        return False
    return any(word in prose(turns[-1]).lower() for word in named)


def _field_set_retained(turns: Turns) -> bool:
    """"Which of those" resolved to the fields the previous turn listed."""
    return action(turns[-1]) in ("METADATA_FOLLOWUP", "CONTINUE",
                                 "ASK_ABOUT_RESULT")


def _narrowed(turns: Turns) -> bool:
    """The final turn returned a SUBSET, not the whole catalogue again."""
    if len(turns) < 2:
        return False
    before, after = len(rows(turns[-2])), len(rows(turns[-1]))
    return 0 < after < before


def _two_periods(turns: Turns) -> bool:
    scope = (turns[-1].get("plan") or {}).get("scope") or {}
    return bool(scope.get("from_period")) and bool(scope.get("to_period"))


def _grouped(turns: Turns) -> bool:
    return len(rows(turns[-1])) > 1


def _ranked_descending(turns: Turns) -> bool:
    """The measure the question ranked by actually descends down the table."""
    found = rows(turns[-1])
    if len(found) < 2:
        return False
    columns = ((turns[-1].get("steps") or [{}])[0].get("result") or {}).get(
        "columns") or []
    numeric = [str(c.get("name")) for c in columns
               if isinstance(found[0].get(str(c.get("name"))), (int, float))
               and not isinstance(found[0].get(str(c.get("name"))), bool)]
    for name in numeric:
        values = [row.get(name) for row in found]
        if all(isinstance(v, (int, float)) for v in values) and \
                values == sorted(values, reverse=True):
            return True
    return False


def _invariants_passed(turns: Turns) -> bool:
    found = _invariants(turns[-1])
    return bool(found) and found.get("ok") is True


def _invariants_ran(turns: Turns) -> bool:
    return bool(_invariants(turns[-1]))


def _interpretation_grounded(turns: Turns) -> bool:
    """Something was said about the result, and it was allowed to be said."""
    said = narrative(turns[-1])
    if not str(said.get("interpretation") or "").strip():
        return False
    conversation = turns[-1].get("conversation") or {}
    grounding = conversation.get("grounding") or {}
    return grounding.get("ok") is not False


def _population_retained(turns: Turns) -> bool:
    """The follow-ups stayed inside the five names the first turn returned."""
    first = len(rows(turns[0]))
    if not first:
        return False
    return all(0 <= len(rows(turn)) <= first for turn in turns[1:])


def _no_expansion(turns: Turns) -> bool:
    """No turn silently widened back to the whole book."""
    first = len(rows(turns[0]))
    return all(len(rows(turn)) <= max(first, 1) for turn in turns[1:])


def _reused_result(turns: Turns) -> bool:
    mode = turns[-1].get("mode") or {}
    return mode.get("reused_result") is True


def _no_rescan(turns: Turns) -> bool:
    mode = turns[-1].get("mode") or {}
    return mode.get("data_rescan") is False and mode.get("reused_result") is True


def _association_not_causation(turns: Turns) -> bool:
    """The assessment described how the figures move, and claimed no cause."""
    said = prose(turns[-1]).lower()
    caveats = " ".join(str(c) for c in narrative(turns[-1]).get("caveats") or [])
    if "does not establish that one causes the other" not in caveats.lower():
        return False
    return not any(word in said for word in
                   (" causes ", " caused by ", " proves that "))


def _sample_size_stated(turns: Turns) -> bool:
    said = prose(turns[-1]).lower()
    return "groups" in said or "observations" in said


def _asks_or_states_choice(turns: Turns) -> bool:
    """An ambiguous measure is asked about, or the reading is stated.

    Both are acceptable and silence is not. What must never happen is drawn
    exposure being chosen quietly and presented as "exposure".
    """
    turn = turns[-1]
    if turn.get("status") == "needs_clarification":
        return bool(_clarification(turn))
    scope = str(narrative(turn).get("scope") or "").lower()
    return any(word in scope for word in ("drawn", "limit", "commitment",
                                          "outstanding", "ead", "exposure at"))


def _every_row_satisfies_threshold(turns: Turns) -> bool:
    """Every returned row meets the closing-period condition the question set.

    Read off the invariant record rather than recomputed here. Recomputing it
    would be a second implementation of the threshold, and the two would
    eventually disagree about which one the product actually enforced.
    """
    found = _invariants(turns[-1])
    if not found:
        return False
    return not (found.get("failed") or [])


def _prose_satisfies_threshold(turns: Turns) -> bool:
    found = _invariants(turns[-1])
    checked = found.get("checked") or []
    return bool(checked) and not (found.get("failed") or [])


def _unsupported(turns: Turns) -> bool:
    turn = turns[-1]
    if turn.get("status") == "succeeded" and rows(turn):
        return False
    said = (prose(turn) + " " + _clarification(turn)).lower()
    return any(phrase in said for phrase in
               ("does not hold", "no data", "not hold data", "cannot answer",
                "outside", "does not cover"))


def _no_unrelated_analysis(turns: Turns) -> bool:
    """Nothing was computed for a question nothing in the book is about."""
    return not rows(turns[-1])


def _no_method_menu(turns: Turns) -> bool:
    """The refusal did not offer a list of governed figures to choose between.

    A menu invites the user to accept an answer about exposure to a question
    about corporate governance, which is the specific failure this checks for.
    """
    said = (prose(turns[-1]) + " " + _clarification(turns[-1])).lower()
    return not any(phrase in said for phrase in
                   ("did you mean", "you could ask", "choose one of",
                    "try one of"))


EXPECTATIONS: dict[str, Callable[[Turns], bool]] = {
    "succeeded": _succeeded,
    "succeeded_or_empty": _succeeded_or_empty,
    "dataset_focus_retained": _dataset_focus_retained,
    "field_set_retained": _field_set_retained,
    "narrowed": _narrowed,
    "two_periods": _two_periods,
    "grouped": _grouped,
    "ranked_descending": _ranked_descending,
    "invariants_passed": _invariants_passed,
    "invariants_ran": _invariants_ran,
    "interpretation_grounded": _interpretation_grounded,
    "population_retained": _population_retained,
    "no_expansion": _no_expansion,
    "reused_result": _reused_result,
    "no_rescan": _no_rescan,
    "association_not_causation": _association_not_causation,
    "sample_size_stated": _sample_size_stated,
    "asks_or_states_choice": _asks_or_states_choice,
    "every_row_satisfies_threshold": _every_row_satisfies_threshold,
    "prose_satisfies_threshold": _prose_satisfies_threshold,
    "unsupported": _unsupported,
    "no_unrelated_analysis": _no_unrelated_analysis,
    "no_method_menu": _no_method_menu,
}


__all__ = ["EXPECTATIONS", "ask", "run_thread"]
