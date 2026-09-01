"""
The routing policy: every threshold, in one versioned object. §31.

    "Freeze selected thresholds into a versioned routing policy.
     Test on sealed holdout only after selection."

Why the thresholds move out of the modules that use them
---------------------------------------------------------
They were module constants — `routing.COMPLEX_AT`, `retrieval.FLOOR`,
`retrieval.MAX_CASES`, the pack budget — and as constants they are unversioned,
untunable and unreportable. §31 asks for all four properties at once: tune them
against the development set, freeze the chosen values, ship the frozen set
inside the Teaching Release, and be able to say afterwards which values served
a given answer.

So a Policy is a value. The modules keep their constants as the DEFAULT policy,
because a default that lives in the module it governs cannot drift from it, and
every caller that wants a tuned policy passes one.

What tuning may and may not see
--------------------------------
§31's second sentence is the load-bearing one. Thresholds are chosen against
the development set; the sealed holdout is touched once, after selection, to
say what the chosen values are worth. A threshold tuned against the holdout
measures the tuning, and the number afterwards is not an estimate of anything.
Nothing in this module can reach the holdout, and the factory-side sweep takes
its cases as an argument for exactly that reason.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclass_fields
from typing import Any

POLICY_VERSION = "1.0.0"


@dataclass(frozen=True)
class Policy:
    """§31's seven thresholds, frozen together.

    Together on purpose. They interact: a lower retrieval floor with an
    unchanged example cap shows the planner weaker examples rather than more
    of them, and a higher escalation threshold with an unchanged critic
    threshold moves work from the complex planner to the critic rather than
    reducing it. Tuning one at a time produces a set that was never evaluated
    as a set, so the policy is the unit and the sweep evaluates combinations.
    """

    #: The route score at or above which a request goes straight to the
    #: complex planner. §24's direct signals bypass this entirely.
    direct_complex_at: int = 3
    #: The score at which a routine plan that validated is nonetheless
    #: re-planned by the complex model. Above `direct_complex_at` by
    #: construction: a request that would have gone direct cannot also be an
    #: escalation.
    escalate_at: int = 5
    #: How many validation problems a rejected plan may have before the critic
    #: is used rather than a plain replan.
    critic_at: int = 1
    #: Confidence below which CreditProbe asks instead of answering. §40
    #: counts a clarification as neither correct nor incorrect, so this trades
    #: coverage against precision and nothing else.
    abstain_below: float = 0.45
    #: The relevance a teaching case must clear to be shown at all.
    retrieval_floor: float = 0.18
    #: The most examples in one Teaching Pack. §17 caps it at five.
    max_examples: int = 5
    #: Tokens the Teaching Pack may spend.
    token_budget: int = 4000

    def __post_init__(self) -> None:
        if not 0 <= self.abstain_below <= 1:
            raise ValueError("abstain_below is a confidence, 0 to 1")
        if not 0 <= self.retrieval_floor <= 1:
            raise ValueError("retrieval_floor is a relevance, 0 to 1")
        if not 0 <= self.max_examples <= 5:
            raise ValueError("§17 permits at most five examples")
        if self.token_budget < 0:
            raise ValueError("a token budget cannot be negative")
        if self.escalate_at < self.direct_complex_at:
            # A request scoring above the escalation threshold but below the
            # direct one is a contradiction: it would be escalated to a route
            # it was already eligible for.
            raise ValueError("escalate_at must be at or above "
                             "direct_complex_at")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> Policy:
        raw = dict(raw) if isinstance(raw, dict) else {}
        allowed = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in allowed})

    @property
    def fingerprint(self) -> str:
        """A handle for this exact set of values.

        Goes into the Teaching Release manifest and onto every routing record,
        so "which thresholds served this answer" has an answer that survives
        the next tuning run.
        """
        blob = json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def describe(self) -> list[tuple[str, str]]:
        """The policy as rows an administrator reads."""
        return [
            ("Direct complex route at", f"score ≥ {self.direct_complex_at}"),
            ("Escalate to complex at", f"score ≥ {self.escalate_at}"),
            ("Use the critic at", f"{self.critic_at} validation problem(s)"),
            ("Ask instead of answering below",
             f"{self.abstain_below:.0%} confidence"),
            ("Retrieval relevance floor", f"{self.retrieval_floor:.2f}"),
            ("Teaching examples", f"at most {self.max_examples}"),
            ("Teaching Pack budget", f"{self.token_budget} tokens"),
        ]


def default() -> Policy:
    """The policy the modules' own constants describe.

    Read from those modules rather than retyped, so a constant that changes
    without a tuning run still produces a policy that matches what the product
    actually does — and the mismatch is visible instead of silent.
    """
    from backend.orchestration import routing as rt
    from backend.teaching import pack as tp
    from backend.teaching import retrieval as rv

    return Policy(
        direct_complex_at=rt.COMPLEX_AT,
        escalate_at=max(rt.COMPLEX_AT + 2, rt.COMPLEX_AT),
        critic_at=1,
        abstain_below=0.45,
        retrieval_floor=rv.FLOOR,
        max_examples=rv.MAX_CASES,
        token_budget=_default_budget(tp),
    )


def _default_budget(pack_module: Any) -> int:
    """The Teaching Pack's own default budget, read from its signature.

    A number copied here would be right on the day it was copied.
    """
    import inspect

    try:
        signature = inspect.signature(pack_module.build)
        given = signature.parameters["budget"].default
        return int(given)
    except Exception:  # noqa: BLE001 - a default must not be the failure
        return 4000


#: The grids a sweep searches. Deliberately small: §31 asks for chosen
#: thresholds, not for a hyperparameter search, and a grid large enough to
#: overfit a development set of a few thousand cases is a grid that will.
GRID: dict[str, tuple[Any, ...]] = {
    "direct_complex_at": (2, 3, 4, 5),
    "escalate_at": (4, 5, 6, 7),
    "critic_at": (1, 2),
    "abstain_below": (0.35, 0.45, 0.55),
    "retrieval_floor": (0.12, 0.18, 0.25, 0.32),
    "max_examples": (2, 3, 4, 5),
    "token_budget": (2000, 4000, 6000),
}


def candidates(*, base: Policy | None = None,
               axes: tuple[str, ...] = ()) -> list[Policy]:
    """Every policy a sweep should try, one axis at a time.

    One axis at a time rather than the full cross product, and the reason is
    honest rather than computational: a full grid over seven axes is 4,608
    policies, each needing a full evaluation run, and a development set of a
    few thousand cases cannot distinguish that many candidates from noise. A
    coordinate sweep over a set that interacts is an approximation, and calling
    it one is better than reporting a global optimum that is a sampling
    artefact.
    """
    start = base or default()
    wanted = axes or tuple(GRID)
    out: list[Policy] = [start]
    seen = {start.fingerprint}
    for axis in wanted:
        for value in GRID.get(axis, ()):
            body = start.to_dict()
            if body.get(axis) == value:
                continue
            body[axis] = value
            try:
                candidate = Policy.from_dict(body)
            except ValueError:
                # A combination the invariants refuse — an escalation
                # threshold below the direct one, say. Skipped rather than
                # raising: an invalid point in a grid is not an error.
                continue
            if candidate.fingerprint not in seen:
                seen.add(candidate.fingerprint)
                out.append(candidate)
    return out


__all__ = ["GRID", "POLICY_VERSION", "Policy", "candidates", "default"]
