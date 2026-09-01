"""A picture is shown when the question wanted one. §16.

The selector chose from the SHAPE of the result: a subject column, a measure
column, twenty-five rows — the exact geometry of a horizontal bar chart. It is
right about the geometry and it cannot see the request, so "Which borrowers are
on the watchlist?" came back as a bar chart of twenty-five names, drawn over a
list somebody had asked for as a list.

The missing input was never in the result. It was in the question.

This suite holds three things at once, and the third is the one that keeps the
other two honest:

  1. A retrieval question opens on its rows.
  2. A question whose objective is a shape — a trend, a distribution, a
     migration, a concentration, a composition, a scenario comparison, a
     correlation, a segmentation — still opens on its chart.
  3. The chart is DEMOTED, never deleted. §16: the chart supplements the
     analysis rather than replacing it. A gate that removed the chart would
     pass (1) and (2) and would be a different defect.
"""

from __future__ import annotations

import pytest

from backend.orchestration import visualize as vz
from backend.orchestration import viz_intent as vi

# A borrower ranking: identity subject, one money measure, ten rows. Without
# the gate this is unambiguously a horizontal bar chart, which is what makes
# it the right fixture — the geometry is not in dispute.
RANKING_COLUMNS = [
    {"name": "borrower_name", "semantic": "identity", "rank": 0},
    {"name": "ead", "semantic": "money", "rank": 2},
]
RANKING_ROWS = [{"borrower_name": f"Borrower {i}", "ead": 1000 - i}
                for i in range(10)]

PERIOD_COLUMNS = [
    {"name": "period", "semantic": "period", "rank": 0},
    {"name": "coverage_pct", "semantic": "percent", "rank": 2},
]
PERIOD_ROWS = [{"period": f"Q{i} 2026", "coverage_pct": i} for i in range(1, 5)]

MIGRATION_COLUMNS = [
    {"name": "from_state", "semantic": "text", "rank": 0},
    {"name": "to_state", "semantic": "text", "rank": 1},
    {"name": "value", "semantic": "count", "rank": 2},
]
MIGRATION_ROWS = [{"from_state": "1", "to_state": "2", "value": 4}]


# --------------------------------------------------------- the classifier


class TestWhatTheQuestionAskedFor:

    @pytest.mark.parametrize("question", [
        "Which borrowers have the strongest evidence of liquidity stress?",
        "Which customers are on the watchlist?",
        "Show me the top 10 borrowers by exposure",
        "Show the largest exposures",
        "List the facilities in arrears",
        "Find borrowers whose leverage has increased",
        "Rank borrowers by 12-month PD",
        "Give me the Stage 2 names",
        "What is total ECL?",
        "Who is near covenant breach?",
        "Identify the 10 borrowers with the highest probability of "
        "credit deterioration over the next 12 months",
    ])
    def test_a_request_for_rows_is_read_as_one(self, question):
        assert vi.classify(question) == vi.RETRIEVAL, question
        assert vi.wants_rows(question), question

    @pytest.mark.parametrize("question", [
        "How has ECL coverage trended over the last eight quarters?",
        "Show me the distribution of DSCR across the book",
        "How have internal ratings migrated over the last year?",
        "What is the sector concentration of the portfolio?",
        "Show the composition of Stage 2 by sector",
        "Compare ECL across scenarios",
        "Is there a correlation between utilisation and DPD?",
        "Break the book down by segment",
        "Show the Stage 2 balance over time",
    ])
    def test_an_objective_that_is_a_shape_is_read_as_one(self, question):
        assert vi.classify(question) == vi.VISUAL, question
        assert not vi.wants_rows(question), question

    @pytest.mark.parametrize("question", [
        "Explain why Stage 2 rose",
        "Why is this borrower flagged?",
        "Prepare the five situations senior management should discuss first",
    ])
    def test_wording_that_decides_nothing_leaves_the_shape_rule_alone(
            self, question):
        assert vi.classify(question) == vi.NEUTRAL, question

    def test_an_explicit_request_for_a_chart_outranks_the_classifier(self):
        """A person looking at their own result knows what they want."""
        question = "Show me the top 10 borrowers by exposure as a bar chart"
        assert vi.classify(question) == vi.RETRIEVAL
        assert vi.asked_for_a_chart(question)
        assert not vi.wants_rows(question)

    def test_an_explicit_request_for_a_table_is_honoured_on_a_visual_question(
            self):
        question = "Show the sector concentration as a table"
        assert vi.classify(question) == vi.VISUAL
        assert vi.wants_rows(question)

    def test_a_multi_condition_screen_over_periods_is_still_a_list(self):
        """The Q4 acceptance question. "Over the last four reporting periods"
        is a WINDOW, not a time series: the answer is a list of borrowers that
        met four conditions, and drawing it is decoration."""
        question = ("Find borrowers whose leverage increased, EBITDA margin "
                    "declined and debt-service capacity weakened over the "
                    "last four reporting periods.")
        assert vi.classify(question) == vi.RETRIEVAL


# ------------------------------------------------------------ the selector


class TestTheSelectorObeysTheQuestion:

    def test_a_borrower_list_opens_on_its_rows(self):
        chosen = vz.choose(RANKING_COLUMNS, RANKING_ROWS,
                           question="Which borrowers are on the watchlist?")
        assert chosen.chart_first is False
        assert chosen.source == "intent"
        assert "asked for rows" in chosen.reason

    def test_the_chart_is_demoted_and_not_deleted(self):
        """§16: the chart supplements rather than replaces.

        This is the assertion that stops the fix becoming a different defect.
        A gate that returned a bare TABLE would satisfy every test above.
        """
        chosen = vz.choose(RANKING_COLUMNS, RANKING_ROWS,
                           question="Which borrowers are on the watchlist?")
        assert chosen.chart == vz.HORIZONTAL_BAR
        assert chosen.x == "borrower_name"
        assert chosen.y == ["ead"]
        assert vz.TABLE in chosen.to_dict()["toggle"]
        assert chosen.chart in chosen.to_dict()["toggle"]

    def test_the_same_result_charts_when_the_objective_is_visual(self):
        """Identical columns and rows. Only the wording differs."""
        chosen = vz.choose(RANKING_COLUMNS, RANKING_ROWS,
                           question="Show the sector concentration of the book")
        assert chosen.chart_first is True
        assert chosen.source == "shape"

    def test_a_time_series_is_never_demoted(self):
        """"Show me" opens the sentence; the trend is the objective."""
        chosen = vz.choose(PERIOD_COLUMNS, PERIOD_ROWS,
                           question="Show me coverage by quarter")
        assert chosen.chart == vz.LINE
        assert chosen.chart_first is True

    def test_a_migration_matrix_is_never_demoted(self):
        chosen = vz.choose(MIGRATION_COLUMNS, MIGRATION_ROWS,
                           question="Which facilities moved stage?")
        assert chosen.chart == vz.HEATMAP
        assert chosen.chart_first is True

    def test_an_explicit_request_beats_the_gate(self):
        chosen = vz.choose(RANKING_COLUMNS, RANKING_ROWS, requested="chart",
                           question="Which borrowers are on the watchlist?")
        assert chosen.chart_first is True
        assert chosen.source == "asked"

    def test_no_question_still_chooses_a_chart_but_does_not_open_it(self):
        """A result replayed with no question keeps its chart, as the table.

        This used to assert `chart_first is True` — the shape rule decided,
        and a subject column beside a measure column opened as a bar chart.
        §11 reverses that default: DATA FIRST, GRAPH OPTIONAL. Geometry alone
        is not evidence that anybody wanted to see a picture, and with no
        question there is no other evidence to have. The chart is still
        chosen, still named, and still one click away.
        """
        chosen = vz.choose(RANKING_COLUMNS, RANKING_ROWS)
        assert chosen.chart == vz.HORIZONTAL_BAR
        assert chosen.chart_first is False

    def test_an_empty_result_still_draws_nothing(self):
        chosen = vz.choose(RANKING_COLUMNS, [],
                           question="Which borrowers are on the watchlist?")
        assert chosen.chart == vz.TABLE
