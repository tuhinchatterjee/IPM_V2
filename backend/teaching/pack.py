"""
The Teaching Pack: what a retrieved case looks like inside a prompt. §18.

The rule, and why it is a whitelist
-----------------------------------
§18 names seven things a pack may contain and six it may not. Implemented as a
whitelist rather than a blacklist, because the blacklist version fails the
moment somebody adds a field to `TeachingCase`: a new field is included by
default and nobody notices until it turns out to have carried something it
should not. Here a new field is invisible until a person adds its name to
`INCLUDED` and says why.

What a pack is for
------------------
Showing a planner how a question of this shape is read and planned. It carries
the reading, the objectives, the plan skeleton, the invariants and the answer
contract — the DOING of the case. It never carries a result, because the point
of the whole architecture is that the deterministic runtime calculates the live
answer and the teaching library only teaches how to get there. A pack with a
number in it is a pack that teaches the number.

Sanitization
------------
Three passes, and each catches something the others do not:

- the case must be STRUCTURE_ONLY. A DIAGNOSTIC case may legitimately carry
  the exact values that validate a method (§8), and those "remain evaluation
  and reference data and are never given to the live planner before
  execution". So diagnostic cases do not become packs at all.
- every string is scanned for a portfolio figure and redacted. The schema
  already refuses one on a structure-only case; this is the second lock, on
  the path where it would actually reach a model.
- an empty field is dropped rather than sent as an empty object, because a
  budget spent on `{}` is a budget not spent on an invariant.

Token budget
------------
Configurable, and enforced by dropping whole packs rather than truncating one.
A half-truncated pack is a worked example with its ending cut off, which is a
worse teacher than one fewer example.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from backend.teaching import schema as sc
from backend.teaching import status as st

PACK_VERSION = "1.0.0"

#: Roughly four characters to a token. Deliberately an estimate: the exact
#: count depends on the tokenizer, and a budget that needs the provider's
#: tokenizer to be evaluated is a budget that cannot be checked offline.
CHARS_PER_TOKEN = 4

#: What §18 admits, in the order a reader wants them. The comment on each is
#: the reason it is allowed to be in front of a model.
INCLUDED: tuple[tuple[str, str], ...] = (
    # The question, sanitized. Without it the rest has no subject.
    ("question", "question"),
    # The structured reading: what the question was understood to be asking.
    ("reading", ""),
    # The objectives, so the planner sees what "complete" means here.
    ("objectives", "objectives"),
    # The plan skeleton — the shape, never a compiled query.
    ("plan", "analytical_plan_contract"),
    ("method", "method_contract"),
    # The invariants a correct result must satisfy.
    ("invariants", "invariants"),
    # What to do instead of answering, where that is the lesson.
    ("clarification", "clarification_contract"),
    ("abstention", "abstention_contract"),
    # What the answer must look like.
    ("answer", "result_contract"),
    ("visualization", "visualization_contract"),
)

#: Named so a test can assert they never appear, and so the reason is written
#: down next to the rule rather than in a commit message.
EXCLUDED: tuple[str, ...] = (
    # A live or client result. The runtime calculates; the library teaches.
    "result_values",
    # Benchmark gold. The seal is the whole basis of every accuracy claim.
    "gold",
    # Hidden reasoning. Not ours to pass on, and not a specification.
    "chain_of_thought",
    # Anything confidential. §47.
    "client_data",
    # The prose. A reviewer's paragraph is not a specification, and it is the
    # single largest thing on a case.
    "description",
    "notes",
    # Review metadata. Who approved a case teaches nothing about analysis.
    "reviewer",
    "approved_at",
    "review_status",
)

_FIGURE = sc._FIGURE
_REDACTED = "[figure removed]"


@dataclass
class Pack:
    """One case, as it appears in a prompt."""

    case_id: str
    case_version: int
    family_id: str
    body: dict[str, Any] = field(default_factory=dict)

    def estimated_tokens(self) -> int:
        return estimate(self.body)

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "case_version": self.case_version,
                "family": self.family_id, **self.body}


def estimate(payload: Any) -> int:
    """How much of the budget a pack costs."""
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return max(1, len(text) // CHARS_PER_TOKEN)


def sanitize(text: str) -> str:
    """A string with any portfolio figure taken out.

    Not an assertion that one was there — a structure-only case does not
    validate with one — but the second lock on the path where a figure would
    actually reach a model.
    """
    return _FIGURE.sub(_REDACTED, str(text or ""))


def _clean(value: Any) -> Any:
    """Every string inside a structure, sanitized; empty branches dropped."""
    if isinstance(value, str):
        return sanitize(value)
    if isinstance(value, dict):
        out = {k: _clean(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in ({}, [], "", None)}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value if v not in ({}, [], "", None)]
    return value


def _reading(case: sc.TeachingCase) -> dict[str, Any]:
    """The structured reading, assembled from the fields that carry it.

    Assembled rather than taken from one field because §4 spreads the reading
    across capability, action, concepts, metrics, dimensions, filters, period,
    grain and population — and a planner shown only the concepts learns to
    ignore the period.
    """
    reading: dict[str, Any] = {
        "capability": case.expected_capability,
        "conversation_action": case.expected_conversation_action,
        "outcome": case.expected_outcome,
        "concepts": list(case.concepts),
        "metrics": list(case.metrics),
        "dimensions": list(case.dimensions),
        "filters": list(case.filters),
        "period": dict(case.period_contract),
        "grain": case.grain,
        "population": dict(case.population_contract),
        "datasets": list(case.required_datasets),
        "relationships": list(case.required_relationships),
        "operations": list(case.operations),
    }
    if case.ambiguities:
        reading["ambiguities"] = list(case.ambiguities)
    if case.same_turn_discourse.referents:
        reading["same_turn_referents"] = dict(
            case.same_turn_discourse.referents)
        reading["local_cohorts"] = dict(case.same_turn_discourse.cohorts)
    forbidden = case.scope_contract.get("forbidden_behaviours")
    if forbidden:
        # The trap is the lesson. A pack that shows only the right shape
        # cannot distinguish it from a plausible substitute.
        reading["must_not"] = list(forbidden)
    return reading


def _turns(case: sc.TeachingCase) -> list[dict[str, Any]]:
    """A thread, as the turns that make it one.

    Only for multi-turn cases: repeating the question as a one-item thread
    spends budget saying what the question field already said.
    """
    if case.turn_count() < 2:
        return []
    return [{"turn": turn.turn_index,
             "message": sanitize(turn.user_message),
             "action": turn.conversation_action,
             "inherits": turn.inherited_context,
             "scope_delta": turn.scope_delta,
             "resolves": turn.expected_referent_resolution,
             "must": sanitize(turn.expected_answer_behavior)}
            for turn in case.conversation_turns]


def make(case: sc.TeachingCase) -> Pack | None:
    """One case as a pack, or None when it may not become one.

    Returns None rather than raising: a caller assembling a pack for five
    cases should drop the one it cannot use, not fail the request. The
    conditions are §8's and §47's, and both are about what may be put in front
    of a live model rather than about whether the case is any good.
    """
    if case.data_sensitivity != st.PUBLIC:
        return None

    body: dict[str, Any] = {}
    for name, attribute in INCLUDED:
        if name == "reading":
            value = _reading(case)
        elif name == "objectives":
            value = [{"id": o.id, "text": sanitize(o.text),
                      "required": o.required} for o in case.objectives]
        else:
            value = getattr(case, attribute, None)
        cleaned = _clean(value)
        if cleaned in ({}, [], "", None):
            continue
        body[name] = cleaned

    thread = _turns(case)
    if thread:
        body["thread"] = thread

    return Pack(case_id=case.case_id, case_version=case.case_version,
                family_id=case.family_id, body=body)


def build(cases: list[sc.TeachingCase], *, budget: int = 4000) -> list[Pack]:
    """As many packs as the budget holds, in the order given.

    Whole packs, never a truncated one: a worked example with its ending cut
    off teaches the beginning of a method, which is worse than one fewer
    example. The order is the caller's — retrieval has already decided which
    case is most worth the budget.
    """
    packs: list[Pack] = []
    spent = 0
    for case in cases:
        pack = make(case)
        if pack is None:
            continue
        cost = pack.estimated_tokens()
        if spent + cost > int(budget):
            continue
        packs.append(pack)
        spent += cost
    return packs


def render(packs: list[Pack]) -> str:
    """The packs as the text a prompt carries.

    JSON rather than prose. The planner returns a structured document (§20),
    and an example shown as prose teaches it that prose is an acceptable
    shape.
    """
    return json.dumps([p.to_dict() for p in packs], indent=1, sort_keys=True,
                      default=str)


def contains_figure(packs: list[Pack]) -> list[str]:
    """Any figure that survived. Used by the leakage tests, and cheap enough
    to assert in production if it ever needs to be."""
    found: list[str] = []
    for pack in packs:
        text = json.dumps(pack.to_dict(), default=str)
        found += [m for m in re.findall(_FIGURE, text)]
    return found


__all__ = ["CHARS_PER_TOKEN", "EXCLUDED", "INCLUDED", "PACK_VERSION", "Pack",
           "build", "contains_figure", "estimate", "make", "render",
           "sanitize"]
