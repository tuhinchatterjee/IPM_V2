"""
The only thing the answer is allowed to be made of.

Why the packet exists
---------------------
Once a plan has run, there are two possible sources for the sentences that
follow: what was executed, and what the writer knows about credit risk. The
second is where invented figures come from — not from bad faith, but from a
writer with a half-filled table and a paragraph to finish.

So the packet is assembled first and the prose is written from it afterwards,
with nothing else in scope. Every figure a sentence may state is in here;
every figure not in here is one the sentence may not state. The rubric checks
that afterwards, and the packet is what it checks against.

What travels with the figures
-----------------------------
Provenance, because a figure whose source cannot be named is a figure nobody
can verify. Coverage and missingness, because a reading that leans on a field
that is empty for most of the book is wrong in a way the number itself does
not show. The governed actions and the deterministic escalation route, so
that recommendation and routing are things the writer REPORTS rather than
things it decides. And what remains, so an answer that stopped early can say
what it stopped for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import actions as act
from backend.early_warning import escalation as esc
from backend.early_warning import facts as ff
from backend.early_warning import grain as grain_mod
from backend.early_warning.conversation import execute as ex
from backend.early_warning.conversation import plan as plan_mod


@dataclass
class ResultPacket:
    """Everything executed, and everything a sentence may draw on."""

    question: str = ""
    normalized_request: str = ""
    selected_functionality: str = grain_mod.DOMAIN_ID
    plan: dict[str, Any] = field(default_factory=dict)
    output_grain: str = ""
    period: str = ""
    comparison_period: str = ""
    filters: dict[str, Any] = field(default_factory=dict)

    steps: list[dict[str, Any]] = field(default_factory=list)
    figures: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)

    #: The fact packs the steps produced. The existing composer and the
    #: existing rubric both read packs, so a pipeline that discarded them
    #: would have to reinvent both.
    packs: list[ff.FactPack] = field(default_factory=list)

    provenance: list[str] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    governed_actions: list[dict[str, Any]] = field(default_factory=list)
    escalation: dict[str, Any] = field(default_factory=dict)

    budget: dict[str, Any] = field(default_factory=dict)

    #: Which analysis the request asked for. The plan decides it; the packet
    #: carries it so the headline can be about that rather than about
    #: whichever step ran first.
    intent: str = ""
    #: Index into `packs` of the one the answer is chiefly about.
    primary_index: int = 0

    @property
    def primary(self) -> ff.FactPack | None:
        """The pack the answer is chiefly about.

        Not `packs[0]`. Every population-scoped plan reads the population
        first as context, so "the first pack" meant the answer was always
        about the population — a reader who asked which obligors are High was
        told the portfolio's average score, and one who asked for the ten
        biggest risers was told the same thing again.
        """
        if not self.packs:
            return None
        if 0 <= self.primary_index < len(self.packs):
            return self.packs[self.primary_index]
        return self.packs[0]

    def numbers(self) -> list[float]:
        """Every figure any sentence may state. What the rubric checks."""
        found: list[float] = []
        for pack in self.packs:
            found.extend(pack.numbers())
        probe = ff.FactPack(scope="packet", label="", period=self.period,
                            figures=self.figures, rows=self.rows,
                            caveats=self.caveats)
        found.extend(probe.numbers())
        for action in self.governed_actions:
            found.extend(ff.FactPack(scope="a", label="", period="",
                                     figures=action).numbers())
        if self.escalation:
            found.extend(ff.FactPack(scope="e", label="", period="",
                                     figures=self.escalation).numbers())
        return found

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "request": {
                "question": self.question,
                "normalized_request": self.normalized_request,
                "selected_functionality": self.selected_functionality,
                "plan": self.plan,
            },
            "scope": {
                "output_grain": self.output_grain, "period": self.period,
                "comparison_period": self.comparison_period,
                "filters": dict(self.filters),
            },
            "results": {
                "steps": list(self.steps), "figures": dict(self.figures),
                "rows": list(self.rows),
            },
            "evidence": {
                "provenance": list(self.provenance),
                "coverage": dict(self.coverage),
                "caveats": list(self.caveats),
            },
            "governed": {
                "actions": list(self.governed_actions),
                "escalation": dict(self.escalation),
            },
            "diagnostics": list(self.diagnostics),
            "budget": dict(self.budget),
        }


def build(question: str, request: Any, plan: plan_mod.Plan,
          executed: list[ex.Executed], *,
          package: grain_mod.GrainPackage,
          budget: dict[str, Any] | None = None) -> ResultPacket:
    """Assemble the packet from what actually ran."""
    packet = ResultPacket(
        question=question,
        normalized_request=str(getattr(request, "normalized_business_request",
                                        "") or question),
        plan=plan.to_dict(),
        output_grain=plan.output_grain,
        intent=str(getattr(plan, "intent", "") or ""),
        budget=dict(budget or {}),
    )

    # Which run the answer is chiefly about: the one that ran the analysis the
    # request asked for, falling back to the first that produced anything.
    # Chosen BEFORE the loop so the headline figures, rows, period and filters
    # all come from the same step — a headline whose numbers came from one
    # analysis and whose rows came from another is two answers wearing one
    # sentence.
    headline = _headline(executed, packet.intent)

    for run in executed:
        packet.steps.append(run.to_dict())
        packet.diagnostics.append({
            "analysis": run.step.analysis,
            "statement": run.statement,
            "row_count": run.row_count,
            "grain": run.grain,
            "duration_ms": run.duration_ms,
        })
        if run.pack is not None:
            if run is headline:
                packet.primary_index = len(packet.packs)
            packet.packs.append(run.pack)
            packet.provenance.extend(run.pack.provenance)
            for caveat in run.pack.caveats:
                if caveat not in packet.caveats:
                    packet.caveats.append(caveat)
        # The headline step sets the packet's figures; every other step adds
        # its own under its analysis name, so two steps cannot silently
        # overwrite each other's numbers.
        if run.figures:
            if run is headline:
                packet.figures.update(run.figures)
                packet.period = run.step.period or packet.period
                packet.comparison_period = (run.step.comparison_period
                                             or packet.comparison_period)
                packet.filters = dict(run.step.filters or {})
            else:
                packet.figures[run.step.analysis] = dict(run.figures)
        if run.rows and run is headline:
            packet.rows = list(run.rows)
    # A headline step that produced no rows of its own still deserves the
    # supporting context: the ranking's names under a movement reading, say.
    if not packet.rows:
        for run in executed:
            if run.rows:
                packet.rows = list(run.rows)
                break

    packet.coverage = dict(package.coverage)
    if not packet.period:
        packet.period = package.current_period

    _add_governed(packet)
    return packet


#: The analysis that PRODUCES a given intent, where the two are spelled
#: differently. "Escalation" and "action" are both answered by the governed
#: ACTION step, and a headline chooser that compared the words directly
#: found no match — so "should either be escalated?" was headlined by
#: whatever else the plan happened to run, and came back as a sector summary.
_INTENT_ANALYSIS: dict[str, str] = {
    "escalation": plan_mod.ACTION,
    "action": plan_mod.ACTION,
    "remediation": plan_mod.ACTION,
    "report": plan_mod.ACTION,
}


def _headline(executed: list[ex.Executed], intent: str) -> Any:
    """The run the answer is chiefly about.

    The analysis the request asked for, if it ran and produced something.
    Otherwise the first run that produced anything at all, which is what the
    packet did before intent was carried — so a plan whose intent never ran
    still gets an answer rather than an empty one.
    """
    useful = [r for r in executed if r.figures or r.pack is not None]
    if not useful:
        return executed[0] if executed else None
    wanted = str(intent or "").strip().lower()
    for name in (wanted, _INTENT_ANALYSIS.get(wanted, "")):
        if not name:
            continue
        for run in useful:
            if str(run.step.analysis).strip().lower() == name:
                return run
    return useful[0]


def _add_governed(packet: ResultPacket) -> None:
    """The actions the library selects and the route the matrix decides.

    Both are carried as FACTS. The writer reports them; it does not choose
    an action and it does not decide a rung — a recommendation invented at
    answer time is not a governed one, and an escalation decided in prose is
    not a control.
    """
    pack = packet.primary
    if pack is None:
        return
    figures = pack.figures or {}

    drivers = figures.get("drivers") or []
    if drivers:
        selected = act.for_drivers([d.get("code", "") for d in drivers])
        packet.governed_actions = [a.to_dict() for a in selected]
        first = act.single_highest_value(selected)
        if first is not None:
            packet.figures.setdefault("single_highest_value", first.to_dict())

    band = figures.get("ews_band")
    exposure = figures.get("exposure")
    if band and exposure is not None:
        route = esc.route_for(str(band), float(exposure))
        packet.escalation = {
            "severity": route.get("severity", band),
            "exposure_tier": route.get("exposure_tier", ""),
            "escalated_to": list(route.get("escalated_to") or []),
            "escalated_to_roles": list(route.get("escalated_to_roles") or []),
            "notified": list(route.get("notified") or []),
            "ack_sla_days": route.get("ack_sla_days"),
            "decision_sla_days": route.get("decision_sla_days"),
            "decided_by": "escalation matrix, not by the answer layer",
        }


__all__ = ["ResultPacket", "build"]
