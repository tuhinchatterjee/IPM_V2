"""One borrower, four layers, every component on the row. Sections 11C-11D.

The defect
----------
The borrower screen showed which signals fired and how bad the worst one was.
It did not show, for any single condition, what the value is NOW, what it was
LAST time, which way it moved, what the line is, whether it is over it, how
serious that is, whether it has been true before, or how CreditProbe came to
be looking at it. A credit officer reading that screen cannot tell a name that
has just crossed a line from one that has been over it for a year, and those
are different conversations.

What this builds
----------------
The same four layers the methodology publishes, each carrying every governed
component that was tested against this borrower — fired or not — with:

    Current | Previous | Movement | Threshold | Status | Severity |
    Persistence | Detection (TAC) | What it means

Not only the ones that fired. A layer showing three amber rows and hiding the
eleven green ones behind them is a layer that reads as an emergency, and the
reason to publish a threshold is so somebody can see a measure sitting
comfortably inside it.

Untested components are shown as untested, with the reason. "Nothing fires"
and "nothing could be tested" are different answers and only one of them is
reassuring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import assessment as ea
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx
from backend.product import methodology as me

SCORECARD_VERSION = "1.0.0"

#: What a component's Status column can say. Each is a fact about the
#: measure, not an adjective about the borrower.
OVER = "Over threshold"
WITHIN = "Within threshold"
UNTESTED = "Not tested"

STATUS_MEANS: dict[str, str] = {
    OVER: "The measure is beyond the governed line at this reporting date.",
    WITHIN: "The measure is inside the governed line at this reporting date.",
    UNTESTED: ("This deployment does not carry the field the condition reads, "
               "so nothing is known either way."),
}

#: The Persistence column. How many consecutive periods this has been true is
#: not something two periods can answer, so what is published is what two
#: periods DO support.
FIRST_PERIOD = "First period"
CARRIED_OVER = "Carried over"
NOT_APPLICABLE = "—"


@dataclass
class Component:
    """One governed condition on one borrower, as a row."""

    signal: str
    label: str
    family: str
    layer: str
    layer_name: str
    current: Any = None
    previous: Any = None
    movement: float | None = None
    threshold: Any = None
    #: The threshold as a phrase. The raw number alone is misleading on a
    #: ratio test, where a negative value encodes "at or below" rather than a
    #: negative quantity.
    threshold_reads: str = ""
    unit: str = tx.COUNT
    status: str = WITHIN
    severity: str = tx.WATCH
    persistence: str = NOT_APPLICABLE
    detection: str = tx.THRESHOLD_BASED
    detection_letter: str = "T"
    state: str = ea.HEALTHY
    means: str = ""
    unavailable: str = ""

    @property
    def available(self) -> bool:
        return not self.unavailable

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal, "label": self.label,
            "family": self.family,
            "family_label": tx.FAMILIES.get(self.family, self.family),
            "layer": self.layer, "layer_name": self.layer_name,
            "current": self.current, "previous": self.previous,
            "movement": self.movement, "threshold": self.threshold,
            "threshold_reads": self.threshold_reads,
            "unit": self.unit,
            "currency": tx.CURRENCY if self.unit == tx.MONEY else "",
            "status": self.status,
            "status_means": STATUS_MEANS.get(self.status, ""),
            "severity": self.severity,
            "persistence": self.persistence,
            "detection": self.detection,
            "detection_letter": self.detection_letter,
            "detection_means": tx.TAC_MEANS.get(self.detection, ""),
            "state": self.state,
            "state_means": ea.STATE_MEANS.get(self.state, ""),
            "means": self.means,
            "available": self.available, "unavailable": self.unavailable,
        }


@dataclass
class Layer:
    """One of the four layers, with its components underneath it."""

    key: str
    number: int
    name: str
    watches: str
    matters: str
    components: list[Component] = field(default_factory=list)
    gap: str = ""

    @property
    def over(self) -> int:
        return sum(1 for c in self.components if c.status == OVER)

    @property
    def tested(self) -> int:
        return sum(1 for c in self.components if c.available)

    @property
    def severity(self) -> str:
        """The worst severity among the components that are over the line."""
        firing = [c.severity for c in self.components if c.status == OVER]
        for level in (tx.SEVERE, tx.CONCERN, tx.WATCH):
            if level in firing:
                return level
        return ""

    def sentence(self) -> str:
        """What this layer is saying about this borrower, in one line."""
        if not self.tested:
            return ("Nothing in this layer could be tested for this "
                    "borrower.")
        if not self.over:
            return (f"All {self.tested} tested conditions are within "
                    "threshold.")
        return (f"{self.over} of {self.tested} tested conditions are beyond "
                "threshold.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.key, "number": self.number, "name": self.name,
            "watches": self.watches, "matters": self.matters,
            "gap": self.gap,
            "over": self.over, "tested": self.tested,
            "untested": len(self.components) - self.tested,
            "severity": self.severity, "sentence": self.sentence(),
            "components": [c.to_dict() for c in self.components],
        }


def _persistence(observation: sg.Observation) -> str:
    if not observation.available:
        return NOT_APPLICABLE
    if observation.lifecycle in (sg.PERSISTING, sg.WORSENING):
        return CARRIED_OVER
    if observation.lifecycle == sg.NEW and observation.fired:
        return FIRST_PERIOD
    return NOT_APPLICABLE


def _component(observation: sg.Observation) -> Component:
    signal = tx.BY_KEY.get(observation.signal)
    layer_key = me.layer_of(observation.family)
    named = next((entry.name for entry in me.layers()
                  if entry.key == layer_key), "Not mapped to a layer")
    status = (UNTESTED if not observation.available
              else OVER if observation.fired else WITHIN)
    detection = signal.tac if signal else tx.THRESHOLD_BASED
    return Component(
        signal=observation.signal, label=observation.label,
        family=observation.family, layer=layer_key, layer_name=named,
        current=observation.value, previous=observation.previous,
        movement=observation.movement, threshold=observation.threshold,
        threshold_reads=signal.threshold_reads if signal else "",
        unit=observation.unit, status=status,
        severity=observation.severity,
        persistence=_persistence(observation),
        detection=detection,
        detection_letter=tx.TAC_LETTER.get(detection, "T"),
        state=ea.state_of(observation),
        means=observation.means or (signal.means if signal else ""),
        unavailable=observation.unavailable)


#: The query parameter names the frontend's `borrower-link` module owns. Two
#: surfaces agreeing on a URL by coincidence is how a deep link quietly stops
#: working, so the names live in one place on each side and are asserted equal
#: by a test.
BORROWER_PARAM = "customer_id"
PERIOD_PARAM = "period"


def _period_for_url(period: str) -> str:
    """`Q2 2026` travels as `Q2-2026`: a URL with a space in it gets mangled."""
    return (period or "").strip().replace(" ", "-")


def _deep_link(standing: sg.Standing) -> dict[str, Any]:
    """Section 11J. Borrower 360, at the borrower AND the reporting date.

    A link that opens Borrower 360 at "latest" from a Q1 warning shows a
    different quarter's numbers beside the same sentence, and the reader has
    no way to know. The period is omitted rather than sent empty, because
    `?period=` asks for a quarter called nothing.
    """
    parts = [f"{BORROWER_PARAM}={standing.borrower_id}"]
    when = _period_for_url(standing.period)
    if when:
        parts.append(f"{PERIOD_PARAM}={when}")
    return {
        "customer_id": standing.borrower_id,
        "reporting_period": standing.period,
        "href": "/borrower-360?" + "&".join(parts),
        "label": "Open Borrower 360 at this reporting date",
    }


def build(standing: sg.Standing,
          observations: list[sg.Observation] | None = None) -> dict[str, Any]:
    """The borrower's four-layer scorecard. Sections 11C and 11D.

    `observations` is every governed signal tested against this borrower,
    fired or not. Where it is not supplied it is recomputed from the record,
    because a scorecard showing only what fired is the screen this replaces.
    """
    if observations is None:
        observations = list(standing.observations)
    if not observations:
        # A standing built before this field existed, or one reconstructed
        # from a stored dictionary. Re-evaluating loses the lifecycle, which
        # only exists because two periods were compared — so the components
        # will read as first-period rather than carried over. That is the
        # right direction to be wrong in, and it is visible rather than
        # silent, because Persistence then says so.
        observations = sg.evaluate(standing.record, None,
                                   period=standing.period)

    found = ea.assess(standing, standing.record)
    layers: dict[str, Layer] = {}
    for entry in me.layers():
        layers[entry.key] = Layer(
            key=entry.key, number=entry.number, name=entry.name,
            watches=entry.watches, matters=entry.matters, gap=entry.gap)

    for observation in observations:
        component = _component(observation)
        if component.layer in layers:
            layers[component.layer].components.append(component)

    ordered = sorted(layers.values(), key=lambda entry: entry.number)
    return {
        "version": SCORECARD_VERSION,
        "taxonomy_version": tx.TAXONOMY_VERSION,
        "owner": tx.THRESHOLD_OWNER,
        "borrower_id": standing.borrower_id,
        "period": standing.period,
        "currency": tx.CURRENCY,
        # Section 11G first: the level, and why, before any component table.
        # A reader who stops after the first screen should still have the
        # answer rather than the workings.
        "assessment": found.to_dict(),
        "risk_level": found.level,
        # Section 11J. The deep link carries the borrower AND the reporting
        # period, because a screen that opens Borrower 360 at "latest" from a
        # Q1 warning shows a different quarter's numbers beside the same
        # sentence, and the reader has no way to know.
        "borrower_360": _deep_link(standing),
        "columns": ["Current", "Previous", "Movement", "Threshold", "Status",
                    "Severity", "Persistence", "Detection", "What it means"],
        "layers": [entry.to_dict() for entry in ordered],
        "statement": (
            "Every governed condition tested against this borrower, over the "
            "line or inside it. A layer that showed only what fired would "
            "read as an emergency whatever the borrower was doing."),
    }


# --------------------------------------------------------------- section 11I


def timeline(borrower_id: str, snapshot: Any, periods: list[str],
             *, limit: int = 8) -> dict[str, Any]:
    """What this borrower has been doing, quarter by quarter. Section 11I.

    A borrower's Early Warning position at one date says whether something is
    wrong. It does not say whether the bank has been watching this happen for
    two years or whether it appeared last Tuesday, and those are the same
    screen for an officer deciding whether to escalate.

    Each period is a real evaluation against that period's own row and the row
    before it — never an interpolation, and never carried forward from the
    latest assessment. A timeline that repeats today's answer at every date is
    a chart of one fact.
    """
    from backend.early_warning import assessment as ea

    wanted = list(periods)[-limit:]
    entries: list[dict[str, Any]] = []
    for position, period in enumerate(wanted):
        index = periods.index(period)
        prior = periods[index - 1] if index > 0 else ""
        rows = snapshot[(snapshot["period"] == period)
                        & (snapshot["borrower_id"] == borrower_id)]
        if rows.empty:
            # Not on book at that date. Said, rather than drawn as a zero:
            # "no exposure" and "no warnings" are different facts.
            entries.append({
                "period": period, "on_book": False,
                "risk_level": "", "fired": 0, "families": 0,
                "primary_concern": "", "why_now": "",
                "sentence": f"Not on book at {period}.",
            })
            continue
        before = snapshot[(snapshot["period"] == prior)
                          & (snapshot["borrower_id"] == borrower_id)]
        standing = sg.stand(
            rows.iloc[0].to_dict(),
            before.iloc[0].to_dict() if not before.empty else {},
            borrower_id=borrower_id, period=period, previous_period=prior)
        found = ea.assess(standing, standing.record)
        entries.append({
            "period": period, "on_book": True,
            "risk_level": found.level,
            "risk_means": found.means,
            "fired": len(standing.fired),
            "families": len(found.families),
            "new": len(found.new), "resolved": len(found.resolved),
            "worsening": len(found.worsening),
            "primary_concern": found.primary_concern,
            "why_now": found.why_now,
            "priority": standing.priority,
            "sentence": standing.sentence(),
            "first": position == 0,
        })

    moved = [e for e in entries if e.get("on_book")]
    changed = [b for a, b in zip(moved, moved[1:], strict=False)
               if a["risk_level"] != b["risk_level"]]
    return {
        "version": SCORECARD_VERSION,
        "borrower_id": borrower_id,
        "periods": [e["period"] for e in entries],
        "entries": entries,
        "level_changes": len(changed),
        "statement": (
            "Every period is evaluated against its own reporting row and the "
            "one before it. Nothing here is carried forward from the latest "
            "assessment."),
    }


__all__ = ["BORROWER_PARAM", "CARRIED_OVER", "Component", "FIRST_PERIOD",
           "Layer", "PERIOD_PARAM",
           "NOT_APPLICABLE", "OVER", "SCORECARD_VERSION", "STATUS_MEANS",
           "UNTESTED", "WITHIN", "build", "timeline"]
