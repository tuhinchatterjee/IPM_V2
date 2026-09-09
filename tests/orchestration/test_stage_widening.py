"""The widening is recorded once, and every layer reads that record.

Unit-level companion to `tests/api/test_stage_or_worse.py`: that suite proves
the answer is right on the live book, this one proves the mechanism that makes
it right cannot come apart.
"""

from __future__ import annotations

import pytest

from backend.orchestration import invariants as inv
from backend.orchestration import ordinal


class _Build:
    """The three attributes the invariant layer reads off a build."""

    def __init__(self, filters, widened=(), conditions=()):
        self.filters = list(filters)
        self.widened = list(widened)
        self.conditions = list(conditions)
        self.top_n = 0
        self.shape = ""
        self.grain = "customer"


class TestTheReaderItself:
    def test_or_worse_on_a_scale_where_higher_is_worse_is_at_least(self):
        found = ordinal.read("stage 2 or worse", "ifrs9_stage", "2")
        assert found is not None and found.op == "gte"

    def test_or_better_on_the_same_scale_is_at_most(self):
        found = ordinal.read("stage 2 or better", "ifrs9_stage", "2")
        assert found is not None and found.op == "lte"

    def test_a_plain_value_widens_nothing(self):
        assert ordinal.read("stage 2", "ifrs9_stage", "2") is None

    def test_a_scale_whose_direction_is_not_governed_widens_nothing(self):
        assert ordinal.read("sector 2 or worse", "sector", "2") is None


class TestTheCheckMatchesThePlan:
    def test_a_widened_restriction_is_promised_as_a_range(self):
        widened = ordinal.read("stage 2 or worse", "ifrs9_stage", "2")
        checks = inv.compile_checks(
            _Build([("ifrs9_stage", "2")], [widened]),
            "Which borrowers are at stage 2 or worse?")
        rules = {c.rule for c in checks}
        assert "filter_bound" in rules
        assert "filter_equality" not in rules

    def test_a_plain_restriction_is_still_promised_as_equality(self):
        checks = inv.compile_checks(_Build([("ifrs9_stage", "2")]),
                                    "Which borrowers are at stage 2?")
        rules = {c.rule for c in checks}
        assert "filter_equality" in rules
        assert "filter_bound" not in rules

    def test_a_stage_three_row_passes_the_widened_check(self):
        widened = ordinal.read("stage 2 or worse", "ifrs9_stage", "2")
        build = _Build([("ifrs9_stage", "2")], [widened])
        checks = inv.compile_checks(build, "stage 2 or worse")
        bound = next(c for c in checks if c.rule == "filter_bound")
        rows = [{"ifrs9_stage": 2}, {"ifrs9_stage": 3}]
        assert inv._HANDLERS["filter_bound"](bound, rows, None) is None

    def test_a_stage_one_row_still_fails_it(self):
        # The check must be able to FAIL, or asserting that it passes proves
        # nothing about the guard.
        widened = ordinal.read("stage 2 or worse", "ifrs9_stage", "2")
        build = _Build([("ifrs9_stage", "2")], [widened])
        bound = next(c for c in inv.compile_checks(build, "stage 2 or worse")
                     if c.rule == "filter_bound")
        failure = inv._HANDLERS["filter_bound"](
            bound, [{"ifrs9_stage": 1}], None)
        assert failure is not None
        assert "at or above" in failure.detail

    def test_a_column_it_cannot_read_is_not_ruled_against(self):
        # An honest abstention: a check that cannot parse the column cannot
        # say the answer contradicts the question.
        widened = ordinal.read("stage 2 or worse", "ifrs9_stage", "2")
        build = _Build([("ifrs9_stage", "2")], [widened])
        bound = next(c for c in inv.compile_checks(build, "stage 2 or worse")
                     if c.rule == "filter_bound")
        assert inv._HANDLERS["filter_bound"](
            bound, [{"ifrs9_stage": "unrated"}], None) is None

    @pytest.mark.parametrize("question,field,value,op", [
        ("borrowers 90 days or more past due", "dpd_days", "90", "gte"),
        ("borrowers at grade 7 or worse", "internal_grade", "7", "gte"),
        ("borrowers at grade 7 or better", "internal_grade", "7", "lte"),
    ])
    def test_other_governed_scales_read_the_same_way(self, question, field,
                                                     value, op):
        found = ordinal.read(question, field, value)
        assert found is not None and found.op == op

    def test_the_qualifier_has_to_follow_the_value_it_qualifies(self):
        """A governed limit, asserted so it is a decision rather than a gap.

        The reader looks for the qualifier IMMEDIATELY after the value. "90
        days past due or more" puts three words between them and is not read,
        which is deliberate: widening the gap lets an "or" belonging to a
        different clause attach to the wrong condition, and a population
        silently widened by a stray conjunction is a worse failure than one
        not widened at all.
        """
        assert ordinal.read("90 days past due or more", "dpd_days", "90") is None
        assert ordinal.read("90 days or more past due", "dpd_days", "90") is not None
