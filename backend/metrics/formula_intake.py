"""Reading a formula somebody typed, without changing a character of it.

§4 makes a user formula a first-class input: a person may type pure notation,
business language, or the two mixed, and CreditProbe has to understand it as a
metric definition. §5 makes the harder demand — the formula must survive that
understanding EXACTLY. Somebody who wrote

    Previous / Current - 1

did not write the conventional growth formula, and a system that quietly makes
them agree has silently answered a different question and put the person's name
on it.

How preservation is guaranteed
-------------------------------
Not by telling a model to be careful. The model never writes the formula.

Pass 1 is asked for OFFSETS into the text the person typed — where the formula
starts and ends, where the numerator sits inside it, where the denominator sits
— and CreditProbe slices the person's own string with them. A model that
hallucinated a "corrected" formula would produce offsets that do not bracket
it, and the slice would still be what was typed. The only way for the stored
formula to differ from the typed one is for the offsets to be wrong, and
:func:`_sliced` refuses offsets that do not land on the original.

So `FormulaIntake.formula_text` is always a substring of `FormulaIntake.said`.
A test asserts exactly that, over every example in §4 and §34.

Pass 2 is where a model is allowed to write: the metric's name, what it is for,
its unit, its period rule. None of those is the formula.

The unconventional flag
------------------------
§5 and §34 want the person warned, not corrected. `unconventional` is filled in
when the two operands of a growth expression are in the order that inverts the
usual reading — detected from the period words INSIDE the operands, not from
guessing at intent — and it carries the conventional alternative as a separate
string the person may choose. Nothing chooses it for them.

Degrading
---------
With no provider configured the deterministic reader below does the whole job.
It handles every example §4 lists, because those examples are arithmetic with
names in them and arithmetic is parseable. What a model adds is the messy
middle: "take the stage 2 and stage 3 EAD and put it over the total", where the
operator is a preposition.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

INTAKE_VERSION = "3.0.0"

TOOL_NAME = "read_formula"

#: The longest formula this will read. A "formula" of four thousand characters
#: is a paste, and a paste is not a metric definition.
MAX_FORMULA = 600

#: Operators a formula may contain, in the order they are recognised.
OPERATORS = ("/", "*", "+", "-", "×", "÷", "−")

#: Words that mean the current period, and words that mean the one before it.
#: Used ONLY to decide whether to raise the unconventional flag — never to
#: reorder anything.
CURRENT_WORDS = ("current", "latest", "this", "present", "now")
PREVIOUS_WORDS = ("previous", "prior", "last", "preceding", "earlier",
                  "year ago", "year-ago")

#: A growth expression: something over something, minus one.
_GROWTH = re.compile(r"^\s*\(?(?P<top>[^/()]+)\)?\s*/\s*\(?(?P<bottom>[^/()]+)\)?\s*\)?\s*-\s*1\s*$")

#: Where a formula plausibly begins in a sentence that also contains English.
_FORMULA_CHARS = re.compile(r"[0-9A-Za-z_%\.\s\(\)\+\-\*/×÷−]+")

#: Whether a span contains a word at all. `has_arithmetic` below decides the
#: operator question, because an operator can be a symbol or a word.
_HAS_WORD = re.compile(r"[A-Za-z]")

#: A label somebody put in front of their formula: "QoQ exposure change: (…)".
#: The colon is where the sentence stops describing and starts calculating.
_LABELLED = re.compile(r"^(?P<label>[^:]{0,80}):\s*(?P<formula>.+)$", re.DOTALL)

#: The "minus one" that turns a ratio into a growth rate. Held separately from
#: the ratio so that splitting the ratio does not put it in the denominator.
_MINUS_ONE = re.compile(r"\s*[-−]\s*1(?:\.0+)?\s*$")

SYSTEM = """You are reading a message a credit-risk professional typed into \
CreditProbe's Lens builder, to decide whether it defines a METRIC FORMULA and, if \
it does, exactly WHERE in their text that formula is.

YOU MUST NOT WRITE THE FORMULA. You return character offsets into their message. \
CreditProbe slices their own text with your offsets, so whatever you return, what \
gets stored is what they typed. Offsets are 0-based, `end` is exclusive, and the \
text between them must be the formula and nothing else.

WHAT COUNTS AS A FORMULA REQUEST

Any of these:
  "Add Stage 2 Exposure / Total Exposure."
  "(Current Quarter Exposure / Previous Quarter Exposure) - 1"
  "High EWS exposure divided by total corporate exposure."
  "Take Stage 2 EAD plus Stage 3 EAD and divide by total EAD."
  "Show covenant breach exposure divided by corporate exposure."
  "Build a chart of this formula by sector."

The person may use notation, business language, or both. "divided by" is a \
division. "plus" is an addition. A numerator described in words and a denominator \
described in words is a ratio.

WHAT DOES NOT COUNT

A request to add an EXISTING metric by name ("add total exposure", "show me the \
Stage 2 ratio") is not a formula request — it names one thing, with no operator \
and no arithmetic. Set `is_formula` false for those. A request to change a Lens's \
layout, period or filters is not a formula request either.

OFFSETS

`formula_start` / `formula_end` bracket the whole formula, including any words \
that are part of it ("divided by", "plus"). Leave out leading verbs that are not \
part of the arithmetic — "Add ", "Show me ", "Build a chart of ".

`numerator_start` / `numerator_end` and `denominator_start` / `denominator_end` \
bracket the two sides where there is a division. Set all four to -1 where there \
is no division.

Use -1 for any offset you cannot determine. Never guess: an offset that does not \
land on the formula is rejected and the deterministic reader is used instead, \
which is a better outcome than a mis-sliced formula."""


# ---------------------------------------------------------------------------
# What comes out
# ---------------------------------------------------------------------------


@dataclass
class Unconventional:
    """A formula that reads backwards from the usual convention, flagged.

    §5: the person is told, offered the conventional alternative, and their
    choice is honoured. `conventional` is a suggestion held beside the
    formula, never applied to it.
    """

    because: str = ""
    conventional: str = ""
    convention_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"because": self.because, "conventional": self.conventional,
                "convention_name": self.convention_name,
                "choices": [
                    {"id": "keep", "label": "Keep My Formula"},
                    {"id": "conventional", "label": "Use Conventional Formula"},
                    {"id": "edit", "label": "Edit Formula"},
                ]}


@dataclass
class FormulaIntake:
    """Pass 1's answer: what the person typed, read but not rewritten."""

    said: str = ""
    #: ALWAYS a substring of `said`. See the module docstring.
    formula_text: str = ""
    is_formula: bool = False
    numerator_text: str = ""
    denominator_text: str = ""
    operation: str = ""
    #: What the person also asked for around the formula: a chart, a grouping,
    #: a period window. Held so §15 does not need a second read of the message.
    wants_chart: bool = False
    group_by: str = ""
    period_hint: str = ""
    unconventional: Unconventional | None = None
    #: Pass 2's reading. Prose, and therefore allowed to be written.
    suggested_name: str = ""
    intent: str = ""
    unit_hint: str = ""
    #: True when a model read the message. False means the deterministic
    #: reader did, which is still a correct read of anything with an operator
    #: in it.
    understood: bool = False
    model: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def preserved(self) -> bool:
        """The property this module exists to guarantee."""
        return not self.formula_text or self.formula_text in self.said

    def to_dict(self) -> dict[str, Any]:
        return {
            "said": self.said,
            "formula": self.formula_text,
            "is_formula": self.is_formula,
            "numerator": self.numerator_text,
            "denominator": self.denominator_text,
            "operation": self.operation,
            "wants_chart": self.wants_chart,
            "group_by": self.group_by,
            "period_hint": self.period_hint,
            "unconventional": (self.unconventional.to_dict()
                               if self.unconventional else None),
            "suggested_name": self.suggested_name,
            "intent": self.intent,
            "unit_hint": self.unit_hint,
            "understood": self.understood,
            "model": self.model,
            "preserved": self.preserved,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Slicing, which is the only way text gets out of here
# ---------------------------------------------------------------------------


def _sliced(said: str, start: Any, end: Any) -> str:
    """The person's own characters between two offsets, or nothing.

    Refuses rather than clamps. An offset pair that does not describe a
    sensible span is a model that did not find the formula, and the right
    answer to that is to fall back to the deterministic reader — not to return
    a span nobody meant.
    """
    try:
        a, b = int(start), int(end)
    except (TypeError, ValueError):
        return ""
    if a < 0 or b <= a or b > len(said):
        return ""
    return said[a:b].strip()


# ---------------------------------------------------------------------------
# The deterministic reader
# ---------------------------------------------------------------------------

#: Business phrasings of an operator, longest first so "divided by" wins over
#: "by". Each maps to the symbol it means; NONE of them rewrites the formula,
#: they only say which operation was found.
_WORD_OPERATORS: tuple[tuple[str, str], ...] = (
    ("divided by", "/"), ("divide by", "/"), ("over", "/"), ("per", "/"),
    ("as a share of", "/"), ("as a percentage of", "/"), ("of total", "/"),
    ("multiplied by", "*"), ("times", "*"),
    ("plus", "+"), ("added to", "+"),
    ("minus", "-"), ("less", "-"),
)

_LEADING_VERBS = re.compile(
    r"^\s*(please\s+)?(add|show|show me|build|make|create|give me|include|"
    r"put|draw|chart|plot|take|compute|calculate|work out)\s+"
    r"(a\s+|an\s+|the\s+|me\s+)?(chart\s+of\s+|graph\s+of\s+|trend\s+of\s+)?"
    r"(metric\s+(for|called)\s+)?", re.IGNORECASE)

_CHART_WORDS = re.compile(
    r"\b(chart|graph|plot|trend|bar chart|line chart|breakdown|split)\b",
    re.IGNORECASE)

_GROUP_BY = re.compile(
    r"\b(?:by|per|across|split by|broken down by|grouped by)\s+"
    r"(sector|region|segment|country|rating|rating band|rating_bucket|"
    r"grade|grade band|stage|product|product type|obligor|customer|"
    r"quarter|period|month|year|collateral type)\b", re.IGNORECASE)

_PERIOD_HINT = re.compile(
    r"\b(?:last|latest|past|previous)\s+(?P<n>\d{1,2})\s+"
    r"(?P<unit>quarters?|months?|years?)\b", re.IGNORECASE)


def _strip_trailing_instruction(text: str) -> str:
    """Cut the request off the end of a formula, without touching the formula.

    "Stage 2 Exposure / Total Exposure by sector" contains a formula and an
    instruction about how to draw it. The formula ends where the instruction
    starts, and the instruction is recorded separately rather than being made
    part of the arithmetic.
    """
    cut = len(text)
    for pattern in (_GROUP_BY, _CHART_WORDS, _PERIOD_HINT):
        found = pattern.search(text)
        if found and found.start() < cut:
            cut = found.start()
    trimmed = text[:cut].strip(" ,.;:")
    return trimmed or text.strip(" ,.;:")


def _divides(text: str) -> bool:
    lowered = text.lower()
    return ("/" in text or "÷" in text
            or any(w in lowered for w, s in _WORD_OPERATORS if s == "/"))


def has_arithmetic(text: str) -> bool:
    """Whether a span performs a calculation at all.

    Symbols OR words: "Stage 2 exposure divided by total exposure" is
    arithmetic, and a check that only looked for `/` would call it prose and
    send somebody to the metric library for a metric that does not exist.
    A bare hyphen inside a word ("quarter-on-quarter") is not arithmetic, so
    the symbol test requires whitespace or a digit around a minus sign.
    """
    if not text:
        return False
    if re.search(r"[/*×÷+]", text):
        return True
    if re.search(r"(?:\s|\d|\))\s*[-−]\s*(?:\s|\d|\()", text):
        return True
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(w)}\b", lowered)
               for w, _ in _WORD_OPERATORS)


def _operation_of(text: str) -> str:
    """Which arithmetic the text performs, as a symbol. Never a rewrite."""
    lowered = text.lower()
    if _MINUS_ONE.search(text) and _divides(text):
        return "growth"
    if _divides(text):
        return "/"
    for word, symbol in _WORD_OPERATORS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return symbol
    for symbol in ("*", "×", "+"):
        if symbol in text:
            return "*" if symbol in ("*", "×") else "+"
    if re.search(r"(?:\s|\d|\))\s*[-−]\s*(?:\s|\d|\()", text):
        return "-"
    return ""


def _tidy(side: str) -> str:
    """One side of a ratio, with the punctuation that bracketed it removed.

    Unbalanced parentheses only. `(a + b)` keeps its brackets because they are
    part of the expression; the stray `)` left behind by splitting `(a / b)`
    down the middle does not, because it never belonged to that side.
    """
    text = side.strip().strip(" ,.;:")
    while text.startswith("(") and text.count("(") > text.count(")"):
        text = text[1:].strip()
    while text.endswith(")") and text.count(")") > text.count("("):
        text = text[:-1].strip()
    # "Stage 2 EAD plus Stage 3 EAD and divide by total EAD" splits on "divide
    # by", leaving a numerator ending in the conjunction that introduced it.
    # The conjunction joined the two sides; it is not part of either.
    text = re.sub(r"\s+(?:and|then)\s*$", "", text.strip(), flags=re.IGNORECASE)
    return text.strip(" ,.;:")


def _split_ratio(text: str) -> tuple[str, str]:
    """The two sides of a division, as substrings of `text`.

    The growth tail is removed before splitting, so `(a / b) - 1` yields `a`
    and `b` rather than `a` and `b) - 1` — which was a real defect, and the
    kind that reaches the user as a denominator nobody typed.

    Splits on the FIRST division only. "a / b / c" has no single meaning as a
    ratio and is left to the formula checker to refuse by name.
    """
    body = _MINUS_ONE.sub("", text) if _MINUS_ONE.search(text) else text
    for symbol in ("/", "÷"):
        if symbol in body:
            top, _, bottom = body.partition(symbol)
            return _tidy(top), _tidy(bottom)
    lowered = body.lower()
    for word, symbol in _WORD_OPERATORS:
        if symbol != "/":
            continue
        found = re.search(rf"\b{re.escape(word)}\b", lowered)
        if found:
            return _tidy(body[:found.start()]), _tidy(body[found.end():])
    return "", ""


def _period_sense(text: str) -> str:
    """Whether a side of a ratio names the current period or a previous one."""
    lowered = text.lower()
    if any(w in lowered for w in PREVIOUS_WORDS):
        return "previous"
    if any(w in lowered for w in CURRENT_WORDS):
        return "current"
    return ""


def _unconventional(formula: str, top: str, bottom: str,
                    operation: str) -> Unconventional | None:
    """§5. Whether this growth formula reads backwards, and what the
    conventional one would be.

    Only ever raised when BOTH sides name a period explicitly. A ratio whose
    sides say nothing about periods is not unconventional; it is a ratio, and
    warning about it would train people to dismiss the warning.
    """
    if operation != "growth":
        return None
    if _period_sense(top) != "previous" or _period_sense(bottom) != "current":
        return None
    # The conventional form, built by swapping the person's OWN two spans
    # inside their own formula. Not generated prose: if they choose it, they
    # get their words the other way round, which is what they would have
    # typed. A sentinel is used for the first replacement so that swapping a
    # span whose text also occurs in the other one cannot corrupt it.
    if top not in formula or bottom not in formula:  # pragma: no cover
        return None
    swapped = formula.replace(top, "\x00", 1)
    swapped = swapped.replace(bottom, top, 1)
    swapped = swapped.replace("\x00", bottom, 1)
    return Unconventional(
        because=(
            f"You entered {formula}. That divides the PREVIOUS period by the "
            f"CURRENT one, which is the inverse of the conventional growth "
            f"calculation. Should CreditProbe keep your formula?"),
        conventional=swapped,
        convention_name="Period-on-period growth",
    )


def read_deterministic(said: str) -> FormulaIntake:
    """Everything §4 lists, read without a model.

    Kept complete rather than as a stub, for two reasons: it is the fallback
    when no provider is configured, and it is the thing the model's offsets are
    checked against — a span that does not contain an operator is a span that
    is not a formula, whoever proposed it.
    """
    said = (said or "").strip()
    intake = FormulaIntake(said=said)
    if not said:
        return intake

    body = _LEADING_VERBS.sub("", said, count=1).strip()
    # Find the span in the ORIGINAL, so the returned text is a substring of it.
    at = said.find(body) if body else -1
    if at < 0:
        body, at = said, 0

    candidate = _strip_trailing_instruction(body).strip(" ,.;:")
    # "QoQ exposure change: (Current / Previous) - 1" — the label before the
    # colon describes the metric, the part after it IS the metric. Dropped
    # only when what follows is itself arithmetic, so a colon inside a formula
    # cannot truncate one.
    labelled = _LABELLED.match(candidate)
    if labelled and has_arithmetic(labelled.group("formula")):
        candidate = labelled.group("formula").strip(" ,.;:")

    if not candidate or not has_arithmetic(candidate):
        # No arithmetic anywhere: this names one thing, so it is a request for
        # an existing metric rather than a formula. §4's own boundary.
        intake.notes.append(
            "No arithmetic was found, so this reads as a request for a metric "
            "that already exists rather than as a new formula.")
        return _with_extras(intake, said)

    if not _HAS_WORD.search(candidate) and not re.search(r"\d", candidate):
        return _with_extras(intake, said)

    start = said.find(candidate, at)
    if start < 0:
        start = said.find(candidate)
    if start < 0:  # pragma: no cover - candidate came out of said
        return _with_extras(intake, said)

    intake.formula_text = said[start:start + len(candidate)]
    intake.is_formula = True
    intake.operation = _operation_of(intake.formula_text)
    top, bottom = _split_ratio(intake.formula_text)
    intake.numerator_text, intake.denominator_text = top, bottom
    if intake.operation == "growth" and top and bottom:
        intake.unconventional = _unconventional(
            intake.formula_text, top, bottom, intake.operation)
    return _with_extras(intake, said)


def _with_extras(intake: FormulaIntake, said: str) -> FormulaIntake:
    """The chart, grouping and period the message asked for around the formula."""
    intake.wants_chart = bool(_CHART_WORDS.search(said))
    grouped = _GROUP_BY.search(said)
    if grouped:
        intake.group_by = grouped.group(1).strip().lower().replace(" ", "_")
        intake.wants_chart = True
    window = _PERIOD_HINT.search(said)
    if window:
        intake.period_hint = (f"last {window.group('n')} "
                              f"{window.group('unit').lower()}")
    return intake


# ---------------------------------------------------------------------------
# Pass 1 — faithful normalisation, with a model where one is configured
# ---------------------------------------------------------------------------


def _schema(length: int) -> dict[str, Any]:
    offset = {"type": "integer", "minimum": -1, "maximum": length}
    return {
        "type": "object",
        "properties": {
            "is_formula": {
                "type": "boolean",
                "description": "True only when the message defines a "
                               "calculation with arithmetic in it."},
            "formula_start": offset,
            "formula_end": offset,
            "numerator_start": offset,
            "numerator_end": offset,
            "denominator_start": offset,
            "denominator_end": offset,
            "operation": {
                "type": "string",
                "enum": ["", "/", "*", "+", "-", "growth"],
                "description": "The arithmetic performed. 'growth' for a "
                               "ratio with minus one after it."},
            "wants_chart": {"type": "boolean"},
            "group_by": {
                "type": "string",
                "description": "The field the person asked to cut it by, or "
                               "empty."},
            "period_hint": {
                "type": "string",
                "description": "The period window asked for, e.g. \"last 8 "
                               "quarters\", or empty."},
        },
        "required": ["is_formula", "formula_start", "formula_end", "operation"],
    }


def normalise(said: str, *, model: str = "", effort: str = "",
              budget: Any = None) -> FormulaIntake:
    """Pass 1. What the person typed, located rather than rewritten.

    The deterministic read runs FIRST and is what is returned unless the model
    finds a formula it missed or brackets one more precisely. That ordering is
    deliberate: the common case — somebody typing arithmetic — is answered
    without a model call at all, which is §44's point about not paying for a
    model where nothing needs judgement.
    """
    said = (said or "").strip()[:MAX_FORMULA * 4]
    base = read_deterministic(said)
    if not said:
        return base

    from backend.llm import LLMError, get_provider

    provider = get_provider()
    if not provider.configured:
        base.notes.append("Read without a model: no AI provider is configured.")
        return base

    # A message the deterministic reader already resolved into a bracketed
    # ratio needs nothing further. Spending a call to confirm it is spending.
    if base.is_formula and base.numerator_text and base.denominator_text:
        return base

    if budget is not None:
        from backend.agentic.budgets import MODEL_CALLS

        if not budget.try_spend(MODEL_CALLS):
            base.notes.append(
                "Read without a model: this request's model-call budget is "
                "spent.")
            return base

    try:
        answer = provider.structured(
            system=SYSTEM,
            prompt=_pass1_prompt(said),
            schema=_schema(len(said)),
            tool_name=TOOL_NAME,
            tool_description="Locate the formula in this message. Call this "
                             "exactly once.",
            max_tokens=600, purpose="formula_reading", model=model,
            role="router", effort=effort)
    except (LLMError, Exception) as e:  # noqa: BLE001 - never block the builder
        logger.warning("formula pass 1 failed: %s", e)
        base.notes.append(
            "Read without a model: the live model could not be reached.")
        return base

    return _from_offsets(said, answer, base)


def _pass1_prompt(said: str) -> str:
    numbered = "".join(
        f"{i:>4}: {said[i:i + 60]!r}\n" for i in range(0, len(said), 60))
    return (
        f"MESSAGE ({len(said)} characters):\n{said}\n\n"
        f"THE SAME MESSAGE, WITH THE OFFSET OF EACH LINE'S FIRST CHARACTER:\n"
        f"{numbered}\n"
        "Return the offsets. Do not return any text.")


def _from_offsets(said: str, answer: Any, base: FormulaIntake) -> FormulaIntake:
    """The model's offsets, applied to the person's own string, or the
    deterministic read where they do not hold up."""
    data = answer.data or {}
    if not data.get("is_formula"):
        # The model says this is not a formula. Where the deterministic reader
        # found arithmetic, it is trusted over the model: an operator is not a
        # matter of opinion.
        if base.is_formula:
            return base
        base.understood, base.model = True, answer.model
        return _with_extras(base, said)

    formula = _sliced(said, data.get("formula_start"), data.get("formula_end"))
    if not formula or not has_arithmetic(formula):
        base.notes.append(
            "The model's formula offsets did not bracket any arithmetic, so "
            "the deterministic reading was kept.")
        return base

    top = _sliced(said, data.get("numerator_start"), data.get("numerator_end"))
    bottom = _sliced(said, data.get("denominator_start"),
                     data.get("denominator_end"))
    if top and top not in formula:
        top = ""
    if bottom and bottom not in formula:
        bottom = ""
    if not top or not bottom:
        top, bottom = _split_ratio(formula)

    operation = str(data.get("operation") or "") or _operation_of(formula)
    intake = FormulaIntake(
        said=said, formula_text=formula, is_formula=True,
        numerator_text=top, denominator_text=bottom, operation=operation,
        understood=True, model=answer.model, notes=list(base.notes))
    if operation == "growth" and top and bottom:
        intake.unconventional = _unconventional(formula, top, bottom, operation)
    intake = _with_extras(intake, said)
    if data.get("group_by"):
        intake.group_by = str(data["group_by"]).strip().lower().replace(" ", "_")
        intake.wants_chart = True
    if data.get("period_hint"):
        intake.period_hint = str(data["period_hint"]).strip()
    if data.get("wants_chart"):
        intake.wants_chart = True
    return intake


# ---------------------------------------------------------------------------
# Pass 2 — what the formula is FOR
# ---------------------------------------------------------------------------

INTENT_SYSTEM = """You are naming and describing a metric a credit-risk \
professional has just defined by typing a formula into CreditProbe.

You are given their message and the formula exactly as they typed it. Say what the \
metric should be CALLED, what it is FOR, and what UNIT it is in.

RULES

1. Never restate, correct or reorder their formula. It is given to you so you can \
name what it measures, not so you can improve it. If it looks unconventional, that \
has already been flagged separately — say nothing about it here.
2. The name is what a risk officer would call this on a dashboard: "QoQ Exposure \
Change %", "Stage 2 Ratio", "High-Severity EWS Exposure Share". Short, specific, \
no verbs.
3. `intent` is one sentence: what a senior risk user learns from this number.
4. `unit` is what the RESULT is measured in, which is often not what the inputs \
are. A currency amount over a currency amount is a percent or a ratio, not a \
currency."""


def _intent_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "What this metric is called on a dashboard."},
            "intent": {"type": "string",
                       "description": "One sentence: what it tells a risk officer."},
            "unit": {"type": "string",
                     "enum": ["percent", "ratio", "currency", "count", "days",
                              "score", "index", "number"]},
        },
        "required": ["name", "intent", "unit"],
    }


def _guess_unit(intake: FormulaIntake) -> str:
    if intake.operation in ("/", "growth"):
        return "percent"
    if re.search(r"\b(count|number of|how many)\b", intake.said, re.IGNORECASE):
        return "count"
    return "number"


def _guess_name(intake: FormulaIntake) -> str:
    """A name from the person's own words, for when no model is configured."""
    source = intake.formula_text or intake.said
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]*", source)
    skip = {"the", "a", "an", "of", "by", "and", "divided", "divide", "over",
            "plus", "minus", "times", "per", "share", "take", "add", "show"}
    kept = [w for w in words if w.lower() not in skip][:6]
    if not kept:
        return "New metric"
    return " ".join(w[:1].upper() + w[1:] for w in kept)


def read_intent(intake: FormulaIntake, *, model: str = "", effort: str = "",
                budget: Any = None) -> FormulaIntake:
    """Pass 2. The name, the purpose and the unit — never the formula.

    Mutates and returns the same intake so a caller holds one object through
    both passes; the formula fields are not touched, which a test asserts.
    """
    before = intake.formula_text
    intake.unit_hint = intake.unit_hint or _guess_unit(intake)
    intake.suggested_name = intake.suggested_name or _guess_name(intake)
    if not intake.is_formula:
        return intake

    from backend.llm import LLMError, get_provider

    provider = get_provider()
    if not provider.configured:
        return intake
    if budget is not None:
        from backend.agentic.budgets import MODEL_CALLS

        if not budget.try_spend(MODEL_CALLS):
            return intake

    try:
        answer = provider.structured(
            system=INTENT_SYSTEM,
            prompt=(f"MESSAGE: {intake.said}\n"
                    f"FORMULA AS TYPED: {intake.formula_text}\n"
                    f"NUMERATOR: {intake.numerator_text or '(none)'}\n"
                    f"DENOMINATOR: {intake.denominator_text or '(none)'}\n\n"
                    "Name it."),
            schema=_intent_schema(), tool_name="name_metric",
            tool_description="Name and describe this metric. Call this "
                             "exactly once.",
            max_tokens=400, purpose="formula_intent", model=model,
            role="router", effort=effort)
    except (LLMError, Exception) as e:  # noqa: BLE001
        logger.warning("formula pass 2 failed: %s", e)
        return intake

    data = answer.data or {}
    intake.suggested_name = str(data.get("name") or intake.suggested_name).strip()
    intake.intent = str(data.get("intent") or "").strip()
    intake.unit_hint = str(data.get("unit") or intake.unit_hint).strip()
    intake.model = intake.model or answer.model
    # The one invariant this pass must not break.
    assert intake.formula_text == before, "pass 2 must not touch the formula"
    return intake


def read(said: str, *, model: str = "", effort: str = "",
         budget: Any = None) -> FormulaIntake:
    """Both passes, in order. What a caller normally wants."""
    intake = normalise(said, model=model, effort=effort, budget=budget)
    return read_intent(intake, model=model, effort=effort, budget=budget)


__all__ = [
    "INTAKE_VERSION", "MAX_FORMULA", "CURRENT_WORDS", "PREVIOUS_WORDS",
    "FormulaIntake", "Unconventional",
    "read", "read_deterministic", "normalise", "read_intent",
]
