"""
The governed semantic reader, used to check the model rather than replace it.

The change in role
------------------
The deterministic reader used to BE the product's understanding, and it was the
wrong tool for that: it cannot follow unusual phrasing, and asking it to was how
six questions in a row came back confidently wrong.

But it is very good at one narrow thing — deciding whether a sentence is asking
*about the data* or *for a figure computed from the data* — because that
distinction is carried by the shape of the sentence rather than by credit
vocabulary. "What data do you have about borrower ratings?" contains no
numerical operation, and no amount of context makes it a request for a number.

So it stays, one level up, as a guardrail:

    live reading   →   does the governed semantic reader agree?
                          yes  →  proceed
                          no   →  one repair call, saying what looks wrong
                                     agrees now  →  proceed
                                     still not   →  use the SAFE reading
                                                    and record the rejection

What it must never do
---------------------
Reach for a registered analysis. A rejected model reading falls back to the
*deterministic reading of the same question*, which then goes through exactly
the same planner, validator and runtime. It does not fall back to a different
question that happens to have a certified answer — that substitution is the
defect this release removes, and re-introducing it here under the word
"guardrail" would be the same bug wearing a better name.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import capability as cap

logger = logging.getLogger(__name__)

#: How sure the deterministic reader must be before it is allowed to contradict
#: the model. Below this it has an opinion, not a finding.
STRONG = 0.75

#: Verdict outcomes.
AGREED = "agreed"
REPAIRED = "repaired"
REJECTED = "rejected"
UNCHECKED = "unchecked"

#: What answers each capability. A disagreement inside a family — DATA_DISCOVERY
#: against DATA_DICTIONARY — is a nuance and is left to the model. A
#: disagreement ACROSS families changes which subsystem answers, and that is
#: what is worth stopping.
_FAMILY: dict[str, str] = {
    **{c: "data" for c in cap.FROM_DATA_BUILDER},
    **{c: "method" for c in cap.FROM_STUDIO},
    cap.Capability.ANALYSIS: "analysis",
    cap.Capability.PROJECT_ACTION: "action",
    cap.Capability.INVESTIGATION_ACTION: "action",
    cap.Capability.ANALYSIS_ACTION: "action",
    cap.Capability.CLARIFICATION: "clarification",
}

_FAMILY_LABEL = {
    "data": "a question about the governed data itself",
    "method": "a question about an analytical method",
    "analysis": "a request to compute a figure",
    "action": "a request to change a workspace object",
    "clarification": "a request CreditProbe cannot act on as it stands",
}


def family(intent: str) -> str:
    return _FAMILY.get(intent, "analysis")


@dataclass
class Verdict:
    """What the guardrail made of the live reading.

    Recorded on the Trace whatever the outcome, including AGREED: "the model and
    the governed semantic reader independently read this the same way" is
    genuine evidence about an answer, and hiding it when things go well would
    make its appearance a signal that something is wrong.
    """

    outcome: str = UNCHECKED
    model_intent: str = ""
    safe_intent: str = ""
    safe_confidence: float = 0.0
    safe_reasoning: str = ""
    conflict: str = ""
    repair_attempted: bool = False
    repaired_intent: str = ""
    note: str = ""
    #: Names the model produced that the catalogue does not carry.
    dropped: list[str] = field(default_factory=list)

    @property
    def agreed(self) -> bool:
        return self.outcome in (AGREED, UNCHECKED)

    @property
    def rejected(self) -> bool:
        return self.outcome == REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "model_intent": self.model_intent,
            "safe_intent": self.safe_intent,
            "safe_confidence": round(self.safe_confidence, 3),
            "safe_reasoning": self.safe_reasoning,
            "conflict": self.conflict,
            "repair_attempted": self.repair_attempted,
            "repaired_intent": self.repaired_intent,
            "note": self.note,
            "dropped": list(self.dropped),
            "label": {
                AGREED: "Governed semantic guardrail agreed",
                REPAIRED: "Live reading repaired by the governed semantic guardrail",
                REJECTED: "LIVE LLM READING REJECTED BY GOVERNED SEMANTIC GUARDRAIL",
                UNCHECKED: "No live reading to check",
            }.get(self.outcome, self.outcome),
        }


def check(question: str, reading: cap.Reading) -> Verdict:
    """Whether the governed semantic reader contradicts this live reading.

    Only cross-family disagreement counts, and only when the deterministic
    reader is confident. Everything else is left alone: a guardrail that fires
    on nuance would put the deterministic reader back in charge, which is the
    arrangement being dismantled.
    """
    safe_intent, safe_confidence, why = cap.recognise(question)
    verdict = Verdict(outcome=AGREED, model_intent=reading.intent,
                      safe_intent=safe_intent, safe_confidence=safe_confidence,
                      safe_reasoning=why)

    if reading.source != "llm":
        verdict.outcome = UNCHECKED
        return verdict

    if family(reading.intent) == family(safe_intent):
        verdict.note = ("The model and the governed semantic reader read this "
                        "the same way.")
        return verdict

    if safe_confidence < STRONG:
        verdict.note = (
            "The governed semantic reader read this differently but was not "
            f"confident ({safe_confidence:.2f}), so the live reading stands.")
        return verdict

    verdict.conflict = (
        f"The model read this as {_FAMILY_LABEL[family(reading.intent)]} "
        f"({reading.intent}). The governed semantic reader reads it as "
        f"{_FAMILY_LABEL[family(safe_intent)]} ({safe_intent}) with confidence "
        f"{safe_confidence:.2f}: {why}")
    verdict.outcome = REJECTED  # provisional; repair may rescue it
    return verdict


def repair_note(question: str, reading: cap.Reading,
                verdict: Verdict) -> str:
    """The one instruction the repair call is given.

    States the conflict and the evidence, and asks for a re-read. It does not
    tell the model which answer to give: an instruction to "return
    DATA_DISCOVERY" would make the repair call a formality and would hide a
    genuine disagreement where the deterministic reader is the one that is
    wrong.
    """
    wanted = _FAMILY_LABEL[family(verdict.safe_intent)]
    return (
        "RE-EVALUATE. Your previous reading of this request conflicts with "
        "CreditProbe's governed semantic reader.\n\n"
        f"  request:        {question}\n"
        f"  you read it as: {reading.intent} — {_FAMILY_LABEL[family(reading.intent)]}\n"
        f"  governed reader: {verdict.safe_intent} — {wanted} "
        f"(confidence {verdict.safe_confidence:.2f})\n"
        f"  because:        {verdict.safe_reasoning}\n\n"
        "Read the request again against the capabilities available to you. If "
        "the request names no numerical operation over the book, it is not an "
        "ANALYSIS however many credit terms it contains. If it genuinely does "
        "require a figure computed from governed data, say so again and "
        "explain why in `reasoning` — you are not being told you are wrong, "
        "you are being asked to check."
    )


def settle(question: str, reading: cap.Reading, verdict: Verdict, *,
           repaired: cap.Reading | None) -> tuple[cap.Reading, Verdict]:
    """The reading to act on, after a repair call has been made or skipped.

    When the repair still conflicts, the SAFE reading is used — but built from
    the deterministic reader over the same question, so the request the user
    actually asked is what gets planned.
    """
    if repaired is not None:
        verdict.repair_attempted = True
        verdict.repaired_intent = repaired.intent
        if family(repaired.intent) == family(verdict.safe_intent):
            verdict.outcome = REPAIRED
            verdict.note = (
                "The live reading conflicted with the governed semantic "
                "reader; a single re-read resolved it.")
            return repaired, verdict
        # Repaired into a third reading, or held its ground. Either way the
        # conflict stands.
        reading = repaired

    verdict.outcome = REJECTED
    verdict.note = (
        "The live reading was rejected: it would have sent this request to the "
        "wrong subsystem. CreditProbe used its governed semantic reading of the "
        "same question instead — it did NOT substitute a different analysis.")
    logger.warning("Guardrail rejected a live reading of %r: %s",
                   question[:80], verdict.conflict)
    return _safe_reading(question, reading, verdict), verdict


def _safe_reading(question: str, reading: cap.Reading,
                  verdict: Verdict) -> cap.Reading:
    """The deterministic reading, keeping what the model got right.

    Concepts, entities and periods the model resolved are kept: they were
    sanitised against the catalogue and are usually correct even when the
    routing was not. Only the routing decision is overridden.
    """
    return dataclasses.replace(
        reading,
        intent=verdict.safe_intent,
        computation_required=verdict.safe_intent in cap.COMPUTES,
        confidence=verdict.safe_confidence,
        source="guardrail",
        reasoning=(f"{verdict.safe_reasoning} (The live model read this as "
                   f"{verdict.model_intent}; the governed semantic guardrail "
                   "overruled that.)"),
    )


__all__ = ["AGREED", "REJECTED", "REPAIRED", "STRONG", "UNCHECKED", "Verdict",
           "check", "family", "repair_note", "settle"]
