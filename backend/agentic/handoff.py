"""
Handing work between specialists, and what happens when they disagree.
§24, §25.

A handoff is a contract, not a conversation
-------------------------------------------
§24 is explicit: *"Do not pass raw unlimited conversation history."* The reason
is not only token cost. A specialist handed a transcript has to work out what it
is being asked for, and two specialists handed the same transcript work it out
differently — so the same evidence produces two incompatible answers and nothing
in the system can say which one addressed the question.

A `Handoff` therefore carries exactly what §24 lists — scope, population,
periods, evidence references, requested output, constraints, and a return
contract — and nothing else. `population` holds identifiers and a count, never
rows: passing 400 borrower records between agents is copying client data around
the process for no reason, and the receiving agent reads them from the governed
runtime anyway.

Disagreement
------------
§25's example is the important one, because it is the case where averaging is
most tempting and most wrong:

    Portfolio Risk:  deterioration appears broad.
    Validation:      the evidence shows it concentrated in 12 borrowers.

"Deterioration is somewhat broad" is a sentence that describes nothing. The
resolution rule here is that a conflict is settled **by the deterministic
evidence** — whichever finding is supported by a result with more coverage, more
recent data and passing invariants — and the losing finding is *preserved* on
the Trace rather than deleted. A reader can see that a specialist disagreed and
why it was not accepted.

Where the evidence does not separate them, nothing is resolved: the conflict is
reported as unresolved and the answer says so. That is an honest outcome, and it
is the one §25 asks for by forbidding the dishonest one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: How many entity identifiers a handoff may name before it becomes a
#: population reference instead. Twelve is the size of a list a person reads;
#: beyond that the receiving agent should be given the filter, not the members.
MAX_NAMED_ENTITIES = 12


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _present(value: Any) -> bool:
    """Whether a contract part was actually returned.

    An empty string, an empty list and an empty document are all "not
    returned". Zero is not — a count of zero deteriorating borrowers is a real
    finding, and treating it as absence is how a clean result becomes a failed
    handoff.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


@dataclass
class Handoff:
    """One specialist asking another for something specific. §24's fields."""

    from_agent: str
    to_agent: str
    reason: str
    #: The population, as a filter plus at most a few names.
    scope: dict[str, Any] = field(default_factory=dict)
    entities: list[str] = field(default_factory=list)
    entity_count: int = 0
    periods: list[str] = field(default_factory=list)
    #: AnalysisRun ids and task keys the receiving agent may read.
    evidence: list[dict[str, Any]] = field(default_factory=list)
    requested_output: str = ""
    constraints: list[str] = field(default_factory=list)
    #: What the receiver must return for this handoff to be considered met.
    return_contract: tuple[str, ...] = ("finding", "evidence")
    #: pending | met | unmet
    status: str = "pending"
    at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if len(self.entities) > MAX_NAMED_ENTITIES:
            self.entity_count = self.entity_count or len(self.entities)
            self.entities = self.entities[:MAX_NAMED_ENTITIES]
        self.entity_count = self.entity_count or len(self.entities)

    def sentence(self) -> str:
        """The handoff as the Trace reads it aloud."""
        return f"{self.from_agent} → {self.to_agent}: {self.reason}"

    def met_by(self, returned: dict[str, Any]) -> bool:
        """Did the receiver return what was asked for?

        Checked rather than assumed: a specialist that returns prose with no
        evidence reference has not met a contract that asked for evidence, and
        letting that pass is how an unsupported sentence reaches the synthesis.

        The whole returned document is passed rather than named arguments,
        because the contract comes from the RECEIVER's definition and may name
        parts this module has never heard of. Checking two hard-coded fields
        against a three-part contract silently fails the third every time.
        """
        given = returned or {}
        met = all(_present(given.get(part)) for part in self.return_contract)
        self.status = "met" if met else "unmet"
        return met

    def missing_from(self, returned: dict[str, Any]) -> list[str]:
        """Which parts of the contract the receiver did not return."""
        given = returned or {}
        return [p for p in self.return_contract if not _present(given.get(p))]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "reason": self.reason,
            "scope": dict(self.scope),
            "entities": list(self.entities),
            "entity_count": self.entity_count,
            "periods": list(self.periods),
            "evidence": list(self.evidence),
            "requested_output": self.requested_output,
            "constraints": list(self.constraints),
            "return_contract": list(self.return_contract),
            "status": self.status,
            "at": self.at,
            "sentence": self.sentence(),
        }


def build(*, from_agent: Any, to_agent: Any, reason: str,
          scope: dict[str, Any] | None = None,
          entities: list[str] | None = None, entity_count: int = 0,
          periods: list[str] | None = None,
          evidence: list[dict[str, Any]] | None = None,
          requested_output: str = "",
          constraints: list[str] | None = None) -> Handoff:
    """Build a handoff, taking the return contract from the receiver's own
    definition rather than from the sender's expectations."""
    contract = tuple(getattr(to_agent, "output_contract", ())
                     or ("finding", "evidence"))
    limits = list(constraints or [])
    domains = tuple(getattr(to_agent, "allowed_data_domains", ()) or ())
    if domains:
        limits.append(
            f"Read only: {', '.join(domains)}.")
    steps = int(getattr(to_agent, "maximum_steps", 0) or 0)
    if steps:
        limits.append(f"At most {steps} steps.")

    return Handoff(
        from_agent=str(getattr(from_agent, "agent_id", from_agent)),
        to_agent=str(getattr(to_agent, "agent_id", to_agent)),
        reason=reason, scope=dict(scope or {}),
        entities=list(entities or []), entity_count=entity_count,
        periods=list(periods or []), evidence=list(evidence or []),
        requested_output=requested_output, constraints=limits,
        return_contract=contract)


# ---------------------------------------------------------------------------
# Disagreement
# ---------------------------------------------------------------------------


@dataclass
class Claim:
    """One agent's position, and what supports it."""

    agent_id: str
    statement: str
    #: AnalysisRun ids behind it.
    analyses: list[int] = field(default_factory=list)
    #: How many rows the supporting result covered.
    coverage_rows: int = 0
    #: Did the supporting result pass its invariants?
    validated: bool = False
    #: The period the claim is about, so a stale one loses to a current one.
    period: str = ""

    @property
    def support(self) -> int:
        """How strongly the deterministic evidence backs this claim.

        Deliberately crude and deliberately explicit. Validation is worth more
        than volume — a checked result over a thousand rows beats an unchecked
        one over a million, because the unchecked one may be measuring the
        wrong thing at scale.
        """
        score = 0
        if self.validated:
            score += 4
        if self.analyses:
            score += 2
        if self.coverage_rows >= 100_000:
            score += 2
        elif self.coverage_rows > 0:
            score += 1
        return score

    def to_dict(self) -> dict[str, Any]:
        return {"agent_id": self.agent_id, "statement": self.statement,
                "analyses": list(self.analyses),
                "coverage_rows": self.coverage_rows,
                "validated": self.validated, "period": self.period,
                "support": self.support}


@dataclass
class Conflict:
    """Two specialists who do not agree, and what was done about it."""

    about: str
    claims: list[Claim] = field(default_factory=list)
    accepted: str = ""
    basis: str = ""
    resolved: bool = False
    at: str = field(default_factory=_now)

    @property
    def agents(self) -> list[str]:
        return [c.agent_id for c in self.claims]

    def to_dict(self) -> dict[str, Any]:
        return {
            "about": self.about,
            "between": self.agents,
            "claims": [c.to_dict() for c in self.claims],
            "accepted": self.accepted,
            "basis": self.basis,
            "resolved": self.resolved,
            "at": self.at,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        if not self.resolved:
            return (f"{' and '.join(self.agents)} reached different "
                    f"conclusions about {self.about}, and the evidence does "
                    f"not separate them.")
        winner = next((c for c in self.claims if c.agent_id == self.accepted),
                      None)
        return (f"{self.accepted} is accepted: {winner.statement}"
                if winner else f"{self.accepted} is accepted.")


def resolve(about: str, claims: list[Claim]) -> Conflict:
    """Settle a disagreement against the deterministic evidence, or say it is
    unsettled.

    Never averages, never picks the more confident sentence, and never prefers
    the more senior agent. The only thing that decides is what the governed
    runtime actually produced — which is the same rule the rest of the product
    runs on, applied to agents rather than to sentences.
    """
    conflict = Conflict(about=about, claims=list(claims))
    if len(claims) < 2:
        conflict.resolved = True
        conflict.accepted = claims[0].agent_id if claims else ""
        conflict.basis = "Only one specialist reported on this."
        return conflict

    ranked = sorted(claims, key=lambda c: -c.support)
    best, second = ranked[0], ranked[1]

    if best.support == second.support:
        conflict.resolved = False
        conflict.basis = (
            "Both findings rest on evidence of equal weight, so CreditProbe "
            "reports the disagreement rather than choosing between them.")
        return conflict

    conflict.resolved = True
    conflict.accepted = best.agent_id
    conflict.basis = _why(best, second)
    return conflict


def _why(best: Claim, second: Claim) -> str:
    """The specific reason one claim was accepted, in a reader's terms."""
    reasons: list[str] = []
    if best.validated and not second.validated:
        reasons.append("its result passed the business invariants and the "
                       "other did not")
    if best.analyses and not second.analyses:
        reasons.append("it is backed by a governed analysis")
    if best.coverage_rows > second.coverage_rows and second.coverage_rows:
        reasons.append(f"it covers {best.coverage_rows:,} rows against "
                       f"{second.coverage_rows:,}")
    if not reasons:
        reasons.append("the evidence behind it is stronger")
    return (f"{best.agent_id}'s finding is accepted because "
            f"{'; '.join(reasons)}. {second.agent_id}'s finding is kept on "
            f"the Trace.")


def unresolved(conflicts: list[Conflict]) -> list[Conflict]:
    return [c for c in conflicts if not c.resolved]


__all__ = [
    "MAX_NAMED_ENTITIES",
    "Claim",
    "Conflict",
    "Handoff",
    "build",
    "resolve",
    "unresolved",
]
