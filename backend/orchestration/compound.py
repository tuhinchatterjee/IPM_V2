"""
A sentence that asks two things gets two answers.

The failure
-----------
    What fields are available in the ratings data, and which are financial
    ratios?

CreditProbe listed the fields and stopped. The second clause was not refused,
not deferred and not mentioned — it was silently dropped, which is the worst of
the three, because the answer looks complete. The user's next message was:

    You didn't answer my second question.

and that had to be handled as a repair, when it should never have arisen.

How this works
--------------
The sentence is split into objectives — the same splitter the correction path
already uses, so the two agree by construction about what the second question
was. The first objective is answered normally. The remaining ones are then put
through the **follow-up path**, against a working memory built from the answer
that was just produced. That is the whole trick: "which are financial ratios"
asked immediately after a field list is exactly the follow-up CreditProbe
already knows how to answer, so answering it in the same turn requires no new
capability — only the wiring to notice it was asked.

What it will not do
-------------------
Guess. A clause the follow-up path cannot answer is left outstanding rather
than approximated, and stays available to the correction path. Two half-answers
are worse than one whole one and an honest note.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: How many clauses are attempted. A sentence asking four separate questions is
#: a sentence that should be four messages, and answering all of them produces
#: a wall nobody reads.
MAX_CLAUSES = 2


@dataclass
class Completion:
    """What the extra clauses added, and what they could not."""

    #: The clause texts that were answered, in order.
    answered: list[str] = field(default_factory=list)
    #: The clause texts that could not be, left for the correction path.
    outstanding: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"answered": list(self.answered),
                "outstanding": list(self.outstanding)}


def clauses(question: str) -> list[str]:
    """Every separate thing this sentence asks for, in order."""
    from backend.orchestration import memory as wm

    return wm.objectives(question)


def complete(answered: Any, question: str, context: Any) -> Completion:
    """Answer the clauses beyond the first, in the same turn.

    Mutates `answered.result` in place — the merged answer is one result, not
    two stacked, because the surface renders one answer and a second shape is a
    second renderer that will drift.
    """
    found = Completion()
    try:
        _complete(answered, question, context, found)
    except Exception as e:  # noqa: BLE001 - a second clause must not lose the first
        logger.warning("A compound clause could not be completed: %s", e)
    return found


def _complete(answered: Any, question: str, context: Any,
              found: Completion) -> None:
    from backend.orchestration import conversation as cv
    from backend.orchestration import followups
    from backend.orchestration import memory as wm

    result = getattr(answered, "result", None)
    if result is None:
        return

    parts = clauses(question)
    if len(parts) < 2:
        return

    for clause in parts[1:MAX_CLAUSES]:
        # Memory rebuilt from the answer that has just been produced, so the
        # clause resolves against THIS turn's result rather than the previous
        # turn's. Anything else answers "which of those" about the wrong set.
        memory = wm.observe(wm.WorkingMemory(), answered, None)
        extra = followups.answer(clause, cv.METADATA_FOLLOWUP, memory, context)
        if extra is None:
            found.outstanding.append(clause)
            continue
        _merge(result, extra, clause)
        found.answered.append(clause)


def _merge(primary: Any, extra: Any, clause: str) -> None:
    """Fold the second answer into the first, without losing either.

    The prose is joined. The ROWS become the second clause's, because the
    second clause narrows the first — a list of fields followed by which of
    them are ratios is most usefully a table of the ratios, with the full list
    still described in the sentence above it.
    """
    primary.answer = f"{primary.answer.rstrip()} {extra.answer.lstrip()}".strip()

    if extra.rows:
        primary.rows = extra.rows
        primary.columns = extra.columns or primary.columns
    primary.values = {**primary.values, **extra.values}
    primary.detail = {
        **primary.detail,
        "compound": {
            **(primary.detail.get("compound") or {}),
            clause: extra.detail or {"answered": True},
        },
    }
    for warning in extra.warnings:
        if warning not in primary.warnings:
            primary.warnings.append(warning)
    for follow_up in extra.follow_ups:
        if follow_up not in primary.follow_ups:
            primary.follow_ups.append(follow_up)


__all__ = ["MAX_CLAUSES", "Completion", "clauses", "complete"]
