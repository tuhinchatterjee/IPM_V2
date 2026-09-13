"""
Which fact a direction word is about.

LIVE-5 failed on a sentence that was true. Its reading said the premise was
not supported — 3 improved, 21 held, 6 deteriorated — and named the largest
deterioration at 8.0 points. The guard refused it, because the Contracting
population carries `ews_change_1m: -8.0` for two obligors that improved AND
`+8.0` for five that deteriorated, and the guard was binding direction to a
MAGNITUDE.

    Yamama Projects 6      -8.0   improved
    Salman Partners 4      -8.0   improved
    Sahara Development     +8.0   deteriorated
    Tihama Ventures        +8.0   deteriorated
    Al Rajhi Resources 8   +8.0   deteriorated
    Sahara Projects 9      +8.0   deteriorated
    Tadawi Partners 9      +8.0   deteriorated

The guard already dropped a size that the result carried both ways. What
starved that safeguard was a change-name pattern that did not recognise
`largest_deterioration` as a movement — so the only 8.0 it saw was the
improvers', the collision looked like a certainty, and "deteriorated ... 8.0"
read as a contradiction.

Two things follow. Direction is decided per FACT by the metric module, not by
a number. And a reading that wants a size checked names the fact it is talking
about, which is the only way to tell these seven obligors apart.
"""

from __future__ import annotations

import pytest

from backend.early_warning import metrics as mt
from backend.early_warning import wide
from backend.early_warning.conversation import derivation as dv
from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import reading as rd

IMPROVER = "rows.CORP-102361.ews_change_1m"   # Yamama Projects 6,   -8.0
DETERIORATOR = "rows.CORP-100034.ews_change_1m"  # Sahara Development, +8.0


@pytest.fixture(scope="module")
def contracting():
    frame = wide.with_movement("2026-06")
    return frame[frame["sector"] == "Contracting"]


# ------------------------------------------------- the collision is real

def test_the_population_carries_the_same_size_both_ways(contracting):
    changes = contracting["ews_change_1m"]
    assert set(changes[changes.abs() == 8.0]) == {-8.0, 8.0}


def test_the_census_is_what_the_reading_said_it_was(contracting):
    changes = contracting["ews_change_1m"]
    assert len(changes) == 30
    assert int((changes < 0).sum()) == 3
    assert int((changes == 0).sum()) == 21
    assert int((changes > 0).sum()) == 6


def test_the_largest_deterioration_is_a_rise_of_eight(contracting):
    assert float(contracting["ews_change_1m"].max()) == 8.0
    assert float(contracting["ews_change_1m"].min()) == -10.0


# --------------------------------------------------- direction per fact

@pytest.mark.parametrize("name,value,expected", [
    ("rows.CORP-1.ews_change_1m", -8.0, "improved"),
    ("rows.CORP-2.ews_change_1m", 8.0, "deteriorated"),
    ("largest_deterioration", 8.0, "deteriorated"),
    ("largest_improvement", -10.0, "improved"),
    ("movement_census.largest_deterioration.change", 8.0, "deteriorated"),
    ("movement_census.largest_improvement.change", -10.0, "improved"),
    ("movement.layers.L4.score_change", -15.46, "improved"),
    ("movement.layers.L4.points_contributed", -2.32, "improved"),
    ("ews_change_12m", 3.0, "deteriorated"),
])
def test_the_metric_module_decides_which_way(name, value, expected):
    assert mt.describes(name, value) == expected


@pytest.mark.parametrize("name,value", [
    ("rows.CORP-1.ews_score", 8.0),
    ("exposure", 6460.56),
    ("obligors", 30.0),
    ("movement_census.total", 30.0),
    ("movement_census.deteriorated_count", 6.0),
    ("period", 2026.0),
])
def test_a_level_or_a_count_is_not_a_move(name, value):
    """Counts, levels and labels have no direction to contradict."""
    assert mt.movement_sign(name, value) == 0


def test_a_metric_nobody_has_classified_is_left_alone():
    assert mt.worse_when_positive("mystery_change_1m") == 0
    assert mt.movement_sign("mystery_change_1m", -5.0) == 0


def test_the_semantics_come_from_the_field_dictionary():
    from backend.early_warning import dictionary as dic

    assert (dic.describe("ews_score") or {})["higher_is_worse"] is True
    assert mt.worse_when_positive("ews_change_1m") == 1
    assert (dic.describe("exposure") or {})["higher_is_worse"] is False


# ------------------------------------------- the ambiguous size is skipped

def collision_packet() -> packet_mod.ResultPacket:
    return packet_mod.ResultPacket(
        period="2026-06",
        figures={"largest_deterioration": 8.0, "largest_improvement": -10.0,
                 "movement_population": 30, "improved": 3, "unchanged": 21,
                 "worsened": 6},
        rows=[{"customer_id": "CORP-102361", "ews_change_1m": -8.0},
              {"customer_id": "CORP-100034", "ews_change_1m": 8.0},
              {"customer_id": "CORP-103270", "ews_change_1m": -10.0}])


def test_a_size_the_result_carries_both_ways_is_not_checked():
    changes = rd._signed_changes(collision_packet(), [])
    assert "8.0" not in changes, (
        "8.0 is an improvement for two obligors and a deterioration for five")
    assert changes.get("10.0") == -1, "10.0 is only ever the improvement"


def test_the_live_5_sentence_is_no_longer_refused():
    written = {"direct": "",
               "interpretation": ("The premise that every Contracting obligor "
                                  "improved is not supported: 3 improved, 21 "
                                  "held and 6 deteriorated, with the largest "
                                  "deterioration at 8.0 points."),
               "points": [], "drivers": [],
               "follow_ups": ["Which six Contracting obligors deteriorated, "
                              "and by how much?"],
               "caveats": []}
    assert rd._direction_conflicts(
        written, rd._signed_changes(collision_packet(), [])) == []


def test_an_unambiguous_size_is_still_checked():
    written = {"direct": "Al Rajhi Logistics 8 deteriorated by 10.0 points.",
               "interpretation": "", "points": [], "drivers": [],
               "follow_ups": [], "caveats": []}
    conflicts = rd._direction_conflicts(
        written, rd._signed_changes(collision_packet(), []))
    assert [c["token"] for c in conflicts] == ["10.0"]


# ------------------------------------------------ the structured binding

FACTS = {
    "rows.CORP-102361.ews_change_1m": -8.0,
    "rows.CORP-100034.ews_change_1m": 8.0,
    "movement_census.largest_deterioration.change": 8.0,
    "movement_census.largest_improvement.change": -10.0,
    "movement_census.improved_count": 3.0,
    "exposure": 6460.56,
}


def bind(**claim):
    checked, settled = rd._checked_movements([claim], FACTS)
    return checked[0], settled


@pytest.mark.parametrize("ref,direction,value,accepted", [
    # The same size, opposite obligors. This is the whole point.
    (IMPROVER, "improved", 8.0, True),
    (IMPROVER, "decreased", 8.0, True),
    (IMPROVER, "down", 8.0, True),
    (IMPROVER, "deteriorated", 8.0, False),
    (IMPROVER, "increased", 8.0, False),
    (IMPROVER, "up", 8.0, False),
    (DETERIORATOR, "deteriorated", 8.0, True),
    (DETERIORATOR, "increased", 8.0, True),
    (DETERIORATOR, "up", 8.0, True),
    (DETERIORATOR, "improved", 8.0, False),
    (DETERIORATOR, "decreased", 8.0, False),
    (DETERIORATOR, "down", 8.0, False),
])
def test_the_binding_tells_the_two_apart(ref, direction, value, accepted):
    checked, _ = bind(fact_ref=ref, direction=direction, value=value)
    assert checked["accepted"] is accepted, checked.get("reason")


def test_the_census_extreme_can_be_bound():
    checked, settled = bind(
        fact_ref="movement_census.largest_deterioration.change",
        direction="deteriorated", value=8.0)
    assert checked["accepted"] is True
    assert "8.0" in settled


def test_the_signed_value_may_be_declared_instead_of_the_size():
    checked, _ = bind(fact_ref=IMPROVER, direction="improved", value=-8.0)
    assert checked["accepted"] is True


def test_a_value_that_is_not_the_fact_is_refused():
    checked, _ = bind(fact_ref=IMPROVER, direction="improved", value=9.0)
    assert checked["accepted"] is False
    assert "which the result carries at -8" in checked["reason"]


def test_a_reference_to_nothing_is_refused_cleanly():
    checked, _ = bind(fact_ref="rows", direction="improved", value=8.0)
    assert checked["accepted"] is False
    assert "no fact called 'rows'" in checked["reason"]


def test_a_direction_this_product_does_not_read_is_refused():
    checked, _ = bind(fact_ref=IMPROVER, direction="sideways", value=8.0)
    assert checked["accepted"] is False


def test_a_level_has_no_direction_to_contradict():
    checked, _ = bind(fact_ref="exposure", direction="increased", value=6460.56)
    assert checked["accepted"] is True
    assert "does not measure a move" in checked["reason"]


def test_a_bound_size_is_exempt_from_the_size_check():
    """A named fact beats a guess about a nearby verb."""
    written = {"direct": "Sahara Development deteriorated by 8.0 points.",
               "interpretation": "", "points": [], "drivers": [],
               "follow_ups": [], "caveats": []}
    _, settled = bind(fact_ref=DETERIORATOR, direction="deteriorated",
                      value=8.0)
    changes = {"8.0": -1}   # as if the packet only carried the improvers
    assert rd._direction_conflicts(written, changes) != []
    assert rd._direction_conflicts(written, changes, settled) == []


# --------------------------------------------------- every reading section

@pytest.mark.parametrize("section", [
    "direct", "interpretation", "points", "follow_ups", "caveats", "drivers"])
def test_direction_is_checked_in_every_section(section):
    written = {"direct": "", "interpretation": "", "points": [],
               "drivers": [], "follow_ups": [], "caveats": []}
    sentence = "Al Rajhi Logistics 8 deteriorated by 10.0 points."
    if isinstance(written[section], list):
        written[section] = [sentence]
    else:
        written[section] = sentence
    conflicts = rd._direction_conflicts(
        written, rd._signed_changes(collision_packet(), []))
    assert conflicts and conflicts[0]["field"].startswith(section)


@pytest.mark.parametrize("prose", [
    "As at 2026-06 the position improved.",
    "It improved out of HIGH into LOW.",
    "L4 network and relationship improved.",
    "The top 5 improved.",
    "3 improved, 21 held and 6 deteriorated.",
])
def test_labels_ordinals_and_counts_are_left_alone(prose):
    written = {"direct": prose, "interpretation": "", "points": [],
               "drivers": [], "follow_ups": [], "caveats": []}
    assert rd._direction_conflicts(
        written, rd._signed_changes(collision_packet(), [])) == []


# ------------------------------------------------------------- end to end

LIVE_5 = ("Given every Contracting obligor improved last month, which one "
          "improved most?")


def run(monkeypatch, behaviour: str, thread: str):
    from backend.early_warning.conversation import pipeline as pl
    from backend.early_warning.conversation import seam as seam_mod
    from tests.early_warning.stub_provider import StubProvider, install

    tool = seam_mod.STAGES[seam_mod.INTERPRETATION].tool_name
    install(monkeypatch, StubProvider(behaviour=behaviour, behaviour_for=tool))
    turn = pl.answer(LIVE_5, thread_id=thread).to_dict()
    detail = next(e["detail"] for e in reversed(turn["events"])
                  if e["stage"] == pl.FINAL_ANSWER)
    return turn, detail


def test_the_live_5_reading_survives(monkeypatch):
    from backend.early_warning.conversation import seam as seam_mod

    _, detail = run(monkeypatch, "live_5_census", "l5b-e2e")
    assert detail["engine"] == seam_mod.MODEL, (
        detail.get("model_call", {}).get("fallback_reason"))
    assert detail["direction_conflicts"] == []
    assert detail["ungrounded_figures"] == []
    assert detail["movement_claims"]
    assert all(m["accepted"] for m in detail["movement_claims"])


def test_the_same_reading_with_the_wrong_way_round_is_discarded(monkeypatch):
    from backend.early_warning.conversation import seam as seam_mod

    _, detail = run(monkeypatch, "live_5_wrong_way", "l5b-e2e-wrong")
    assert detail["engine"] == seam_mod.DETERMINISTIC
    refused = [m for m in detail["movement_claims"] if not m["accepted"]]
    assert refused and refused[0]["fact_direction"] == "deteriorated"
    assert detail["direction_conflicts"]


def test_the_census_reaches_the_packet_with_its_names(monkeypatch):
    from backend.early_warning.conversation import pipeline as pl
    from tests.early_warning.stub_provider import StubProvider, install

    install(monkeypatch, StubProvider())
    turn = pl.answer(LIVE_5, thread_id="l5b-census").to_dict()
    census = turn["result_packet"]["results"]["figures"]["movement_census"]
    assert census["total"] == 30
    assert census["improved_count"] == 3
    assert census["held_count"] == 21
    assert census["deteriorated_count"] == 6
    assert census["largest_improvement"]["change"] == -10.0
    assert census["largest_improvement"]["customer_name"] == "Al Rajhi Logistics 8"
    assert census["largest_deterioration"]["change"] == 8.0
    assert census["largest_deterioration"]["customer_name"]


def test_the_census_names_are_published_to_the_writer(monkeypatch):
    from backend.early_warning.conversation import pipeline as pl
    from tests.early_warning.stub_provider import StubProvider, install

    stub = install(monkeypatch, StubProvider())
    pl.answer(LIVE_5, thread_id="l5b-published")
    context = next(c["packet"] for c in stub.calls
                   if c["tool"] == "interpret_the_result")
    published = context["fact_index"]
    for name in ("movement_census.improved_count",
                 "movement_census.deteriorated_count",
                 "movement_census.largest_deterioration.change",
                 "movement_census.largest_improvement.change"):
        assert name in published, name
    # And the measure's NAME is not published as a figure.
    assert "movement_census.measure" not in published
