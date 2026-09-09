"""A bound is a line. A magnitude is a distance. They are not the same reading.

Three families, and the whole of Phase 0A is that the product must tell them
apart:

    LEVEL      "headroom below 15%"        one date.  headroom < 15
    CROSSING   "headroom fell below 15%"   two dates. was >= 15, now < 15
    MAGNITUDE  "headroom fell by 15%"      two dates. the change was <= -15

What was actually wrong
-----------------------
The level reading did not exist. "Which customers have covenant headroom below
15%?" dropped the restriction in silence, fell back to ranking the measure, and
answered "the 10 largest customers by covenant headroom" — a true sentence
about a question nobody asked, when 1,209 customers were under the line.

The crossing reading was worse, because it looked right. "fell below 15%" was
read as "fell by more than 15", so the answer included borrowers whose headroom
had RISEN (0.02 to 10.85) and borrowers who closed at 15.05, above the very
threshold the question named.

The safety invariant
--------------------
NO DISPLAYED QUALIFYING VALUE MAY VIOLATE THE QUESTION'S OWN THRESHOLD. For a
level that is the current value; for a crossing it is the CLOSING value, and
the opening one is free to sit on the other side of the line — that is what
makes it a crossing.
"""

from __future__ import annotations

import pytest

from backend.orchestration import dynamic as dy
from backend.orchestration import thresholds as th

# The measures the mandate names, each with a bound a credit officer would set.
LEVEL_CASES = [
    ("Which customers have covenant headroom below 15%?",
     "covenant_headroom_pct", "lt", 15.0),
    ("Show customers with covenant headroom below 10%.",
     "covenant_headroom_pct", "lt", 10.0),
    ("Which borrowers have DSCR below 1.2x?", "dscr", "lt", 1.2),
    ("Which borrowers have interest coverage below 2x?",
     "interest_coverage", "lt", 2.0),
    ("Which borrowers have utilisation above 90%?",
     "utilisation_pct", "gt", 90.0),
    ("Which customers are more than 30 days past due?",
     "dpd_days", "gt", 30.0),
    ("Which facilities have LGD above 45%?", "lgd_pct", "gt", 45.0),
    ("Which borrowers have collateral coverage below 80%?",
     "collateral_coverage_pct", "lt", 80.0),
]

CROSSING_CASES = [
    ("Which customers' covenant headroom fell below 15%?",
     "covenant_headroom_pct", "gte", "lt", 15.0),
    ("Which borrowers' DSCR dropped below 1.2x?", "dscr", "gte", "lt", 1.2),
    ("Which borrowers' interest coverage fell below 2x?",
     "interest_coverage", "gte", "lt", 2.0),
    ("Which facilities moved above 90% utilisation?",
     "utilisation_pct", "lte", "gt", 90.0),
    ("Which customers became 30+ DPD?", "dpd_days", "lt", "gte", 30.0),
    ("Which facilities' LGD rose above 45%?", "lgd_pct", "lte", "gt", 45.0),
]

MAGNITUDE_CASES = [
    ("Which customers' ECL rose more than 20%?", "total_ecl", "change_pct"),
    ("Which borrowers' PD increased more than 50 bps?",
     "pd_12m_pct", "change_abs"),
    ("Which customers' rating deteriorated two notches?",
     "internal_grade", "change_abs"),
]


class TestALevelIsOneDate:

    @pytest.mark.parametrize("question,field,op,value", LEVEL_CASES)
    def test_the_bound_is_read_as_a_level(self, question, field, op, value):
        conditions, unread = dy.read_conditions(question)
        levels = [c for c in conditions if c.kind == "level"]
        assert levels, f"no level read from {question!r}; unread={unread}"
        assert levels[0].field == field
        assert levels[0].op == op
        assert levels[0].value == pytest.approx(value)

    @pytest.mark.parametrize("question,field,op,value", LEVEL_CASES)
    def test_a_level_never_becomes_a_movement(self, question, field, op, value):
        del field, op, value
        conditions, _ = dy.read_conditions(question)
        assert not [c for c in conditions
                    if c.kind in ("change_pct", "change_abs")], (
            "a question with no movement word produced a movement condition")

    def test_a_level_needs_only_one_period(self):
        from backend.orchestration import analysis_planner as ap

        conditions, _ = dy.read_conditions(LEVEL_CASES[0][0])
        assert not ap.asserts_movement(conditions)


class TestACrossingIsTwoDates:

    @pytest.mark.parametrize("question,field,open_op,close_op,value",
                             CROSSING_CASES)
    def test_both_halves_are_read(self, question, field, open_op, close_op,
                                  value):
        conditions, unread = dy.read_conditions(question)
        opening = [c for c in conditions if c.kind == "level_open"]
        closing = [c for c in conditions if c.kind == "level_close"]
        assert opening and closing, f"{question!r} unread={unread}"
        assert opening[0].field == field and closing[0].field == field
        assert opening[0].op == open_op
        assert closing[0].op == close_op
        assert closing[0].value == pytest.approx(value)

    @pytest.mark.parametrize("question,field,open_op,close_op,value",
                             CROSSING_CASES)
    def test_the_two_halves_sit_on_opposite_sides_of_the_line(
            self, question, field, open_op, close_op, value):
        del field
        conditions, _ = dy.read_conditions(question)
        opening = next(c for c in conditions if c.kind == "level_open")
        closing = next(c for c in conditions if c.kind == "level_close")
        assert opening.value == closing.value == pytest.approx(value), (
            "a crossing is one line, tested at two dates")
        opposite = {"lt": "gte", "lte": "gt", "gt": "lte", "gte": "lt"}
        assert opening.op == opposite[closing.op], (
            f"{open_op}/{close_op} do not straddle the threshold")

    @pytest.mark.parametrize("question,field,open_op,close_op,value",
                             CROSSING_CASES)
    def test_a_crossing_never_becomes_a_magnitude(self, question, field,
                                                  open_op, close_op, value):
        del field, open_op, close_op, value
        conditions, _ = dy.read_conditions(question)
        assert not [c for c in conditions
                    if c.kind in ("change_pct", "change_abs")], (
            "the bound was read as the size of the movement")

    def test_a_crossing_needs_two_periods(self):
        from backend.orchestration import analysis_planner as ap

        conditions, _ = dy.read_conditions(CROSSING_CASES[0][0])
        assert ap.asserts_movement(conditions), (
            "a crossing compares two dates and must be planned as such")


class TestAMagnitudeIsStillAMagnitude:
    """The narrowing that keeps the crossing reading safe.

    Only POSITIONAL words make a crossing. After a movement verb the
    comparatives state a distance — "rose more than 20%" is a twenty per cent
    rise, not a crossing of the twenty line — and reading them as crossings
    would break a family that was already right.
    """

    @pytest.mark.parametrize("question,field,kind", MAGNITUDE_CASES)
    def test_a_comparative_after_a_movement_stays_a_distance(
            self, question, field, kind):
        conditions, _ = dy.read_conditions(question)
        found = [c for c in conditions if c.field == field]
        assert found, f"nothing read from {question!r}"
        assert found[0].kind == kind
        assert not [c for c in conditions
                    if c.kind in ("level_open", "level_close")], (
            "a magnitude was mis-read as a threshold crossing")


class TestTheReaderItself:

    def test_a_bound_with_no_measure_is_reported_not_dropped(self):
        _, unread = th.read("Which of them are below 15%?")
        assert unread, "an unreadable bound must be reported, never dropped"

    def test_a_whole_name_still_resolves_through_the_lexicon(self):
        conditions, _ = th.read("borrowers with DSCR below 1.2")
        assert [c for c in conditions if c.field == "dscr"]

    @pytest.mark.parametrize("phrase,op", [
        ("below", "lt"), ("under", "lt"), ("less than", "lt"),
        ("above", "gt"), ("over", "gt"), ("more than", "gt"),
        ("at or below", "lte"), ("at least", "gte"),
    ])
    def test_every_bound_word_maps_to_one_comparison(self, phrase, op):
        assert th._bound_op(phrase) == op
