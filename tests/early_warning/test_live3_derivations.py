"""
The LIVE-3 packet, and the two figures its reading was discarded for.

The multi-part analytical case reached the real provider intact — seven of
seven model calls, two of two executions, no schema error, no truncation — and
lost its final interpretation to two numbers.

**`-4.86` was right.** The Contracting movement from 2024-11 to 2026-06 gives
`L1.points_contributed = -2.54` and `L4.points_contributed = -2.32`, and those
sum to exactly -4.86 of a -2.38 point move. The refs were right, the operation
was right, the arithmetic was right. The reading declared the SIZE, 4.86,
where the contract asks for the signed value, and the whole paragraph went.

**`6,301.85` was not.** Swept against every permitted fact: every published
month's Contracting exposure, every dominant-layer group and its complement,
every single-attribute subgroup across the sector and the book, every subset
and complement sum of the grouping's rows, cumulative sums under four
orderings, and the total less any one, two or three obligors. Nothing
reproduces it. It stays rejected, and this file pins that.

The third error — "the result carries no fact called `rows`" — was the writer
guessing at a vocabulary nobody had published. It now gets the index.
"""

from __future__ import annotations

import pytest

from backend.early_warning import facts as ff
from backend.early_warning.conversation import derivation as dv
from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import reading as rd

#: The window the live plan used. Not six months — Opus reached for the
#: earliest published month — which is why the figures below are not the ones
#: the six-month reading carries.
FROM_PERIOD, TO_PERIOD = "2024-11", "2026-06"

L1_CONTRIBUTION = -2.54
L4_CONTRIBUTION = -2.32
TOGETHER = -4.86
THE_MOVE = -2.38
L4_BEFORE, L4_AFTER, L4_CHANGE = 18.77, 3.31, -15.46

#: The figure nothing in the result produces.
UNSUPPORTED = 6301.85
CONTRACTING_EXPOSURE = 6460.56


@pytest.fixture(scope="module")
def movement() -> dict:
    pack = ff.movement(FROM_PERIOD, TO_PERIOD, {"sector": "Contracting"})
    figures = pack.figures or {}
    return dict(figures.get("movement") or figures)


@pytest.fixture(scope="module")
def live_packet(movement) -> packet_mod.ResultPacket:
    return packet_mod.ResultPacket(
        question=("Why has Contracting deteriorated over six months, is it "
                  "concentrated in a handful of names, and which layer is "
                  "driving it?"),
        period=TO_PERIOD, comparison_period=FROM_PERIOD,
        figures={"movement": movement, "exposure": CONTRACTING_EXPOSURE,
                 "obligors": 30})


def index(packet) -> dict[str, float]:
    return dv.index(rd._facts_of(packet))


# --------------------------------------------------- the packet is the one

def test_the_reconstructed_packet_is_the_live_one(movement):
    """If these drift, everything below is about a different result."""
    assert movement["ews_change"] == pytest.approx(THE_MOVE)
    by_layer = {entry["layer"]: entry for entry in movement["layers"]}
    assert by_layer["L1"]["points_contributed"] == pytest.approx(L1_CONTRIBUTION)
    assert by_layer["L4"]["points_contributed"] == pytest.approx(L4_CONTRIBUTION)
    assert by_layer["L4"]["score_before"] == pytest.approx(L4_BEFORE)
    assert by_layer["L4"]["score_after"] == pytest.approx(L4_AFTER)
    assert by_layer["L4"]["score_change"] == pytest.approx(L4_CHANGE)


def test_the_contribution_is_the_weighted_change(movement):
    """`points_contributed` is `score_change x weight`, already governed."""
    for entry in movement["layers"]:
        assert entry["points_contributed"] == pytest.approx(
            entry["score_change"] * entry["weight"], abs=0.01), entry["layer"]


# ------------------------------------------------------------------- -4.86

def test_minus_four_eighty_six_is_the_sum_of_two_governed_contributions(
        live_packet):
    facts = index(live_packet)
    claim = dv.check([{
        "value": TOGETHER, "op": "sum",
        "refs": ["movement.layers.L1.points_contributed",
                 "movement.layers.L4.points_contributed"]}], facts)[0]
    assert claim.accepted is True
    assert claim.sign_corrected is False
    assert claim.recomputed == pytest.approx(TOGETHER, abs=0.005)


def test_the_size_declared_where_the_signed_value_was_asked_for(live_packet):
    """The live failure, exactly: refs right, operation right, sign wrong."""
    facts = index(live_packet)
    claim = dv.check([{
        "value": abs(TOGETHER), "op": "sum",
        "refs": ["movement.layers.L1.points_contributed",
                 "movement.layers.L4.points_contributed"]}], facts)[0]
    assert claim.accepted is True
    assert claim.sign_corrected is True
    assert claim.recomputed == pytest.approx(TOGETHER, abs=0.005)


def test_a_size_that_is_not_the_size_is_still_refused(live_packet):
    facts = index(live_packet)
    claim = dv.check([{
        "value": 5.10, "op": "sum",
        "refs": ["movement.layers.L1.points_contributed",
                 "movement.layers.L4.points_contributed"]}], facts)[0]
    assert claim.accepted is False


def test_the_prose_may_state_the_size_of_the_contribution(live_packet):
    facts = index(live_packet)
    claims = dv.check([{
        "value": TOGETHER, "op": "sum",
        "refs": ["movement.layers.L1.points_contributed",
                 "movement.layers.L4.points_contributed"]}], facts)
    written = {"direct": "",
               "interpretation": ("L1 and L4 between them took 4.86 points "
                                  "off it."),
               "points": [], "drivers": [], "follow_ups": [], "caveats": []}
    allowed = rd._allowed_figures(live_packet, {}, {}, claims)
    assert rd._ungrounded(written, allowed, {TO_PERIOD, FROM_PERIOD}) == []


def test_the_runtime_now_carries_the_contribution_share(movement):
    """Server-owned, so the reading quotes rather than divides."""
    by_layer = {e["layer"]: e for e in movement["layers"]}
    assert by_layer["L1"]["share_of_move_pct"] == pytest.approx(
        L1_CONTRIBUTION / movement["ta_change"] * 100, abs=0.1)
    assert movement["leading_layer_contribution"] == pytest.approx(
        by_layer[movement["leading_layer"]]["points_contributed"])
    assert movement["ews_change_size"] == pytest.approx(abs(THE_MOVE))
    assert movement["direction"] == "improved"


# --------------------------------------------------------------- 6,301.85

def test_the_unsupported_exposure_is_in_no_permitted_fact(live_packet):
    facts = index(live_packet)
    assert not any(abs(v - UNSUPPORTED) < 0.05 for v in facts.values())


def test_no_grouping_produces_the_unsupported_exposure():
    """Swept over the level the live reading was talking about."""
    level = ff.level("dominant_layer", TO_PERIOD, only={"sector": "Contracting"})
    exposures = [float(r.get("exposure") or 0) for r in level.rows]
    total = float((level.figures or {}).get("exposure") or 0)
    assert total == pytest.approx(CONTRACTING_EXPOSURE, abs=0.05)
    assert all(abs(e - UNSUPPORTED) > 0.05 for e in exposures)
    assert all(abs(total - e - UNSUPPORTED) > 0.05 for e in exposures)
    assert abs(sum(exposures) - UNSUPPORTED) > 0.05


def test_the_unsupported_exposure_stays_rejected(live_packet):
    written = {"direct": "",
               "interpretation": (f"The weakest group is L2 at 36.54 across "
                                  f"SAR {UNSUPPORTED:,.2f}m of the SAR "
                                  f"{CONTRACTING_EXPOSURE:,.2f}m in scope."),
               "points": [], "drivers": [], "follow_ups": [], "caveats": []}
    allowed = rd._allowed_figures(live_packet, {}, {}, [])
    problems = rd._ungrounded(written, allowed, {TO_PERIOD, FROM_PERIOD})
    assert "6,301.85" in problems


def test_a_declaration_cannot_launder_it(live_packet):
    """Declaring an unsupported figure does not make it supported."""
    facts = index(live_packet)
    claim = dv.check([{"value": UNSUPPORTED, "op": "difference",
                       "refs": ["exposure", "obligors"]}], facts)[0]
    assert claim.accepted is False


def test_the_share_it_should_have_quoted_is_a_governed_fact():
    """What the reading needed instead of a manufactured subtotal."""
    level = ff.level("dominant_layer", TO_PERIOD, only={"sector": "Contracting"})
    shares = {r["dominant_layer"]: r["exposure_share_pct"] for r in level.rows}
    assert shares and abs(sum(shares.values()) - 100.0) < 0.2
    assert all(0 <= v <= 100 for v in shares.values())


# ------------------------------------------------- the reference vocabulary

def test_the_writer_is_shown_the_names_it_must_cite(live_packet):
    published = rd._published_index(live_packet)
    assert "movement.layers.L1.points_contributed" in published
    assert "movement.layers.L4.points_contributed" in published
    assert "movement.ews_change" in published


def test_every_published_name_resolves(live_packet):
    facts = index(live_packet)
    for name in rd._published_index(live_packet):
        assert dv._resolve(name, facts) is not None, name


def test_a_bare_rows_reference_is_refused_cleanly(live_packet):
    """The live third error. `rows` is a list; the index holds numbers."""
    claim = dv.check([{"value": 1.0, "op": "sum", "refs": ["rows"]}],
                     index(live_packet))[0]
    assert claim.accepted is False
    assert "no fact called rows" in claim.reason


def test_a_layer_code_is_not_published_as_a_figure(live_packet):
    """`layer: "L4"` is a name. Indexing its digits would publish a 4."""
    published = rd._published_index(live_packet)
    assert not any(k.endswith((".layer", ".name")) for k in published)


def test_the_index_prefers_the_name_a_person_would_write(live_packet):
    published = rd._published_index(live_packet)
    assert "movement.layers.L4.score_change" in published
    assert "movement.layers[3].score_change" not in published


# ------------------------------------------------------ direction and sign

@pytest.mark.parametrize("prose,conflict", [
    ("L4 network and relationship fell 15.46 to 3.31.", False),
    ("L4 network and relationship declined 15.46 to 3.31.", False),
    ("L4 network and relationship improved 15.46 points.", False),
    ("L4 network and relationship rose 15.46 to 3.31.", True),
    ("L4 network and relationship increased 15.46 points.", True),
    ("L4 network and relationship deteriorated 15.46 points.", True),
    ("L4 network and relationship widened 15.46 points.", True),
])
def test_the_verb_is_checked_against_the_sign(live_packet, prose, conflict):
    changes = rd._signed_changes(live_packet, [])
    written = {"direct": prose, "interpretation": "", "points": [],
               "drivers": [], "follow_ups": [], "caveats": []}
    assert bool(rd._direction_conflicts(written, changes)) is conflict, prose


def test_a_signed_figure_carries_its_own_direction(live_packet):
    changes = rd._signed_changes(live_packet, [])
    written = {"direct": "L4 moved -15.46 over the window.",
               "interpretation": "", "points": [], "drivers": [],
               "follow_ups": [], "caveats": []}
    assert rd._direction_conflicts(written, changes) == []


def test_a_level_is_not_a_move(live_packet):
    """3.31 is where L4 ended. The verb near it governs the change."""
    changes = rd._signed_changes(live_packet, [])
    assert "15.46" in changes
    assert "3.31" not in changes


def test_a_verb_in_the_previous_sentence_governs_nothing_here(live_packet):
    changes = rd._signed_changes(live_packet, [])
    written = {"direct": "",
               "interpretation": ("Its underlying condition has not eased. "
                                  "L4 rose 15.46 points."),
               "points": [], "drivers": [], "follow_ups": [], "caveats": []}
    conflicts = rd._direction_conflicts(written, changes)
    assert [c["said"] for c in conflicts] == ["rose"]


def test_an_ordinal_is_not_the_size_of_a_move(live_packet):
    changes = dict(rd._signed_changes(live_packet, []), **{"4": 1})
    written = {"direct": "", "interpretation": "It eased. 4 of the 10 share L2.T1.",
               "points": [], "drivers": [], "follow_ups": [], "caveats": []}
    assert rd._direction_conflicts(written, changes) == []


def test_a_size_the_result_carries_both_ways_is_not_checked():
    """Two true readings and no way to tell which — so the guard says nothing."""
    packet = packet_mod.ResultPacket(
        figures={"a_change": 5.5, "b_change": -5.5})
    assert "5.5" not in rd._signed_changes(packet, [])


# ------------------------------------------------------------- end to end

LIVE_3 = ("Why has Contracting deteriorated over six months, is it "
          "concentrated in a handful of names, and which layer is driving it?")


def run(monkeypatch, behaviour: str, thread: str):
    from backend.early_warning.conversation import pipeline as pl
    from backend.early_warning.conversation import seam as seam_mod
    from tests.early_warning.stub_provider import StubProvider, install

    tool = seam_mod.STAGES[seam_mod.INTERPRETATION].tool_name
    install(monkeypatch, StubProvider(behaviour=behaviour, behaviour_for=tool))
    turn = pl.answer(LIVE_3, thread_id=thread).to_dict()
    detail = next(e["detail"] for e in reversed(turn["events"])
                  if e["stage"] == pl.FINAL_ANSWER)
    return turn, detail


def test_the_live_3_reading_survives(monkeypatch):
    """A summed contribution, stated as a size, against published names."""
    from backend.early_warning.conversation import seam as seam_mod

    turn, detail = run(monkeypatch, "live_3_reading", "l3-e2e")
    assert detail["engine"] == seam_mod.MODEL, detail.get("model_call", {}).get(
        "fallback_reason")
    assert detail["ungrounded_figures"] == []
    assert detail["direction_conflicts"] == []
    claims = detail["derived_claims"]
    assert claims and all(c["accepted"] for c in claims)


def test_the_same_reading_with_the_wrong_verb_is_discarded(monkeypatch):
    from backend.early_warning.conversation import seam as seam_mod

    turn, detail = run(monkeypatch, "live_3_wrong_direction", "l3-e2e-verb")
    assert detail["engine"] == seam_mod.DETERMINISTIC
    assert detail["direction_conflicts"]
    said = detail["direction_conflicts"][0]
    assert said["direction_written"] == "up"
    assert said["direction_in_the_result"] == "down"
    # Every figure in it was grounded. That is the point.
    assert detail["ungrounded_figures"] == []


def test_an_unsupported_subtotal_is_still_discarded(monkeypatch):
    from backend.early_warning.conversation import seam as seam_mod

    turn, detail = run(monkeypatch, "live_3_unsupported_subtotal",
                       "l3-e2e-subtotal")
    assert detail["engine"] == seam_mod.DETERMINISTIC
    assert "6,301.85" in detail["ungrounded_figures"]


def test_the_headline_is_the_question_the_request_leads_with(monkeypatch):
    """"Why has Contracting deteriorated" is a diagnosis, whatever else the
    sentence also asks for. Pass two's merge used to take the first label in
    the cue table's declaration order and report a ranking."""
    from tests.early_warning.stub_provider import StubProvider, install
    from backend.early_warning.conversation import pipeline as pl

    install(monkeypatch, StubProvider())
    turn = pl.answer(LIVE_3, thread_id="l3-headline").to_dict()
    assert turn["result_packet"]["intent"] == "diagnosis"
    assert turn["answer"]["scope"] == "diagnosis"
