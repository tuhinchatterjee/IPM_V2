"""
A ranking answers by the measure it was ranked on.

The live certification asked "Given every Contracting obligor improved last
month, which one improved most?". Ownership was right, the plan was right —
it ranked Contracting by one-month score movement — and the reading that came
back said this:

    As at 2026-06, 11 obligors in Contracting sit at high or above. The 5
    largest by exposure are listed, led by Al Rajhi Logistics 8 at 0.0
    (very low)...

Three sentences about three different populations. The count came from a
high-plus filter the ranking did not have; the order was claimed as exposure
over a list sorted by movement; the leader was described by a current score
of zero rather than by the ten-point fall that put it first. None of it
answers "which improved most", and the model then had to construct the
false-premise rebuttal out of raw rows — arithmetic the grounding guard
refuses, correctly, having never been shown the workings.

So the ranking pack now carries what it was ordered by, which way, whether it
was filtered to high-plus, and a census of the whole population's movement.
The composer reads all four.
"""

from __future__ import annotations

import pytest

from backend.early_warning import compose as cp
from backend.early_warning import facts as ff
from backend.early_warning.conversation import execute as ex

IMPROVERS = [
    {"customer_id": "C1", "customer_name": "Al Rajhi Logistics 8",
     "ews_change_1m": -10.0, "anchor_change_1m": -14.0, "ews_score": 0.0,
     "ews_band": "VERY_LOW", "exposure": 319.61},
    {"customer_id": "C2", "customer_name": "Yamama Projects 6",
     "ews_change_1m": -8.0, "anchor_change_1m": 0.0, "ews_score": 12.0,
     "ews_band": "VERY_LOW", "exposure": 134.24},
    {"customer_id": "C3", "customer_name": "Salman Partners 4",
     "ews_change_1m": -8.0, "anchor_change_1m": 0.0, "ews_score": 16.0,
     "ews_band": "VERY_LOW", "exposure": 172.63},
]

CENSUS = {"movement_measure": "ews_change_1m", "movement_population": 30,
          "improved": 3, "unchanged": 21, "worsened": 6,
          "largest_improvement": -10.0, "largest_deterioration": 12.0}


def movement_pack(**over) -> ff.FactPack:
    figures = {"obligors": 30, "exposure": 6460.56, "high_plus_count": 11,
               "named": 3, "ordered_by": "ews_change_1m", "descending": False,
               "filtered_to_high_plus": False, **CENSUS}
    figures.update(over.pop("figures", {}))
    return ff.FactPack(scope="ranking", label="Contracting", period="2026-06",
                       figures=figures, rows=list(IMPROVERS), **over)


def exposure_pack() -> ff.FactPack:
    return ff.FactPack(
        scope="ranking", label="Contracting", period="2026-06",
        figures={"obligors": 30, "high_plus_count": 11, "named": 3,
                 "ordered_by": "exposure", "descending": True,
                 "filtered_to_high_plus": True},
        rows=[dict(r, ews_score=60.0, ews_band="HIGH") for r in IMPROVERS])


def said(composed) -> str:
    return " ".join([composed.direct, composed.interpretation,
                     *composed.points])


# ------------------------------------------------------- the ranked measure

def test_a_movement_ranking_says_it_ranked_on_movement():
    out = cp.ranking(movement_pack())
    assert "improved most over the month are listed" in out.direct
    assert "largest by exposure" not in out.direct


def test_the_leader_is_named_by_the_move_that_put_it_first():
    out = cp.ranking(movement_pack())
    assert "Al Rajhi Logistics 8 at -10.0 points" in out.direct


def test_every_line_shows_the_ranked_measure():
    out = cp.ranking(movement_pack())
    assert out.points[0].startswith("Al Rajhi Logistics 8 at -10.0 points")
    assert "-8.0 points" in out.points[1]


def test_a_descending_movement_ranking_reads_as_deterioration():
    out = cp.ranking(movement_pack(figures={"descending": True}))
    assert "deteriorated most over the month are listed" in out.direct


def test_an_exposure_ranking_still_reads_the_way_it_did():
    out = cp.ranking(exposure_pack())
    assert "largest by exposure are listed" in out.direct
    assert "ordered by exposure rather than by score" in out.interpretation


def test_an_unfamiliar_measure_is_named_from_the_field_dictionary():
    out = cp.ranking(movement_pack(figures={"ordered_by": "ews_score",
                                            "descending": True,
                                            "movement_measure": ""}))
    assert "early warning score" in out.direct.lower()


# --------------------------------------------------------------- the counts

def test_the_opening_count_is_the_population_the_ranking_ran_over():
    out = cp.ranking(movement_pack())
    assert "30 obligors in Contracting match" in out.direct
    assert "sit at high or above" not in out.direct


def test_a_high_plus_ranking_may_still_say_high_or_above():
    out = cp.ranking(exposure_pack())
    assert "11 obligors in Contracting sit at high or above" in out.direct


def test_the_census_answers_how_many_actually_improved():
    out = cp.ranking(movement_pack())
    assert "3 of the 30 improved" in out.interpretation
    assert "21 held" in out.interpretation
    assert "6 deteriorated" in out.interpretation


@pytest.mark.parametrize("improved,expected", [
    (0, "None of the 30 improved"),
    (30, "All 30 improved"),
    (3, "3 of the 30 improved"),
])
def test_the_census_reads_correctly_at_the_edges(improved, expected):
    out = cp.ranking(movement_pack(figures={
        "improved": improved, "unchanged": 30 - improved, "worsened": 0}))
    assert expected in out.interpretation


def test_an_exposure_ranking_has_no_census_to_state():
    out = cp.ranking(exposure_pack())
    assert "improved" not in out.interpretation


# ------------------------------------------------------------ the small slips

def test_a_row_without_a_band_does_not_print_empty_brackets():
    assert cp._band_phrase(0.0, "") == "0.0"
    assert cp._band_phrase(0.0, "VERY_LOW") == "0.0 (very low)"


def test_a_zero_move_is_not_written_with_a_sign():
    flat = dict(IMPROVERS[0], ews_change_1m=0.0)
    out = cp.ranking(movement_pack(figures={}))
    out2 = cp.ranking(ff.FactPack(
        scope="ranking", label="Contracting", period="2026-06",
        figures={"obligors": 30, "ordered_by": "ews_change_1m", **CENSUS},
        rows=[flat]))
    assert "+0.0" not in " ".join(out2.points)
    assert "unchanged" in out2.points[0]
    del out


def test_a_movement_ranking_warns_about_notch_driven_falls():
    out = cp.ranking(movement_pack())
    assert "notch" in out.interpretation


def test_the_next_drills_follow_the_question_that_was_asked():
    out = cp.ranking(movement_pack())
    joined = " ".join(out.follow_ups).lower()
    assert "move" in joined or "anchor" in joined


# --------------------------------------------------------- the census itself

def test_the_census_counts_the_population_not_the_listed_rows():
    """The limit decides how many names are shown, not how many moved."""
    import pandas as pd

    frame = pd.DataFrame({"ews_change_1m": [-10.0, -8.0, -8.0]
                          + [0.0] * 21 + [1.0] * 6})
    got = ex._movement_census(frame, "ews_change_1m")
    assert got["movement_population"] == 30
    assert got["improved"] == 3
    assert got["unchanged"] == 21
    assert got["worsened"] == 6
    assert got["largest_improvement"] == -10.0


def test_no_census_for_a_measure_that_is_not_a_movement():
    import pandas as pd

    frame = pd.DataFrame({"exposure": [1.0, 2.0]})
    assert ex._movement_census(frame, "exposure") == {}


def test_no_census_where_the_column_is_absent():
    import pandas as pd

    assert ex._movement_census(pd.DataFrame({"exposure": [1.0]}),
                               "ews_change_1m") == {}


def test_a_column_of_nothing_yields_no_census():
    import pandas as pd

    frame = pd.DataFrame({"ews_change_1m": [None, None]})
    assert ex._movement_census(frame, "ews_change_1m") == {}


# ------------------------------------------------------------- end to end

def test_the_live_question_is_answered_by_movement(monkeypatch):
    from backend.early_warning.conversation import pipeline as pl
    from tests.early_warning.stub_provider import StubProvider, install

    plan = {"steps": [{
        "analysis": "ranking", "domain": "early_warning", "period": "2026-06",
        "comparison_period": "2026-05", "filters": {"sector": "Contracting"},
        "group_by": "", "measures": ["ews_change_1m", "anchor_change_1m",
                                     "ews_score", "ews_band", "exposure"],
        "order_by": "ews_change_1m", "descending": False, "limit": 5,
        "customer_id": "", "layer": "", "signal_key": "", "from_band": "",
        "to_band": "", "direction": "", "left": "", "right": "",
        "rationale": "Rank Contracting by one-month movement."}],
        "output_grain": "borrower_month", "intent": "ranking", "notes": []}
    install(monkeypatch, StubProvider(replies={"plan_the_analysis": plan}))
    turn = pl.answer("Given every Contracting obligor improved last month, "
                     "which one improved most?",
                     thread_id="ranking-live-5").to_dict()
    answer = turn["answer"]
    text = " ".join([answer.get("direct") or "",
                     answer.get("interpretation") or ""])
    # It names the improver, by its improvement.
    assert "Al Rajhi Logistics 8" in text
    assert "-10.0 points" in text
    # And it contradicts the premise with a counted figure rather than a guess.
    assert "of the 30 improved" in text
    assert "largest by exposure" not in text


def test_the_window_is_named_so_a_mismatch_is_visible():
    """The product publishes a one-month and a twelve-month change column and
    nothing between them, so a six-month question is answered on the closest
    one. A reader who is not told which window they are looking at cannot see
    that."""
    monthly = cp.ranking(movement_pack())
    annual = cp.ranking(movement_pack(figures={
        "ordered_by": "ews_change_12m", "movement_measure": "ews_change_12m"}))
    assert "over the month" in monthly.direct
    assert "over twelve months" in annual.direct
