"""DATA FIRST, GRAPH OPTIONAL. §11.

A chart opens when the reader wanted to see a shape. It does not open because
the result's columns happen to look like axes — which is the only thing the
shape rule can see, and it is the same for "show the distribution of DPD" and
"list the twenty borrowers with the highest PD".

The rule used to be narrower: questions written in retrieval language got the
table, and anything the vocabulary could not classify fell through to the
shape rule. "Which datasets carry exposure?" and "total exposure by sector"
are not written in trend language, so they landed there and came back drawn.
"""

from __future__ import annotations

import pytest

from backend.orchestration import visualize as vz
from backend.orchestration import viz_intent as vi

#: Questions §11 names: list, show, which, how many, top, bottom, rank,
#: filter, data, datasets, fields, rows, borrowers, facilities, exposure.
ROWS_PLEASE: tuple[str, ...] = (
    "List the 20 borrowers with the highest 12-month PD in Q2 2026.",
    "Show me the ten borrowers with the lowest covenant headroom.",
    "Which borrowers are on the watchlist?",
    "How many facilities are more than 90 days past due?",
    "What datasets do you have?",
    "Which fields does customer_ratings carry?",
    "Rank sectors by Stage 2 exposure.",
    "Top 20 exposures.",
    "Bottom 10 by DSCR.",
    "Filter to Stage 3 borrowers in Contracting.",
    "Total exposure by sector for Q2 2026.",
    "Give me the facility list for CORP-100376.",
    "Identify the customers with a covenant breach this quarter.",
    "What is the ECL for the Contracting sector?",
    "Find the borrowers whose rating fell two notches.",
)

#: Questions whose meaning IS a shape. §11's own list: trend over time,
#: migration matrix, distribution, concentration, relationship network,
#: scenario comparison.
DRAW_IT: tuple[str, ...] = (
    "Show the trend in Stage 2 coverage over the last eight quarters.",
    "How has ECL evolved over time?",
    "Show me the Stage migration matrix.",
    "What is the distribution of DPD across the book?",
    "Show sector concentration in the corporate book.",
    "Compare the base and stress scenarios across sectors.",
    "What is the correlation between leverage and DSCR?",
    "Break the portfolio down by rating grade.",
    "Show the composition of exposure by stage.",
    "How did ratings migrate between Q1 2026 and Q2 2026?",
)


@pytest.mark.parametrize("question", ROWS_PLEASE)
def test_a_question_for_rows_opens_as_a_table(question: str):
    assert vi.wants_rows(question) is True


@pytest.mark.parametrize("question", DRAW_IT)
def test_a_question_about_a_shape_opens_as_a_chart(question: str):
    assert vi.classify(question) == vi.VISUAL
    assert vi.wants_rows(question) is False


class TestTheReaderOutranksTheRule:
    def test_asking_for_a_chart_gets_a_chart(self):
        assert vi.wants_rows("Draw me a chart of exposure by sector") is False
        assert vi.wants_rows("Show that as a bar chart") is False

    def test_asking_for_a_table_gets_a_table(self):
        assert vi.wants_rows(
            "Show the trend in ECL as a table") is True
        assert vi.wants_rows("Just the numbers, no chart") is True


class TestTheGateDemotesRatherThanDeletes:
    """The chart is still built. It simply is not what opens."""

    def _result(self):
        columns = [{"name": "sector", "semantic": "identity"},
                   {"name": "ead", "semantic": "money"}]
        rows = [{"sector": s, "ead": float(n)} for n, s in
                enumerate(["Contracting", "Retail", "Energy", "Shipping"], 1)]
        return columns, rows

    def test_a_ranking_keeps_its_chart_but_shows_the_table(self):
        columns, rows = self._result()
        visual = vz.choose(columns, rows,
                           question="Rank sectors by exposure.")
        assert visual.chart_first is False
        assert visual.chart != vz.TABLE, (
            "the chart was deleted rather than demoted — §11 says the table "
            "is the default view, not that the chart stops existing")

    def test_an_unclassifiable_question_shows_the_table(self):
        columns, rows = self._result()
        visual = vz.choose(columns, rows, question="Exposure by sector")
        assert visual.chart_first is False

    def test_an_explicit_request_still_opens_the_chart(self):
        columns, rows = self._result()
        visual = vz.choose(columns, rows, requested="chart",
                           question="Rank sectors by exposure.")
        assert visual.chart_first is True


def test_a_metadata_answer_carries_no_chart_at_all():
    """§13. Not demoted — absent. There is nothing here to plot."""
    from backend.metadata import answers as ma
    from backend.metadata import questions as mq

    answer = ma.respond(mq.read("Which data domains exist in CreditProbe?"))
    assert answer["chart"] == {}
    assert answer["visualization"]["kind"] == "table"
