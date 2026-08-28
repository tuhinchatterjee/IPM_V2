"""
What a request actually asks for, clause by clause. P0.3.

The failure this exists to fix
------------------------------
    "Which customers experienced a rating downgrade, an increase in ECL of more
     than 20%, worsening DPD and declining covenant headroom over the latest
     year? Rank them by EAD."

CreditProbe read every measure in the message as a CONDITION, including the one
in "Rank them by EAD" — so the answer was a cohort of customers whose EAD had
also risen. That is a different, narrower question, and nothing on screen said
so. The requested ranking was never performed and its absence was invisible.

The cause is that the runtime had one bucket. Every measure phrase in the
message went into it, and a measure named in order to ORDER the answer is
indistinguishable, once in that bucket, from a measure named to RESTRICT it.

So this module reads the VERB of each clause. "Rank" orders, "identify" selects,
"compare" contrasts, "decompose" attributes. The verb is what a reader uses and
it is what the runtime should use, and it is general grammar rather than a
phrase list: "Rank them by headcount" would parse identically and the module has
no idea what headcount is.

Coverage, and why it is a validator rather than a report
--------------------------------------------------------
P0.3: "Do not display a final answer while silently omitting objectives."

Every objective carries a status. An answer is only presentable when each
objective is COMPLETE, or is explicitly reported as PARTIAL, UNAVAILABLE or
NEEDS_CLARIFICATION. Silence is the one outcome that is not allowed, because a
polished paragraph that answers three of five clauses reads exactly like one
that answers all five.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import discourse as dsc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# What a clause asks to have done
# ---------------------------------------------------------------------------

SELECT = "SELECT"          # define / find a population
RANK = "RANK"              # order a population by a measure
COMPARE = "COMPARE"        # contrast two populations
DECOMPOSE = "DECOMPOSE"    # attribute a total change to drivers
AGGREGATE = "AGGREGATE"    # compute a measure, possibly grouped
ASSESS = "ASSESS"          # judge / determine whether something holds
DESCRIBE = "DESCRIBE"      # explain, summarise, report
ATTRIBUTE = "ATTRIBUTE"    # which members contributed most

ACTIONS: tuple[str, ...] = (SELECT, RANK, COMPARE, DECOMPOSE, AGGREGATE,
                            ASSESS, DESCRIBE, ATTRIBUTE)

#: The verb each action is recognised by. Ordered: the first pattern that
#: matches the clause's leading verb wins, and the more specific actions are
#: listed before the general ones so "break down" is DECOMPOSE rather than
#: DESCRIBE.
_VERBS: tuple[tuple[str, str], ...] = (
    (DECOMPOSE, r"decompos\w*|break\s+down|attribut\w*\s+the\s+change|"
                r"split\s+the\s+change|bridge"),
    (COMPARE, r"compar\w*|contrast\w*|versus|vs\.?|benchmark\w*|"
              r"difference\s+between"),
    (RANK, r"rank\w*|sort\w*|order\w*(?!\s+book)|top\s+\d+|bottom\s+\d+|"
           r"largest|smallest|biggest|highest|lowest|worst|best"),
    (ATTRIBUTE, r"contributed?\s+(?:the\s+)?most|contributed?\s+to|"
                r"who\s+contributed|driving|drove|drivers?\s+of|"
                r"accounted\s+for|responsible\s+for"),
    (SELECT, r"identif\w*|find|which|who|whose|list|show\s+(?:me\s+)?the\s+"
             r"\w+\s+(?:who|whose|with)|select"),
    (ASSESS, r"determin\w*|assess\w*|evaluat\w*|check|verify|whether|"
             r"test\s+whether|is\s+there|are\s+there"),
    (AGGREGATE, r"calculat\w*|comput\w*|what\s+is|what\s+are|how\s+much|"
                r"how\s+many|total|sum|average|show|display|give"),
    (DESCRIBE, r"tell|explain|summaris\w*|summariz\w*|describ\w*|report|"
               r"investigat\w*|review|what\s+changed|what\s+is\s+driving"),
)

_COMPILED: tuple[tuple[str, Any], ...] = tuple(
    (action, re.compile(rf"\b(?:{pattern})", re.I)) for action, pattern in _VERBS)

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
UNAVAILABLE = "UNAVAILABLE"
NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
PLANNED = "PLANNED"
#: §21. An objective that was attempted and broke — the analysis errored, an
#: invariant failed, a kernel refused. Distinct from UNAVAILABLE, which means
#: the data cannot answer it, and from PARTIAL, which means it was answered
#: incompletely. Without FAILED a broken objective is recorded as one of those
#: two, and both read to a user as "we looked and this is what there is".
FAILED = "FAILED"

STATUSES: tuple[str, ...] = (COMPLETE, PARTIAL, UNAVAILABLE,
                             NEEDS_CLARIFICATION, FAILED, PLANNED)

#: Statuses a finished answer may carry. PLANNED is not one of them: an
#: objective still marked PLANNED when the answer is assembled was never
#: executed and never reported, which is the silent omission P0.3 forbids.
#: FAILED is one of them — a failure that has been reported is not a silent
#: omission, and hiding it would be.
SETTLED: frozenset[str] = frozenset(
    {COMPLETE, PARTIAL, UNAVAILABLE, NEEDS_CLARIFICATION, FAILED})


@dataclass
class Objective:
    """One thing the user asked for."""

    objective_id: str
    description: str
    action: str
    clause_index: int
    #: The cohort this objective is about, where the message defines one.
    cohort_id: str = ""
    #: For COMPARE: the second cohort.
    against_cohort_id: str = ""
    #: The measure phrase the clause names, where it names one. Free text at
    #: this stage — binding it to a governed field is the planner's job, and
    #: doing it here would make this module know the catalogue.
    measure_phrase: str = ""
    #: Set once the plan exists.
    planned_task: str = ""
    #: Set once something was computed for it.
    result_reference: str = ""
    status: str = PLANNED
    #: Why it is not COMPLETE, when it is not.
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "description": self.description,
            "action": self.action,
            "clause_index": self.clause_index,
            "cohort_id": self.cohort_id,
            "against_cohort_id": self.against_cohort_id,
            "measure_phrase": self.measure_phrase,
            "planned_task": self.planned_task,
            "result_reference": self.result_reference,
            "status": self.status,
            "note": self.note,
        }

    def settle(self, status: str, *, note: str = "",
               result_reference: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(f"'{status}' is not an objective status.")
        self.status = status
        if note:
            self.note = note
        if result_reference:
            self.result_reference = result_reference


#: "by EAD", "on ECL", "in exposure" — the measure a RANK or a COMPARE is done
#: on. Captured as written; the planner resolves it against the catalogue.
_BY_MEASURE = re.compile(
    r"\b(?:by|on|using|according\s+to|in\s+terms\s+of)\s+(?P<measure>[^,.;]{2,60})",
    re.I)


@dataclass
class Reading:
    """Every objective in one message, with the discourse behind it."""

    question: str
    discourse: dsc.Discourse
    objectives: list[Objective] = field(default_factory=list)

    @property
    def cohorts(self) -> list[dsc.Cohort]:
        return self.discourse.cohorts

    def objective(self, objective_id: str) -> Objective | None:
        return next((o for o in self.objectives
                     if o.objective_id == objective_id), None)

    def of_action(self, action: str) -> list[Objective]:
        return [o for o in self.objectives if o.action == action]

    @property
    def defining(self) -> Objective | None:
        """The objective that builds the population everything else uses."""
        return next((o for o in self.objectives
                     if o.action == SELECT and o.cohort_id), None)

    @property
    def ranking(self) -> Objective | None:
        return next((o for o in self.objectives if o.action == RANK), None)

    @property
    def comparison(self) -> Objective | None:
        return next((o for o in self.objectives
                     if o.action == COMPARE and o.against_cohort_id), None)

    def clause_text(self, index: int) -> str:
        for clause in self.discourse.clauses:
            if clause.index == index:
                return clause.text
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "objectives": [o.to_dict() for o in self.objectives],
            "discourse": self.discourse.to_dict(),
            "coverage": coverage(self).to_dict(),
        }


def read(question: str, *, has_conversation_population: bool = False
         ) -> Reading:
    """Decompose a message into its objectives."""
    found = dsc.read(
        question, has_conversation_population=has_conversation_population)
    objectives: list[Objective] = []

    for clause in found.clauses:
        action = _action_of(clause.text)
        cohort_id, against = _cohorts_for(clause, found, action)
        objectives.append(Objective(
            objective_id=f"obj_{len(objectives) + 1}",
            description=clause.text,
            action=action,
            clause_index=clause.index,
            cohort_id=cohort_id,
            against_cohort_id=against,
            measure_phrase=_measure_phrase(clause.text, action),
        ))

    return Reading(question=question, discourse=found, objectives=objectives)


#: How specific each action's verbs are. A clause matching two actions takes the
#: more specific one regardless of which verb came first: "Show which sectors
#: and customers contributed most" opens with "show" and is an attribution
#: question, and reading it as a plain aggregation loses the whole request.
_SPECIFICITY: dict[str, int] = {
    DECOMPOSE: 6, COMPARE: 5, ATTRIBUTE: 4, RANK: 3,
    SELECT: 2, ASSESS: 2, AGGREGATE: 1, DESCRIBE: 0,
}


def _action_of(text: str) -> str:
    """The verb the clause leads with.

    Scanned over the clause rather than only its first word, because a clause
    can open with an adverbial — "then rank them", "finally compare" — and the
    verb is what matters, not its position. Ties within one specificity are
    broken by position, so a clause with two equally specific verbs takes the
    one the sentence leads with.
    """
    best: tuple[int, int, str] | None = None
    for action, pattern in _COMPILED:
        match = pattern.search(text)
        if not match:
            continue
        rank = _SPECIFICITY.get(action, 0)
        here = (rank, -match.start(), action)
        if best is None or here > best:
            best = here
    return best[2] if best else DESCRIBE


def _cohorts_for(clause: dsc.Clause, found: dsc.Discourse,
                 action: str) -> tuple[str, str]:
    """Which cohort this clause is about, and which it is set against."""
    here = [c for c in found.cohorts if c.clause_index == clause.index]
    referred = [r.cohort for r in found.resolutions
                if r.mention.clause_index == clause.index and r.cohort]

    if action == COMPARE:
        # A comparison names one side and refers to the other. The referred
        # cohort is the subject; the one this clause introduces is the foil.
        subject = referred[0] if referred else (here[0] if here else None)
        foil = next((c for c in here if not subject or
                     c.cohort_id != subject.cohort_id), None)
        if subject is None and len(here) >= 2:
            subject, foil = here[0], here[1]
        return (subject.cohort_id if subject else "",
                foil.cohort_id if foil else "")

    if referred:
        return referred[0].cohort_id, ""
    # A defining clause is about the cohort it introduces — the restricted one
    # where there is a choice, because that is the one that has to be built.
    restricted = [c for c in here if c.restricted]
    chosen = restricted[0] if restricted else (here[0] if here else None)
    return (chosen.cohort_id if chosen else ""), ""


def _measure_phrase(text: str, action: str) -> str:
    """The measure a ranking or comparison is performed on, as written."""
    if action not in (RANK, COMPARE, ATTRIBUTE, AGGREGATE):
        return ""
    match = _BY_MEASURE.search(text)
    if not match:
        return ""
    return " ".join(match.group("measure").split()).rstrip(" .,;")


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


@dataclass
class Coverage:
    """Whether the answer about to be shown covers what was asked."""

    objectives: list[Objective]

    @property
    def total(self) -> int:
        return len(self.objectives)

    @property
    def complete(self) -> int:
        return sum(1 for o in self.objectives if o.status == COMPLETE)

    @property
    def unsettled(self) -> list[Objective]:
        """Objectives nothing was ever recorded against.

        The whole point. These are the clauses an answer would omit in silence.
        """
        return [o for o in self.objectives if o.status not in SETTLED]

    @property
    def unmet(self) -> list[Objective]:
        return [o for o in self.objectives if o.status != COMPLETE]

    @property
    def presentable(self) -> bool:
        """P0.3's gate: nothing may be silently omitted."""
        return not self.unsettled

    def sentence(self) -> str:
        """What the answer says about its own coverage.

        Written even when everything is complete, because "all five parts of
        your question were answered" is worth as much to a reader as the
        warning is, and a note that only ever appears when something is wrong
        is a note people learn to skim past.
        """
        if not self.objectives:
            return ""
        if self.presentable and not self.unmet:
            return (f"All {self.total} parts of this request were answered."
                    if self.total > 1 else "")
        parts: list[str] = []
        for objective in self.unmet:
            label = objective.description.strip().rstrip(".")
            if len(label) > 90:
                label = label[:87] + "…"
            said = {
                PARTIAL: "partly answered",
                UNAVAILABLE: "could not be answered",
                NEEDS_CLARIFICATION: "needs more detail",
                FAILED: "could not be completed",
                PLANNED: "was not answered",
            }.get(objective.status, objective.status.lower())
            reason = f" — {objective.note}" if objective.note else ""
            parts.append(f"“{label}” {said}{reason}")
        return "; ".join(parts) + "."

    @property
    def failed(self) -> list[Objective]:
        return [o for o in self.objectives if o.status == FAILED]

    def by_status(self) -> dict[str, int]:
        """§21 and §45: the coverage table the Trace and the Calculation Pack
        show. Counted by status rather than by "how many are complete",
        because the difference between an objective that failed and one the
        data cannot answer is the difference a reader needs."""
        counts = {status: 0 for status in STATUSES}
        for objective in self.objectives:
            counts[objective.status] = counts.get(objective.status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "complete": self.complete,
            "presentable": self.presentable,
            "by_status": self.by_status(),
            "failed": [o.objective_id for o in self.failed],
            "unmet": [o.objective_id for o in self.unmet],
            "unsettled": [o.objective_id for o in self.unsettled],
            "sentence": self.sentence(),
            "objectives": [o.to_dict() for o in self.objectives],
        }


def coverage(reading: Reading) -> Coverage:
    return Coverage(objectives=list(reading.objectives))


__all__ = [
    "ACTIONS",
    "AGGREGATE",
    "ASSESS",
    "ATTRIBUTE",
    "COMPARE",
    "COMPLETE",
    "Coverage",
    "DECOMPOSE",
    "DESCRIBE",
    "FAILED",
    "NEEDS_CLARIFICATION",
    "Objective",
    "PARTIAL",
    "PLANNED",
    "RANK",
    "Reading",
    "SELECT",
    "SETTLED",
    "STATUSES",
    "UNAVAILABLE",
    "coverage",
    "read",
]
