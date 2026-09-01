"""«stage 2 or worse» is not «stage 2». Part 12.

The defect
----------
    "Which borrowers had a PD increase and are booked at stage 2 or worse?"

resolved `ifrs9_stage = 2`. The stage 3 borrowers — the ones actually in
trouble, the ones the question was reaching for — were silently excluded from a
population that claimed to include them. The answer ran, looked complete, and
was a narrower question than the one asked.

The comparison vocabulary the semantic reader carries only fires when the
comparator comes BEFORE the number: "above 2", "at least 2". Credit officers
write the other order — "stage 2 or worse", "grade BB or below", "90 days or
more" — and that shape was not read at all.

Worse is not a direction, it is a direction ON A MEASURE
---------------------------------------------------------
"or worse" cannot be compiled without knowing which way the measure runs. A
higher IFRS 9 stage is worse; a higher interest cover is better; an internal
grade ordinal runs 1 to 10 with 10 the worst; days past due rise as things
deteriorate. So the qualifier is resolved against the measure's own direction
rather than against the word, and a measure whose direction is not governed
here produces nothing rather than a guess.

What it does not do
-------------------
It reads a qualifier that is already in the sentence. It does not widen a
population the question did not widen, and where the sentence says only
"stage 2", `= 2` stays `= 2`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

ORDINAL_VERSION = "1.0.0"

#: Governed ordinal dimensions, and whether a HIGHER value is the worse one.
#: Named rather than inferred: a scale's direction is a fact about the scale,
#: and inferring it from the column name is how "coverage" and "shortfall" end
#: up pointing the same way.
DIRECTION: dict[str, bool] = {
    "ifrs9_stage": True,          # 1 → 2 → 3, and 3 is default
    "internal_grade": True,       # the ordinal runs 1..10, 10 the weakest
    "risk_rating": True,
    "dpd_days": True,
    "days_past_due": True,
    "rating_bucket": True,
    "pd_12m_pct": True,
    "interest_coverage": False,   # more cover is better
    "dscr": False,
    "collateral_coverage_pct": False,
}

#: The qualifier as a credit officer writes it, and what it asserts about the
#: value: `worse` widens away from the good end, `better` towards it, and the
#: directional words say which end without reference to the measure at all.
_QUALIFIERS: tuple[tuple[str, str], ...] = (
    (r"or\s+worse|and\s+worse|or\s+below\s+that|and\s+worse\s+still", "worse"),
    (r"or\s+better|and\s+better", "better"),
    (r"or\s+(?:more|higher|above|greater)|and\s+(?:above|higher)"
     r"|or\s+over", "higher"),
    (r"or\s+(?:less|lower|below|fewer)|and\s+(?:below|lower)"
     r"|or\s+under", "lower"),
)

#: The qualifier must follow the VALUE, within a few characters — "stage 2 or
#: worse", "90 days or more". A wider window picks up an "or" belonging to a
#: different clause and applies it to the wrong condition.
_WINDOW = 24


@dataclass(frozen=True)
class Qualified:
    """One value restriction the sentence widened, and how."""

    field: str
    value: str
    #: `gte` or `lte`. Never `eq`: a qualifier that resolved to equality is a
    #: qualifier that was not there.
    op: str
    #: The words in the question that did it, so the Trace can quote them.
    phrase: str

    @property
    def says(self) -> str:
        direction = "at or above" if self.op == "gte" else "at or below"
        return (f"The question says “{self.phrase}”, so this reads "
                f"{self.field.replace('_', ' ')} {direction} {self.value} "
                "rather than exactly it.")

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "value": self.value, "op": self.op,
                "phrase": self.phrase, "says": self.says}


def _operator(qualifier: str, higher_is_worse: bool) -> str:
    if qualifier == "higher":
        return "gte"
    if qualifier == "lower":
        return "lte"
    if qualifier == "worse":
        return "gte" if higher_is_worse else "lte"
    return "lte" if higher_is_worse else "gte"


def read(question: str, field: str, value: str) -> Qualified | None:
    """Whether the question widened this value restriction, and which way.

    Returns None where the sentence names the value plainly, where the
    dimension's direction is not governed, or where the qualifier sits too far
    from the value to be about it.
    """
    said = str(question or "")
    if not said or field not in DIRECTION:
        return None
    spelled = str(value or "").strip()
    if not spelled:
        return None

    # Find the value as it appears in the sentence, then look just past it.
    for match in re.finditer(rf"\b{re.escape(spelled)}\b", said, re.IGNORECASE):
        tail = said[match.end():match.end() + _WINDOW]
        for pattern, qualifier in _QUALIFIERS:
            found = re.match(rf"\s*(?:{pattern})\b", tail, re.IGNORECASE)
            if not found:
                continue
            phrase = said[match.start():match.end() + found.end()].strip()
            return Qualified(
                field=field, value=spelled,
                op=_operator(qualifier, DIRECTION[field]),
                phrase=phrase)
    return None


def apply(question: str,
          restrictions: list[tuple[str, str]],
          ) -> tuple[list[tuple[str, str]], list[Qualified]]:
    """Every value restriction, with the ones the sentence widened marked.

    The restrictions come back unchanged — they are still `(field, value)` —
    with a parallel list of the qualifiers found, because the caller decides
    what a widened restriction compiles to and this only reads the sentence.
    """
    found: list[Qualified] = []
    for field, value in restrictions:
        qualified = read(question, field, value)
        if qualified is not None:
            found.append(qualified)
    return list(restrictions), found


__all__ = ["DIRECTION", "ORDINAL_VERSION", "Qualified", "apply", "read"]
