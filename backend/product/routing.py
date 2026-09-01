"""
Telling a question about the PRODUCT from a question about the BOOK.

The distinction, and why it is not obvious
------------------------------------------
    "What is CreditProbe AI?"          -> the product
    "Which borrowers are deteriorating?" -> the book
    "What is Early Warning?"           -> the product
    "What is on the Early Warning list?" -> the book

The same nouns appear on both sides. "Early Warning", "Borrower 360", "Data
Builder" and "Trace" are the names of product modules AND the subjects of
portfolio questions, so a keyword list alone routes half of them wrongly.

What actually separates them is the VERB and the SHAPE of the question. A
product question asks what something IS, what it DOES, why it MATTERS, how it
WORKS, or what the difference is between it and something else. A data question
asks WHICH, HOW MANY, HOW MUCH, or WHAT WAS — of borrowers, sectors, periods
and amounts.

So the reader is built the other way round from the obvious one: a question
that names a governed population, a measure, a period or a borrower identifier
is a DATA question whatever else it contains, and only what survives that test
is offered to the product reader.

The cost of each mistake is asymmetric, which decides the ties. Sending a
product question to the data planner produced "CreditProbe has no governed data
about CreditProbe AI" — the failure this module exists to fix. Sending a data
question to the product layer would answer a portfolio question with a brochure,
which is worse. So the data test runs first and wins ties.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------- what it asks

#: "What is X", "what does X do", "explain X", "how does X work", "why is X
#: useful" — the shapes a question about a THING takes, as opposed to a
#: question about rows.
_ASKS_ABOUT_A_THING = re.compile(
    # A noun may stand between "what" and its verb: "what SIGNALS are used",
    # "what CAPABILITIES does it have". Questions of that shape about rows are
    # already claimed by the rows test, which runs first.
    r"\bwhat\s+(?:\w+\s+){0,3}?(?:is|are|does|do|can|makes?)\b"
    r"|\bwhat'?s\b"
    r"|\bexplain\b|\bdescribe\b|\btell me about\b|\bwalk me through\b"
    r"|\bhow\s+(?:does|do|is|are|can|would)\b"
    r"|\bhow\s+(?:often|frequently|regularly)\b"
    r"|\bwhy\s+(?:is|are|does|do|should|would)\b"
    r"|\bwhat.{0,20}\bdifference\b"
    r"|\bcapabilit(?:y|ies)\b|\bfeatures?\b|\bmodules?\b"
    r"|\bmethodolog(?:y|ies)\b|\barchitecture\b",
    re.IGNORECASE)

#: The product's own name and the names of its parts. Necessary but never
#: sufficient — see the module docstring.
_PRODUCT_NOUNS = re.compile(
    r"\bcreditprobe\b|\bthis (?:product|platform|system|tool|application)\b"
    r"|\bthe (?:product|platform)\b"
    r"|\bearly warning\b|\bborrower ?360\b|\bborrower 3-?60\b"
    r"|\bdata builder\b|\banalysis studio\b|\btrace\b|\blineage\b"
    r"|\bscorecard validation\b|\bstress testing\b|\banalysis studio\b"
    r"|\bagentic ai\b|\bagentic\b|\bthe engine\b|\bgoverned engine\b"
    r"|\bsystem engine\b|\bcreditprobe engine\b|\banalytical engine\b"
    r"|\brisk cases?\b|\bworkflow\b|\bassurance\b|\bcockpit\b"
    r"|\bexternal intelligence\b|\bgroup risk\b|\bconnected counterpart\w*\b"
    # The capability NAMES, as opposed to the concepts they are about. "What
    # is IFRS 9?" is a question about a standard and the governed catalogue
    # answers it; "What is IFRS 9 intelligence?" names a module.
    r"|\becl intelligence\b|\bifrs ?9 (?:and ecl )?intelligence\b"
    r"|\bportfolio intelligence\b|\bcollateral intelligence\b"
    r"|\bcovenant intelligence\b|\bliquidity intelligence\b"
    # "signal" is a product noun in the Early Warning sense. A question ASKING
    # FOR signals on a borrower is caught by the rows test above before this
    # is reached, so naming it here cannot capture a query.
    r"|\bsignals?\b|\bwarnings?\b|\brisk case\b|\bwatchlist methodolog\w*\b",
    re.IGNORECASE)

#: A question that is unambiguously about the product even without a verb test:
#: nothing in a borrower book is called "TAC methodology" or "the role of AI".
_UNAMBIGUOUS = re.compile(
    r"\bwhat is creditprobe\b|\bwhat'?s creditprobe\b"
    r"|\brole of ai\b|\bai (?:is )?(?:used|leveraged|role)\b"
    r"|\bhow is ai\b|\bhow does creditprobe use ai\b"
    r"|\btac\b(?:\s+methodolog\w*)?"
    r"|\bfour[- ]layer\b|\bfour layers\b"
    r"|\bsignal catalogue\b|\bsignal catalog\b"
    r"|\bpersistent warning\b"
    r"|\bthan a (?:normal |traditional |standard )?(?:bi )?dashboard\b"
    r"|\bcompared to a dashboard\b",
    re.IGNORECASE)

# ------------------------------------------------------------ what it asks OF

#: A question that names rows. `which`/`how many`/`how much` of borrowers,
#: customers, facilities, sectors — plus any borrower identifier or an explicit
#: reporting period, either of which settles it on its own.
_ASKS_FOR_ROWS = re.compile(
    r"\bwhich\s+(?:\w+\s+){0,3}?(?:borrowers?|customers?|clients?|"
    r"counterpart(?:y|ies)|obligors?|facilities|accounts?|sectors?|names?|"
    r"exposures?|groups?|cases?|signals? (?:are|is) (?:firing|active))\b"
    r"|\bhow many\b|\bhow much\b"
    r"|\blist (?:the |all )?(?:borrowers?|customers?|facilities|sectors?)\b"
    r"|\btop \d+\b|\bbottom \d+\b"
    r"|\bwho (?:has|have|is|are|was|were)\b",
    re.IGNORECASE)

_NAMES_A_BORROWER = re.compile(r"\b(?:SA|CORP)-\d+\b", re.IGNORECASE)

_NAMES_A_PERIOD = re.compile(
    r"\bq[1-4]\s*\d{4}\b|\bfy\s*\d{4}\b|\b(?:in|during|for|at)\s+\d{4}\b",
    re.IGNORECASE)

#: Measures. A question naming one is asking about the book, not the product —
#: "what is ECL" being the exception the catalogue reader already handles.
_NAMES_A_MEASURE = re.compile(
    r"\bexposure at default\b|\bead\b|\becl\b|\bexpected credit loss\b"
    r"|\bprobability of default\b|\bpd\b|\blgd\b|\bdscr\b|\butilisation\b"
    r"|\bleverage\b|\bheadroom\b|\bdays past due\b|\bdpd\b|\bstage [123]\b"
    r"|\bimpairment\b|\bprovision\w*\b",
    re.IGNORECASE)

PRODUCT = "product"
DATA = "data"

#: Which product tool a question resolves to, tried in order. The first pattern
#: that matches wins, so the specific ones come before the general ones.
_TOPIC: tuple[tuple[str, str], ...] = (
    # "Explain CreditProbe end to end" is the one question that asks for
    # everything, and it is the only one that gets everything.
    (r"\bend[- ]to[- ]end\b|\bcreditprobe in full\b"
     r"|\b(?:explain|describe|tell me about) (?:the )?(?:whole|entire|full) "
     r"(?:product|platform|system)\b", "explain_creditprobe_end_to_end"),
    (r"\btac\b", "describe_tac_methodology"),
    (r"\bfour[- ]layers?\b|\bfour[- ]layer\b", "describe_early_warning_methodology"),
    (r"\bpersistent warning\b|\bwhat does .{0,20}warning mean\b",
     "describe_warning_states"),
    (r"\bsignal(?:s)? .{0,30}(?:catalogue|catalog|list)\b"
     r"|\bwhat signals\b|\bwhich signals\b|\bhow often .{0,30}signals?\b"
     r"|\bsignals? (?:are|is) (?:used|collected)\b", "list_early_warning_signals"),
    (r"\bbecomes? a (?:risk )?case\b|\bcase (?:creation|promotion)\b"
     r"|\bsignal become\b", "describe_case_promotion"),
    (r"\bearly warning\b", "describe_early_warning_methodology"),
    (r"\brole of ai\b|\bhow (?:is|does) ai\b|\bhow does creditprobe use ai\b"
     r"|\bai (?:leveraged|used)\b|\bai architecture\b", "describe_ai_role"),
    (r"\bagentic\b", "describe_agentic_ai"),
    (r"\b(?:governed |system |creditprobe )?engine\b", "describe_governed_engine"),
    (r"\barchitecture\b", "describe_creditprobe_architecture"),
    (r"\bborrower ?360\b|\bborrower 3-?60\b", "describe_borrower360"),
    (r"\bdata builder\b", "describe_data_builder"),
    (r"\banalysis studio\b", "describe_analysis_studio"),
    (r"\btrace\b|\blineage\b", "describe_trace_lineage"),
    (r"\bscorecard validation\b|\bmodel risk\b", "describe_scorecard_validation"),
    (r"\bstress test\w*\b", "describe_stress_testing"),
    (r"\bexternal intelligence\b|\bmacro intelligence\b",
     "describe_external_intelligence"),
    (r"\bgroup risk\b|\bconnected counterpart\w*\b", "describe_group_risk"),
    (r"\bworkflow\b|\brisk cases?\b", "describe_workflow"),
    (r"\bgovernance\b|\bcontrols?\b|\blearning governance\b",
     "describe_governance_controls"),
    (r"\bifrs\s*9\b|\becl intelligence\b", "describe_ifrs9_intelligence"),
    (r"\brating\w*\b", "describe_rating_intelligence"),
    # Three questions that used to share one answer, and should not: why a CRO
    # cares is about OUTCOMES, how a team uses it is about the WEEK, and how it
    # differs from a dashboard is about investigation and traceability. One
    # answer for all three is the template-shaped writing section 17 forbids.
    (r"\bdashboard\b|\bbi tool\b|\breporting tool\b|\bpower ?bi\b"
     r"|\btableau\b|\bcompared to a report\b",
     "creditprobe_versus_a_dashboard"),
    (r"\bhelp a .{0,40}team\b|\bhelp a corporate\b|\bday to day\b"
     r"|\bday-to-day\b|\bhow (?:would|do|can) (?:a|our|my) .{0,40}"
     r"(?:team|desk|function|department)\b|\btypical .{0,30}investigation\b"
     r"|\bwalk me through .{0,30}investigation\b",
     "how_creditprobe_helps_a_team"),
    (r"\bimpressive\b|\bstand out\b|\bwhy should\b"
     r"|\bvalue\b|\bhelp a cro\b|\bhelp a credit risk\b|\buseful to\b"
     r"|\bwhy is creditprobe useful\b", "why_creditprobe"),
    (r"\bwhat can creditprobe do\b|\ball .{0,20}features?\b"
     r"|\bevery .{0,20}(?:module|capabilit)\w*\b|\bcapabilit\w*\b"
     r"|\bfeatures?\b|\bmodules?\b", "list_creditprobe_capabilities"),
)

_TOPIC_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), tool) for pattern, tool in _TOPIC)


@dataclass(frozen=True)
class Intent:
    """Which side of the line a question falls, and why."""

    kind: str = DATA
    tool: str = ""
    why: str = ""

    @property
    def is_product(self) -> bool:
        return self.kind == PRODUCT

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "tool": self.tool, "why": self.why}


def _tool_for(question: str) -> str:
    for pattern, tool in _TOPIC_COMPILED:
        if pattern.search(question):
            return tool
    return "get_creditprobe_overview"


def read(question: str) -> Intent:
    """Whether this question is about CreditProbe or about the book."""
    said = str(question or "").strip()
    if not said:
        return Intent(kind=DATA, why="empty question")

    # The unambiguous ones first: nothing in a borrower book is called "TAC
    # methodology", "the role of AI" or "the four-layer framework".
    if _UNAMBIGUOUS.search(said):
        return Intent(kind=PRODUCT, tool=_tool_for(said),
                      why="the question names a CreditProbe methodology or "
                          "architecture by name")

    # A question naming rows, a borrower or a dated period is about the book,
    # whatever product nouns it also contains. "Which borrowers are on the
    # Early Warning list in Q2 2026" names a module and is still a query.
    if _ASKS_FOR_ROWS.search(said) or _NAMES_A_BORROWER.search(said) \
            or _NAMES_A_PERIOD.search(said):
        return Intent(kind=DATA,
                      why="the question asks for rows, a borrower or a "
                          "dated period")

    if not _PRODUCT_NOUNS.search(said):
        return Intent(kind=DATA, why="the question names nothing about the "
                                     "product itself")

    if not _ASKS_ABOUT_A_THING.search(said):
        return Intent(kind=DATA,
                      why="the question names a module but does not ask what "
                          "it is or does")

    # A product noun, asked about as a thing, with no rows in sight — but a
    # governed measure still tips it back. "What is the average ECL in the
    # Early Warning population" is a data question wearing a product noun.
    if _NAMES_A_MEASURE.search(said) and not _UNAMBIGUOUS.search(said):
        return Intent(kind=DATA,
                      why="the question names a governed measure, so it is "
                          "asking about the book")

    return Intent(kind=PRODUCT, tool=_tool_for(said),
                  why="the question asks what a part of CreditProbe is or does")


#: Signal families a question may name, so "what signals are used for
#: liquidity risk" narrows the catalogue instead of returning all of it.
_FAMILY_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bliquidity\b|\bcash ?flow\b", "liquidity"),
    (r"\bleverage\b|\bdebt service\b|\bdscr\b", "leverage"),
    (r"\bcovenants?\b", "covenant"),
    (r"\bcollateral\b|\bsecurity\b", "collateral"),
    (r"\bratings?\b|\bwatchlist\b|\bmigration\b", "rating"),
    (r"\bifrs\s*9\b|\bstaging?\b|\bsicr\b|\becl\b", "ifrs9"),
    (r"\bbehaviour\w*\b|\bbehavior\w*\b|\butilisation\b|\bdelinquen\w*\b"
     r"|\bdays past due\b|\bdpd\b", "behavioural"),
    (r"\bfinancial\b|\brevenue\b|\bebitda\b|\bmargin\b|\bprofitab\w*\b",
     "financial"),
)


def family_in(question: str) -> str:
    """The signal family a question names, or ''."""
    said = str(question or "")
    for pattern, family in _FAMILY_WORDS:
        if re.search(pattern, said, re.IGNORECASE):
            return family
    return ""


#: A question that asks for depth. Progressive disclosure has two settings, and
#: this is what moves it to the second one: "explain the Early Warning
#: methodology IN DETAIL" gets the per-layer signal listings that the plain
#: question deliberately holds back and offers instead.
_WANTS_DEPTH = re.compile(
    r"\bin (?:full|detail|depth)\b|\bdetailed\b|\bexpand\b|\bexpanded\b"
    r"|\bfull (?:catalogue|catalog|list|detail)\b|\beverything\b"
    r"|\bcomprehensiv\w*\b|\bexhaustiv\w*\b|\bdeep dive\b"
    r"|\bgo deeper\b|\bmore detail\b|\ball (?:of )?the signals?\b",
    re.IGNORECASE)


def wants_depth(question: str) -> bool:
    """Whether the question asked for the held-back detail."""
    return bool(_WANTS_DEPTH.search(str(question or "")))


def answer(question: str) -> Any:
    """The product answer for a question, or None if it is not one."""
    from backend.product import answers as pa

    intent = read(question)
    if not intent.is_product:
        return None
    deep = wants_depth(question)
    if intent.tool == "list_early_warning_signals":
        # A catalogue question that names a family wants that family. Returning
        # all forty-three signals to somebody who asked about liquidity is a
        # correct answer to a question they did not ask.
        return pa.call(intent.tool, family=family_in(question), detail=deep)
    if intent.tool == "describe_early_warning_methodology":
        return pa.call(intent.tool, detail=deep)
    return pa.call(intent.tool)


__all__ = ["DATA", "Intent", "PRODUCT", "answer", "family_in", "read",
           "wants_depth"]
