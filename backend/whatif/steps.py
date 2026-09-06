"""
A What-If built one instruction at a time, and the state that survives between
them.

Why a thread is a list of steps, not a transcript
--------------------------------------------------
"Now add a five-point LGD increase" only means something against what the
thread has already established. Re-reading the whole conversation to work that
out would make the answer depend on how the question was phrased three turns
ago, and would make "change the PD increase from 20% to 15%" impossible to
honour precisely — you cannot edit a sentence, only a structure.

So the thread carries STRUCTURE: an ordered list of steps, each one a typed
transformation with the words that produced it kept alongside. Editing step two
and recomputing is then an ordinary operation rather than an act of
interpretation, and the same thread replayed tomorrow produces the same
figures.

Composition, and why order of ENTRY does not decide the answer
--------------------------------------------------------------
Steps are applied by the engine in a fixed order of KIND — rating, then macro,
then financial, then PD, LGD, collateral, EAD — not in the order somebody
happened to type them. A person who adds an LGD shock and then a rating
downgrade gets the same book as one who adds them the other way round, which is
what "the scenario" ought to mean. Entry order is preserved for the narrative,
because the story of how the scenario was built is worth keeping, but it does
not change the arithmetic.

What is deliberately NOT in here
--------------------------------
Results. A step says what to do to the book, never what happened. Caching an
ECL figure on a step would let an edited step keep a stale answer, and the
whole point of the structure is that the answer is always recomputed from it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from backend.whatif import macro as mc
from backend.whatif import scenarios as sc
from backend.whatif import staging as st

STATE_VERSION = "1.0.0"

#: The step kinds a thread can hold. These are the six journeys plus the
#: parameter shocks they decompose into.
RATING = sc.RATING
PD = sc.PD
LGD = sc.LGD
EAD = sc.EAD
CCF = "ccf"
COLLATERAL = sc.COLLATERAL
HAIRCUT = "haircut"
MACRO = sc.MACRO
STAGE = "stage"
FINANCIAL = sc.FINANCIAL

KINDS: tuple[str, ...] = (RATING, PD, LGD, EAD, CCF, COLLATERAL, HAIRCUT,
                          MACRO, STAGE, FINANCIAL)

#: How each kind reads in a sentence.
KIND_LABELS: dict[str, str] = {
    RATING: "Rating movement", PD: "PD adjustment", LGD: "LGD adjustment",
    EAD: "EAD adjustment", CCF: "CCF adjustment",
    COLLATERAL: "Collateral adjustment", HAIRCUT: "Haircut adjustment",
    MACRO: "Macroeconomic shock", STAGE: "Stage migration",
    FINANCIAL: "Financial adjustment",
}


class StepError(ValueError):
    """An instruction that cannot be turned into a step, said plainly."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _identifier() -> str:
    return f"s-{uuid.uuid4().hex[:10]}"


@dataclass(frozen=True)
class Step:
    """One transformation, with the words that asked for it."""

    kind: str
    shocks: tuple[sc.Shock, ...] = ()
    population: sc.Population = field(default_factory=sc.Population)
    #: What the person actually typed, kept verbatim.
    instruction: str = ""
    #: What CreditProbe understood, in its own words, for the restatement.
    interpreted: str = ""
    step_id: str = field(default_factory=_identifier)
    created_at: str = field(default_factory=_now)
    enabled: bool = True
    #: For a STAGE step: how many, or what share, moves and between which stages.
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    def describe(self) -> str:
        if self.interpreted:
            return self.interpreted
        if self.shocks:
            said = "; ".join(s.describe() for s in self.shocks)
            where = self.population.describe()
            return f"{said} for {where}" if not self.population.is_whole_book else said
        return self.label

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "kind": self.kind, "label": self.label,
                "instruction": self.instruction,
                "interpreted": self.describe(),
                "enabled": self.enabled, "created_at": self.created_at,
                "shocks": [s.to_dict() for s in self.shocks],
                "population": self.population.to_dict(),
                "detail": dict(self.detail)}

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> Step:
        try:
            shocks = tuple(
                sc.Shock(kind=str(s["kind"]), magnitude=float(s["magnitude"]),
                         unit=str(s.get("unit") or sc.RELATIVE),
                         target=str(s.get("target") or ""))
                for s in body.get("shocks") or [])
            pop = body.get("population") or {}
            population = sc.Population(
                sectors=tuple(pop.get("sectors") or ()),
                rating_bands=tuple(pop.get("rating_bands") or ()),
                stages=tuple(int(x) for x in (pop.get("stages") or ())),
                borrower_ids=tuple(pop.get("borrower_ids") or ()),
                watchlist_only=bool(pop.get("watchlist_only", False)))
            return cls(kind=str(body["kind"]), shocks=shocks, population=population,
                       instruction=str(body.get("instruction") or ""),
                       interpreted=str(body.get("interpreted") or ""),
                       step_id=str(body.get("step_id") or _identifier()),
                       created_at=str(body.get("created_at") or _now()),
                       enabled=bool(body.get("enabled", True)),
                       detail=dict(body.get("detail") or {}))
        except (KeyError, TypeError, ValueError) as e:
            raise StepError(f"A saved scenario step could not be read: {e}") from e


#: The order the engine applies kinds in. Rating first because it decides the
#: PD a borrower starts from; EAD last because a drawdown is capped against the
#: undrawn commitment, which nothing else moves.
APPLY_ORDER: tuple[str, ...] = (RATING, MACRO, FINANCIAL, STAGE, PD, LGD,
                                CCF, COLLATERAL, HAIRCUT, EAD)


@dataclass(frozen=True)
class ScenarioState:
    """Everything a What-If thread has settled."""

    period: str = ""
    steps: tuple[Step, ...] = ()
    staging: st.StagingPolicy = field(default_factory=st.StagingPolicy)
    #: The active ECL methodology, "" until the gate has been answered.
    methodology: str = ""
    model_version: str = ""
    thread_id: str = ""
    title: str = ""
    #: Every state this thread has been in, most recent last, for undo.
    history: tuple[tuple[Step, ...], ...] = ()

    # ------------------------------------------------------------ identity

    @property
    def is_baseline(self) -> bool:
        return not self.active

    @property
    def active(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.enabled)

    @property
    def kinds(self) -> tuple[str, ...]:
        seen: list[str] = []
        for step in self.active:
            if step.kind not in seen:
                seen.append(step.kind)
        return tuple(seen)

    def step(self, step_id: str) -> Step | None:
        for found in self.steps:
            if found.step_id == step_id:
                return found
        return None

    # ------------------------------------------------------------ editing

    def _remember(self) -> tuple[tuple[Step, ...], ...]:
        """Keep the last ten states. Enough to undo a conversation, not a day."""
        return (*self.history, self.steps)[-10:]

    def add(self, step: Step) -> ScenarioState:
        if step.kind not in KINDS:
            raise StepError(
                f"'{step.kind}' is not a What-If step this engine applies. "
                f"The kinds are: {', '.join(KINDS)}.")
        return replace(self, steps=(*self.steps, step), history=self._remember())

    def edit(self, step_id: str, **changes: Any) -> ScenarioState:
        """Change one step in place, keeping its identity and its position.

        The identity matters: a saved What-If that is reopened and edited
        should show the same step in the same place, changed — not a new step
        appended and the old one deleted.
        """
        found = self.step(step_id)
        if found is None:
            raise StepError(
                f"This scenario has no step '{step_id}'. It has "
                f"{len(self.steps)} step(s): "
                + ", ".join(f"{s.step_id} ({s.label})" for s in self.steps))
        allowed = {"shocks", "population", "instruction", "interpreted",
                   "enabled", "detail"}
        unknown = set(changes) - allowed
        if unknown:
            raise StepError(
                f"A scenario step has no {', '.join(sorted(unknown))} to change.")
        return replace(self, history=self._remember(), steps=tuple(
            replace(s, **changes) if s.step_id == step_id else s for s in self.steps))

    def remove(self, step_id: str) -> ScenarioState:
        if self.step(step_id) is None:
            raise StepError(f"This scenario has no step '{step_id}'.")
        return replace(self, history=self._remember(),
                       steps=tuple(s for s in self.steps if s.step_id != step_id))

    def disable(self, step_id: str) -> ScenarioState:
        return self.edit(step_id, enabled=False)

    def enable(self, step_id: str) -> ScenarioState:
        return self.edit(step_id, enabled=True)

    def undo(self) -> ScenarioState:
        """Back one state. Undoing with nothing to undo returns the baseline."""
        if not self.history:
            return replace(self, steps=())
        return replace(self, steps=self.history[-1], history=self.history[:-1])

    def reset(self) -> ScenarioState:
        """Back to the reported book, keeping the period and the criteria."""
        return replace(self, steps=(), history=self._remember())

    def with_staging(self, staging: st.StagingPolicy) -> ScenarioState:
        return replace(self, staging=staging)

    def with_methodology(self, method: str, version: str = "") -> ScenarioState:
        return replace(self, methodology=str(method or ""), model_version=version)

    def with_period(self, period: str) -> ScenarioState:
        return replace(self, period=str(period or ""))

    # ------------------------------------------------------------ composing

    def scenario(self, *, key: str = "thread", name: str = "") -> sc.Scenario:
        """The steps composed into one scenario the engine can run.

        Shocks are ordered by KIND, not by when they were typed, so the answer
        does not depend on the order somebody built the question in.
        """
        shocks: list[sc.Shock] = []
        for kind in APPLY_ORDER:
            for step in self.active:
                if step.kind == kind:
                    shocks.extend(step.shocks)
        population = _merge_populations([s.population for s in self.active])
        assumptions = sc.Assumptions(
            reevaluate_sicr=True,
            rating_deterioration_sicr=bool(
                (self.staging.rule(st.RATING_NOTCHES) or st.Rule("", "", "", 0)).enabled),
            rating_sicr_notches=int(
                (self.staging.rule(st.RATING_NOTCHES) or st.Rule("", "", "", 2)).threshold or 2),
            collateral_to_lgd=True)
        return sc.Scenario(
            key=key, name=name or self.title or self.describe(),
            shocks=tuple(shocks), population=population,
            assumptions=assumptions, severity="custom",
            rationale=self.describe(), period=self.period)

    def describe(self) -> str:
        if self.is_baseline:
            return "the reported position, with no shock applied"
        return " then ".join(s.describe() for s in self.active)

    # ------------------------------------------------------------ carrying

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_version": STATE_VERSION,
            "thread_id": self.thread_id,
            "title": self.title,
            "period": self.period,
            "is_baseline": self.is_baseline,
            "steps": [s.to_dict() for s in self.steps],
            "active_steps": len(self.active),
            "kinds": list(self.kinds),
            "staging": self.staging.describe(),
            "staging_version": self.staging.version,
            "methodology": self.methodology or None,
            "model_version": self.model_version or None,
            "macro_version": mc.MACRO_VERSION,
            "description": self.describe(),
            "can_undo": bool(self.history) or bool(self.steps),
        }

    @classmethod
    def from_dict(cls, body: dict[str, Any] | None) -> ScenarioState:
        if not body:
            return cls()
        return cls(
            period=str(body.get("period") or ""),
            steps=tuple(Step.from_dict(s) for s in (body.get("steps") or [])),
            staging=st.StagingPolicy.from_dict(body.get("staging")),
            methodology=str(body.get("methodology") or ""),
            model_version=str(body.get("model_version") or ""),
            thread_id=str(body.get("thread_id") or ""),
            title=str(body.get("title") or ""))


def _merge_populations(populations: list[sc.Population]) -> sc.Population:
    """One population from several steps' worth.

    Steps NARROW: a thread that says "construction" and then "Stage 1" means
    Stage 1 construction. Where two steps name different sectors the union is
    taken, because "construction, and also shipping" is the only reading of two
    sector statements that does not silently produce an empty book.
    """
    sectors: list[str] = []
    bands: list[str] = []
    stages: list[int] = []
    ids: list[str] = []
    watchlist = False
    for population in populations:
        for value in population.sectors:
            if value not in sectors:
                sectors.append(value)
        for value in population.rating_bands:
            if value not in bands:
                bands.append(value)
        for value in population.stages:
            if value not in stages:
                stages.append(value)
        for value in population.borrower_ids:
            if value not in ids:
                ids.append(value)
        watchlist = watchlist or population.watchlist_only
    return sc.Population(sectors=tuple(sectors), rating_bands=tuple(bands),
                         stages=tuple(sorted(stages)), borrower_ids=tuple(ids),
                         watchlist_only=watchlist)


__all__ = [
    "APPLY_ORDER", "CCF", "COLLATERAL", "EAD", "FINANCIAL", "HAIRCUT", "KINDS",
    "KIND_LABELS", "LGD", "MACRO", "PD", "RATING", "STAGE", "STATE_VERSION",
    "ScenarioState", "Step", "StepError",
]
