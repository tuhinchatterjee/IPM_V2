"""
Which officer is working on this request.

Four levels the user actually sees
----------------------------------
    1  CREDIT ANALYST          one dataset, one figure, or a lookup
    2  SENIOR CREDIT OFFICER   several steps, two domains, two periods
    3  PORTFOLIO RISK LEAD     a segment or the portfolio, or forward risk
    4  CHIEF ORCHESTRATOR      broad, multi-domain, coordinated specialist work

These are job titles, not model names. §3 is explicit that an agent role and a
model role are different things, and the reason is practical: the model behind
"Chief Orchestrator" is configuration, it changes, and a user who has learned to
read the title as a model name learns something that becomes false.

Where the level comes from
--------------------------
§5 forbids phrase-specific rules — "if the question contains 'investigate' then
level 4" — and it is right to. That approach produces a product where the level
is a property of vocabulary rather than of work, so "look at Contracting" and
"investigate Contracting" get different officers for the same analysis.

So the level is read off the **complexity score that already exists**.
`backend/orchestration/routing.py` counts structural signals — datasets,
concepts, periods, referents, breadth, methodology, prediction, nesting,
ambiguity, demo-safe mode — deterministically, before any model is called, and
records them on the Trace. This module adds the signals that routing has no
reason to care about (does this touch several governed *domains*? does it need
several specialists? is a material action in play?) and maps the total onto a
title.

Two scores, not one
-------------------
Complexity is *how much work*. Risk is *how much it matters if it is wrong* —
methodology, prediction, materiality, workflow implications, a broad request in
front of a client. A cheap question about a certified method used for
provisioning is low complexity and high risk, and it deserves a senior officer
even though the arithmetic is trivial. Taking the higher of the two floors is
what makes that happen.

What is persisted
-----------------
Everything §5 lists: the level, the title, a structured reason, both scores, the
agent count and the planned task count. The reason is structured rather than
prose because the Trace has to show *why* this request got a Chief Orchestrator,
and a sentence a model wrote is not an audit record.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The four levels
# ---------------------------------------------------------------------------

CREDIT_ANALYST = 1
SENIOR_CREDIT_OFFICER = 2
PORTFOLIO_RISK_LEAD = 3
CHIEF_ORCHESTRATOR = 4

LEVELS: tuple[int, ...] = (
    CREDIT_ANALYST,
    SENIOR_CREDIT_OFFICER,
    PORTFOLIO_RISK_LEAD,
    CHIEF_ORCHESTRATOR,
)

TITLES: dict[int, str] = {
    CREDIT_ANALYST: "Credit Analyst",
    SENIOR_CREDIT_OFFICER: "Senior Credit Officer",
    PORTFOLIO_RISK_LEAD: "Portfolio Risk Lead",
    CHIEF_ORCHESTRATOR: "Chief Orchestrator",
}

#: What each level is for, in the words the product uses about it. Shown in
#: Trace and Agent Operations so the level is explicable without this file.
REMIT: dict[int, str] = {
    CREDIT_ANALYST:
        "Metadata, one dataset, a descriptive figure, a presentation change, "
        "or a question the previous result already answers.",
    SENIOR_CREDIT_OFFICER:
        "Several calculation steps, two governed domains, a period comparison, "
        "a join, or a certified method run over a chosen slice.",
    PORTFOLIO_RISK_LEAD:
        "A segment or the whole portfolio: deterioration screens, "
        "concentration, risk appetite, Early Warning, scenario work.",
    CHIEF_ORCHESTRATOR:
        "Broad or open-ended work across several domains and analyses, "
        "coordinated between specialists and reconciled before it is reported.",
}

#: The score at which each level starts.
#:
#: Calibrated against §69's own five questions rather than guessed. The first
#: attempt mapped routing's scale straight through — level 2 at routing's
#: COMPLEX_AT of 3 — and over-promoted everything: "which customers had a
#: downgrade and an ECL increase over the latest year" scores 7 on a scale
#: where a two-dataset question already scores 3, and came out as a Chief
#: Orchestrator. Routing's scale answers "is this worth the complex model",
#: which saturates early on purpose; officer level answers "how senior is this
#: work", which does not.
FLOORS: tuple[tuple[int, int], ...] = (
    (13, CHIEF_ORCHESTRATOR),
    (9, PORTFOLIO_RISK_LEAD),
    (4, SENIOR_CREDIT_OFFICER),
    (0, CREDIT_ANALYST),
)

#: A request needing this many specialists is coordinated work by definition,
#: whatever it scored.
COORDINATED_AT = 3

#: Grains that make work segment-level or portfolio-level by definition. §4
#: defines level 3 by exactly this — "segment-level investigation,
#: portfolio-level analysis" — and a score alone cannot express it: a
#: borrower-grain question across two domains and two periods scores the same
#: as a sector-wide investigation, and they are not the same job.
SEGMENT_GRAINS: frozenset[str] = frozenset(
    {"sector", "segment", "region", "product", "business_unit", "rating_band"})
PORTFOLIO_GRAINS: frozenset[str] = frozenset({"portfolio", "book"})

#: How many governed checks make a request an open-ended investigation rather
#: than a calculation. Three: one is a figure, two is a comparison, three is
#: somebody looking around.
BROAD_AT = 3


# ---------------------------------------------------------------------------
# Signals this module adds on top of routing's
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reason:
    """One structural reason for the level, and what it contributed."""

    id: str
    weight: int
    detail: str
    #: "complexity" or "risk" — which of the two scores this fed.
    kind: str = "complexity"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "weight": self.weight, "detail": self.detail,
                "kind": self.kind}


#: Language that scopes a request at the portfolio or a segment rather than at
#: named entities. Not a level rule: it contributes a weight like every other
#: signal, and a request carrying it alone does not reach level 3.
_PORTFOLIO_SCOPE = re.compile(
    r"\bportfolio\b|\bthe book\b|\bbook-?wide\b|\bacross the bank\b"
    r"|\brisk appetite\b|\bconcentrat\w+\b|\bexposure limits?\b", re.I)

_SEGMENT_SCOPE = re.compile(
    r"\bsector\b|\bsegment\b|\bindustry\b|\bregion\b|\bproduct line\b"
    r"|\bvintage\b|\brating band\b|\bbusiness unit\b", re.I)

#: Work whose being wrong has consequences beyond the screen it is on.
_MATERIAL = re.compile(
    r"\bprovision\w*\b|\bimpairment\b|\bwrite[- ]?off\b|\blimit\b"
    r"|\bapprove\b|\bcertif\w+\b|\bpublish\b|\bsign[- ]?off\b"
    r"|\bregulator\w*\b|\bdisclos\w+\b|\bboard\b|\bcommittee\b", re.I)


def reasons(question: str, *, decision: Any = None, reading: Any = None,
            agents: int = 0, tasks: int = 0, proactive: bool = False,
            demo_safe: bool = False) -> list[Reason]:
    """Every structural reason this request needs a more senior officer.

    `decision` is the routing decision that has already been made for this
    turn. Its signals are carried in verbatim rather than recomputed — two
    modules counting datasets separately is two modules that eventually
    disagree, and the Trace would show both.
    """
    text = " ".join((question or "").split())
    found: list[Reason] = []

    def add(rid: str, weight: int, detail: str, kind: str = "complexity") -> None:
        found.append(Reason(id=rid, weight=weight, detail=detail, kind=kind))

    # ---- routing's own signals, carried in ------------------------------
    for signal in list(getattr(decision, "signals", ()) or ()):
        sid = str(getattr(signal, "id", "") or "")
        weight = int(getattr(signal, "weight", 0) or 0)
        detail = str(getattr(signal, "detail", "") or "")
        # Methodology, prediction, ambiguity and demo-safe mode are reasons the
        # answer MATTERS rather than reasons it is long. Scored as risk.
        kind = ("risk" if sid in {"methodology", "predictive", "ambiguous",
                                  "low_confidence", "demo_safe"}
                else "complexity")
        add(f"route:{sid}", weight, detail, kind)

    # ---- domain breadth --------------------------------------------------
    # Datasets are counted by routing. Domains are not, and they are the better
    # measure of coordination: four datasets inside IFRS 9 is one specialist's
    # work, while one dataset each from ratings, staging and covenants is three
    # specialists who have to agree.
    #
    # The second-domain weight is 1 rather than 2 on purpose. Two domains
    # almost always means two datasets, which routing has already scored, and
    # weighting both at 2 pushed "which customers had a downgrade and an ECL
    # increase over the latest year" — a two-domain, two-period, borrower-grain
    # question, which is exactly §4's Level 2 — up to a Portfolio Risk Lead. The
    # third domain is where the work genuinely stops being one officer's, and
    # that is where the weight steps up.
    domains = _domains_of(reading)
    if len(domains) >= 3:
        add("domains", 3,
            f"{len(domains)} governed credit domains are involved "
            f"({', '.join(sorted(domains))}).")
    elif len(domains) == 2:
        add("domains", 1,
            f"Two governed credit domains are involved "
            f"({', '.join(sorted(domains))}).")

    # ---- analytical grain -------------------------------------------------
    grain = str(getattr(reading, "grain", "") or "").lower()
    if grain in {"portfolio", "segment", "sector"}:
        add("grain", 2, f"The answer is reported at the {grain} grain.")

    if _PORTFOLIO_SCOPE.search(text):
        add("portfolio_scope", 2,
            "The request is scoped at the portfolio rather than at named "
            "borrowers.")
    elif _SEGMENT_SCOPE.search(text):
        add("segment_scope", 1,
            "The request is scoped at a segment rather than at named "
            "borrowers.")

    # ---- operations -------------------------------------------------------
    operations = int(getattr(reading, "operation_count", 0) or 0)
    if operations >= 4:
        add("operations", 2, f"The plan needs {operations} analytical steps.")

    # ---- coordination -----------------------------------------------------
    if agents >= COORDINATED_AT:
        add("agents", 3, f"{agents} specialists are needed and have to agree.")
    elif agents == 2:
        add("agents", 1, "Two specialists are needed.")
    if tasks >= 6:
        add("tasks", 2, f"The plan decomposes into {tasks} delegated tasks.")

    # ---- risk -------------------------------------------------------------
    if _MATERIAL.search(text):
        # Weight 4, which is exactly the Senior Credit Officer floor. That is
        # the point: a question about a figure the bank certifies to its board
        # is a senior officer's on its own, however trivial the arithmetic.
        add("material", 4,
            "The request touches something with consequences beyond the "
            "screen — a provision, a limit, a certification or a disclosure.",
            kind="risk")
    if proactive:
        add("proactive", 4,
            "CreditProbe is reviewing a newly published period on its own "
            "initiative rather than answering a question.",
            kind="risk")
    if demo_safe and not any(r.id == "route:demo_safe" for r in found):
        add("demo_safe", 2,
            "Demo Safe Mode is on, where a misunderstanding is expensive.",
            kind="risk")

    return found


def _domains_of(reading: Any) -> set[str]:
    """Which governed credit domains this reading touches.

    Read from the semantic ontology rather than from a list here, so publishing
    a new domain into the Data Builder widens the count without a code change.
    """
    from backend.agentic import registry

    concepts = list(getattr(reading, "concepts", ()) or ())
    concepts += [c for c in (getattr(reading, "metrics", ()) or ())
                 if c not in concepts]
    found: set[str] = set()
    for concept in concepts:
        domain = registry.domain_of(str(concept))
        if domain:
            found.add(domain)
    return found


# ---------------------------------------------------------------------------
# The selection
# ---------------------------------------------------------------------------


@dataclass
class Selection:
    """Which officer is working on this, and everything that decided it."""

    level: int = CREDIT_ANALYST
    title: str = TITLES[CREDIT_ANALYST]
    complexity_score: int = 0
    risk_score: int = 0
    agent_count: int = 0
    planned_task_count: int = 0
    reasons: list[Reason] = field(default_factory=list)
    #: The level before an escalation, when this selection replaced one.
    escalated_from: int = 0
    escalated_from_title: str = ""

    @property
    def score(self) -> int:
        """The score the level was actually read off."""
        return max(self.complexity_score, self.risk_score)

    @property
    def coordinated(self) -> bool:
        return self.level == CHIEF_ORCHESTRATOR or self.agent_count >= COORDINATED_AT

    @property
    def status_line(self) -> str:
        """What the working indicator says. §4."""
        return f"{self.title} is working"

    @property
    def selection_reason(self) -> str:
        """One sentence a person can read, built from the top structural
        reasons rather than written by a model."""
        if not self.reasons:
            return ("Nothing about this request needs more than a Credit "
                    "Analyst.")
        top = sorted(self.reasons, key=lambda r: -r.weight)[:3]
        return " ".join(r.detail for r in top)

    def escalation_line(self) -> str:
        """The restrained transition §9 asks for. Empty unless escalated."""
        if not self.escalated_from or self.escalated_from >= self.level:
            return ""
        return f"Escalating to {self.title}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "officer_level": self.level,
            "officer_title": self.title,
            "remit": REMIT.get(self.level, ""),
            "selection_reason": self.selection_reason,
            "complexity_score": self.complexity_score,
            "risk_score": self.risk_score,
            "score": self.score,
            "agent_count": self.agent_count,
            "planned_task_count": self.planned_task_count,
            "coordinated": self.coordinated,
            "status_line": self.status_line,
            "reasons": [r.to_dict() for r in self.reasons],
            "escalated_from": self.escalated_from or None,
            "escalated_from_title": self.escalated_from_title,
            "escalation_line": self.escalation_line(),
        }


def select(question: str, *, decision: Any = None, reading: Any = None,
           agents: int = 0, tasks: int = 0, proactive: bool = False,
           demo_safe: bool = False,
           deterministic: bool = False) -> Selection:
    """Which officer is working on this request.

    `deterministic` is the caller saying governed services answer this exactly
    — a catalogue lookup, a field definition, a presentation change. Those are
    a Credit Analyst's work by definition however the sentence is phrased, and
    no scoring can move them: there is no model call to escalate to.
    """
    if deterministic:
        return Selection(
            level=CREDIT_ANALYST, title=TITLES[CREDIT_ANALYST],
            reasons=[Reason(
                id="deterministic", weight=0,
                detail=("Governed services answer this exactly, with no "
                        "analysis to coordinate."))])

    found = reasons(question, decision=decision, reading=reading,
                    agents=agents, tasks=tasks, proactive=proactive,
                    demo_safe=demo_safe)
    complexity = sum(r.weight for r in found if r.kind == "complexity")
    risk = sum(r.weight for r in found if r.kind == "risk")
    level = level_for(max(complexity, risk))

    # Two floors the score cannot express, both from §4's own definitions.
    level = max(level, floor_for(reading))

    # And a ceiling, from the same definitions. See `ceiling_for`.
    level = min(level, ceiling_for(reading))

    # Coordination is a floor of its own. Three specialists whose findings have
    # to be reconciled IS the Chief Orchestrator's job, whatever the sentence
    # scored — the alternative is a Senior Credit Officer credited with
    # resolving a disagreement between four agents.
    if agents >= COORDINATED_AT:
        level = max(level, CHIEF_ORCHESTRATOR)

    return Selection(
        level=level, title=TITLES[level],
        complexity_score=complexity, risk_score=risk,
        agent_count=agents, planned_task_count=tasks, reasons=found)


def level_for(score: int) -> int:
    """The officer level a score reaches."""
    for floor, level in FLOORS:
        if score >= floor:
            return level
    return CREDIT_ANALYST


def floor_for(reading: Any) -> int:
    """The minimum level the SHAPE of the work sets, whatever it scored.

    §4 defines the top two levels by grain rather than by difficulty:

        Level 3  segment-level investigation, portfolio-level analysis
        Level 4  broad open-ended investigations, several datasets and
                 several analyses, coordinated specialist work

    A score cannot carry that distinction. "Which customers had a downgrade and
    an ECL increase over the latest year" and "something seems wrong with
    Contracting, investigate it" score identically — two domains, several
    concepts, a period comparison — and they are different jobs: the first is
    a borrower query a Senior Credit Officer answers, the second is a sector
    investigation that belongs to the Portfolio Risk Lead.

    So the grain sets a floor, and an open-ended investigation AT the portfolio
    grain sets a higher one: a whole-book look-around is coordinated work by
    construction, not because of any word in the sentence.
    """
    grain = str(getattr(reading, "grain", "") or "").strip().lower()
    operations = int(getattr(reading, "operation_count", 0) or 0)
    broad = operations >= BROAD_AT

    if grain in PORTFOLIO_GRAINS:
        return CHIEF_ORCHESTRATOR if broad else PORTFOLIO_RISK_LEAD
    if grain in SEGMENT_GRAINS:
        return PORTFOLIO_RISK_LEAD
    return CREDIT_ANALYST


def ceiling_for(reading: Any) -> int:
    """The maximum level the SHAPE of the work allows, whatever it scored.

    The symmetric half of `floor_for`, and it exists because the asymmetry
    was a defect.

        "Which customers had a rating downgrade and an increase in ECL over
         the latest year?"

    came out as a **Portfolio Risk Lead**. It scores 10 — three datasets, four
    concepts, two periods, a rating migration, two domains, two specialists —
    and 10 clears the Portfolio Risk Lead floor of 9. Every one of those
    signals is real. None of them makes the work portfolio work.

    §4 defines the top two levels by GRAIN, not by difficulty:

        Level 2  several calculation steps, two governed domains, a period
                 comparison, a join
        Level 3  a segment or the whole portfolio

    That question is level 2's definition, sentence for sentence. It is a
    borrower comparison — a hard one — and answering it does not make somebody
    a Portfolio Risk Lead any more than a difficult reconciliation makes them
    a CRO. `floor_for` already lets the grain raise the level; without a
    ceiling, the score could raise it past the point where the level still
    means what §4 says it means.

    Two things lift the ceiling, and both are real widenings of the work
    rather than measures of its difficulty: an open-ended look-around (three
    or more governed checks, which is `BROAD_AT`), and coordination, which
    `select` applies afterwards as a floor of its own so that three
    specialists still reach the Chief Orchestrator.

    A reading with no grain sets no ceiling. An unknown shape is not a small
    one, and capping on absence would quietly demote every turn whose grain
    the reading could not resolve.
    """
    grain = str(getattr(reading, "grain", "") or "").strip().lower()
    if not grain or grain in SEGMENT_GRAINS or grain in PORTFOLIO_GRAINS:
        return CHIEF_ORCHESTRATOR
    if int(getattr(reading, "operation_count", 0) or 0) >= BROAD_AT:
        return CHIEF_ORCHESTRATOR
    return SENIOR_CREDIT_OFFICER


def escalate(previous: Selection, *, to: int, why: str) -> Selection:
    """Move to a more senior officer part-way through a request.

    §9: an escalation is not a failure, and the UI must not render it as one.
    It happens because the work turned out to be wider than the sentence — a
    plan that needed a third domain, a validation that needed repair, a probe
    that opened a second question. The reason travels with the selection
    because that is what the transition line says.

    Escalation is one-directional. Discovering half-way through that the work
    was simpler than it looked does not demote the officer in front of the
    user: the request genuinely occupied that person's attention, and a title
    that walks backwards reads as a mistake being covered up.
    """
    target = max(int(to), previous.level)
    if target == previous.level:
        return previous
    reasons_now = list(previous.reasons)
    reasons_now.append(Reason(id="escalation", weight=0, detail=why,
                              kind="complexity"))
    return Selection(
        level=target, title=TITLES[target],
        complexity_score=previous.complexity_score,
        risk_score=previous.risk_score,
        agent_count=previous.agent_count,
        planned_task_count=previous.planned_task_count,
        reasons=reasons_now,
        escalated_from=previous.level,
        escalated_from_title=previous.title)


def title_for(level: int) -> str:
    return TITLES.get(int(level or 0), TITLES[CREDIT_ANALYST])


__all__ = [
    "CHIEF_ORCHESTRATOR",
    "COORDINATED_AT",
    "CREDIT_ANALYST",
    "BROAD_AT",
    "FLOORS",
    "LEVELS",
    "ceiling_for",
    "PORTFOLIO_GRAINS",
    "PORTFOLIO_RISK_LEAD",
    "REMIT",
    "SENIOR_CREDIT_OFFICER",
    "TITLES",
    "Reason",
    "SEGMENT_GRAINS",
    "Selection",
    "escalate",
    "floor_for",
    "level_for",
    "reasons",
    "select",
    "title_for",
]
