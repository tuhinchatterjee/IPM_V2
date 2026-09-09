"""One question does not imply one analysis, or one chart.

The defect these tests hold shut
--------------------------------
"Investigate the Shipping sector." ran four governed analyses — exposure over
the year, ECL over the year, exposure by IFRS 9 stage, and the borrowers behind
both — computing twenty-four rows between them. What reached the reader was a
four-row table of SENTENCES about those analyses. The stage distribution, the
movement pairs and the seventeen named borrowers were computed, paid for, and
discarded before anything was rendered.

The tests are written against the mechanism rather than against the two example
strings: the shape rules take rows, columns and a chosen visual, and the
end-to-end tests assert that whatever the investigation planner chose to run,
every analysis that produced rows arrives as a block a reader can see.
"""

from __future__ import annotations

import pytest

from backend.orchestration import package as pk

# --------------------------------------------------------------- shape rules


class TestWhatOneResultEarns:
    """`kinds_for` is the whole of the "how many charts" decision."""

    def test_no_rows_is_a_sentence_and_nothing_else(self) -> None:
        kinds, why = pk.kinds_for([], [{"name": "sector"}], None)
        assert kinds == (pk.NARRATIVE,)
        assert "no rows" in why

    def test_one_row_and_one_measure_is_a_figure_not_a_chart(self) -> None:
        kinds, why = pk.kinds_for(
            [{"total_ecl": 1234.5}],
            [{"name": "total_ecl", "role": "measure", "unit": "SAR mn"}],
            {"chart": "bar", "chart_first": True})
        assert kinds == (pk.KPI,)
        assert "single bar" in why

    def test_a_from_to_matrix_is_a_matrix_with_its_table_under_it(self) -> None:
        kinds, _ = pk.kinds_for(
            [{"from": "1", "to": "2", "ead": 10.0}],
            [{"name": "from"}, {"name": "to"},
             {"name": "ead", "role": "measure"}],
            {"chart": "heatmap", "chart_first": True})
        assert kinds == (pk.MATRIX, pk.TABLE)

    def test_a_bridge_is_a_decomposition_not_a_bar_chart(self) -> None:
        kinds, why = pk.kinds_for(
            [{"step": "opening", "amount": 100.0},
             {"step": "PD", "amount": 12.0},
             {"step": "closing", "amount": 112.0}],
            [{"name": "step"}, {"name": "amount", "role": "measure"}],
            {"chart": "waterfall", "chart_first": True})
        assert kinds == (pk.DECOMPOSITION, pk.TABLE)
        assert "steps between" in why

    def test_a_chart_the_selector_chose_is_drawn_beside_its_table(self) -> None:
        kinds, _ = pk.kinds_for(
            [{"period": "Q1 2026", "ead": 10.0},
             {"period": "Q2 2026", "ead": 11.0}],
            [{"name": "period"}, {"name": "ead", "role": "measure"}],
            {"chart": "line", "chart_first": True})
        assert kinds == (pk.TABLE, pk.CHART)

    def test_a_chart_the_selector_DEMOTED_stays_demoted(self) -> None:
        """R2 §11 lives in `visualize`, and this module must not overrule it.

        A question that asked for rows gets rows. The chart is still built and
        still offered in the toggle — it simply does not lead, and a second
        component deciding otherwise would be a second component to disagree
        with the first.
        """
        kinds, why = pk.kinds_for(
            [{"ifrs9_stage": "1", "ead": 10.0},
             {"ifrs9_stage": "2", "ead": 4.0},
             {"ifrs9_stage": "3", "ead": 1.0}],
            [{"name": "ifrs9_stage"}, {"name": "ead", "role": "measure"}],
            {"chart": "bar", "chart_first": False})
        assert kinds == (pk.TABLE,)
        assert "beside it" in why

    def test_a_result_the_selector_left_as_a_table_is_a_table(self) -> None:
        kinds, _ = pk.kinds_for(
            [{"customer": "A", "dscr": 1.1, "headroom_pct": 4.0}],
            [{"name": "customer"}, {"name": "dscr", "role": "measure"},
             {"name": "headroom_pct", "role": "measure"}],
            {"chart": "table", "chart_first": False})
        assert kinds == (pk.TABLE,)

    @pytest.mark.parametrize("visual", [
        None,
        {},
        {"chart": ""},
        {"chart": "line"},                       # no chart_first key at all
    ])
    def test_a_missing_or_partial_visual_never_raises(self, visual) -> None:
        kinds, why = pk.kinds_for(
            [{"a": 1, "b": 2}, {"a": 3, "b": 4}],
            [{"name": "a"}, {"name": "b", "role": "measure"}], visual)
        assert kinds
        assert why


# ------------------------------------------------------------- the package


class _Step:
    """The shape `package.build` reads off an executed step."""

    def __init__(self, index, title, rows, columns, visual, *,
                 role="supporting", status="succeeded", error=None,
                 rationale="", asked="", finding=""):
        self.index = index
        self.title = title
        self.role = role
        self.status = status
        self.error = error
        self.rationale = rationale
        self.result = {"rows": rows, "columns": columns, "visual": visual,
                       "asked": asked, "finding": finding}


def _analysis(index, title, *, rows=2, visual=None, **kw):
    return _Step(index, title,
                 [{"period": f"Q{n} 2026", "ead": 10.0 + n}
                  for n in range(1, rows + 1)],
                 [{"name": "period"}, {"name": "ead", "role": "measure"}],
                 visual if visual is not None
                 else {"chart": "line", "chart_first": True}, **kw)


class TestThePackageIsTheAnswer:

    def test_one_analysis_is_one_block(self) -> None:
        built = pk.build([_analysis(0, "Total ECL", role="primary")])
        assert built.block_count == 1
        assert built.analysis_count == 1

    def test_five_analyses_are_five_blocks(self) -> None:
        """The defect, stated as an assertion.

        Not "at least two" — every analysis that produced rows is a block.
        A response that ran five and rendered one is the bug.
        """
        steps = [_analysis(0, "Summary", role="primary"),
                 _analysis(1, "Exposure at default"),
                 _analysis(2, "Expected credit loss"),
                 _analysis(3, "IFRS 9 stage"),
                 _analysis(4, "Largest deteriorating borrowers")]
        built = pk.build(steps)
        assert built.block_count == 5
        assert built.analysis_count == 5
        assert [b.title for b in built.blocks] == [s.title for s in steps]

    def test_every_block_points_at_the_step_that_computed_it(self) -> None:
        """A block carries no figures of its own, so it cannot disagree."""
        steps = [_analysis(n, f"Analysis {n}") for n in range(4)]
        built = pk.build(steps)
        assert [b.step_index for b in built.blocks] == [0, 1, 2, 3]

    def test_the_chart_count_is_emergent_not_a_setting(self) -> None:
        """Three drawn out of four, decided per result and not by a cap."""
        steps = [
            _analysis(0, "Movement", visual={"chart": "line",
                                             "chart_first": True}),
            _analysis(1, "Second movement", visual={"chart": "line",
                                                    "chart_first": True}),
            _analysis(2, "Stage split", visual={"chart": "bar",
                                                "chart_first": False}),
            _analysis(3, "Named borrowers", visual={"chart": "dot",
                                                    "chart_first": True}),
        ]
        built = pk.build(steps)
        assert built.chart_count == 3
        assert built.table_count == 4

    def test_an_analysis_that_failed_is_withheld_with_its_reason(self) -> None:
        steps = [_analysis(0, "Ran", role="primary"),
                 _Step(1, "Did not run", [], [], None,
                       status="failed", error="The dataset is not published.")]
        built = pk.build(steps)
        assert built.analysis_count == 1
        assert built.withheld[0]["title"] == "Did not run"
        assert "not published" in built.withheld[0]["why"]

    def test_the_package_stops_before_it_becomes_a_wall(self) -> None:
        steps = [_analysis(n, f"Analysis {n}") for n in range(pk.MAX_BLOCKS + 3)]
        built = pk.build(steps)
        assert built.block_count == pk.MAX_BLOCKS
        assert len(built.withheld) == 3
        assert all("scrolling" in w["why"] for w in built.withheld)

    def test_a_synthesis_leads_when_there_is_one(self) -> None:
        built = pk.build([_analysis(0, "One")], synthesis="ECL rose 34%.")
        assert built.blocks[0].kinds == (pk.SYNTHESIS,)
        assert built.blocks[0].step_index == -1
        assert built.blocks[0].finding == "ECL rose 34%."

    def test_the_package_serialises_its_own_counts(self) -> None:
        built = pk.build([_analysis(n, f"A{n}") for n in range(3)])
        payload = built.to_dict()
        assert payload["counts"] == {"blocks": 3, "analyses": 3,
                                     "tables": 3, "drawn": 3}
        assert all(set(b) >= {"block_id", "kinds", "step_index", "why"}
                   for b in payload["blocks"])
