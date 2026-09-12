"""
The shapes a real model sends, and whether the stage survives them.

Pass two reads what is being asked and writes it into closed vocabularies —
the analyses this product can plan, the scopes it can cut by, the four
detection layers. Closed is right: a label the planner has no step for would
be reported forever afterwards as an uncovered part of the request.

What a live Sonnet does NOT do is invent a fifth layer. What it does is write
`"l3"` where the schema spells `"L3"`, `"Layer 3"` where it spells the code,
`["L3"]` where it declares a string, or `""` for a field it had nothing to say
about — and the whole pass was being thrown away over the case of one letter.
That cost a real certification case: the multi-part analytical question lost
its reading of the request and fell back to the patterns.

The discipline pinned here is the planner's, applied to this stage: map into
the vocabulary the schema already contains, and DROP what will not map. Never
invent, never widen the enum, never turn a closed field into free text.
"""

from __future__ import annotations

import pytest

from backend.early_warning import layers as lay
from backend.early_warning.conversation import normalise as nm
from backend.early_warning.conversation import seam as seam_mod

tidy = nm._pass_2_tidy
SCHEMA = nm._PASS_2_SCHEMA


def conforms(data: dict) -> list[str]:
    """The stage's own gate: tidy, then validate, exactly as `seam.call` does."""
    return seam_mod._conforms(seam_mod._tidied(data, SCHEMA, tidy), SCHEMA)


def base(**over) -> dict:
    out = {"normalized_business_request": "Why has Contracting deteriorated?",
           "requested_analyses": ["diagnosis"]}
    out.update(over)
    return out


# ------------------------------------------------------- requested_layer

@pytest.mark.parametrize("sent,expected", [
    ("L3", "L3"),
    ("l3", "L3"),
    ("  L3  ", "L3"),
    ("Layer 3", "L3"),
    ("layer 3", "L3"),
    ("L3 external intelligence", "L3"),
    ("external intelligence", "L3"),
    ("external-intelligence", "L3"),
    ("external warning signals", "L3"),
    ("Layer 1", "L1"),
    ("internal behavioural", "L1"),
    ("Layer 4", "L4"),
    (["L3"], "L3"),
])
def test_a_layer_a_real_model_names_is_mapped_to_its_code(sent, expected):
    assert tidy(base(requested_layer=sent))["requested_layer"] == expected


@pytest.mark.parametrize("sent", ["", "   ", None, [], "L9", "L0", "Layer 9",
                                  "the whole score", "unknown", ["L1", "L2"]])
def test_a_layer_that_resolves_to_nothing_is_dropped_not_guessed(sent):
    """Optional means optional. The patterns already read the sentence."""
    assert "requested_layer" not in tidy(base(requested_layer=sent))


def test_the_layer_enum_is_still_closed():
    enum = SCHEMA["properties"]["requested_layer"]["enum"]
    assert set(enum) == set(lay.CODES) | {""}


def test_the_aliases_come_from_the_registry_not_a_second_list():
    """`external intelligence` is L3 here because it is L3 everywhere."""
    for phrase in ("external intelligence", "Layer 3", "external signals"):
        assert tidy(base(requested_layer=phrase))["requested_layer"] \
            == lay.resolve(phrase) == "L3"


@pytest.mark.parametrize("sent", [
    "l3", "Layer 3", "external intelligence", ["L3"], "", None, "L9"])
def test_the_whole_pass_survives_every_layer_shape(sent):
    """The failure this closes: one field losing the entire reading."""
    assert conforms(base(requested_layer=sent)) == [], sent


# ------------------------------------------------- the other closed fields

@pytest.mark.parametrize("sent,expected", [
    (["root cause"], ["diagnosis"]),
    (["Movement"], ["movement"]),
    (["trend", "concentration"], ["movement", "concentration"]),
    (["band migration"], ["transition"]),
    ("diagnosis", ["diagnosis"]),
    (["diagnosis", "diagnosis"], ["diagnosis"]),
    (["sentiment analysis"], []),
    (["diagnosis", "sentiment analysis"], ["diagnosis"]),
])
def test_an_analysis_label_is_mapped_or_dropped(sent, expected):
    assert tidy(base(requested_analyses=sent))["requested_analyses"] == expected


@pytest.mark.parametrize("sent,expected", [
    ("industry", "sector"), ("Sector", "sector"), ("obligor", "borrower"),
    ("grade", "rating"), ("book", "portfolio"), ("borrower", "borrower"),
    ("something else", ""), ("", ""),
])
def test_a_scope_is_mapped_into_the_enum_or_emptied(sent, expected):
    assert tidy(base(requested_scope=sent))["requested_scope"] == expected


@pytest.mark.parametrize("sent,expected", [
    (["escalation"], ["escalate"]), (["notify"], ["inform"]),
    (["Escalate", "report"], ["escalate", "report"]),
    (["approve the limit"], []),
])
def test_an_action_is_mapped_into_the_enum_or_dropped(sent, expected):
    assert tidy(base(requested_actions=sent))["requested_actions"] == expected


def test_a_required_field_the_model_omitted_is_still_missing_afterwards():
    """Tidying corrects vocabulary. It never fills a gap."""
    problems = conforms({"requested_analyses": ["diagnosis"]})
    assert problems
    assert any("normalized_business_request" in p for p in problems)


def test_tidying_adds_no_field_the_model_did_not_send():
    sent = base()
    assert set(tidy(dict(sent))) == set(sent)


def test_an_unrelated_key_survives_untouched():
    out = tidy(base(clarification_needed=True, requested_evidence=False))
    assert out["clarification_needed"] is True
    assert out["requested_evidence"] is False


# ---------------------------------------------------- adversarial shapes

@pytest.mark.parametrize("payload", [
    {"requested_layer": "L3", "requested_scope": "sector",
     "requested_analyses": ["root cause", "concentration"],
     "requested_actions": ["escalation"]},
    {"requested_layer": None, "requested_scope": None,
     "requested_analyses": ["diagnosis"], "requested_actions": None},
    {"requested_layer": "  layer 4  ", "requested_analyses": "movement",
     "requested_grouping": "sector", "requested_period": "2026-06"},
    {"requested_layer": "L2", "requested_analyses": ["diagnosis"],
     "comparison_period": "-6m", "ambiguities": [], "subquestions": []},
])
def test_a_real_reply_shape_conforms_after_tidying(payload):
    assert conforms(base(**payload)) == [], payload


def test_a_reply_that_is_not_an_object_is_left_alone():
    assert tidy is nm._pass_2_tidy
    assert seam_mod._tidied(["not", "an", "object"], SCHEMA, tidy) \
        == ["not", "an", "object"]
