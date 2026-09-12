"""
Which figures a model's reading may write, and which it may not.

The live provider certification failed four of eight cases here, and every one
of them for the same reason: the model wrote a figure the packet was holding.
`movement.ews_change` is stored as `-3.67`; the reading said the score "fell
3.67 points"; the guard compared the string `3.67` against a set containing
only `-3.67` and discarded the whole paragraph. A fifth case died on `-5`,
which no packet in this product has ever carried and no reading ever wrote —
it is what the numeral scanner made of a hyphen inside a word.

So three things are pinned here.

**A figure the packet holds is grounded however English writes it.** Signed in
the cell, in words in the sentence.

**A hyphen between two word characters is a hyphen.** `top-5`, `tier-3`,
`L1.2` — none of them is a figure, and the system prompt asks for two of them
by name.

**Arithmetic must be declared and is recomputed by the server.** A reading may
state a total, a share or a difference only by naming the fields and the
operation; the runtime does the sum itself and drops the claim where its
answer differs. Nothing here evaluates a model-supplied expression.
"""

from __future__ import annotations

import pytest

from backend.early_warning.conversation import derivation as dv
from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import reading as rd

#: `results.figures` exactly as the movement decomposition produced it for the
#: live diagnostic case — the packet whose figures four certification cases
#: were discarded for quoting.
LIVE_MOVEMENT: dict[str, object] = {
    "population": "obligors at high or above in Contracting",
    "movement": {
        "from_period": "2025-12", "to_period": "2026-06",
        "ews_before": 39.85, "ews_after": 36.18,
        "ews_change": -3.67, "ta_change": -2.46,
        "layers": [
            {"layer": "L1", "name": "Layer 1, internal behavioural",
             "weight": 0.4, "score_before": 22.46, "score_after": 11.15,
             "score_change": -11.31, "points_contributed": -4.52},
            {"layer": "L2", "name": "Layer 2, credit and financial fundamentals",
             "weight": 0.15, "score_before": 36.24, "score_after": 48.23,
             "score_change": 11.99, "points_contributed": 1.8},
            {"layer": "L3", "name": "Layer 3, external intelligence",
             "weight": 0.3, "score_before": 1.46, "score_after": 2.39,
             "score_change": 0.93, "points_contributed": 0.28},
            {"layer": "L4", "name": "Layer 4, network and relationship",
             "weight": 0.15, "score_before": 18.77, "score_after": 3.31,
             "score_change": -15.46, "points_contributed": -2.32},
        ],
        "leading_layer": "L1",
    },
    "period": "2026-06",
}

#: The L1 fall from the noisy-spelling case, which failed on `6.34`.
LIVE_NOISY_L1_CHANGE = -6.34


def live_packet() -> packet_mod.ResultPacket:
    return packet_mod.ResultPacket(
        question="Why has Contracting deteriorated over the last six months?",
        period="2026-06", comparison_period="2025-12",
        figures=dict(LIVE_MOVEMENT),
        rows=[{"customer_id": "CORP-100721", "customer_name": "Takamul Group 2",
               "ews_score": 95.0, "exposure": 184.53},
              {"customer_id": "CORP-102241", "customer_name": "Riyada Manufacturing 7",
               "ews_score": 95.0, "exposure": 246.72}])


def allowed(packet: packet_mod.ResultPacket,
            claims: list[dv.Claim] | None = None) -> set[str]:
    return rd._allowed_figures(packet, {}, {}, claims)


def ungrounded(prose: str, packet: packet_mod.ResultPacket,
               claims: list[dv.Claim] | None = None) -> list[str]:
    return rd._ungrounded({"direct": prose, "interpretation": ""},
                          allowed(packet, claims), {"2026-06", "2025-12"})


# ------------------------------------------------- the five rejected figures

@pytest.mark.parametrize("figure,sentence", [
    ("11.31", "L1 internal behavioural fell 11.31 points over the window."),
    ("3.67", "The score fell 3.67 points between the two months."),
    ("15.46", "L4 network and relationship fell 15.46 points."),
])
def test_the_figures_the_live_run_rejected_are_grounded(figure, sentence):
    """Each is in the packet, stored signed and written in words."""
    assert ungrounded(sentence, live_packet()) == [], figure


def test_the_noisy_case_figure_is_grounded():
    packet = packet_mod.ResultPacket(
        period="2026-06",
        figures={"movement": {"layers": [
            {"layer": "L1", "score_change": LIVE_NOISY_L1_CHANGE}]}})
    assert ungrounded("Layer 1 fell 6.34 points.", packet) == []


def test_the_minus_five_was_never_a_figure():
    """`-5` came out of a hyphen, and `5` alone was always allowed.

    Which is the proof: a reading writing a bare five would have passed, so
    the only way the run reported minus five is a minus sign the prose did not
    write.
    """
    assert "5" in rd._ALWAYS_ALLOWED
    assert rd._NUMERAL.findall("the top-5 names by exposure") == []


@pytest.mark.parametrize("phrase", [
    "the top-5 names", "a single tier-3 source", "the six-month window",
    "L1.2 limit behaviour is carrying it", "sub-category L4.3",
    "layer L3 is quiet", "a T&A-weighted view",
])
def test_a_hyphen_inside_a_word_is_not_a_minus_sign(phrase):
    assert rd._NUMERAL.findall(phrase) == [], phrase


@pytest.mark.parametrize("phrase,expected", [
    ("the score is 36.18", ["36.18"]),
    ("SAR 1,049m of exposure", ["1,049"]),
    ("it moved -3.67 points", ["-3.67"]),
    ("(11.31 points)", ["11.31"]),
    ("52 obligors carry SAR 20.2bn", ["52", "20.2"]),
])
def test_a_figure_the_prose_states_is_still_read_as_one(phrase, expected):
    """Tightening the lookbehind must not make the guard blind."""
    assert rd._NUMERAL.findall(phrase) == expected


# ---------------------------------------------------- the guard still bites

@pytest.mark.parametrize("sentence,figure", [
    ("The score fell 42.5 points over the window.", "42.5"),
    ("Roughly 87.3% of the exposure sits in these names.", "87.3"),
    ("L1 fell 11.32 points.", "11.32"),
])
def test_an_invented_figure_is_still_rejected(sentence, figure):
    assert figure in ungrounded(sentence, live_packet())


def test_a_month_nobody_published_is_still_rejected():
    problems = rd._ungrounded(
        {"direct": "As at 2027-01 the score is 36.18", "interpretation": ""},
        allowed(live_packet()), {"2026-06", "2025-12"})
    assert "2027-01" in problems


# ------------------------------------------------ the declared-claim contract

def facts() -> dict[str, float]:
    from backend.early_warning.conversation import reading as reading_mod

    return dv.index(reading_mod._facts_of(live_packet()))


def test_the_fact_index_names_a_nested_figure():
    got = facts()
    assert got["movement.ews_change"] == pytest.approx(-3.67)
    assert got["movement.layers[0].score_change"] == pytest.approx(-11.31)
    assert got["rows[1].exposure"] == pytest.approx(246.72)


def test_a_declared_sum_is_recomputed_and_accepted():
    claims = dv.check(
        [{"value": 431.25, "op": "sum",
          "refs": ["rows[0].exposure", "rows[1].exposure"]}], facts())
    assert [c.accepted for c in claims] == [True]
    assert claims[0].recomputed == pytest.approx(431.25)
    assert ungrounded("The two together carry SAR 431.25m.",
                      live_packet(), claims) == []


def test_a_declared_sum_the_server_disagrees_with_permits_nothing():
    claims = dv.check(
        [{"value": 500.0, "op": "sum",
          "refs": ["rows[0].exposure", "rows[1].exposure"]}], facts())
    assert claims[0].accepted is False
    assert "431.25" in claims[0].reason
    assert "500" in ungrounded("The two together carry SAR 500m.",
                               live_packet(), claims)


def test_a_declared_share_becomes_a_percentage_the_server_checks():
    claims = dv.check(
        [{"value": 123.2, "op": "percent",
          "refs": ["movement.layers[0].points_contributed",
                   "movement.ews_change"]}], facts())
    assert claims[0].accepted is True
    assert claims[0].recomputed == pytest.approx(-4.52 / -3.67 * 100, rel=1e-3)


def test_magnitude_is_one_of_the_operations():
    claims = dv.check(
        [{"value": 3.67, "op": "magnitude", "refs": ["movement.ews_change"]}],
        facts())
    assert claims[0].accepted is True


@pytest.mark.parametrize("claim,why", [
    ({"value": 1.0, "op": "exp", "refs": ["movement.ews_change"]},
     "not an operation"),
    ({"value": 1.0, "op": "sum", "refs": ["movement.no_such_field"]},
     "no fact called"),
    ({"value": 1.0, "op": "difference", "refs": ["movement.ews_change"]},
     "takes 2 facts"),
    ({"value": 1.0, "op": "ratio",
      "refs": ["movement.ews_change", "movement.no_such_field"]},
     "no fact called"),
])
def test_a_claim_the_server_cannot_check_permits_nothing(claim, why):
    got = dv.check([claim], facts())
    assert got[0].accepted is False
    assert why in got[0].reason


def test_a_division_by_zero_is_refused_rather_than_infinite():
    got = dv.check([{"value": 0.0, "op": "ratio",
                     "refs": ["movement.ews_change", "zero"]}],
                   {"movement.ews_change": -3.67, "zero": 0.0})
    assert got[0].accepted is False


def test_nothing_in_the_contract_evaluates_a_model_string():
    """The operator set is closed and each entry is a function of floats."""
    import inspect

    source = inspect.getsource(dv)
    assert "eval(" not in source
    assert "exec(" not in source
    for op, fn in dv.OPERATIONS.items():
        assert callable(fn), op
        assert op in dv.ARITY


def test_an_operation_the_model_invents_is_not_in_the_schema():
    enum = rd.SCHEMA["properties"]["derived_claims"]["items"][
        "properties"]["op"]["enum"]
    assert set(enum) == set(dv.OPERATIONS)
    assert "eval" not in enum


def test_a_derivation_is_arithmetic_over_results_not_over_prose():
    """The question's own numerals are not facts a claim may be built from."""
    from backend.early_warning.conversation import reading as reading_mod

    packet = live_packet()
    packet.question = "Why did it fall 999 points?"
    packet.normalized_request = packet.question
    assert 999.0 not in dv.index(reading_mod._facts_of(packet)).values()
