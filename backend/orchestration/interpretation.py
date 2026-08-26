"""
The model reads the RESULT. It never reads the data, and it never does the sums.

Where this sits
---------------
Last. Everything numerical has already happened: the plan was validated against
the governed catalogue, compiled to parameterised SQL, executed, and reconciled.
What arrives here is a table of figures that are already true.

So the model's job is the one thing a deterministic narrative builder does
badly — saying what the numbers *mean* to a credit officer, in their language,
in a couple of sentences.

The two rules
-------------
**It is given the result, never the book.** A capped, structured extract of the
rows the analysis produced, plus the units, the warnings and the reconciliation.
No raw dataset, no unfiltered read, nothing it could aggregate itself.

**Every figure it writes must already be in the result.** Prose is checked
against the values the runtime returned, and an interpretation containing a
number the result does not carry is DISCARDED — not annotated, not shown with a
warning. A sentence that invents a figure is worse than no sentence, because it
reads exactly like the true ones beside it.

When there is no provider, or the call fails, the deterministic narrative stands
on its own and the answer says which one the reader is looking at.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.llm import LLMError, get_provider

logger = logging.getLogger(__name__)

TOOL_NAME = "write_interpretation"

#: How many result rows the model is shown. Enough to see the shape and the
#: extremes; not enough to be a data export.
MAX_ROWS = 25
MAX_COLUMNS = 14

SYSTEM = """You are the interpretation layer of CreditProbe AI, a credit-risk \
intelligence platform used by banks.

A governed analytical runtime has ALREADY computed the result you are given. \
Every figure in it is correct and reconciled. Your job is to say what it means \
to a credit officer.

ABSOLUTE RULES

1. Never state a number that is not present in the result you were given. Do \
not add, subtract, average, annualise, extrapolate or convert. If you want to \
express a relationship the result does not contain, describe it in words \
("roughly a third", "the largest by some margin") rather than inventing a \
figure.
2. Never assert a cause. The result shows what moved, not why. "Consistent \
with" and "worth checking" are honest; "driven by" and "because of" are not, \
unless the result itself carries the attribution.
3. Never mention data that is not in the result, and never speculate about what \
the rest of the book looks like.
4. Say plainly when the result is empty, or when a warning materially limits \
what can be concluded.

STYLE

Write for a credit committee paper, not a chat window. One short paragraph, two \
at the very most. No bullet lists, no headings, no preamble, no restating the \
question. Lead with the answer. British English. Figures exactly as they appear \
in the result, with their units."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": ("One sentence that answers the question directly, "
                            "with the figure that answers it."),
        },
        "interpretation": {
            "type": "string",
            "description": ("One paragraph, two at most, on what this means "
                            "for the book. No invented arithmetic."),
        },
        "notable": {
            "type": "array", "items": {"type": "string"},
            "description": ("At most three short observations a credit officer "
                            "would want flagged. Empty when there is nothing "
                            "beyond the headline."),
        },
        "caveats": {
            "type": "array", "items": {"type": "string"},
            "description": ("Anything that limits what may be concluded — a "
                            "warning from the runtime, an empty result, a "
                            "population smaller than expected."),
        },
    },
    "required": ["headline", "interpretation"],
}


@dataclass
class Interpretation:
    """What the model made of the result, once it has been checked."""

    headline: str = ""
    interpretation: str = ""
    notable: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    model: str = ""
    duration_ms: int = 0
    request_id: str = ""
    #: Why there is no live interpretation, when there is none.
    unavailable: str = ""
    #: Figures the model wrote that the result does not carry. Non-empty means
    #: the interpretation was discarded.
    ungrounded: list[str] = field(default_factory=list)

    @property
    def live(self) -> bool:
        return bool(self.headline or self.interpretation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "interpretation": self.interpretation,
            "notable": list(self.notable),
            "caveats": list(self.caveats),
            "model": self.model, "duration_ms": self.duration_ms,
            "request_id": self.request_id,
            "live": self.live, "unavailable": self.unavailable,
            "ungrounded": list(self.ungrounded),
        }


def _extract(runtime: Any) -> dict[str, Any]:
    """The result, in the compact shape the model is shown.

    Deliberately built here rather than passing the runtime object through: this
    function is the boundary, and it is easier to be sure nothing leaks out of a
    place that constructs what goes in than out of one that filters what does
    not.
    """
    rows = list(getattr(runtime, "rows", []) or [])
    columns = list(getattr(runtime, "columns", []) or [])[:MAX_COLUMNS]
    keep = [str(c.get("name")) for c in columns if c.get("name")]
    return {
        "columns": [
            {"name": c.get("name"), "label": c.get("label") or c.get("name"),
             "unit": c.get("unit") or ""}
            for c in columns
        ],
        "row_count": len(rows),
        "rows": [{k: r.get(k) for k in keep} for r in rows[:MAX_ROWS]],
        "truncated": max(0, len(rows) - MAX_ROWS),
        "values": dict(getattr(runtime, "values", {}) or {}),
        "warnings": list(getattr(runtime, "warnings", []) or []),
        "reconciliation": getattr(runtime, "reconciliation", None),
    }


def _prompt(question: str, summary: str, result: dict[str, Any], *,
            plan_note: str = "") -> str:
    import json

    lines = [f"QUESTION: {question}", "", f"WHAT WAS COMPUTED: {summary}"]
    if plan_note:
        lines.append(plan_note)
    lines.append("")
    lines.append("COLUMNS (name · label · unit):")
    for column in result["columns"]:
        lines.append(f"  {column['name']} · {column['label']} · "
                     f"{column['unit'] or '—'}")
    lines.append("")
    lines.append(f"ROWS RETURNED: {result['row_count']}"
                 + (f" (showing the first {MAX_ROWS})" if result["truncated"]
                    else ""))
    lines.append(json.dumps(result["rows"], default=str)[:6000])

    if result["values"]:
        lines.append("")
        lines.append("HEADLINE VALUES:")
        lines.append(json.dumps(result["values"], default=str)[:2000])

    if result["warnings"]:
        lines.append("")
        lines.append("RUNTIME WARNINGS (state any that limit the conclusion):")
        for warning in result["warnings"][:8]:
            lines.append(f"  - {warning}")

    if result["reconciliation"]:
        lines.append("")
        lines.append("RECONCILIATION: the population narrowed as follows — "
                     + json.dumps(result["reconciliation"], default=str)[:1200])

    lines.append("")
    lines.append("Write the interpretation. Every figure you use must appear "
                 "above, exactly as it appears above.")
    return "\n".join(lines)


def write(question: str, summary: str, runtime: Any, *,
          plan_note: str = "") -> Interpretation:
    """A live reading of the result, or a stated reason there is not one."""
    provider = get_provider()
    if not provider.configured:
        return Interpretation(
            unavailable="No AI provider is configured, so the reading below "
                        "was assembled from the result rather than written.")
    if runtime is None:
        return Interpretation(unavailable="Nothing was computed to interpret.")

    result = _extract(runtime)
    try:
        answer = provider.structured(
            system=SYSTEM,
            prompt=_prompt(question, summary, result, plan_note=plan_note),
            schema=SCHEMA, tool_name=TOOL_NAME,
            tool_description=("Write the interpretation of this result. Call "
                              "this exactly once."),
            max_tokens=900, purpose="interpretation")
    except LLMError as e:
        from backend.llm import telemetry

        return Interpretation(
            unavailable=("The live model could not be reached for the written "
                         "interpretation, so the reading below was assembled "
                         "from the result. " + telemetry.sanitise(str(e))[:160]))
    except Exception as e:  # noqa: BLE001 - an outage must never lose the answer
        logger.warning("The interpretation call failed: %s", e)
        return Interpretation(
            unavailable="The live model could not be reached for the written "
                        "interpretation, so the reading below was assembled "
                        "from the result.")

    return _checked(answer, runtime, result)


def _checked(answer: Any, runtime: Any,
             result: dict[str, Any]) -> Interpretation:
    """Every figure in the prose, checked against the result that produced it.

    Discarding rather than annotating is the whole point. An interpretation with
    one invented number, shown with a warning above it, is still an
    interpretation a reader will quote.
    """
    from backend.orchestration import assembly

    data = answer.data or {}
    written = Interpretation(
        headline=str(data.get("headline") or "").strip(),
        interpretation=str(data.get("interpretation") or "").strip(),
        notable=[str(v).strip() for v in (data.get("notable") or [])][:3],
        caveats=[str(v).strip() for v in (data.get("caveats") or [])][:4],
        model=answer.model, duration_ms=answer.duration_ms,
        request_id=getattr(answer, "request_id", ""),
    )

    allowed = assembly.grounded_values(runtime, result.get("values"))
    loose: list[str] = []
    for text in (written.headline, written.interpretation, *written.notable):
        loose.extend(assembly.ungrounded(text, allowed))

    if loose:
        logger.error("Discarding a live interpretation carrying ungrounded "
                     "figure(s): %s", sorted(set(loose))[:6])
        return Interpretation(
            ungrounded=sorted(set(loose)),
            unavailable=(
                "The written interpretation was discarded: it contained "
                f"{'a figure' if len(set(loose)) == 1 else 'figures'} the "
                "computed result does not carry. The reading below was "
                "assembled directly from the result instead."),
            model=answer.model, duration_ms=answer.duration_ms)
    return written


__all__ = ["MAX_ROWS", "SCHEMA", "SYSTEM", "TOOL_NAME", "Interpretation", "write"]
