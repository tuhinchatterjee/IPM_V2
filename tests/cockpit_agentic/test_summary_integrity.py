"""The rolling thread summary stays a list of statements. Defect 2 of the
live UAT.

What was seen in a live thread:

    "settled_definitions": ["[", "\\"", "C", "o", "c", "k", "p", "i", "t", ...]

The root cause, found by reading the lifecycle end to end and not by looking
at the symptom:

    settled_definitions=[str(d) for d in (data.get("settled_definitions") or [])]

`data` is the tool input the model returned. The schema asks for an array of
strings and the model normally sends one -- but when it sends a STRING instead,
whether a bare sentence or a serialized array, `for d in value` iterates that
string one character at a time. Nothing downstream could tell the difference:
the result is a genuine `list[str]`, it validates, it is stored, it is echoed
back into the next summary request, and it is re-summarised from there. One bad
response makes a thread permanently corrupt, and each carry-forward multiplies
the summary's size.

The same expression appeared at 37 model-response boundaries in this package.
All of them now go through `contracts.as_text_list`, whose one rule is that a
string is never character-expanded.

These tests use the LABELLED MOCK provider for the lifecycle cases. What they
prove is what this application does with a response, which is where the defect
was.
"""

from __future__ import annotations

import json

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import sonnet as sonnet_mod
from backend.cockpit_agentic import thread as thread_mod
from backend.cockpit_agentic import ledger as L
from backend.cockpit_agentic.contracts import (Exchange, ThreadSummary,
                                               as_text_list,
                                               character_expanded,
                                               repair_text_list)
from tests.cockpit_agentic.fake_provider import FakeProvider

DEFINITION = "Cockpit means the stored twenty-quarter IFRS 9 credit book."
SECOND = "PIT PD is the point-in-time twelve-month probability of default."


def _summary(**fields) -> ThreadSummary:
    return ThreadSummary(thread_id="t", summary_through_exchange_id="e",
                         **fields)


def _exchange() -> Exchange:
    return Exchange(exchange_id="e1", question="What is PIT PD?",
                    answer="It is the point-in-time PD.", kind="answer",
                    fact_ids=["f1"], dataset_release_id="r1")


# ==================================================== 1-5. the normalization

def test_a_scalar_string_becomes_one_element():
    """The SAFE conversion, stated as the contract requires it."""
    assert as_text_list("some definition") == ["some definition"]
    assert as_text_list(DEFINITION) == [DEFINITION]


def test_a_string_is_never_character_expanded():
    """The FORBIDDEN conversion. This is the whole defect in one assertion."""
    for value in ("some definition", DEFINITION, "PD", "x"):
        out = as_text_list(value)
        assert out == [value]
        assert not any(len(item) == 1 and len(value) > 1 for item in out), (
            f"{value!r} was character-expanded")
    # And the shape the live thread actually held is not something this can
    # produce from any input.
    assert as_text_list('["Cockpit"]') != list('["Cockpit"]')


def test_a_serialized_json_array_is_parsed_back_into_its_elements():
    """The model sometimes returns the array as a STRING. That is a
    serialization accident, not one long statement and not 47 characters."""
    assert as_text_list(json.dumps([DEFINITION, SECOND])) == [DEFINITION,
                                                              SECOND]
    # Something that merely looks like an array and is not stays whole.
    assert as_text_list("[not json at all") == ["[not json at all"]
    assert as_text_list("[a, b]") == ["[a, b]"]


def test_a_real_list_passes_through_unchanged():
    assert as_text_list([DEFINITION, SECOND]) == [DEFINITION, SECOND]
    assert as_text_list(("a", "b")) == ["a", "b"]
    assert as_text_list([]) == []
    assert as_text_list(None) == []
    assert as_text_list("") == []
    assert as_text_list("   ") == []


def test_numbers_objects_and_nesting_are_handled_without_expansion():
    assert as_text_list([1, 2.5]) == ["1", "2.5"]
    assert as_text_list([[DEFINITION], [SECOND]]) == [DEFINITION, SECOND]
    assert as_text_list({"a": DEFINITION}) == [DEFINITION]
    assert as_text_list(b"bytes text") == ["bytes text"]


# ==================================================== 6-7. the detection

def test_a_character_expansion_is_detected():
    assert character_expanded(list(json.dumps([DEFINITION])))
    assert character_expanded(list("some definition"))


def test_detection_does_not_flag_real_short_lists():
    """Conservative on purpose. Quarter labels, rating grades and fact ids are
    short lists of short strings, and mistaking one for corruption would
    delete real evidence."""
    assert not character_expanded(["2026Q1", "2026Q2", "2026Q3"])
    assert not character_expanded(["f1", "f2", "f3", "f4", "f5", "f6", "f7",
                                   "f8", "f9"])
    assert not character_expanded(["AAA", "AA", "A", "BBB", "BB", "B", "CCC",
                                   "CC", "C"])
    assert not character_expanded([DEFINITION, SECOND])
    assert not character_expanded([])
    assert not character_expanded("a string, not a list")


# ==================================================== 8-10. the recovery

def test_a_rejoinable_expansion_is_rebuilt_exactly():
    """Recovery is a rejoin, not a reconstruction: the original statements
    come back character for character or they do not come back."""
    corrupt = list(json.dumps([DEFINITION, SECOND]))
    values, outcome = repair_text_list(corrupt)
    assert outcome == "recovered"
    assert values == [DEFINITION, SECOND]


def test_an_unrejoinable_expansion_is_cleared_and_nothing_is_invented():
    values, outcome = repair_text_list(list("some settled definition"))
    assert outcome == "cleared"
    assert values == []


def test_recovery_touches_only_the_malformed_field(caplog):
    summary = _summary(
        settled_definitions=[DEFINITION],
        corrections=[SECOND],
        authorized_references=["f1", "f2"],
        supported_conclusions=["ECL fell in 2026Q2."],
        unresolved_questions=["Which sector?"])
    summary.corrections = list("a correction that cannot be rejoined")

    report = summary.repair()

    assert report.cleared == ["corrections"]
    assert report.recovered == []
    assert summary.corrections == []
    # Everything else is exactly what it was, evidence references included.
    assert summary.settled_definitions == [DEFINITION]
    assert summary.authorized_references == ["f1", "f2"]
    assert summary.supported_conclusions == ["ECL fell in 2026Q2."]
    assert summary.unresolved_questions == ["Which sector?"]
    # And it is recorded rather than absorbed.
    assert report.occurred and report.to_dict()["cleared"] == ["corrections"]


# ==================================================== 11-12. the contract

def test_every_summary_list_field_is_a_list_of_strings_whatever_arrives():
    """The five fields the contract names, each given a bare string."""
    summary = _summary(
        settled_definitions=DEFINITION,
        corrections=SECOND,
        authorized_references="f1",
        supported_conclusions="ECL fell.",
        unresolved_questions="Which sector?")
    for name in K.SUMMARY_TEXT_FIELDS:
        values = getattr(summary, name)
        assert isinstance(values, list)
        assert all(isinstance(v, str) for v in values)
        assert len(values) == 1, f"{name} was character-expanded"


def test_the_live_failure_reproduced_through_update_summary():
    """The exact shape the model returned, through the real call path.

    Before the fix this stored 47 single characters beginning `["`, `"`, `C`.
    """
    returned = {"current_topic": "the Cockpit",
                # A STRING where the schema asked for an array -- both of the
                # shapes that were seen.
                "settled_definitions": json.dumps([DEFINITION]),
                "corrections": SECOND,
                "authorized_references": ["f1"],
                "supported_conclusions": [],
                "unresolved_questions": []}
    provider = FakeProvider(structured_script=[returned])
    ledger, _ = L.LedgerStore().open(request_id="sum", mode="standard",
                                     prices=L.Prices())

    updated = sonnet_mod.update_summary(None, _exchange(), provider, ledger)

    assert updated.settled_definitions == [DEFINITION]
    assert updated.corrections == [SECOND]
    assert not any(len(v) <= 1 for v in updated.settled_definitions)
    assert updated.authorized_references == ["f1"]


# ==================================================== 13. nothing carries on

def test_a_corrupt_stored_summary_is_never_carried_into_the_next_request():
    """A thread summarised by an earlier release. Construction cannot fix it --
    a stored expansion is already a list of strings -- so it is detected and
    undone on the way out, and the recovery is reported with the answer."""
    state = thread_mod.ThreadState(thread_id="t", dataset_release_id="r1")
    stored = _summary(authorized_references=["f1"])
    stored.settled_definitions = list(json.dumps([DEFINITION]))
    stored.supported_conclusions = list("a conclusion that cannot be rejoined")
    state.summary = stored

    rendered, _selection = state.context_for(limits=L.STANDARD_LIMITS)

    assert rendered["settled_definitions"] == [DEFINITION]
    assert rendered["supported_conclusions"] == []
    # The stored results and the evidence references are untouched.
    assert rendered["authorized_references"] == ["f1"]
    # The recovery travels with the answer instead of being absorbed.
    assert rendered["recovery"]["recovered"] == ["settled_definitions"]
    assert rendered["recovery"]["cleared"] == ["supported_conclusions"]
    assert "cleared" in rendered["recovery_note"]
    assert state.last_repair.occurred


def test_a_cleared_field_is_not_refilled_with_a_manufactured_conclusion():
    """The rule that matters more than the recovery: a summary that lost a
    conclusion says so. It does not produce one from the recent exchanges."""
    state = thread_mod.ThreadState(thread_id="t", dataset_release_id="r1")
    stored = _summary()
    stored.supported_conclusions = list("ECL fell sharply in the last quarter")
    state.summary = stored
    state.record(_exchange())

    rendered, _selection = state.context_for(limits=L.STANDARD_LIMITS)

    assert rendered["supported_conclusions"] == []
    assert "ECL fell" not in json.dumps(rendered)
    assert "do not state a conclusion" in rendered["recovery_note"]


# ==================================================== the growth check

def test_the_summary_does_not_grow_across_turns_when_a_string_comes_back():
    """The token consequence, measured.

    A character-expanded field is one JSON element per character, so it
    serializes to about five bytes per character of the statement it replaced
    -- measured here, it doubles the whole summary -- and it is echoed into
    the NEXT summary request, which re-expands whatever comes back. Three
    turns of that is what made a thread's context grow without bound.
    """
    from backend.cockpit_agentic.context import estimate_tokens

    ledger, _ = L.LedgerStore().open(request_id="grow", mode="standard",
                                     prices=L.Prices())
    returned = {"current_topic": "the Cockpit",
                "settled_definitions": json.dumps([DEFINITION, SECOND]),
                "corrections": [],
                "authorized_references": ["f1"],
                "supported_conclusions": [],
                "unresolved_questions": []}
    provider = FakeProvider(structured_script=[dict(returned)
                                               for _ in range(3)])

    sizes = []
    summary = None
    for _ in range(3):
        summary = sonnet_mod.update_summary(summary, _exchange(), provider,
                                            ledger)
        sizes.append(estimate_tokens(summary.to_dict()))

    assert sizes[0] == sizes[1] == sizes[2], (
        f"the summary grew across turns: {sizes}")
    assert summary.settled_definitions == [DEFINITION, SECOND]

    # And what it would have cost: the same content, character-expanded once.
    expanded = dict(summary.to_dict())
    expanded["settled_definitions"] = list(json.dumps([DEFINITION, SECOND]))
    assert estimate_tokens(expanded) > 2 * sizes[0], (
        "the expansion is not the size problem it was measured to be")


def test_the_expansion_expression_is_gone_from_every_response_boundary():
    """The root cause, checked where it lived rather than where it showed.

    `[str(x) for x in (data.get(...) or [])]` is the expression that
    character-expands a string. It appeared 37 times across the two model-facing
    modules; none may come back, because the next one will corrupt a different
    field and be just as invisible.
    """
    import pathlib
    import re

    pattern = re.compile(
        r"\[\s*str\((\w+)\)\s+for\s+\1\s+in\s+\((?:data|raw|s|a|c|t|item)\b",
        re.S)
    root = pathlib.Path(__file__).resolve().parents[2] / "backend"
    offenders = [
        str(path.relative_to(root.parent))
        for path in (root / "cockpit_agentic").glob("*.py")
        if pattern.search(path.read_text())]
    assert not offenders, (
        f"the character-expanding comprehension is back in: {offenders}")
