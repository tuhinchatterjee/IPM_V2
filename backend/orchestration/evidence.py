"""
Everything a written answer is allowed to say, as a list of facts.

Why a package rather than a check
----------------------------------
The old check asked one question: is every NUMBER in this prose somewhere in
the result? That catches an invented figure, which is the loudest failure and
not the most common one. These all pass a numeric check and are all wrong:

* a borrower named in the prose who is not in the result;
* a condition asserted — "all of them are Stage 3" — that the result
  contradicts;
* a period stated that the analysis did not read;
* a cause asserted — "because the sector is distressed" — that nothing
  established.

So the answer is checked against a **package**: every figure, entity, period
and condition the result actually supports, each with an id, a source and a
unit. Prose is grounded when everything it asserts appears in the package, and
it is discarded when it is not.

Discarded, not annotated
------------------------
An interpretation with one invented sentence, shown under a warning, is still
an interpretation somebody will paste into a credit paper. Where the live prose
cannot be grounded, CreditProbe shows the deterministic summary instead and
says the written interpretation was withheld.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: How many identities the package carries. Enough to check any sentence a
#: reader would write about a result; a prose paragraph naming more than this
#: is not prose anybody reads.
MAX_ENTITIES = 200

#: Figures are quoted rounded. "18,475" is the same fact as 18475.294.
#:
#: The range runs to six because a figure sitting against a covenant boundary
#: is written with as many decimals as it takes to stay on the right side of
#: it — see `figures._respecting`. A grounding check that rejected 14.9996%
#: because it only knew about 15.0 would discard the one sentence in the answer
#: that was being careful.
ROUNDINGS = (0, 1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class Fact:
    """One thing the result establishes, and where it came from.

    Every field answers a question a reviewer asks about a sentence in a credit
    paper. What figure. Of what. In what unit. At what date. About whom. From
    which part of which result. Under what conditions. Ranked how. And how far
    it may be relied on. A fact that cannot answer all nine is a number, and a
    number with no provenance is what this package exists to replace.
    """

    id: str
    kind: str          # figure | entity | period | condition | column
    description: str
    value: Any = None
    #: The governed metric this is a value OF, where it is a value of one.
    metric: str = ""
    unit: str = ""
    period: str = ""
    entity: str = ""
    #: Where in the result this came from: "row 3.total_ecl", "summary.change".
    source: str = ""
    #: The plan conditions that were true of the rows this came from.
    conditions: tuple[str, ...] = ()
    #: What the result was ordered by, where it was ordered.
    ranking_basis: str = ""
    #: computed | derived | asserted. A figure the runtime returned, a figure
    #: CreditProbe worked out from those, or something the plan promised.
    confidence: str = "computed"
    #: Whether the invariants that cover this fact held.
    validated: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind,
                "description": self.description, "value": self.value,
                "metric": self.metric, "unit": self.unit,
                "period": self.period, "entity": self.entity,
                "source": self.source, "conditions": list(self.conditions),
                "ranking_basis": self.ranking_basis,
                "confidence": self.confidence, "validated": self.validated}


@dataclass
class Package:
    """Everything a written answer may assert about one result."""

    facts: list[Fact] = field(default_factory=list)
    #: Normalised figures, for the numeric check.
    figures: set[str] = field(default_factory=set)
    #: Lower-cased identities and names present in the result.
    entities: set[str] = field(default_factory=set)
    #: Periods the analysis actually read.
    periods: set[str] = field(default_factory=set)
    #: Conditions the plan applied, in the words the answer may use.
    conditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"facts": [f.to_dict() for f in self.facts[:60]],
                "fact_count": len(self.facts),
                "periods": sorted(self.periods),
                "conditions": list(self.conditions),
                "entity_count": len(self.entities)}


@dataclass
class Grounding:
    """Whether a piece of prose is supported by the package."""

    ok: bool = True
    ungrounded_figures: list[str] = field(default_factory=list)
    unknown_entities: list[str] = field(default_factory=list)
    wrong_periods: list[str] = field(default_factory=list)
    causal_claims: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        out: list[str] = []
        if self.ungrounded_figures:
            out.append("figures the result does not contain: "
                       + ", ".join(self.ungrounded_figures[:4]))
        if self.unknown_entities:
            out.append("names that are not in the result: "
                       + ", ".join(self.unknown_entities[:4]))
        if self.wrong_periods:
            out.append("periods the analysis did not read: "
                       + ", ".join(self.wrong_periods[:4]))
        if self.causal_claims:
            out.append("a cause nothing established: "
                       + "; ".join(self.causal_claims[:2]))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": self.problems,
                "ungrounded_figures": list(self.ungrounded_figures),
                "unknown_entities": list(self.unknown_entities),
                "wrong_periods": list(self.wrong_periods),
                "causal_claims": list(self.causal_claims)}


# ---------------------------------------------------------------------------
# Building the package
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_PERIOD = re.compile(r"\bQ[1-4]\s*\d{4}\b|\b(?:19|20)\d{2}\b")
#: A borrower name, including the numeric suffix the demo book uses. Without
#: the suffix "Ghat Holding 1771" is extracted as "Ghat Holding", which is not
#: in the result under that name — and a grounding check that rejects the
#: borrowers actually in the table is worse than no check at all.
_NAME = re.compile(
    r"\b(?:[A-Z][a-z0-9&'-]+)(?:\s+[A-Z][a-z0-9&'-]+){0,3}(?:\s+\d{2,6})?\b")

#: Words that assert a cause. CreditProbe computes what moved; it does not
#: establish why, and prose that says why is prose nobody can check.
_CAUSAL = re.compile(
    r"\bbecause\b|\bdue to\b|\bcaused by\b|\bdriven by\b|\bas a result of\b"
    r"|\bleads? to\b|\bresulted? in\b|\bexplains?\b|\battributable to\b"
    r"|\bstems? from\b|\bowing to\b|\btriggered by\b", re.I)

#: Openings that are ordinary English rather than a borrower's name.
_NOT_A_NAME = frozenset({
    "the", "this", "that", "these", "those", "a", "an", "and", "but", "or",
    "creditprobe", "ifrs", "stage", "real", "estate", "q1", "q2", "q3", "q4",
    "together", "each", "every", "both", "all", "none", "no", "one", "two",
    "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "exposure", "expected", "credit", "loss", "days", "past", "due", "total",
    "ead", "ecl", "pd", "lgd", "dpd", "dscr", "it", "they", "their", "its",
    "between", "across", "at", "in", "of", "from", "to", "by", "over",
})


def build(runtime: Any, build_plan: Any = None,
          extra: dict[str, Any] | None = None) -> Package:
    """Everything this result establishes, as facts a sentence may quote."""
    package = Package()

    def figure(value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            number = float(value)
            for candidate in (number, abs(number)):
                package.figures.add(_normal(candidate))
                for places in ROUNDINGS:
                    package.figures.add(_normal(round(candidate, places)))
        elif isinstance(value, str):
            for found in _NUMBER.findall(value):
                package.figures.add(_normal(found.replace(",", "")))

    # Everything every fact from this result shares: the conditions the plan
    # applied, what it was ordered by, and whether the checks held. Carried on
    # each fact rather than alongside them, so a fact quoted on its own still
    # says what it was true UNDER.
    context = _context(build_plan)

    index = 0

    def record(kind: str, description: str, **kwargs: Any) -> None:
        nonlocal index
        index += 1
        package.facts.append(Fact(id=f"f{index}", kind=kind,
                                  description=description,
                                  **{**context, **kwargs}))

    for key, value in (extra or {}).items():
        figure(value)
        record("figure", f"{key} = {value}", value=value, source=f"values.{key}")

    if runtime is not None:
        figure(getattr(runtime, "row_count", 0))
        record("figure",
               f"the result has {getattr(runtime, 'row_count', 0)} rows",
               value=getattr(runtime, "row_count", 0), source="row_count")

        for key, value in (getattr(runtime, "summary", None) or {}).items():
            figure(value)
            record("figure", f"{key} = {value}", value=value, metric=key,
                   source=f"summary.{key}",
                   # A summary figure CreditProbe worked out from the rows
                   # rather than one the query returned per row.
                   confidence="derived")

        for position, row in enumerate(getattr(runtime, "rows", []) or []):
            if not isinstance(row, dict):
                continue
            for value in row.values():
                figure(value)
                if isinstance(value, str) and value.strip():
                    package.entities.add(value.strip().lower())
                    if _PERIOD.fullmatch(value.strip()):
                        package.periods.add(value.strip())
            if position < MAX_ENTITIES:
                identity = _identity(row)
                if identity:
                    record("entity", f"{identity} is in the result",
                           entity=identity, source=f"row[{position}]",
                           period=str(row.get("period") or ""))

    if build_plan is not None:
        for name in ("period", "opening", "closing"):
            value = str(getattr(build_plan, name, "") or "")
            if value:
                package.periods.add(value)
                record("period", f"the analysis read {value}", period=value,
                       source=f"plan.{name}")
        for condition in (getattr(build_plan, "conditions", None) or []):
            described = _describe(condition)
            if described:
                package.conditions.append(described)
                record("condition", described, source="plan.conditions")
        for field_name, value in (getattr(build_plan, "filters", None) or []):
            package.entities.add(str(value).strip().lower())
            record("condition", f"restricted to {field_name} = {value}",
                   source="plan.filters")

    return package


def _context(build_plan: Any) -> dict[str, Any]:
    """What every fact from this result is true under."""
    conditions: list[str] = []
    for condition in (getattr(build_plan, "conditions", None) or []):
        described = _describe(condition)
        if described:
            conditions.append(described)
    for field_name, value in (getattr(build_plan, "filters", None) or []):
        conditions.append(f"{str(field_name).replace('_', ' ')} = {value}")

    basis = ""
    matches = list(getattr(build_plan, "matches", None) or [])
    if str(getattr(build_plan, "shape", "") or "") == "ranking" and matches:
        basis = str(getattr(matches[0].concept, "label", "") or "")

    return {"conditions": tuple(conditions), "ranking_basis": basis}


def _identity(row: dict[str, Any]) -> str:
    for key in ("borrower_name", "customer_id", "account_id", "sector",
                "region", "segment"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _describe(condition: Any) -> str:
    described = getattr(condition, "describe", None)
    if callable(described):
        try:
            return str(described())
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _normal(value: Any) -> str:
    try:
        return f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Checking prose against it
# ---------------------------------------------------------------------------


def check(text: str, package: Package, *, allow_causal: bool = False) -> Grounding:
    """Whether this sentence says only what the result supports."""
    grounding = Grounding()
    if not text or not text.strip():
        return grounding

    # Periods are checked as periods. Scanning them for numbers first reports
    # the 4 in "Q4 2019" as an invented figure, which buries the real finding
    # — that the analysis never read Q4 2019 — under a nonsense one.
    without_periods = _PERIOD.sub(" ", text)

    for raw in _NUMBER.findall(without_periods):
        cleaned = raw.replace(",", "")
        if _normal(cleaned) in package.figures:
            continue
        # A year or quarter is checked as a period, not as a figure.
        if _PERIOD.search(raw) or len(cleaned.strip("-")) == 4 and cleaned.isdigit():
            continue
        grounding.ungrounded_figures.append(raw)

    for period in _PERIOD.findall(text):
        normalised = " ".join(period.split())
        if package.periods and normalised not in package.periods:
            grounding.wrong_periods.append(normalised)

    # Names are read from the text with periods removed, so "Q4 2019" is
    # reported once — as a period the analysis did not read — rather than
    # twice, under two headings, one of which is nonsense.
    for name in _NAME.findall(without_periods):
        cleaned = name.strip()
        words = cleaned.lower().split()
        if not words or all(w in _NOT_A_NAME for w in words):
            continue
        if len(words) == 1 and text.strip().startswith(cleaned):
            # A capitalised first word is usually just the start of a sentence.
            continue
        lowered = cleaned.lower()
        if lowered in package.entities:
            continue
        # A name the result carries in a longer form. "Ghat Holding" is the
        # borrower "Ghat Holding 1771", and reporting it as unknown would
        # discard a correct sentence about a row on the screen.
        if any(known.startswith(lowered) or lowered.startswith(known)
               for known in package.entities):
            continue
        # A name only counts as unknown when the package HAS names to check it
        # against. A portfolio total names nobody, and flagging every
        # capitalised word in its explanation would discard every answer.
        if package.entities and _looks_like_a_name(cleaned):
            grounding.unknown_entities.append(cleaned)

    if not allow_causal:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if _CAUSAL.search(sentence):
                grounding.causal_claims.append(sentence.strip()[:120])

    grounding.ok = not (grounding.ungrounded_figures
                        or grounding.unknown_entities
                        or grounding.wrong_periods
                        or grounding.causal_claims)
    return grounding


def _looks_like_a_name(phrase: str) -> bool:
    """Whether this is plausibly a borrower rather than a capitalised noun.

    Deliberately conservative: two capitalised words, or one with a digit in
    it. A single ordinary capitalised word is much more likely to be the start
    of a clause than a counterparty, and discarding an answer over one is the
    failure mode that makes a grounding check unusable.
    """
    words = phrase.split()
    return len(words) >= 2 or any(c.isdigit() for c in phrase)


def withheld(grounding: Grounding) -> str:
    """What to tell the user when the written interpretation was discarded."""
    return (
        "CreditProbe wrote an interpretation of this result and then withheld "
        "it, because it asserted "
        + "; ".join(grounding.problems)
        + ". The figures below are unaffected — they were computed by the "
          "governed runtime — and the summary beside them is assembled from "
          "the result rather than written.")


__all__ = ["MAX_ENTITIES", "Fact", "Grounding", "Package", "build", "check",
           "withheld"]
