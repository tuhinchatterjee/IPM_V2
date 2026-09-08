"""
The What-If investigation brain: what a question is, and what it is answered from.

Why this module exists
----------------------
A What-If thread had one reading of a message: is this a scenario? Anything
that was not a scenario fell through, so "Why did Stage 3 ECL increase?" either
did nothing or, worse, was read as another shock and quietly changed the answer
it was asking about.

A credit officer does not use a scenario tool by stating scenarios. They state
one, then interrogate it — and before they state one at all they ask what the
thing does, what data it has, and what they are allowed to shock. So every
message in a thread is read as one of FOURTEEN things, and which one it is
decides both what answers it and whether the scenario STATE may be touched.

  Asking about the PRODUCT — state untouched, no ECL calculated

    HELP           "What do you do?" "How do I configure a scenario?"
    DATA           "What data do you have access to?"
    FIELDS         "What fields are available?" "Can I shock CCF?"
    METHODOLOGY    "What is the difference between Delta and ML?"

  Asking about the BOOK's history — state untouched

    PLAUSIBILITY   "Has a 20% PD rise ever happened?"
    MACRO_ANALYSIS "Show me the sensitivity of unemployment to our PDs."

  Asking about the RESULT on screen — state untouched

    EXPLAIN        "Why did Stage 3 ECL increase?" "Who caused this?"
    VIEW           "Show this by sector." "Chart it by rating."
    COMPARISON     "Compare Delta and ML."
    EXPLAINABILITY "Which ML features drove the difference?"
    EXPORT         "Download the detailed Excel."

  CHANGING something — the book is priced again

    SCENARIO       "Downgrade construction borrowers two notches."
    MODIFY         "Now increase LGD by 5 points." "Undo the last step."
    MACRO_CONFIG   "Use my own unemployment sensitivity: PD ×1.2 per 1pp."

The division is not cosmetic. An EXPLAIN that recomputed would be answering a
question about a result that no longer exists; a MODIFY that did not would be
lying about what it did; and a HELP question that reached the scenario builder
is how "what can you do?" became a shock nobody asked for.

Order matters, and every step of it was a defect first — see `classify`.

Where the numbers come from
---------------------------
Every figure in an answer is computed HERE, from the borrower-level before and
after the engine already produced. Nothing is estimated, and nothing is left to
a language model to recall: the model's job is to read the question and to put
the returned numbers into a sentence, and a number it has not been handed is a
number it must not write.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

INVESTIGATE_VERSION = "2.0.0"

#: About the product, the data or the method. No book is read and no ECL is
#: calculated, so no methodology has to be chosen to answer one.
HELP = "help"
DATA = "data"
FIELDS = "fields"
METHODOLOGY = "methodology"

#: About what the book has DONE, historically. Reads the book; changes nothing.
PLAUSIBILITY = "plausibility"
MACRO_ANALYSIS = "macro_analysis"

#: About the result already on screen. Answered from the borrower-level frame
#: the run produced, never by running it again.
EXPLAIN = "explain"
VIEW = "view"
COMPARISON = "comparison"
EXPLAINABILITY = "explainability"
EXPORT = "export"

#: Changing something. The book is priced again.
SCENARIO = "scenario"
MODIFY = "modify"
MACRO_CONFIG = "macro_config"

INTENTS: tuple[str, ...] = (
    HELP, DATA, FIELDS, METHODOLOGY,
    PLAUSIBILITY, MACRO_ANALYSIS,
    EXPLAIN, VIEW, COMPARISON, EXPLAINABILITY, EXPORT,
    SCENARIO, MODIFY, MACRO_CONFIG,
)

#: The three things an intent can do, which is what the product actually has to
#: branch on. A screen that had to know all fourteen to decide whether to lock
#: the composer would relearn this map in every caller.
ASKS = "asks"          # about the product, the data or the method
READS = "reads"        # the book's history, or the result on screen
CHANGES = "changes"    # the scenario, and the book is priced again

FAMILY: dict[str, str] = {
    HELP: ASKS, DATA: ASKS, FIELDS: ASKS, METHODOLOGY: ASKS,
    PLAUSIBILITY: READS, MACRO_ANALYSIS: READS,
    EXPLAIN: READS, VIEW: READS, COMPARISON: READS,
    EXPLAINABILITY: READS, EXPORT: READS,
    SCENARIO: CHANGES, MODIFY: CHANGES, MACRO_CONFIG: CHANGES,
}

#: Reader-facing names, for the configuration screen and the trace.
LABELS: dict[str, str] = {
    HELP: "Product help",
    DATA: "Data domain question",
    FIELDS: "Field catalogue question",
    METHODOLOGY: "Methodology question",
    PLAUSIBILITY: "Historical plausibility",
    MACRO_ANALYSIS: "Macro sensitivity analysis",
    EXPLAIN: "Explain the result",
    VIEW: "View or break down",
    COMPARISON: "Methodology comparison",
    EXPLAINABILITY: "Model explainability",
    EXPORT: "Export",
    SCENARIO: "New scenario",
    MODIFY: "Modify the scenario",
    MACRO_CONFIG: "Macro sensitivity configuration",
}

# ------------------------------------------------------------- classifying

#: About the PRODUCT. These must never reach the scenario builder: "what can
#: you do?" contains no magnitude, so the builder asked how big it should be.
_HELP = re.compile(
    r"\bwhat\s+(?:do|can)\s+you\s+do\b|\bwhat\s+are\s+you\b"
    r"|\bwho\s+are\s+you\b|\bwhat\s+is\s+(?:this|what[- ]if)\b"
    r"|\bhow\s+(?:can|do)\s+you\s+help\b|\bhelp\s+me\s+(?:get\s+)?start"
    r"|\bhow\s+do\s+i\s+(?:use|start|begin|configure|set\s+up|build|run|"
    r"create)\b"
    r"|\bgive\s+me\s+an?\s+example\b|\bshow\s+me\s+an?\s+example\b"
    r"|\bwhat\s+(?:kind\s+of\s+)?scenarios?\s+can\s+i\b"
    r"|\bwhat\s+can\s+i\s+(?:do|ask|run|change|shock)\b"
    r"|\bwhat\s+are\s+my\s+options\b|\bwhere\s+do\s+i\s+start\b"
    r"|\bexplain\s+what[- ]if\b|\bhow\s+does\s+(?:this|what[- ]if)\s+work\b",
    re.IGNORECASE)

#: About the DATA DOMAIN. Which datasets, which book, which period.
_DATA = re.compile(
    r"\bwhat\s+data\b|\bwhich\s+data\b|\bdata\s+(?:do|can)\s+you\b"
    r"|\bwhat\s+datasets?\b|\bwhich\s+datasets?\b|\bdata\s+sources?\b"
    r"|\bwhich\s+(?:data\s+)?domain\b|\bwhat\s+domain\b"
    r"|\bwhat\s+(?:book|portfolio)\s+(?:do|are)\s+you\b"
    r"|\bdo\s+you\s+have\s+access\s+to\b|\bwhere\s+does\s+(?:the|this)\s+"
    r"data\s+come\s+from\b"
    r"|\bwhat\s+(?:is\s+the\s+)?(?:latest|current|most\s+recent)\s+"
    r"(?:reporting\s+)?period\b|\bwhich\s+periods?\b|\bwhat\s+periods?\b"
    r"|\bhow\s+many\s+quarters\b|\bwhat\s+quarters\b",
    re.IGNORECASE)

#: About the FIELD CATALOGUE. What is there, and what may be shocked or filtered.
_FIELDS = re.compile(
    r"\bwhat\s+fields?\b|\bwhich\s+fields?\b|\bfields?\s+(?:are|do)\s+"
    r"(?:available|you)\b|\bfield\s+(?:list|catalogue|catalog)\b"
    r"|\bwhat\s+(?:columns?|attributes?|variables?)\s+(?:are|do)\b"
    r"|\bwhat\s+(?:risk\s+)?parameters?\s+can\s+i\s+shock\b"
    r"|\bwhich\s+(?:risk\s+)?parameters?\b"
    r"|\bcan\s+i\s+(?:shock|change|filter\s+(?:on|by)|adjust)\s+"
    r"(?:the\s+)?(?:pd|lgd|ccf|ead|rating|stage|collateral|exposure)\b"
    r"|\bwhat\s+can\s+i\s+filter\b|\bwhat\s+is\s+shockable\b"
    r"|\bshow\s+(?:me\s+)?(?:all\s+)?technical\s+fields\b",
    re.IGNORECASE)

#: About the METHOD rather than about a result. "What is the Delta Model?" is a
#: question with an answer on the model page; "compare Delta and ML" is a
#: request to run something, and `_COMPARISON` below catches that first.
_METHODOLOGY_Q = re.compile(
    r"\bwhat\s+is\s+the\s+(?:delta|ml|xgboost)\b"
    r"|\bhow\s+does\s+(?:the\s+)?(?:delta|ml|xgboost)\s+(?:model\s+)?work\b"
    r"|\bwhat\s+(?:ecl\s+)?methodolog\w+\s+(?:do|are|can)\b"
    r"|\bwhich\s+methodolog\w+\s+(?:should|do|can)\b"
    r"|\bdifference\s+between\s+(?:the\s+)?delta\s+and\b"
    r"|\bwhen\s+should\s+i\s+use\s+(?:the\s+)?(?:delta|ml)\b"
    r"|\bwhat\s+(?:model|models)\s+do\s+you\s+(?:use|have|support)\b"
    r"|\bhow\s+was\s+the\s+model\s+trained\b|\bmodel\s+version\b",
    re.IGNORECASE)

#: About what the book has DONE. Not about the result on screen.
_PLAUSIBILITY = re.compile(
    r"\bhas\s+(?:this|that|it)\s+ever\s+happened\b|\bever\s+happened\b"
    r"|\bhow\s+(?:plausible|likely|realistic|severe)\b|\bis\s+(?:this|that)\s+"
    r"(?:plausible|realistic|severe|reasonable|extreme)\b"
    r"|\bhistorical(?:ly)?\s+(?:plausib\w+|precedent|comparison|context|"
    r"experience|observed)\b|\bin\s+the\s+past\b|\bprecedent\b"
    r"|\bhow\s+often\s+(?:has|did|does)\b|\bhow\s+unusual\b"
    r"|\bcompared?\s+(?:to|with|against)\s+history\b"
    r"|\bwhy\s+(?:did\s+you\s+call|is\s+(?:this|that))\s+.{0,20}severe\b"
    r"|\bwhat\s+does\s+history\s+say\b|\bhave\s+we\s+seen\s+this\b",
    re.IGNORECASE)

#: The empirical macro relationship. Reads history; changes no configuration.
_MACRO_ANALYSIS = re.compile(
    r"\bsensitivity\s+of\s+\w+\s+(?:with|to|against)\b"
    r"|\banalys[ei]\s+(?:the\s+)?relationship\b|\brelationship\s+"
    r"(?:with|between|to)\s+.{0,30}\b(?:pd|ifrs\s*9|default)\b"
    r"|\bhow\s+(?:does|do|much\s+does)\s+\w+\s+(?:affect|drive|move|"
    r"influence)\s+(?:our\s+)?(?:pd|default|ecl)\b"
    r"|\bempirical\s+(?:sensitivity|relationship)\b"
    r"|\bestimate\s+the\s+(?:sensitivity|relationship)\b"
    r"|\bcorrelation\s+between\b|\bregress\w*\b"
    r"|\bhistorical\s+sensitivity\b",
    re.IGNORECASE)

#: Setting a macro relationship for this thread. Changes configuration.
_MACRO_CONFIG = re.compile(
    r"\b(?:use|apply|set|define)\s+(?:my|a|the)\s+own\b"
    r"|\bdefine\s+(?:my|a|the)\s+(?:own\s+)?(?:sensitivity|relationship)\b"
    r"|\bcustom\s+(?:sensitivity|relationship)\b"
    r"|\buse\s+(?:the\s+)?(?:estimated|empirical|configured|reference)\s+"
    r"(?:sensitivity|relationship)\b"
    r"|\bset\s+(?:the\s+)?(?:pd|lgd)\s+(?:response|sensitivity)\b"
    r"|\boverride\s+the\s+sensitivity\b|\bkeep\s+the\s+configured\b",
    re.IGNORECASE)

#: Running the same scenario on the other methodology.
_COMPARISON = re.compile(
    r"\bcompare\s+(?:it\s+)?(?:with|to|against|and)?\s*(?:the\s+)?"
    r"(?:delta|ml|xgboost|both|other)\b"
    r"|\b(?:delta|ml|xgboost)\s+(?:vs\.?|versus)\s+(?:delta|ml|xgboost)\b"
    r"|\brun\s+(?:it\s+)?(?:again\s+)?(?:with|on|under)\s+(?:the\s+)?"
    r"(?:delta|ml|xgboost)\b"
    r"|\bwhat\s+would\s+(?:the\s+)?(?:delta|ml|xgboost)\s+say\b"
    r"|\bcompare\s+(?:the\s+two\s+)?methodolog\w+"
    r"|\bcompare\s+both\s+models?\b|\bboth\s+methodolog\w+",
    re.IGNORECASE)

#: Asking the MODEL why, rather than asking the scenario why.
_EXPLAINABILITY = re.compile(
    r"\bshap\b|\bfeature\s+importance\b|\btop\s+predictors?\b"
    r"|\bwhich\s+(?:ml\s+)?features?\b|\bwhat\s+(?:did\s+)?the\s+model\s+"
    r"(?:see|learn|weight|use)\b"
    r"|\bwhy\s+(?:did\s+)?the\s+(?:ml\s+)?model\s+(?:predict|say|think)\b"
    r"|\bmodel\s+explanation\b|\bexplain\s+the\s+(?:ml\s+)?model\b"
    r"|\bout\s+of\s+distribution\b|\bfeature\s+contributions?\b",
    re.IGNORECASE)

#: Asking for the workbook.
_EXPORT = re.compile(
    r"\bdownload\b|\bexport\b|\bexcel\b|\bxlsx\b|\bspreadsheet\b"
    r"|\bworkbook\b|\bcsv\b|\bgive\s+me\s+the\s+(?:file|detail)\b"
    r"|\baccount[- ]level\s+results?\b|\bsave\s+(?:it\s+)?(?:to|as)\s+"
    r"(?:a\s+)?(?:file|excel)\b",
    re.IGNORECASE)

#: Asking WHY, WHO, HOW MUCH about a result that already exists. These never
#: touch the scenario.
_EXPLAIN = re.compile(
    r"\bwhy\b|\bwhat\s+(?:caused|drove|explains)\b|\bexplain\b|\bbecause\b"
    r"|\bhow\s+much\s+(?:of|is|was|comes)\b|\bhow\s+many\b|\bwhich\s+borrowers?\b"
    r"|\bwhich\s+(?:sectors?|names?|customers?|grades?|ratings?)\s+"
    r"(?:contributed|drove|caused|explain)"
    r"|\bwho\b|\bresponsible\b|\bcontributed\b|\bdriver\b|\bdrivers\b"
    r"|\battribut\w+|\bdue\s+to\b|\breconcile\b|\bmakes?\s+up\b"
    r"|\bwhat\s+happened\s+to\b|\bcompare\b|\bdifference\s+between\b"
    r"|\bwhy\s+is\s+ml\b|\bhow\s+come\b",
    re.IGNORECASE)

#: Asking to SEE the same result differently.
_VIEW = re.compile(
    r"\bshow\b|\bbreak\s*(?:it|this)?\s*down\b|\bbreakdown\b|\bby\s+"
    r"(?:sector|segment|stage|rating|grade|customer|borrower|period)\b"
    r"|\bas\s+a\s+(?:chart|table|graph)\b|\bchart\b|\btable\b|\blist\b"
    r"|\bgive\s+me\b|\btop\s+\d+\b|\bdisplay\b",
    re.IGNORECASE)

#: Unmistakably changing the scenario.
_MODIFY = re.compile(
    r"\bundo\b|\breset\b|\bremove\b|\bdrop\s+the\b|\bdelete\b|\bstart\s+again\b"
    r"|\bnow\s+(?:increase|decrease|raise|reduce|lower|cut|add|apply|downgrade|"
    r"upgrade|move|shock|stress)\b"
    r"|\bchange\s+the\s+\w+\s+to\b|\balso\s+(?:increase|decrease|raise|reduce|"
    r"lower|cut|add|apply|downgrade|upgrade|move|shock)\b"
    r"|\bwhat\s+(?:happens|if)\s+i\s+now\b|\bkeep\s+the\b.{0,40}\bremove\b",
    re.IGNORECASE)

#: What a breakdown is asked for BY.
_DIMENSION: tuple[tuple[str, str, str], ...] = (
    (r"\bsector\b", "sector", "Sector"),
    (r"\bsegment\b", "segment", "Segment"),
    (r"\bstages?\b", "stage_baseline", "Opening stage"),
    (r"\b(?:rating|grade)s?\b", "opening_rating", "Opening rating"),
    (r"\b(?:customers?|borrowers?|names?|clients?)\b", "display_name", "Borrower"),
)


@dataclass
class Reading:
    """What the message is, and what it asks about."""

    intent: str = SCENARIO
    dimension: str = ""
    dimension_label: str = ""
    #: A specific Stage the question is about, where it names one.
    stage: int = 0
    #: What the question wants explained, where it is one of the known topics.
    topic: str = ""
    wants_chart: bool = False
    wants_table: bool = False
    #: Whether the message points at the result on screen rather than at the
    #: book. "Show this by sector" is a cut of the scenario; "show Stage 1 PD
    #: by sector" is a question about the reported book, and answering the
    #: second from a scenario's figures would be a different answer entirely.
    about_the_result: bool = False
    #: The macro variable the message names, where it names one.
    variable: str = ""
    question: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def family(self) -> str:
        """Whether this asks, reads, or changes."""
        return FAMILY.get(self.intent, CHANGES)

    @property
    def changes_state(self) -> bool:
        return self.family == CHANGES

    @property
    def needs_a_result(self) -> bool:
        """Whether answering it requires a scenario to have been run."""
        return self.intent in (EXPLAIN, VIEW, COMPARISON, EXPLAINABILITY,
                               EXPORT)

    @property
    def calculates_ecl(self) -> bool:
        """Whether answering it prices the book, and so needs a methodology.

        A product question, a field question and a historical question do not.
        Asking one and being met with "which ECL methodology should I use?" is
        the gate asking a question with no right answer.
        """
        return self.changes_state

    @property
    def label(self) -> str:
        return LABELS.get(self.intent, self.intent)

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "label": self.label,
                "family": self.family, "changes_state": self.changes_state,
                "needs_a_result": self.needs_a_result,
                "calculates_ecl": self.calculates_ecl,
                "dimension": self.dimension,
                "dimension_label": self.dimension_label, "stage": self.stage,
                "topic": self.topic, "wants_chart": self.wants_chart,
                "wants_table": self.wants_table,
                "about_the_result": self.about_the_result,
                "variable": self.variable,
                "notes": list(self.notes)}


#: A sentence that OPENS with one of these is a question about something,
#: never an instruction to do it.
_INTERROGATIVE = re.compile(
    r"\s*(?:why|what|which|who|whom|whose|how|was|were|is|are|am|did|does|do|"
    r"can|could|would|should|has|have|had|will)\b",
    re.IGNORECASE)

#: Except when the question IS the scenario. "What if I downgrade everyone two
#: notches?" opens with an interrogative and is an instruction.
_HYPOTHETICAL = re.compile(
    r"\bwhat\s*[- ]?\s*if\b|\bwhat\s+happens?\s+(?:if|when)\b"
    r"|\bwhat\s+would\s+happen\b|\bsuppose\b|\bassume\b",
    re.IGNORECASE)

#: Pointing at the result rather than at the book.
_DEICTIC = re.compile(
    r"\bthis\b|\bthat\b|\bit\b|\bthem\b|\bthese\b|\bthose\b"
    r"|\bthe\s+(?:result|scenario|movement|increase|decrease|change|rise|"
    r"fall|impact|effect|shock|what[- ]if)\b",
    re.IGNORECASE)

#: Topics an EXPLAIN question can be about, in the order they are tested.
_TOPIC: tuple[tuple[str, str], ...] = (
    (r"\bmeasurement\s+basis\b|\blifetime\s+pd\s+replac\w+|\b12[- ]?m(?:onth)?\s+"
     r"pd\s+(?:to|into|replaced|became)\b|\bbasis\s+change\b"
     r"|\blifetime\s+pd\b.{0,30}\binstead\b|\bbecause\s+lifetime\b"
     # The question people actually ask, which never uses the words
     # "measurement basis": why does crossing into Stage 2 cost anything at
     # all when nothing about the borrower changed?
     r"|\bmov\w+\s+(?:in)?to\s+stage\s*2\b.{0,30}\b(?:cost|worth|expensive)"
     r"|\bwhy\s+does\s+stage\s*2\s+cost\b"
     r"|\blifetime\s+pd\b.{0,40}\b(?:used|applied|apply|instead|rather)\b",
     "basis"),
    (r"\bstage\s*3\b|\bstage\s+three\b", "stage3"),
    (r"\bstage\s+migration\b|\bstage\s+movement\b|\bmoved?\s+from\s+stage\b"
     r"|\bstage\s*1\s*(?:to|->)\s*stage\s*2\b", "stage_migration"),
    (r"\bml\b|\bxgboost\b|\bmodel\s+differ\w*|\bdelta\s+vs\b|\bvs\.?\s+delta\b"
     r"|\bcompare\s+delta\b|\bmethodolog\w+|\bboth\s+models?\b"
     r"|\bdelta\s+model\b", "methodology"),
    (r"\blgd\b|\bloss\s+given\s+default\b", "lgd"),
    (r"\bead\b|\bexposure\s+at\s+default\b|\bccf\b", "ead"),
    (r"\brating\b|\bnotch\w*\b|\bdowngrade\b", "rating"),
    (r"\bmacro\b|\beconom\w+|\bunemployment\b|\boil\b|\bgdp\b", "macro"),
    (r"\bpd\b|\bprobability\s+of\s+default\b", "pd"),
    (r"\bborrowers?\b|\bnames?\b|\bcustomers?\b|\bwho\b|\bresponsible\b",
     "borrowers"),
    (r"\bsector\b", "sector"),
)


def classify(question: str, *, has_result: bool = False,
             has_steps: bool = False) -> Reading:
    """Which of the fourteen things this message is.

    The order below is the whole of the design, and every step of it was a
    defect first.

    **The product questions come before everything.** "What can you do?" names
    no magnitude, so the scenario builder asked how big it should be. A person
    finding out what the tool is must not be answered with a shock.

    **An INTERROGATIVE is never an instruction**, unless it is a hypothetical.
    "Was any of this the rating downgrade?" was read as a scenario and
    downgraded the entire book — a question about a result became the thing it
    was asking about. "What if I downgrade everyone two notches?" still is one.

    **EXPLAIN before VIEW.** "Show me the borrowers responsible" contains
    "show", but it asks who caused something, and answering it with a plain
    table would drop the question.

    **A FULL SCENARIO before VIEW.** "Stress the top 50 exposures by two
    notches" contains "top 50" and was read as a request to see a list; it
    states a magnitude and a direction, so it is an instruction.

    `has_result` and `has_steps` are the thread's state, and they change the
    reading rather than decorating it. On an empty thread there is nothing to
    explain, compare, explain the model of, or export, so a message that would
    otherwise be one of those is a question about the product or the book
    instead — which is what it actually is, before a scenario exists.
    """
    said = str(question or "").strip()
    reading = Reading(question=said)
    if not said:
        return reading

    from backend.whatif import language as lang

    asked = bool(_INTERROGATIVE.match(said)) and not _HYPOTHETICAL.search(said)

    # ---- 1. about the PRODUCT, the DATA, the FIELDS or the METHOD.
    #
    # First, and unconditionally. None of these reads the book, none needs a
    # methodology, and none may reach the scenario builder.
    for pattern, intent in ((_HELP, HELP), (_DATA, DATA), (_FIELDS, FIELDS)):
        if pattern.search(said):
            reading.intent = intent
            return _decorate(reading, said)
    # Methodology QUESTION only where it is not a request to run the other one.
    if _METHODOLOGY_Q.search(said) and not _COMPARISON.search(said):
        reading.intent = METHODOLOGY
        return _decorate(reading, said)

    # ---- 2. about the macro RELATIONSHIP: reading it, or setting it.
    if _MACRO_CONFIG.search(said):
        reading.intent = MACRO_CONFIG
        return _decorate(reading, said)
    if _MACRO_ANALYSIS.search(said):
        reading.intent = MACRO_ANALYSIS
        return _decorate(reading, said)

    # ---- 3. about the book's HISTORY.
    if _PLAUSIBILITY.search(said):
        reading.intent = PLAUSIBILITY
        return _decorate(reading, said)

    # ---- 4. about the RESULT on screen — but only where one exists.
    #
    # "Download the detailed Excel" on an empty thread is not an export, it is
    # somebody finding out that exports exist.
    if _EXPORT.search(said):
        reading.intent = EXPORT if has_result else HELP
        return _decorate(reading, said)
    if _COMPARISON.search(said):
        reading.intent = COMPARISON if has_result else METHODOLOGY
        return _decorate(reading, said)
    if _EXPLAINABILITY.search(said):
        reading.intent = EXPLAINABILITY if has_result else METHODOLOGY
        return _decorate(reading, said)

    # ---- 5. changing the scenario, explaining it, or looking at it again.
    if _MODIFY.search(said) and not asked:
        reading.intent = MODIFY
        return _decorate(reading, said)

    explains = bool(_EXPLAIN.search(said))
    views = bool(_VIEW.search(said))
    scenario = lang.read(said)
    if explains or asked:
        reading.intent = EXPLAIN
    elif scenario.scenario is not None:
        # A stated magnitude and direction. Whether it is a NEW scenario or a
        # modification of the one on the thread is a fact about the thread, not
        # about the sentence.
        reading.intent = MODIFY if has_steps else SCENARIO
    elif views:
        reading.intent = VIEW
    else:
        # Neither signal. Ask the scenario reader: a sentence it can read as a
        # What-If is one — including "stress the real estate portfolio", which
        # names no magnitude and has to be ASKED how big rather than answered
        # as though it were a question about a result. Everything else is a
        # question, which is the safer of the two readings because it cannot
        # silently change a number.
        opens = bool(getattr(scenario, "opens_whatif", False))
        reading.intent = ((MODIFY if has_steps else SCENARIO) if opens
                          else EXPLAIN)
    return _decorate(reading, said)


def _decorate(reading: Reading, said: str) -> Reading:
    """What the message is ABOUT, whatever kind of message it is."""
    for pattern, column, label in _DIMENSION:
        if re.search(pattern, said, re.IGNORECASE):
            reading.dimension, reading.dimension_label = column, label
            break
    stage = re.search(r"\bstage\s*([123])\b", said, re.IGNORECASE)
    if stage:
        reading.stage = int(stage.group(1))
    for pattern, topic in _TOPIC:
        if re.search(pattern, said, re.IGNORECASE):
            reading.topic = topic
            break
    reading.wants_chart = bool(re.search(r"\bchart\b|\bgraph\b|\bplot\b",
                                         said, re.IGNORECASE))
    reading.wants_table = bool(re.search(r"\btable\b|\blist\b", said,
                                         re.IGNORECASE))
    reading.about_the_result = bool(_DEICTIC.search(said))
    reading.variable = _macro_variable(said)
    return reading


def _macro_variable(said: str) -> str:
    """The macro variable a message names, where it names one."""
    from backend.whatif import macro as mc

    lowered = said.lower()
    for key, name in sorted(
            ((v.key, v.name) for v in mc.VARIABLES),
            key=lambda kv: len(kv[1]), reverse=True):
        if name.lower() in lowered or key.replace("_", " ") in lowered:
            return key
    for word, key in sorted(mc.ALIASES.items(), key=lambda kv: len(kv[0]),
                            reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return key
    return ""


# --------------------------------------------------------------- answering


def _frame(result: Any) -> pd.DataFrame:
    """The borrower-level before and after, as the result holds it."""
    frame = getattr(result, "borrowers", None)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _money(value: float, currency: str = "SAR") -> str:
    return f"{currency} {value:,.1f}m"


def _by(frame: pd.DataFrame, column: str, label: str,
        limit: int = 25) -> dict[str, Any]:
    """The ECL movement grouped by one dimension, largest contribution first."""
    if column not in frame.columns:
        return {"available": False,
                "why": f"This result does not carry {label.lower()}."}
    work = frame.copy()
    for money in ("ecl_baseline", "ecl_stressed", "ead"):
        if money in work.columns:
            work[money] = pd.to_numeric(work[money], errors="coerce").fillna(0.0)
    grouped = (work.groupby(work[column].astype(str))
               .agg(borrowers=("borrower_id", "size"),
                    exposure=("ead", "sum"),
                    ecl_before=("ecl_baseline", "sum"),
                    ecl_after=("ecl_stressed", "sum"))
               .reset_index().rename(columns={column: "label"}))
    grouped["change"] = grouped["ecl_after"] - grouped["ecl_before"]
    grouped["change_pct"] = np.where(
        grouped["ecl_before"] > 0,
        grouped["change"] / grouped["ecl_before"] * 100.0, 0.0)
    total = float(grouped["change"].sum())
    grouped["share_pct"] = (grouped["change"] / total * 100.0) if total else 0.0
    grouped = grouped.reindex(
        grouped["change"].abs().sort_values(ascending=False).index)
    return {"available": True, "dimension": label,
            "rows": grouped.head(limit).round(4).to_dict(orient="records"),
            "total_change": total, "groups": int(len(grouped))}


def _contributors(frame: pd.DataFrame, limit: int = 20) -> dict[str, Any]:
    """The borrowers that moved the provision most, largest first."""
    if frame.empty or "ecl_increase" not in frame.columns:
        return {"available": False, "why": "No borrower-level result."}
    work = frame.copy()
    work["ecl_increase"] = pd.to_numeric(work["ecl_increase"],
                                         errors="coerce").fillna(0.0)
    total = float(work["ecl_increase"].sum())
    top = work.reindex(
        work["ecl_increase"].abs().sort_values(ascending=False).index).head(limit)
    columns = [c for c in ("borrower_id", "display_name", "sector",
                           "opening_rating", "stressed_rating",
                           "stage_baseline", "stage_stressed", "ead",
                           "ecl_baseline", "ecl_stressed", "ecl_increase",
                           "primary_driver") if c in top.columns]
    rows = top[columns].round(4).to_dict(orient="records")
    for row in rows:
        row["share_pct"] = (round(float(row.get("ecl_increase", 0.0))
                                  / total * 100.0, 3) if total else 0.0)
    return {"available": True, "rows": rows, "total_change": total,
            "shown": len(rows), "of": int(len(work))}


def _stage_three(frame: pd.DataFrame, currency: str = "SAR") -> dict[str, Any]:
    """Whether Stage 3 moved, and if so exactly which borrowers and why.

    Stage 3 is the question people ask about most and trust least, because a
    provision on defaulted names moving under a Stage 1 shock looks wrong. It
    usually IS wrong, so this reports the mechanism or reports that there is
    none.
    """
    if frame.empty or "stage_baseline" not in frame.columns:
        return {"available": False, "why": "No borrower-level result."}
    work = frame.copy()
    for column in ("ecl_baseline", "ecl_stressed", "ead"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column],
                                         errors="coerce").fillna(0.0)
    before = pd.to_numeric(work["stage_baseline"], errors="coerce").fillna(1)
    after = pd.to_numeric(work.get("stage_stressed", before),
                          errors="coerce").fillna(before)

    was_three = before >= 3
    now_three = after >= 3
    entered = (~was_three) & now_three
    left = was_three & (~now_three)
    stayed = was_three & now_three

    change = float(work.loc[now_three, "ecl_stressed"].sum()
                   - work.loc[was_three, "ecl_baseline"].sum())
    within = float(work.loc[stayed, "ecl_stressed"].sum()
                   - work.loc[stayed, "ecl_baseline"].sum())
    arriving = float(work.loc[entered, "ecl_stressed"].sum())
    leaving = float(work.loc[left, "ecl_baseline"].sum())

    drivers = []
    if abs(arriving) > 1e-9:
        drivers.append({
            "driver": "Borrowers migrating INTO Stage 3",
            "borrowers": int(entered.sum()),
            "exposure": float(work.loc[entered, "ead"].sum()),
            "effect": arriving})
    if abs(leaving) > 1e-9:
        drivers.append({
            "driver": "Borrowers leaving Stage 3",
            "borrowers": int(left.sum()),
            "exposure": float(work.loc[left, "ead"].sum()),
            "effect": -leaving})
    if abs(within) > 1e-9:
        moved = work[stayed & (work["ecl_stressed"] != work["ecl_baseline"])]
        drivers.append({
            "driver": "Names already in Stage 3, re-measured",
            "borrowers": int(len(moved)),
            "exposure": float(moved["ead"].sum()),
            "effect": within})

    if not drivers:
        return {
            "available": True, "moved": False, "change": 0.0,
            "borrowers_before": int(was_three.sum()),
            "borrowers_after": int(now_three.sum()),
            "note": (
                f"Stage 3 did not move. {int(was_three.sum()):,} borrowers "
                "were in Stage 3 before this scenario and the same are in it "
                "after, at the same provision. A scenario does not cure a "
                "default and does not create one, so unless the shock reached "
                "their exposure, their security or their recovery, their "
                "expected credit loss is unchanged."),
        }
    return {
        "available": True, "moved": True, "change": change,
        "borrowers_before": int(was_three.sum()),
        "borrowers_after": int(now_three.sum()),
        "drivers": drivers,
        "note": (
            f"Stage 3 expected credit loss moved by "
            f"{_money(change, currency)}. Every part of that movement has a "
            "named mechanism below: names arriving, names leaving, or names "
            "already there whose exposure, security or loss rate the scenario "
            "changed."),
    }


def _pd_versus_ecl(frame: pd.DataFrame) -> dict[str, Any]:
    """Why the provision moved by more than the PD did.

    The commonest confusion on a What-If, and it has an arithmetic answer: the
    provision is a product, and a Stage crossing changes which PD is in it.
    """
    if frame.empty:
        return {"available": False}
    work = frame.copy()
    for column in ("pd_12m", "pd_stressed", "ecl_baseline", "ecl_stressed",
                   "ead"):
        if column in work.columns:
            work[column] = pd.to_numeric(work[column],
                                         errors="coerce").fillna(0.0)
    weight = work["ead"] if work.get("ead") is not None else None
    weights = weight if weight is not None and weight.sum() > 0 else None
    pd_before = float(np.average(work["pd_12m"], weights=weights))
    pd_after = float(np.average(work["pd_stressed"], weights=weights))
    ecl_before = float(work["ecl_baseline"].sum())
    ecl_after = float(work["ecl_stressed"].sum())
    return {
        "available": True,
        "pd_before": round(pd_before, 4),
        "pd_after": round(pd_after, 4),
        "pd_change_pct": round((pd_after / pd_before - 1) * 100.0, 3)
        if pd_before else 0.0,
        "ecl_change_pct": round((ecl_after / ecl_before - 1) * 100.0, 3)
        if ecl_before else 0.0,
    }


def answer(reading: Reading, result: Any) -> dict[str, Any]:
    """The deterministic answer to an EXPLAIN or VIEW question.

    Computed from the result already on screen. Nothing here re-runs the
    scenario, and nothing here is estimated: every figure is a sum or an
    average over the borrower rows the engine produced.
    """
    frame = _frame(result)
    currency = getattr(result, "currency", "SAR") or "SAR"
    summary = dict(getattr(result, "summary", {}) or {})
    attribution = dict(getattr(result, "attribution", {}) or {})
    body: dict[str, Any] = {
        "version": INVESTIGATE_VERSION,
        "intent": reading.intent,
        "topic": reading.topic,
        "question": reading.question,
        "state_changed": False,
        "headline": {
            "baseline_ecl": summary.get("baseline_ecl", 0.0),
            "whatif_ecl": summary.get("stressed_ecl", 0.0),
            "change": summary.get("incremental_ecl", 0.0),
            "change_pct": summary.get("incremental_ecl_pct", 0.0),
            "currency": currency,
        },
    }

    if reading.intent == VIEW or (reading.dimension and not reading.topic):
        column = reading.dimension or "sector"
        label = reading.dimension_label or "Sector"
        body["breakdown"] = _by(frame, column, label)
        body["explanation"] = (
            f"The same result, cut by {label.lower()}. Nothing about the "
            "scenario changed — this is the figures already computed, grouped "
            "differently.")
        return body

    topic = reading.topic
    if topic == "stage3" or reading.stage == 3:
        body["stage_3"] = _stage_three(frame, currency)
        body["explanation"] = body["stage_3"].get("note", "")
        return body
    if topic == "basis":
        body["measurement_basis"] = attribution.get("measurement_basis", {})
        body["explanation"] = body["measurement_basis"].get("note", "")
        return body
    if topic in ("stage_migration",):
        body["stage_movement"] = dict(getattr(result, "stage_movement", {}) or {})
        body["measurement_basis"] = attribution.get("measurement_basis", {})
        body["explanation"] = body["measurement_basis"].get("note", "")
        return body
    if topic == "borrowers" or reading.dimension == "display_name":
        body["contributors"] = _contributors(frame)
        body["explanation"] = (
            "The borrowers whose provision moved most, largest first. The "
            "share column is that borrower's part of the whole movement.")
        return body
    if topic == "methodology":
        body["methodology"] = {
            "chosen": summary.get("methodology_label", ""),
            "version": summary.get("methodology_version", ""),
            "model_adjustment": attribution.get("model_adjustment"),
        }
        body["explanation"] = (
            (attribution.get("model_adjustment") or {}).get("note")
            or "This result was priced on one methodology; ask to compare to "
               "see the other.")
        return body
    if topic in ("pd", "lgd", "ead", "rating", "macro", "sector"):
        body["drivers"] = attribution.get("drivers", [])
        body["pd_versus_ecl"] = _pd_versus_ecl(frame)
        if topic == "sector":
            body["breakdown"] = _by(frame, "sector", "Sector")
        body["explanation"] = (
            "Every driver of the movement, split by an exact order-neutral "
            "Shapley value, so the parts add to the whole.")
        return body

    # A general "why". Give the whole decomposition, which is what the
    # question is really asking for.
    body["drivers"] = attribution.get("drivers", [])
    body["measurement_basis"] = attribution.get("measurement_basis", {})
    body["pd_versus_ecl"] = _pd_versus_ecl(frame)
    body["explanation"] = (
        "The movement, split across the drivers that caused it. The effects "
        "sum to the total, and a driver the scenario did not touch is exactly "
        "zero.")
    return body


def describe() -> dict[str, Any]:
    """What the thread does with a message, for the configuration screen."""
    return {
        "version": INVESTIGATE_VERSION,
        "families": [
            {"family": ASKS, "label": "Asks about the product",
             "changes_state": False, "calculates_ecl": False},
            {"family": READS, "label": "Reads the book or the result",
             "changes_state": False, "calculates_ecl": False},
            {"family": CHANGES, "label": "Changes the scenario",
             "changes_state": True, "calculates_ecl": True},
        ],
        "all_intents": [
            {"intent": key, "label": LABELS[key], "family": FAMILY[key],
             "changes_state": FAMILY[key] == CHANGES,
             "needs_a_result": key in (EXPLAIN, VIEW, COMPARISON,
                                       EXPLAINABILITY, EXPORT)}
            for key in INTENTS],
        "intents": [
            {"intent": EXPLAIN, "label": "Explain or investigate",
             "changes_state": False,
             "examples": ["Why did Stage 3 ECL increase?",
                          "How much is due to Stage migration?",
                          "Which borrowers contributed most?"]},
            {"intent": VIEW, "label": "View or break down",
             "changes_state": False,
             "examples": ["Show this by sector.", "Break it down by rating.",
                          "Give me a table."]},
            {"intent": MODIFY, "label": "Change the scenario",
             "changes_state": True,
             "examples": ["Now increase LGD by 5 percentage points.",
                          "Undo the last step.", "Remove the macro shock."]},
        ],
        "statement": (
            "Every message is one of three things, and only one of them may "
            "touch the scenario. An explanation is answered from the result "
            "already computed, so asking why cannot change the number you are "
            "asking about."),
    }


__all__ = [
    "EXPLAIN", "INTENTS", "INVESTIGATE_VERSION", "MODIFY", "Reading", "VIEW",
    "answer", "classify", "describe",
]
