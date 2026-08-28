"""
Approved failures, as curriculum cases. P0.15.

Where this sits, and why here rather than in the backend
---------------------------------------------------------
The review queue lives in the product, because that is where a failure is
noticed and where a reviewer signs off on what the right answer would have
been. Turning an approved item into a `Case` lives HERE, because the dependency
has to run factory to backend and never the other way: a backend module that
can import the curriculum can reach the sealed holdout in one more line, and
the whole point of the seal is that the line is never there to be extended.

So the service returns a specification — plain data — and this reads it.

What an approved item becomes
-----------------------------
A case, in the same shape as every other case, which the evaluator RUNS. Not a
paragraph somebody has to read and reinterpret, and not a stored answer: the
expectation is what a correct answer must DO.

Nothing here trains anything. P0.15 is explicit about it, and so is the queue:
an approved item becomes a specification the product is measured against, and
the learning happens when a person fixes the product and the case goes from
FAILING to PASSING.
"""

from __future__ import annotations

import logging
from typing import Any

from intelligence_factory.curriculum import Case, Turn

logger = logging.getLogger(__name__)

#: The family reviewed failures join. Kept distinct from the twenty-five
#: written families and the twelve generated categories so a report can say how
#: much of the corpus came from real users rather than from a template.
REVIEWED = "reviewed failure"


def case(spec: dict[str, Any]) -> Case:
    """One approved item's specification, as a case."""
    return Case(
        id=str(spec.get("id") or ""),
        family=REVIEWED,
        title=str(spec.get("title") or spec.get("question") or "")[:120],
        turns=[Turn(
            question=str(spec.get("question") or ""),
            capability=str(spec.get("capability") or ""),
            action=str(spec.get("action") or ""),
            datasets=tuple(spec.get("datasets") or ()),
            concepts=tuple(spec.get("concepts") or ()),
            period=str(spec.get("period") or ""),
            outcome=str(spec.get("outcome") or "EXECUTE"),
            invariants=tuple(spec.get("invariants") or ()),
            forbidden=tuple(spec.get("forbidden") or ()),
        )])


def cases(specs: list[dict[str, Any]]) -> list[Case]:
    """Every approved specification, as cases.

    A specification that cannot be read is skipped and logged rather than
    raising: one malformed row must not stop the rest of the corpus from being
    evaluated, and a corpus that refuses to load is one nobody runs.
    """
    out: list[Case] = []
    for spec in specs or []:
        try:
            built = case(spec)
        except Exception as e:  # noqa: BLE001 - one bad row is not the corpus
            logger.warning("Could not read a reviewed case: %s", e)
            continue
        if built.turns and built.turns[0].question:
            out.append(built)
    return out


def from_queue(session: Any) -> list[Case]:
    """Every approved review-queue item, as cases.

    Takes a session rather than importing the service at module scope, so the
    factory can be imported and its corpus counted on a machine with no
    database — which is how the curriculum tests run.
    """
    from backend.services import review_queue as rq

    return cases(rq.specifications(session))


__all__ = ["REVIEWED", "case", "cases", "from_queue"]
