"""
How much of the population a ranking shows, as a fact rather than a sum.

LIVE-5's reading said:

    The ranking names only the 10 obligors returned; the remaining 20 of the
    30 in scope are not shown...

True — thirty Contracting obligors, ten rows, twenty omitted — and refused,
because the twenty was arithmetic the writer did in its own prose and the
packet had never been given it. The guard was right: two counts sitting in a
result do not license a third.

So the runtime counts it. `ranking_coverage` travels on every ranking pack and
is published to the writer, and the figure it may not compute is one it can now
quote.

The count that matters is over the frame the step READ, after its filters. A
ranking of the eleven high-severity names in a thirty-obligor sector that lists
five omits six. A coverage figure taken from the sector total would say
twenty-five, with confidence, and be wrong.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.early_warning.conversation import execute as ex

coverage = ex._ranking_coverage


def population(n: int) -> pd.DataFrame:
    return pd.DataFrame({"customer_id": [f"C{i}" for i in range(n)]})


def rows(n: int) -> list[dict]:
    return [{"customer_id": f"C{i}"} for i in range(n)]


def counted(total: int, returned: int) -> dict:
    return coverage(population(total), rows(returned))["ranking_coverage"]


# ------------------------------------------------------------- the counts

@pytest.mark.parametrize("total,returned,omitted,truncated", [
    (30, 10, 20, True),
    (30, 5, 25, True),
    (10, 10, 0, False),
    (1, 1, 0, False),
    (0, 0, 0, False),
])
def test_the_coverage_counts(total, returned, omitted, truncated):
    got = counted(total, returned)
    assert got["total_in_scope"] == total
    assert got["returned_count"] == returned
    assert got["omitted_count"] == omitted
    assert got["is_truncated"] is truncated


def test_a_limit_above_the_population_omits_nothing():
    """`.head(10)` over three rows returns three, and minus seven is not a
    fact about anything."""
    got = coverage(population(3), rows(3))["ranking_coverage"]
    assert got["returned_count"] == 3
    assert got["omitted_count"] == 0
    assert got["is_truncated"] is False


def test_the_returned_count_is_the_rows_not_the_limit():
    got = coverage(population(3), rows(3))["ranking_coverage"]
    assert got["returned_count"] == len(rows(3))


# ------------------------------------------------- the scope is the filter's

def test_the_scope_is_the_population_the_step_read():
    """Thirty in the sector, eleven after the filter, five listed: six omitted.

    Not twenty-five. The frame handed to `_ranking_coverage` is already
    narrowed by the step's filters, and that is the population the sentence is
    about.
    """
    sector = population(30)
    filtered = sector.head(11)
    got = coverage(filtered, rows(5))["ranking_coverage"]
    assert got["total_in_scope"] == 11
    assert got["omitted_count"] == 6
    assert got["omitted_count"] != 25


def test_the_live_5_arithmetic_is_reproduced_from_the_real_domain():
    """30 - 10 = 20, over the Contracting population the live plan read."""
    from backend.early_warning import wide

    frame = wide.with_movement("2026-06")
    contracting = frame[frame["sector"] == "Contracting"]
    got = coverage(contracting, rows(10))["ranking_coverage"]
    assert got["total_in_scope"] == 30
    assert got["returned_count"] == 10
    assert got["omitted_count"] == 20
    assert got["is_truncated"] is True


# ------------------------------------------------------------- end to end

LIVE_5 = ("Given every Contracting obligor improved last month, which one "
          "improved most?")


def test_the_ranking_pack_carries_its_coverage(monkeypatch):
    from backend.early_warning.conversation import pipeline as pl
    from tests.early_warning.stub_provider import StubProvider, install

    install(monkeypatch, StubProvider())
    turn = pl.answer(LIVE_5, thread_id="coverage-e2e").to_dict()
    got = turn["result_packet"]["results"]["figures"]["ranking_coverage"]
    assert got == {"total_in_scope": 30, "returned_count": 10,
                   "omitted_count": 20, "is_truncated": True}


def test_the_counts_are_published_to_the_writer(monkeypatch):
    from backend.early_warning.conversation import pipeline as pl
    from tests.early_warning.stub_provider import StubProvider, install

    stub = install(monkeypatch, StubProvider())
    pl.answer(LIVE_5, thread_id="coverage-published")
    context = next(c["packet"] for c in stub.calls
                   if c["tool"] == "interpret_the_result")
    published = context["fact_index"]
    for name in ("ranking_coverage.total_in_scope",
                 "ranking_coverage.returned_count",
                 "ranking_coverage.omitted_count"):
        assert name in published, name
    assert published["ranking_coverage.omitted_count"] == 20


def test_the_live_5_sentence_is_now_grounded(monkeypatch):
    from backend.early_warning.conversation import pipeline as pl
    from backend.early_warning.conversation import reading as rd
    from tests.early_warning.stub_provider import StubProvider, install

    install(monkeypatch, StubProvider())
    turn = pl.answer(LIVE_5, thread_id="coverage-grounded")
    written = {"direct": "",
               "interpretation": ("The ranking names only the 10 obligors "
                                  "returned; the remaining 20 of the 30 in "
                                  "scope are not shown."),
               "points": [], "drivers": [], "follow_ups": [], "caveats": []}
    allowed = rd._allowed_figures(turn.packet, {}, {}, [])
    assert rd._ungrounded(written, allowed, {"2026-06", "2026-05"}) == []


# ------------------------------------------------- the guard is not weakened

def test_a_wrong_count_is_still_rejected_on_the_real_packet(monkeypatch):
    """Publishing the coverage does not license a number beside it.

    29 rather than 19: a packet the size of LIVE-5's carries hundreds of
    figures and 19 is one of them — a row's score, a count somewhere. That is
    the guard working, not failing, and a test that wants to prove a figure is
    refused has to pick one the result genuinely does not hold.
    """
    from backend.early_warning.conversation import pipeline as pl
    from backend.early_warning.conversation import reading as rd
    from tests.early_warning.stub_provider import StubProvider, install

    install(monkeypatch, StubProvider())
    turn = pl.answer(LIVE_5, thread_id="coverage-strict")
    written = {"direct": "", "interpretation": "The remaining 29 are not shown.",
               "points": [], "drivers": [], "follow_ups": [], "caveats": []}
    allowed = rd._allowed_figures(turn.packet, {}, {}, [])
    assert "29" in rd._ungrounded(written, allowed, {"2026-06"})


def test_twenty_is_not_always_allowed():
    from backend.early_warning.conversation import reading as rd

    assert "20" not in rd._ALWAYS_ALLOWED


def test_a_subtraction_the_runtime_did_not_publish_is_still_refused():
    """`total_in_scope` and `returned_count` sitting in a packet do not make
    every difference between two counts a fact."""
    from backend.early_warning.conversation import derivation as dv
    from backend.early_warning.conversation import packet as packet_mod
    from backend.early_warning.conversation import reading as rd

    packet = packet_mod.ResultPacket(
        period="2026-06",
        figures={"ranking_coverage": {"total_in_scope": 30,
                                      "returned_count": 10,
                                      "omitted_count": 20,
                                      "is_truncated": True},
                 "obligors": 30, "high_plus_count": 11})
    written = {"direct": "", "interpretation": "That leaves 19 unaccounted for.",
               "points": [], "drivers": [], "follow_ups": [], "caveats": []}
    allowed = rd._allowed_figures(packet, {}, {}, [])
    assert "19" in rd._ungrounded(written, allowed, {"2026-06"})
    # And a declared derivation still has to recompute.
    facts = dv.index(rd._facts_of(packet))
    claim = dv.check([{"value": 19.0, "op": "difference",
                       "refs": ["ranking_coverage.total_in_scope",
                                "ranking_coverage.returned_count"]}], facts)[0]
    assert claim.accepted is False


def test_a_declared_coverage_derivation_still_recomputes():
    from backend.early_warning.conversation import derivation as dv
    from backend.early_warning.conversation import packet as packet_mod
    from backend.early_warning.conversation import reading as rd

    packet = packet_mod.ResultPacket(
        figures={"ranking_coverage": {"total_in_scope": 30,
                                      "returned_count": 10,
                                      "omitted_count": 20}})
    facts = dv.index(rd._facts_of(packet))
    claim = dv.check([{"value": 20.0, "op": "difference",
                       "refs": ["ranking_coverage.total_in_scope",
                                "ranking_coverage.returned_count"]}], facts)[0]
    assert claim.accepted is True


def test_a_coverage_count_is_not_read_as_a_movement():
    """Counts have no direction to contradict."""
    from backend.early_warning import metrics as mt

    for name in ("ranking_coverage.total_in_scope",
                 "ranking_coverage.returned_count",
                 "ranking_coverage.omitted_count"):
        assert mt.movement_sign(name, 20.0) == 0


def test_the_live_5_reading_survives_end_to_end(monkeypatch):
    """The exact sentence, through the whole pipeline, quoting the facts."""
    from backend.early_warning.conversation import pipeline as pl
    from backend.early_warning.conversation import seam as seam_mod
    from tests.early_warning.stub_provider import StubProvider, install

    tool = seam_mod.STAGES[seam_mod.INTERPRETATION].tool_name
    install(monkeypatch, StubProvider(behaviour="live_5_coverage",
                                      behaviour_for=tool))
    turn = pl.answer(LIVE_5, thread_id="coverage-live5").to_dict()
    detail = next(e["detail"] for e in reversed(turn["events"])
                  if e["stage"] == pl.FINAL_ANSWER)
    assert detail["engine"] == seam_mod.MODEL, (
        detail.get("model_call", {}).get("fallback_reason"))
    assert detail["ungrounded_figures"] == []
    assert detail["direction_conflicts"] == []
    assert "the remaining 20 of the 30 in scope" in turn["answer"]["interpretation"]
