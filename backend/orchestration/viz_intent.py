"""Whether the QUESTION wanted a picture. §16.

`visualize.py` chooses a chart from the SHAPE of a result: a subject column, a
measure column, thirty rows, so a horizontal bar chart. That rule is right
about the geometry and blind to the request. "Which borrowers are on the
watchlist?" produces exactly that shape, and the answer came back as a bar
chart of twenty-five names — decoration on top of a list somebody asked for as
a list.

The missing input was never in the result. It is in the question.

Three verdicts
--------------
``RETRIEVAL``   The reader asked for rows. Show them rows. A chart may still
                be OFFERED, and is never the primary.
``VISUAL``      The objective is one whose meaning lives in a shape — a trend,
                a distribution, a migration, a concentration, a composition, a
                scenario comparison, a correlation, a segmentation. Draw it.
``NEUTRAL``     Nothing in the wording decides it. The shape rule stands, as
                it did before this module existed.

What this deliberately does NOT do
----------------------------------
It does not override an explicit request. "Show me that as a chart" is the
reader looking at their own result and knowing what they want, and no
classifier gets a vote against it. Nor does it suppress the shapes whose
CONTENT is a picture regardless of phrasing: a from/to transition matrix is a
migration and a bucketed count is a distribution, whichever verb introduced
them. Those live in `visualize.py`, which is the module that can see them.

Why a vocabulary and not a model
--------------------------------
This runs on every answer, before any provider call, and it decides a
presentation default that the reader can override with one click. A wrong
guess costs a toggle. A model call costs latency on every question in the
product to save that toggle, and cannot be asserted in a test.
"""

from __future__ import annotations

import re

VIZ_INTENT_VERSION = "1.0.0"

RETRIEVAL = "retrieval"
VISUAL = "visual"
NEUTRAL = "neutral"

#: The reader asked for rows. Ordinary credit-officer phrasing, and the exact
#: openings §16 names: show, list, which borrowers, which customers, find,
#: rank, top N, give me, what is, simple lookup, single metric, borrower list,
#: facility list, simple aggregation.
_RETRIEVAL = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+|could you\s+)?"
    r"(?:show|list|find|give|get|fetch|return|display|name|identify|rank)\b"
    r"|^\s*(?:which|who|whose|what|how many|how much)\b"
    r"|\btop\s+\d+\b|\bbottom\s+\d+\b|\bfirst\s+\d+\b"
    r"|\bthe\s+\d+\s+(?:largest|smallest|highest|lowest|worst|best|biggest)\b"
    r"|\b(?:borrower|customer|obligor|facility|account|name|case)s?\s+"
    r"(?:list|table)\b",
    re.IGNORECASE)

#: The objective's meaning IS a shape. §16's list, in the words a credit
#: officer writes them in.
_VISUAL = re.compile(
    r"\btrend(?:s|ed|ing)?\b|\bover time\b|\bmonth[- ]on[- ]month\b"
    r"|\bquarter[- ]on[- ]quarter\b|\byear[- ]on[- ]year\b|\btime series\b"
    r"|\bhistor(?:y|ical)\b|\bevolution\b|\btrajector(?:y|ies)\b"
    r"|\bdistributions?\b|\bspread\b|\bdispersion\b|\bhistogram\b"
    r"|\bmigrat(?:e|ed|ion|ions)\b|\btransition(?:s|ed)?\b|\bmovement between\b"
    r"|\bconcentrat(?:e|ed|ion|ions)\b|\bcompositions?\b|\bbreakdowns?\b"
    r"|\bmix\b|\bsplit (?:by|across)\b|\bshare of\b|\bproportions?\b"
    r"|\bscenarios?\b|\bstress(?:ed)? (?:case|test|comparison)\b"
    r"|\bcorrelat(?:e|ed|ion|ions)\b|\brelationship between\b"
    r"|\bsegments?\b|\bsegmented\b|\bsegmentation\b|\bcohorts?\b"
    r"|\bprofile across\b|\bbreak\w* .{0,24}\bdown by\b|\bdown by\b"
    r"|\bcompare .* (?:across|between|over)\b|\bcomparison across\b",
    re.IGNORECASE)

#: An explicit request for a picture. Not a verdict — a veto over one.
_ASKED_FOR_A_CHART = re.compile(
    r"\bcharts?\b|\bgraphs?\b|\bplots?\b|\bvisuali[sz]\w*\b|\bdraw\b"
    r"|\bbar (?:chart|graph)\b|\bline (?:chart|graph)\b|\bheat ?map\b"
    r"|\bpie chart\b|\bscatter\b|\bhistogram\b|\bwaterfall\b|\bpicture\b",
    re.IGNORECASE)

_ASKED_FOR_A_TABLE = re.compile(
    r"\bas a table\b|\bin a table\b|\btabular\b|\bjust the (?:rows|numbers|"
    r"figures|values)\b|\bno (?:chart|graph|picture)\b",
    re.IGNORECASE)


def asked_for_a_chart(question: str) -> bool:
    """Did the reader ask for a picture in so many words?"""
    return bool(question and _ASKED_FOR_A_CHART.search(question))


def asked_for_a_table(question: str) -> bool:
    return bool(question and _ASKED_FOR_A_TABLE.search(question))


def classify(question: str) -> str:
    """RETRIEVAL, VISUAL or NEUTRAL for `question`.

    VISUAL wins a tie. "Show me the trend in Stage 2 coverage" opens with a
    retrieval verb and asks for a trend; the trend is the objective and the
    verb is only how English starts a sentence. RETRIEVAL is the narrower
    claim and only holds when nothing visual is named.
    """
    text = (question or "").strip()
    if not text:
        return NEUTRAL
    if _VISUAL.search(text):
        return VISUAL
    if _RETRIEVAL.search(text):
        return RETRIEVAL
    return NEUTRAL


def wants_rows(question: str) -> bool:
    """Whether the answer's primary should be the table.

    True when the question asked for rows and did not ask for a picture. The
    chart is still built and still offered — §16 says the chart supplements
    the analysis rather than replacing it — it simply is not what opens.
    """
    if asked_for_a_chart(question):
        return False
    if asked_for_a_table(question):
        return True
    return classify(question) == RETRIEVAL


__all__ = ["NEUTRAL", "RETRIEVAL", "VISUAL", "VIZ_INTENT_VERSION",
           "asked_for_a_chart", "asked_for_a_table", "classify", "wants_rows"]
