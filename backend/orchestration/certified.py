"""
Running a certified methodology, when that is genuinely what was asked for.

This is NOT the fallback that was removed
-----------------------------------------
The deleted behaviour was: *the composer could not read the question, so run
whichever registered analysis scored highest on its wording.* That produced a
sector-concentration reading of 100% for "show me the five largest Real Estate
customers" — a certified, reconciled, completely wrong answer.

This is the opposite direction. A bank's certified methodologies are the reason
the platform is trusted: a rating transition matrix computed by a first
principles group-by is not the same artefact as the bank's approved transition
matrix, even when the numbers agree. So when somebody asks for the approved
methodology **by name**, they get the approved methodology.

The distinction is precision, and it is enforced structurally:

  * this runs BEFORE the composer, not after it — it is a route, not a rescue;
  * it fires only on a near-verbatim match against a contract's own name or one
    of its declared trigger questions;
  * a failure here does NOT fall through to a different certified analysis. It
    falls through to the composer, which will either compose the analysis or ask.

If the match is not obvious to a reader of the question, it does not fire.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import capability as cap

logger = logging.getLogger(__name__)

#: How much of a contract's name or trigger question must be present in the
#: request before its methodology is used. High on purpose: at 0.6 this starts
#: catching questions that merely share vocabulary with a methodology, which is
#: precisely the failure mode being designed out.
MIN_OVERLAP = 0.85

#: How much of the REQUEST the methodology must account for. Containment alone
#: is not enough: "what is our total exposure?" is contained in "what is total
#: exposure by region in the latest quarter?", and matching on that ran a
#: concentration analysis for a question about regions. A methodology that
#: explains only half the words in the request is not the methodology asked for.
MIN_PRECISION = 0.6

#: Words that carry no signal about which methodology is wanted.
_NOISE = frozenset({
    "the", "a", "an", "of", "for", "to", "in", "on", "at", "by", "and", "or",
    "is", "are", "was", "were", "be", "been", "our", "my", "me", "us", "we",
    "show", "give", "display", "what", "which", "how", "please", "can", "you",
    "creditprobe", "ipm", "current", "latest", "now", "run", "calculate",
    "produce", "get", "see", "look", "want", "need", "like", "this", "that",
})


@dataclass
class Match:
    """A certified methodology the request named."""

    analysis_id: str
    name: str
    overlap: float
    matched: str
    #: What the contract says it is for, quoted on the answer.
    when_to_use: str = ""
    period_requirement: str = "point_in_time"
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def because(self) -> str:
        return (f"The request names the certified methodology “{self.name}”, so "
                "CreditProbe ran the bank's approved analysis rather than "
                "composing an equivalent one.")

    def to_dict(self) -> dict[str, Any]:
        return {"analysis_id": self.analysis_id, "name": self.name,
                "overlap": round(self.overlap, 3), "matched": self.matched,
                "when_to_use": self.when_to_use, "because": self.because}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _NOISE and len(w) > 1}


def _overlap(request: set[str], target: set[str]) -> float:
    """How much of the TARGET the request contains.

    Deliberately asymmetric. "Show me the rating transition matrix for the SME
    book" contains every word of the methodology's name plus some of its own,
    and should match; a request containing only half the name should not, however
    short the request is.
    """
    if not target:
        return 0.0
    return len(request & target) / len(target)


def match(question: str, reading: cap.Reading) -> Match | None:
    """The certified methodology this request named, if it named one.

    Returns None far more often than not, and that is the design. Everything it
    declines goes to the composer, which is the general path.
    """
    if reading.intent not in cap.COMPUTES:
        return None

    try:
        from backend.engine.registry import get_registry

        registry = get_registry()
        analyses = list(registry.all())
    except Exception as e:  # noqa: BLE001 - no registry means no certified route
        logger.info("Could not read the analysis registry: %s", e)
        return None

    asked = _words(question)
    if not asked:
        return None

    named = {m.strip().lower() for m in reading.candidate_methods}
    best: Match | None = None

    for entry in analyses:
        contract = entry.contract
        candidates: list[tuple[str, str]] = [("name", contract.name)]
        candidates += [("trigger question", q)
                       for q in (contract.trigger_questions or [])]

        for kind, text in candidates:
            target = _words(text)
            score = _overlap(asked, target)
            precision = len(asked & target) / len(asked) if asked else 0.0
            if precision < MIN_PRECISION:
                continue
            # A model that named the analysis outright is evidence too, but it
            # is not sufficient on its own: the deterministic overlap still has
            # to agree, or a hallucinated id would select a methodology.
            if entry.id.lower() in named and score >= 0.6:
                score = max(score, MIN_OVERLAP)
            if score < MIN_OVERLAP:
                continue
            if best is None or score > best.overlap:
                best = Match(
                    analysis_id=entry.id, name=contract.name, overlap=score,
                    matched=f"the certified analysis's {kind}: “{text}”",
                    when_to_use=contract.when_to_use or "",
                    period_requirement=str(
                        getattr(contract, "period_requirement", "")
                        or "point_in_time"),
                )

    if best is not None:
        logger.info("Request %r names the certified analysis %s (overlap %.2f).",
                    question[:70], best.analysis_id, best.overlap)
    return best


def parameters(found: Match, reading: cap.Reading, *,
               period: tuple[str, str] | None,
               periods: list[str]) -> dict[str, Any]:
    """The certified analysis's parameters, from the reading.

    Only the parameters the contract declares, resolved from what the request
    actually said. Nothing is invented: a contract's own defaults are better
    than a guess assembled here.
    """
    params: dict[str, Any] = {}
    named = [p for p in reading.periods if p in periods]

    if str(found.period_requirement) == "two_period":
        if period:
            params["from_period"], params["to_period"] = period
        elif len(named) >= 2:
            params["from_period"], params["to_period"] = named[0], named[-1]
    elif named:
        params["period"] = named[-1]
    elif period:
        params["period"] = period[1]

    for entity in reading.entities:
        kind, value = entity.get("kind"), entity.get("value")
        if kind in {"sector", "region", "segment", "product_type"} and value:
            params[str(kind)] = str(value)
    return params


__all__ = ["MIN_OVERLAP", "MIN_PRECISION", "Match", "match", "parameters"]
