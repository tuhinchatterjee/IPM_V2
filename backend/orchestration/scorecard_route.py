"""
Scorecard-validation questions, asked in the Cockpit.

A Head of Retail Risk does not change modules to ask whether a scorecard is
holding up. They ask where they are. And the Cockpit answered:

    "How is our personal-finance application scorecard performing?"
        -> "621.9 points of application score in Personal Finance at 2026-08."

which is the average origination score of the book — a true number about a
different question, in the place a reader is least likely to check it. Then:

    "What's the Gini?"
        -> "CreditProbe could not find Gini in the published data ... a
            borrower it has never been given cannot be looked up."

and every turn after that fell into the credit-concern ranking, so eleven
consecutive scorecard questions were answered with the same twenty-five
customers.

None of this needed a new engine. The validation runner already computes
discrimination, calibration, stability and drift for all eight retail
scorecards, over the governed population, with its own limits and its own
evidence-sufficiency rules — it was simply never reachable from the Cockpit's
composer. This module is the route, and nothing else: it decides whether a
sentence is a validation question, decides which scorecard it is about, and
hands it to that runner. It computes no figure of its own.

Deliberately narrow. A question that names no validation concept is not
routed, so "what is the average application score by product" stays with the
planner, which answers it better.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Concepts that belong to model validation rather than to the book. Each one
#: is a term the validation runner has a test for; a sentence carrying none of
#: them is not a validation question however much it mentions scores.
_VALIDATION = re.compile(
    r"\bgini\b|\bauc\b|\broc\b|\bk-?s\b|\bkolmogorov\b"
    r"|\bdiscriminat\w*\b|\bcalibrat\w*\b|\bmis-?calibrat\w*\b"
    r"|\bpsi\b|\bpopulation stabilit\w*\b|\bstabilit\w*\b|\bdrift\w*\b"
    r"|\bbrier\b|\bo/e\b|\bobserved (?:vs|versus|against) (?:expected|predicted)\b"
    r"|\bscorecard\w*\b|\bmodel performance\b|\bback-?test\w*\b"
    r"|\bwoe\b|\bweight of evidence\b|\binformation value\b|\bcharacteristic\w*\b",
    re.IGNORECASE)

#: Words that say the sentence is about the SCORECARD even without a metric —
#: "how is our personal-finance application scorecard performing?"
_ABOUT_A_SCORECARD = re.compile(
    r"\bscorecard\w*\b|\bapplication (?:model|score)card\b"
    r"|\bbehaviour(?:al)? (?:model|score)card\b", re.IGNORECASE)

#: The product each scorecard is for, in the words a reader writes.
_PRODUCTS: tuple[tuple[str, str], ...] = (
    (r"\bcredit\s*cards?\b|\bcards?\b", "credit_card"),
    (r"\bpersonal\s*(?:finance|loans?)\b|\bpersonal\b|\bpf\b", "personal_loan"),
    (r"\bauto\s*(?:finance|loans?)\b|\bauto\b|\bcar\s*loans?\b|\bvehicle\b", "auto_loan"),
    (r"\bhome\s*(?:finance|loans?)\b|\bmortgages?\b|\bhousing\b", "home_loan"),
)

_APPLICATION = re.compile(r"\bapplication\b|\borigination\b|\bapp\b|\bat\s*origination\b",
                          re.IGNORECASE)
_BEHAVIOURAL = re.compile(r"\bbehaviour\w*\b|\bbehavior\w*\b|\bbeh\b", re.IGNORECASE)


@dataclass(frozen=True)
class Routed:
    """A validation question, and the scorecard it is about."""

    question: str
    model_id: str
    #: Why this scorecard and not another — shown, so a reader can disagree.
    because: str = ""
    #: Set when the sentence is plainly a validation question and no scorecard
    #: can be resolved. The caller asks rather than picking one.
    ask: str = ""
    models: tuple[str, ...] = field(default_factory=tuple)


def _models() -> list[Any]:
    from backend.scorecard.validation import models as registry

    return list(registry.all_models())


def _product_in(text: str) -> str:
    for pattern, code in _PRODUCTS:
        if re.search(pattern, text, re.IGNORECASE):
            return code
    return ""


def _kind_in(text: str) -> str:
    # Behavioural first: "behavioural application score" is not a phrase, and
    # "application" appears inside sentences about behavioural models far more
    # often than the other way round.
    if _BEHAVIOURAL.search(text):
        return "beh"
    if _APPLICATION.search(text):
        return "app"
    return ""


def is_a_validation_question(text: str) -> bool:
    """Whether this sentence belongs to the validation runner."""
    said = str(text or "")
    return bool(_VALIDATION.search(said) or _ABOUT_A_SCORECARD.search(said))


def read(question: str, *, carried_model: str = "") -> Routed | None:
    """Route a validation question to one scorecard, or ask which.

    Returns None where the sentence is not a validation question at all, which
    is the common case and leaves the planner exactly as it was.
    """
    said = " ".join(str(question or "").split())
    if not said or not is_a_validation_question(said):
        return None
    try:
        catalogue = _models()
    except Exception as e:  # noqa: BLE001 - no registry, no route
        logger.warning("The scorecard registry could not be read: %s", e)
        return None
    if not catalogue:
        return None
    known = {m.model_id for m in catalogue}

    product, kind = _product_in(said), _kind_in(said)
    if product and kind:
        model_id = f"retail_{kind}_{product}"
        if model_id in known:
            return Routed(said, model_id,
                          because=("the question names the product and the "
                                   "kind of scorecard"))
    if product and not kind:
        # One product, two scorecards. The application one is the default
        # ONLY when the sentence also says something origination-shaped;
        # otherwise the reader is asked, because "how is the credit card
        # scorecard performing" has two different true answers.
        options = [m.model_id for m in catalogue if m.model_id.endswith(product)]
        if len(options) == 1:
            return Routed(said, options[0], because="one scorecard for that product")
        return Routed(said, "", ask=_which_of(options, catalogue),
                      models=tuple(options))
    if carried_model and carried_model in known:
        return Routed(said, carried_model,
                      because="the scorecard this conversation is about")
    if kind and not product:
        options = [m.model_id for m in catalogue
                   if m.model_id.startswith(f"retail_{kind}_")]
        return Routed(said, "", ask=_which_of(options, catalogue),
                      models=tuple(options))
    return Routed(said, "", ask=_which_of([m.model_id for m in catalogue], catalogue),
                  models=tuple(m.model_id for m in catalogue))


def _which_of(model_ids: list[str], catalogue: list[Any]) -> str:
    names = {m.model_id: m.name for m in catalogue}
    listed = [names.get(i, i) for i in model_ids]
    if not listed:
        return "Which scorecard?"
    if len(listed) == 1:
        return f"Do you mean the {listed[0]}?"
    return ("Which scorecard? This deployment validates "
            + ", ".join(listed[:-1]) + " and " + listed[-1] + ".")


#: "How is it performing?", "is it holding up?", "can we still use it?" — a
#: question about the scorecard as a whole rather than about one statistic.
#: The conversational reader has no single tool for it and declines; the
#: findings engine answers exactly it, and was unreachable from here.
_OVERALL = re.compile(
    r"\bperform\w*\b|\bholding up\b|\bhow is (?:it|the|our)\b|\bhow are\b"
    r"|\bstill (?:fit|valid|usable|reliable)\b|\bfit for (?:use|purpose)\b"
    r"|\bchalleng\w*\b|\bcontinued use\b|\bany (?:issues|problems|concerns)\b"
    r"|\bwhat(?:'s| is) wrong\b|\bhow (?:good|bad|healthy)\b",
    re.IGNORECASE)


def asks_about_the_whole_scorecard(text: str) -> bool:
    """Whether the sentence asks how the scorecard is doing, not for one figure."""
    return bool(_OVERALL.search(str(text or "")))


def ask(question: str, model_id: str) -> dict[str, Any]:
    """The validation runner's own answer, unchanged."""
    from backend.scorecard.validation import conversation as reader

    return reader.answer(question, model_id=model_id)


def findings(model_id: str) -> dict[str, Any]:
    """Every applicable test, assessed, with the shortlist to act on first."""
    from backend.scorecard.validation import agent

    return agent.invoke("scv_findings", model_id=model_id)


__all__ = ["Routed", "ask", "asks_about_the_whole_scorecard", "findings",
           "is_a_validation_question", "read"]
