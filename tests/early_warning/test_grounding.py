"""
Whether the answer writer can see anything it is not allowed to say.

The defect this suite exists for
--------------------------------
A live run made seven Opus and Sonnet calls, all successful, and then wrote its
answer deterministically anyway:

    Discarding an Early Warning reading:
    figures ['-06,', '1,049', '1,218', '2,521'] are not in the result packet.

The guard was right to reject the prose and wrong about two of the four.

`1,049` and `2,521` came from the field dictionary's coverage summary — 2,521
fields described, 1,049 fully populated — which the interpretation packet was
carrying. Those are statistics about the SCHEMA, not about the book. A planner
needs them; a credit paragraph has no business with them, and the reading was
right to be discarded for quoting them. The fix is that the writer never sees
them.

`-06,` was not a figure at all. It was `2026-06,` read by a numeral scanner that
took the hyphen for a minus sign and swallowed the comma — so a reading that
quoted its own period correctly was thrown out for citing minus six.

The rule underneath
-------------------
**The allowed set is derived from what the writer may SEE.** The packet carries
only evidence, the allowance is built from the citable sections of that packet,
and the two therefore agree by construction rather than by a whitelist somebody
has to remember to update. A number from anywhere else is still rejected — the
guard is not weakened by any of this, and the test that would notice if it were
is here too.
"""

from __future__ import annotations

import json

import pytest

from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import reading as rd
from backend.early_warning.conversation import seam as seam_mod
from tests.early_warning.stub_provider import StubProvider, install

LIVE_QUESTION = ("Why has Contracting deteriorated over six months, and is it "
                 "concentrated in a handful of names?")

#: The exact figures the live run rejected. Three of them are schema
#: statistics and one was never a figure.
LIVE_REJECTIONS = ("-06,", "1,049", "1,218", "2,521")


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def turn():
    """One real turn, for the packet and the deterministic answer."""
    return pipe.answer(LIVE_QUESTION)


@pytest.fixture(scope="module")
def context(turn):
    return rd._context(turn.question, turn.packet, turn.answer, None)


def _final(turn):
    return next(e for e in turn.events if e.stage == pipe.FINAL_ANSWER)


# --------------------------------------------------- the packet is evidence


def test_the_writer_is_shown_nothing_it_may_not_cite(context):
    """The whole control, in one assertion.

    Every section of the interpretation packet is either citable evidence or
    carries no figure at all. A section outside both lists is a number the
    writer can read and must not use — which is exactly what the coverage
    summary was.
    """
    unaccounted = (set(context)
                   - set(rd.CITABLE_SECTIONS)
                   - set(rd.NON_NUMERIC_SECTIONS))
    assert not unaccounted, (
        f"{sorted(unaccounted)} reach the answer writer and are not evidence")


def test_the_schema_coverage_summary_is_not_in_the_packet(context):
    """Where 1,049 and 2,521 came from."""
    assert "coverage" not in context, (
        "the field dictionary's coverage summary is back in the answer packet")
    flat = json.dumps(context, default=str)
    for statistic in ("2521", "2,521", "1049", "1,049"):
        assert statistic not in flat, (
            f"{statistic} is still visible to the answer writer")


def test_planning_still_gets_the_coverage_it_needs(turn):
    """This change is about the ANSWER writer, not about the domain.

    The counts are still on the packet, still on the trace, and still in the
    grain package a planner reads. Removing them from the product would be a
    different and worse change.
    """
    assert turn.packet.coverage, "the packet lost its coverage summary"
    assert turn.packet.coverage.get("fields", 0) > 2000

    from backend.early_warning import grain as grain_mod

    package = grain_mod.build("x")
    assert package.coverage.get("fields", 0) > 2000
    assert package.field_count > 2000


def test_every_numeral_the_writer_sees_is_one_it_may_cite(turn, context):
    """The invariant that makes the guard maintainable.

    Derived from the packet rather than listed by hand, so a section added to
    the context later either is evidence — and its figures become citable —
    or fails this test.
    """
    allowed = rd._allowed_figures(turn.packet, turn.answer, context)
    periods = rd._permitted_periods(turn.packet)

    for section in rd.CITABLE_SECTIONS:
        value = context.get(section)
        if value is None:
            continue
        text = json.dumps(value, default=str)
        for month in rd._PERIOD_TOKEN.findall(text):
            assert month in periods, f"{section} shows an unpublished {month}"
        for found in rd._NUMERAL.findall(rd._PERIOD_TOKEN.sub(" ", text)):
            assert found in allowed or found.replace(",", "") in allowed, (
                f"{section} shows {found!r}, which the reading may not cite")


# ------------------------------------------------------- the numeral parser


@pytest.mark.parametrize("text,expected", [
    ("In 2026-06, exposure was SAR 15.5bn.", ["15.5"]),
    ("From 2025-12 to 2026-06 the score rose.", []),
    ("Down -3.2 points against the anchor.", ["-3.2"]),
    ("1,049 obligors", ["1,049"]),
    ("11 of 30 obligors, at 81.3%.", ["11", "30", "81.3"]),
    ("2026-06", []),
])
def test_a_period_is_one_token_and_a_figure_never_ends_on_a_comma(text,
                                                                  expected):
    """`2026-06,` gave `-06,`: a minus sign and a swallowed comma.

    A month is one thing. So is a figure, and neither of them is a fragment
    of the other.
    """
    remaining = rd._PERIOD_TOKEN.sub(" ", text)
    assert rd._NUMERAL.findall(remaining) == expected


@pytest.mark.parametrize("month", ["2026-06", "2025-12", "1999-01", "2030-12"])
def test_a_month_is_recognised_as_a_month(month):
    assert rd._PERIOD_TOKEN.findall(f"as at {month}, the position") == [month]


@pytest.mark.parametrize("not_a_month", ["2026-13", "2026-00", "20260-06",
                                          "126-06"])
def test_something_shaped_like_a_month_and_is_not(not_a_month):
    assert not rd._PERIOD_TOKEN.findall(f"as at {not_a_month}")


def test_the_period_the_answer_read_is_citable(turn):
    periods = rd._permitted_periods(turn.packet)
    assert turn.packet.period in periods
    assert len(periods) >= 20, "the published months are not all permitted"


def test_a_month_nobody_published_is_still_refused(turn, context):
    """A period is a permitted reference, not a free pass."""
    allowed = rd._allowed_figures(turn.packet, turn.answer, context)
    periods = rd._permitted_periods(turn.packet)
    problems = rd._ungrounded(
        {"direct": "As at 2031-07 the segment was stable.",
         "interpretation": ""}, allowed, periods)
    assert "2031-07" in problems


# ------------------------------------------- the guard is not weakened


@pytest.mark.parametrize("invented", [
    "Exposure across the segment is SAR 88,412.7m.",
    "Some 47 obligors are at high or above.",
    "The score fell 19.4 points over the period.",
])
def test_an_invented_figure_is_still_rejected(turn, context, invented):
    allowed = rd._allowed_figures(turn.packet, turn.answer, context)
    periods = rd._permitted_periods(turn.packet)
    problems = rd._ungrounded({"direct": "", "interpretation": invented},
                              allowed, periods)
    assert problems, f"{invented!r} passed the grounding check"


def test_the_schema_statistics_would_still_be_rejected_if_they_reappeared(
        turn, context):
    """Not whitelisted. Removed from the packet AND refused in the prose."""
    allowed = rd._allowed_figures(turn.packet, turn.answer, context)
    periods = rd._permitted_periods(turn.packet)
    problems = rd._ungrounded(
        {"direct": "",
         "interpretation": ("The domain describes 2,521 fields, of which "
                            "1,049 are fully populated and 1,218 are not.")},
        allowed, periods)
    assert "2,521" in problems
    assert "1,049" in problems
    assert "1,218" in problems


def test_the_prose_is_discarded_rather_than_annotated(monkeypatch):
    """An interpretation with one invented sentence, shown under a warning,
    is still an interpretation somebody will paste into a credit paper."""
    install(monkeypatch, StubProvider(behaviour="ungrounded",
                                      behaviour_for="interpret_the_result"))
    turn = pipe.answer(LIVE_QUESTION)

    assert "88,412.7" not in turn.answer["interpretation"]
    assert _final(turn).detail["ungrounded_figures"]
    assert _final(turn).detail["engine"] == seam_mod.DETERMINISTIC


# ------------------------------------------------------------- fact refs


def test_a_reading_may_name_the_fields_its_figures_came_from(monkeypatch,
                                                             turn):
    """Structured grounding beside the numeric one.

    A reading that names `high_plus_count` can be traced back to the value it
    quoted; a bare numeral cannot.
    """
    grounded = turn.answer
    keys = [k for k in turn.packet.figures][:3]
    install(monkeypatch, StubProvider(replies={"interpret_the_result": {
        "direct": grounded["direct"],
        "interpretation": grounded["interpretation"],
        "fact_refs": keys}}))
    second = pipe.answer(LIVE_QUESTION)

    call = _final(second).detail["model_call"]
    assert call["engine"] == seam_mod.MODEL, call.get("fallback_reason")
    assert set(call["fact_refs"]) == set(keys)
    assert not call["unresolved_refs"]


def test_a_ref_that_resolves_to_nothing_is_recorded_not_fatal(monkeypatch,
                                                              turn):
    """The numeric check is what rejects a reading.

    A mistyped field name on a reading whose every figure IS in the packet is
    a bookkeeping slip, not an invented number — and discarding a sound
    answer over it would trade a real control for a cosmetic one.
    """
    grounded = turn.answer
    install(monkeypatch, StubProvider(replies={"interpret_the_result": {
        "direct": grounded["direct"],
        "interpretation": grounded["interpretation"],
        "fact_refs": ["exposure", "not_a_figure_anybody_computed"]}}))
    second = pipe.answer(LIVE_QUESTION)

    call = _final(second).detail["model_call"]
    assert call["engine"] == seam_mod.MODEL, call.get("fallback_reason")
    assert "not_a_figure_anybody_computed" in call["unresolved_refs"]


def test_refs_do_not_rescue_an_invented_figure(monkeypatch, turn):
    """Naming a field does not make a number true."""
    install(monkeypatch, StubProvider(replies={"interpret_the_result": {
        "direct": "Exposure is SAR 88,412.7m.",
        "interpretation": "A figure nobody computed, with a ref attached.",
        "fact_refs": ["exposure"]}}))
    second = pipe.answer(LIVE_QUESTION)

    assert _final(second).detail["engine"] == seam_mod.DETERMINISTIC
    assert _final(second).detail["ungrounded_figures"]


# --------------------------------------------------- the acceptance target


def test_the_live_reading_is_accepted_end_to_end(monkeypatch, turn):
    """The exact failure, run again.

    The reading quotes its own period and the packet's own figures, which is
    what a real Opus reading does and what the old parser and the old packet
    together made impossible.
    """
    grounded = turn.answer
    period = turn.packet.period
    reading = {
        "direct": grounded["direct"],
        "interpretation": (
            f"As at {period}, the position is as stated above. "
            + grounded["interpretation"]),
        "points": [],
        "drivers": list(grounded.get("drivers") or [])[:4],
        "follow_ups": list(grounded.get("follow_ups") or [])[:3],
        "caveats": [],
        "fact_refs": [k for k in turn.packet.figures][:3],
    }
    install(monkeypatch, StubProvider(
        replies={"interpret_the_result": reading}))
    second = pipe.answer(LIVE_QUESTION)

    final = _final(second)
    assert not final.detail["ungrounded_figures"], (
        final.detail["ungrounded_figures"])
    assert final.detail["engine"] == seam_mod.MODEL
    assert period in second.answer["interpretation"]


def test_the_acceptance_ledger(monkeypatch):
    """7 charged, 7 succeeded, 0 failed, 3 Sonnet and 4 Opus, all on models."""
    install(monkeypatch, StubProvider())
    result = pipe.answer(LIVE_QUESTION)

    budget = result.budget
    assert budget["model_calls_charged"] == 7, budget
    assert budget["model_calls_succeeded"] == 7, budget
    assert budget["model_calls_failed"] == 0, budget
    assert budget["spent"]["sonnet_calls"] == 3
    assert budget["spent"]["opus_calls"] == 4

    for stage in (pipe.SONNET_PASS_1, pipe.SONNET_PASS_2,
                  pipe.FUNCTIONALITY_SELECTED, pipe.PLAN_CREATED,
                  pipe.SUFFICIENCY_COMPLETE, pipe.FINAL_ANSWER,
                  pipe.SUMMARY_UPDATED):
        assert result.engines.get(stage) == seam_mod.MODEL, (
            f"{stage}: "
            f"{_final(result).detail.get('model_call', {}).get('fallback_reason')}")

    # And the answer states nothing the packet does not carry.
    assert not _final(result).detail["ungrounded_figures"]


def test_the_what_if_proof_is_unchanged(monkeypatch):
    install(monkeypatch, StubProvider())
    result = pipe.answer("What happens to ECL if oil falls 30%?")

    assert result.selection["selected_functionality"] == "what_if"
    assert result.budget["model_calls_charged"] == 4
    assert result.budget["model_calls_succeeded"] == 4
    assert result.budget["spent"]["executions"] == 0
    assert not (set(result.stages) & pipe.ANALYTICAL_STAGES)


def test_no_second_model_call_was_added_to_repair_the_prose(monkeypatch):
    """The closing-stage budget is unchanged.

    One interpretation call, grounded or not. A repair pass would be a
    second Opus call inside the reserve.
    """
    install(monkeypatch, StubProvider(behaviour="ungrounded",
                                      behaviour_for="interpret_the_result"))
    result = pipe.answer(LIVE_QUESTION)

    attempts = [a for a in result.model_attempts
                if a["stage"] == pipe.FINAL_ANSWER]
    assert len(attempts) == 1, f"{len(attempts)} interpretation calls"
    assert result.budget["model_calls_charged"] == 7
