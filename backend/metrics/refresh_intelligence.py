"""What materially changed, what it means here, and what deserves attention.

§26–§30. The question this asks a model is NOT "summarise this dashboard" —
that is what `lens_interpretation` already does, and it reads the current
figures. This reads the CHANGE, which is a different job with a different
failure mode: a summary that is vague is unhelpful, and a change reading that
is confident about a movement that did not happen is worse than nothing.

Three things stop that, in order
---------------------------------
**The change is computed before it is described.** `refresh.compare` has
already subtracted the two snapshots in Python. The model is shown the
differences, not asked to work them out, so there is no arithmetic for it to
get wrong and every figure it may legitimately use already exists.

**Every numerical claim is checked, and an unsupported one discards the
reading.** §29. Extended from the discipline `lens_interpretation._checked`
already applies to a Lens summary, with one addition that matters here: the
protected set includes the DERIVED changes as well as the values, because a
reading of change is supposed to quote a delta and a checker that only knew
the two endpoints would reject every correct sentence.

**Causation is a vocabulary, not a hope.** §28. The output schema makes the
model choose a `basis` for every driver it names — CORRELATION,
POSSIBLE_DRIVER or CONFIRMED_DRIVER — and `_checked` downgrades any
CONFIRMED_DRIVER whose evidence does not include a metric that IS the
mechanism. "Stage 2 and high-severity EWS both rose" survives. "EWS
deterioration caused Stage 2 migration" does not, unless the package contains
a stage-migration figure that is itself the movement.

When nothing changed
--------------------
§30. `interpret` does not call a model at all when the deterministic delta
says nothing material moved. There is no prompt that reliably produces
"nothing happened" from a model asked to be interesting, and there is no
reason to pay for the attempt: the honest sentence is written here, with the
three facts that support it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.metrics import refresh_package
from backend.metrics.refresh import (
    BASELINE,
    Delta,
)

logger = logging.getLogger(__name__)

INTELLIGENCE_VERSION = "3.0.0"

TOOL_NAME = "interpret_lens_change"

#: §28's ladder. A claim must declare which rung it stands on.
FACT = "FACT"
CHANGE = "CHANGE"
CORRELATION = "CORRELATION"
INTERPRETATION = "INTERPRETATION"
POSSIBLE_DRIVER = "POSSIBLE_DRIVER"
CONFIRMED_DRIVER = "CONFIRMED_DRIVER"
BASES = (FACT, CHANGE, CORRELATION, INTERPRETATION, POSSIBLE_DRIVER,
         CONFIRMED_DRIVER)

BASIS_LABELS = {
    FACT: "Fact",
    CHANGE: "Change",
    CORRELATION: "Correlation",
    INTERPRETATION: "Interpretation",
    POSSIBLE_DRIVER: "Possible driver",
    CONFIRMED_DRIVER: "Confirmed driver",
}

#: Metrics whose movement IS a mechanism rather than a symptom of one. A
#: CONFIRMED_DRIVER claim survives only when its evidence names one of these,
#: because a stage transition figure is the migration and a stage 2 ratio is
#: the consequence of it.
MECHANISM_WORDS = ("transition", "migration", "moved", "movement", "new ",
                   "roll", "flow", "into stage", "out of stage", "cure",
                   "downgrade", "upgrade")

SYSTEM = """You are CreditProbe's change analyst, reading what happened to a \
monitoring Lens since the last time it was calculated.

THE QUESTION YOU ANSWER

"What materially changed since the previous comparable refresh, what does that \
mean in the context of THIS Lens, and what deserves attention?"

You are NOT summarising the dashboard. The current figures are on the screen \
already. Your job is the CHANGE.

WHAT YOU ARE GIVEN

Every figure has already been computed by a deterministic engine and every \
change has already been subtracted for you. Values, previous values, absolute \
and relative changes, bounded history in two senses, and the movements grouped \
by whether they came from the Cockpit domain (the book as it stands) or the \
Early Warning domain (what is coming).

TWO TIMESTAMPS, AND THE DIFFERENCE MATTERS MORE THAN ANYTHING ELSE HERE

`refreshed_at` is when the Lens was CALCULATED. `reporting_period` is which \
BUSINESS PERIOD the figures describe. Two refreshes of the same quarter that \
differ are a RESTATEMENT or a definition change — never "the book moved". Only \
a change in reporting period is the book moving. Read `classification` before \
you write anything: it says which of these happened, and it may say several.

ABSOLUTE RULES

1. Never state a figure that is not in the data you were given. Not a value, \
not a previous value, not a change. Do not compute a new one — not a sum, not a \
percentage, not an average of two figures you were shown. Where you want a \
relationship the data does not contain precisely, say it in words \
("materially", "roughly twice"). A sentence containing an unsupported figure \
causes the whole reading to be discarded.

2. Every claim declares its `basis`:
   FACT              — a figure, as given
   CHANGE            — a movement, as given
   CORRELATION       — two things moved together, which you may say
   INTERPRETATION    — what you make of it, said as such
   POSSIBLE_DRIVER   — a mechanism the data is consistent with
   CONFIRMED_DRIVER  — a mechanism the data ESTABLISHES

   CONFIRMED_DRIVER is almost never available to you. It requires a figure \
that IS the mechanism — a stage-transition amount, a rating-migration count — \
not two figures that moved in the same direction. "Stage 2 exposure and \
high-severity EWS exposure both increased" is a CORRELATION. "EWS deterioration \
caused Stage 2 migration" is not something you may write at all unless a \
migration figure in the data shows it.

3. Where a metric's DEFINITION changed between the two refreshes, say so and do \
not present the difference as the book moving. The data tells you which ones.

4. Where the FILTER CONTEXT changed, the two refreshes measure different \
populations. Do not compare headline figures across them at all — say that the \
population changed and what the current one shows.

5. Where nothing material changed, say exactly that. Do not find something to \
say. A quiet quarter reported as quiet is a correct reading.

6. Reference every metric by the name shown in the data, so a reader can see \
which figures support each claim.

STYLE

For a credit committee, not a chat window. Short. British English. Figures \
exactly as given, with their units."""


def _schema() -> dict[str, Any]:
    claim = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "basis": {"type": "string", "enum": list(BASES)},
            "metrics": {
                "type": "array", "items": {"type": "string"},
                "description": "The metric name(s) this claim rests on, "
                               "exactly as shown in the data."},
        },
        "required": ["text", "basis", "metrics"],
    }
    return {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "One sentence: the single most important thing "
                               "that changed. Say 'No material change' where "
                               "that is the truth."},
            "material_changes": {
                "type": "array", "items": claim,
                "description": "What moved, and what each movement means "
                               "here. At most six."},
            "persistent_trends": {"type": "array", "items": claim},
            "new_deterioration": {"type": "array", "items": claim},
            "improvements": {"type": "array", "items": claim},
            "reversals": {"type": "array", "items": claim},
            "cross_metric_corroboration": {
                "type": "array", "items": claim,
                "description": "Where Cockpit and Early Warning movements are "
                               "directionally consistent. CORRELATION, unless "
                               "the data shows a mechanism."},
            "supported_drivers": {"type": "array", "items": claim},
            "uncertainties": {"type": "array", "items": claim},
            "areas_requiring_attention": {"type": "array", "items": claim},
            "no_material_change": {
                "type": "boolean",
                "description": "True when nothing worth reporting moved."},
            "definition_caveat": {
                "type": "string",
                "description": "What part of the movement is a definition or "
                               "filter change rather than the book. Empty "
                               "when neither changed."},
        },
        "required": ["headline", "material_changes", "no_material_change"],
    }


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------


@dataclass
class Claim:
    text: str = ""
    basis: str = INTERPRETATION
    metrics: list[str] = field(default_factory=list)
    #: Set when a CONFIRMED_DRIVER was downgraded for lack of a mechanism.
    downgraded_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "basis": self.basis,
                "basis_label": BASIS_LABELS.get(self.basis, self.basis),
                "metrics": list(self.metrics),
                "downgraded_from": self.downgraded_from}


@dataclass
class ChangeReading:
    """§27's structure, once every figure in it has been checked."""

    headline: str = ""
    material_changes: list[Claim] = field(default_factory=list)
    persistent_trends: list[Claim] = field(default_factory=list)
    new_deterioration: list[Claim] = field(default_factory=list)
    improvements: list[Claim] = field(default_factory=list)
    reversals: list[Claim] = field(default_factory=list)
    cross_metric_corroboration: list[Claim] = field(default_factory=list)
    supported_drivers: list[Claim] = field(default_factory=list)
    uncertainties: list[Claim] = field(default_factory=list)
    areas_requiring_attention: list[Claim] = field(default_factory=list)
    no_material_change: bool = False
    definition_caveat: str = ""
    baseline: bool = False
    model: str = ""
    duration_ms: int = 0
    #: Figures the model wrote that the refresh does not support. Non-empty
    #: means the written reading was discarded.
    ungrounded: list[str] = field(default_factory=list)
    #: Claims whose basis was downgraded for want of a mechanism.
    downgraded: list[str] = field(default_factory=list)
    unavailable: str = ""
    verified: bool = False

    @property
    def live(self) -> bool:
        return bool(self.headline)

    def sections(self) -> dict[str, list[Claim]]:
        return {
            "MATERIAL_CHANGES": self.material_changes,
            "PERSISTENT_TRENDS": self.persistent_trends,
            "NEW_DETERIORATION": self.new_deterioration,
            "IMPROVEMENTS": self.improvements,
            "REVERSALS": self.reversals,
            "CROSS_METRIC_CORROBORATION": self.cross_metric_corroboration,
            "SUPPORTED_DRIVERS": self.supported_drivers,
            "UNCERTAINTIES": self.uncertainties,
            "AREAS_REQUIRING_ATTENTION": self.areas_requiring_attention,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "sections": {name: [c.to_dict() for c in claims]
                         for name, claims in self.sections().items() if claims},
            "material_changes": [c.to_dict() for c in self.material_changes],
            "no_material_change": self.no_material_change,
            "definition_caveat": self.definition_caveat,
            "baseline": self.baseline,
            "model": self.model, "duration_ms": self.duration_ms,
            "ungrounded": list(self.ungrounded),
            "downgraded": list(self.downgraded),
            "unavailable": self.unavailable,
            "live": self.live, "verified": self.verified,
            "version": INTELLIGENCE_VERSION,
        }


# ---------------------------------------------------------------------------
# The deterministic readings — no model involved
# ---------------------------------------------------------------------------


def baseline_reading(delta: Delta) -> ChangeReading:
    """§43. The first comparable refresh has nothing to compare with.

    Said plainly rather than dressed up. A baseline is not a failure and not
    an absence of intelligence; it is the state every Lens is in exactly once.
    """
    return ChangeReading(
        headline=("Baseline refresh recorded. Change interpretation will "
                  "become available after the next comparable refresh."),
        baseline=True, verified=True,
        definition_caveat=delta.comparison.why_none)


def quiet_reading(current: Any, delta: Delta) -> ChangeReading:
    """§30. Nothing material moved, said with the facts that support it.

    No model call. There is no prompt that reliably produces "nothing
    happened" from a model asked to be interesting, and paying for the attempt
    is how a dashboard grows a narrative every morning.
    """
    facts: list[Claim] = []
    previous = delta.comparison.refresh
    if previous is not None and previous.reporting_period == current.reporting_period:
        facts.append(Claim(
            text=(f"The reporting period is unchanged at "
                  f"{current.reporting_period}."), basis=FACT,
            metrics=[]))
    if not delta.source_changed:
        facts.append(Claim(
            text="No source dataset was republished since the previous "
                 "comparable refresh.", basis=FACT, metrics=[]))
    else:
        facts.append(Claim(
            text=("The source data was republished ("
                  + ", ".join(delta.source_changed)
                  + ") and no figure moved materially."), basis=FACT,
            metrics=[]))
    if not delta.definitions_changed:
        facts.append(Claim(text="No metric definition changed.", basis=FACT,
                           metrics=[]))
    return ChangeReading(
        headline=("No material changes were detected since the previous "
                  "comparable refresh."),
        no_material_change=True, verified=True, material_changes=facts)


def filter_changed_reading(delta: Delta) -> ChangeReading:
    """§40. The population changed, so headline figures are not comparable."""
    return ChangeReading(
        headline=("The filter context changed between these two refreshes, so "
                  "they measure different populations. Figures are not "
                  "compared."),
        no_material_change=False, verified=True,
        definition_caveat=(
            "This is a FILTER CONTEXT CHANGE, not a movement in the book. A "
            "Lens narrowed to part of the portfolio shows smaller figures "
            "because it is looking at less of it."),
        material_changes=[Claim(
            text="The previous refresh covered a different population, so no "
                 "comparison is drawn.", basis=FACT, metrics=[])])


# ---------------------------------------------------------------------------
# The model call
# ---------------------------------------------------------------------------


def _prompt(package: dict[str, Any]) -> str:
    import json

    return "\n".join([
        "THE REFRESH, AS COMPUTED. Every figure below is exactly as it "
        "appears on the Lens; copy them character for character and do not "
        "compute new ones.",
        "",
        json.dumps(package, default=str),
        "",
        "Write the change interpretation.",
    ])


def interpret(lens: dict[str, Any], current: Any, delta: Delta,
              package: dict[str, Any], *, budget: Any = None,
              model: str = "", effort: str = "") -> ChangeReading:
    """§26. What changed, interpreted, with every figure verified.

    The deterministic readings above are returned WITHOUT a model call where
    they are the honest answer. That is not a degradation path; it is the
    right answer for three of the states a refresh can be in.
    """
    from backend.llm import LLMError, get_provider

    if BASELINE in delta.classification or delta.comparison.refresh is None:
        return baseline_reading(delta)
    if "filter_changed" in delta.classification:
        return filter_changed_reading(delta)
    if not delta.anything_material:
        return quiet_reading(current, delta)

    provider = get_provider()
    if not provider.configured:
        return _deterministic_reading(delta, why=(
            "No AI provider is configured, so this reading is CreditProbe's "
            "own deterministic account of the movement rather than a written "
            "interpretation of it. The figures are unaffected."))

    if budget is not None:
        from backend.agentic.budgets import MODEL_CALLS

        if not budget.try_spend(MODEL_CALLS):
            return _deterministic_reading(delta, why=(
                "This request's model-call budget is spent, so the movement "
                "is reported without a written interpretation."))

    try:
        answer = provider.structured(
            system=SYSTEM, prompt=_prompt(package), schema=_schema(),
            tool_name=TOOL_NAME,
            tool_description="Interpret what changed on this Lens. Call this "
                             "exactly once.",
            max_tokens=1800, purpose="lens_change_interpretation",
            model=model, role="analyst", effort=effort)
    except LLMError as e:
        from backend.llm import telemetry

        logger.warning("change interpretation call failed: %s", e)
        return _deterministic_reading(delta, why=(
            "The live model could not be reached, so the movement is "
            "reported without a written interpretation. "
            + telemetry.sanitise(str(e))[:160]))
    except Exception as e:  # noqa: BLE001 - never break a Lens
        logger.warning("change interpretation call failed: %s", e)
        return _deterministic_reading(delta, why=(
            "The live model could not be reached, so the movement is "
            "reported without a written interpretation."))

    return checked(answer, package, delta)


def _deterministic_reading(delta: Delta, *, why: str) -> ChangeReading:
    """The movement, listed, when no model wrote about it.

    Not an error state and not an empty panel: the changes were computed
    deterministically and are worth showing on their own. What is missing is
    the reading, and the sentence says so.
    """
    claims = [
        Claim(text=(f"{c.title} moved from "
                    f"{refresh_package._figure(c.previous, c.unit, c.decimals)} "
                    f"to "
                    f"{refresh_package._figure(c.current, c.unit, c.decimals)}."
                    + (" Its definition also changed between the two "
                       "refreshes." if c.definition_changed else "")),
              basis=CHANGE, metrics=[c.title])
        for c in delta.material_changes[:8]
    ]
    headline = (f"{len(delta.material_changes)} figure(s) moved materially "
                "since the previous comparable refresh."
                if delta.material_changes else
                "No material changes were detected.")
    return ChangeReading(
        headline=headline, material_changes=claims,
        no_material_change=not delta.material_changes,
        unavailable=why, verified=True,
        definition_caveat=(
            "One or more metric definitions changed between these refreshes: "
            + ", ".join(delta.definitions_changed)
            if delta.definitions_changed else ""))


# ---------------------------------------------------------------------------
# §29: every numerical claim, checked
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


def checked(answer: Any, package: dict[str, Any], delta: Delta) -> ChangeReading:
    """Every figure the reading contains, matched against the refresh.

    Discarded rather than annotated on a mismatch, for the reason
    `lens_interpretation` gives and which applies twice as hard here: a wrong
    number in a paragraph about what changed is a number a committee will act
    on.
    """
    data = answer.data or {}
    supported = refresh_package.figures(package)
    problems: set[str] = set()

    def claims_of(key: str) -> list[Claim]:
        out: list[Claim] = []
        for raw in (data.get(key) or [])[:8]:
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            problems.update(m for m in _NUMBER.findall(text)
                            if m not in supported)
            basis = str(raw.get("basis") or INTERPRETATION).upper()
            if basis not in BASES:
                basis = INTERPRETATION
            out.append(Claim(
                text=text, basis=basis,
                metrics=[str(n).strip()
                         for n in (raw.get("metrics") or []) if str(n).strip()]))
        return out

    headline = str(data.get("headline", "")).strip()
    problems.update(m for m in _NUMBER.findall(headline) if m not in supported)
    caveat = str(data.get("definition_caveat", "")).strip()
    problems.update(m for m in _NUMBER.findall(caveat) if m not in supported)

    reading = ChangeReading(
        headline=headline,
        material_changes=claims_of("material_changes"),
        persistent_trends=claims_of("persistent_trends"),
        new_deterioration=claims_of("new_deterioration"),
        improvements=claims_of("improvements"),
        reversals=claims_of("reversals"),
        cross_metric_corroboration=claims_of("cross_metric_corroboration"),
        supported_drivers=claims_of("supported_drivers"),
        uncertainties=claims_of("uncertainties"),
        areas_requiring_attention=claims_of("areas_requiring_attention"),
        no_material_change=bool(data.get("no_material_change")),
        definition_caveat=caveat,
        model=answer.model, duration_ms=answer.duration_ms)

    if problems:
        logger.error("discarding a change interpretation: ungrounded figures %s",
                     sorted(problems))
        fallback = _deterministic_reading(delta, why=(
            "The written interpretation referenced "
            + ", ".join(sorted(problems)[:4])
            + ", which does not appear anywhere in this refresh, so it was "
              "withheld. The movement below is CreditProbe's own "
              "deterministic account and is unaffected."))
        fallback.ungrounded = sorted(problems)
        fallback.model = answer.model
        return fallback

    reading.downgraded = _enforce_causation(reading, package)
    reading.verified = True
    _keep_known_metrics(reading, package)
    return reading


def _enforce_causation(reading: ChangeReading,
                       package: dict[str, Any]) -> list[str]:
    """§28. A CONFIRMED_DRIVER claim needs a mechanism, not a coincidence.

    Downgraded rather than discarded: the observation is usually true and
    worth keeping — what is not supported is the word "caused", and the basis
    label is where that word lives.
    """
    names = {m.get("name", "").lower()
             for m in (package.get("metrics") or [])}
    names |= {c.get("name", "").lower() for c in (package.get("charts") or [])}
    mechanisms = {n for n in names
                  if any(word in n for word in MECHANISM_WORDS)}

    downgraded: list[str] = []
    for claims in reading.sections().values():
        for claim in claims:
            if claim.basis != CONFIRMED_DRIVER:
                continue
            evidence = {m.lower() for m in claim.metrics}
            if evidence & mechanisms:
                continue
            claim.downgraded_from = CONFIRMED_DRIVER
            claim.basis = CORRELATION
            downgraded.append(claim.text[:120])
    return downgraded


def _keep_known_metrics(reading: ChangeReading,
                        package: dict[str, Any]) -> None:
    """Drop metric references the refresh does not contain.

    A claim naming a metric that is not on this Lens is a claim whose evidence
    link would go nowhere. The sentence is kept — its figures were checked —
    and the dangling reference is not.
    """
    known = {m.get("name", "") for m in (package.get("metrics") or [])}
    known |= {c.get("name", "") for c in (package.get("charts") or [])}
    for claims in reading.sections().values():
        for claim in claims:
            claim.metrics = [m for m in claim.metrics if m in known]


__all__ = [
    "BASES", "BASIS_LABELS", "CHANGE", "CONFIRMED_DRIVER", "CORRELATION",
    "FACT", "INTELLIGENCE_VERSION", "INTERPRETATION", "POSSIBLE_DRIVER",
    "Claim", "ChangeReading", "baseline_reading", "checked",
    "filter_changed_reading", "interpret", "quiet_reading",
]
