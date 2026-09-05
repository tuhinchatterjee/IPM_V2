"""What is worth putting in front of a committee, decided by rules.

No language model decides materiality here. A model asked "is a 40 basis point
move in the default rate material?" will answer confidently, differently on
Tuesday, and with no threshold anybody can challenge. A committee that cannot
challenge the threshold cannot challenge the finding, and a finding nobody can
challenge is not governance, it is decoration.

So: thresholds are declared, stored on the template, and every finding carries
the rule that fired and the numbers that fired it. A member who disagrees
argues with the threshold, which is the argument worth having.

What the AI does instead
------------------------
It writes the finding up. Given "retail default rate moved from 6.24% to 6.88%,
which is +0.64pp against a 0.50pp threshold", a model produces a better English
sentence than a template does. It is not asked whether 0.64 exceeds 0.50.

Fingerprints
------------
Every finding carries one, derived from the rule and what it is about but NOT
from the observed value. Regenerating a pack must not raise "Retail default
rate deteriorated" a second time as a new item merely because the figure moved
from 6.88% to 6.91% — the pack owner already answered that finding, and asking
them again teaches them to ignore the list.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from backend.models.playbook import SEVERITIES, SEVERITY_RANK
from backend.playbook import snapshots as snap

#: The comparisons a rule can make. Kept small: every one of these is
#: explainable in a sentence on the finding itself, which is the constraint
#: that matters.
COMPARISONS: tuple[str, ...] = (
    "absolute_change",      # moved by more than X, in the metric's own unit
    "relative_change",      # moved by more than X per cent of where it was
    "above",                # is above X
    "below",                # is below X
    "outside_band",         # is outside [low, high]
    "unavailable",          # has no value at all, when the pack expects one
    "stale",                # commentary written about figures that have moved
)

#: Which direction of movement a rule cares about.
DIRECTIONS: tuple[str, ...] = ("any", "worse", "better", "up", "down")

DEFAULT_SEVERITY = "MEDIUM"


@dataclass(frozen=True)
class Rule:
    """One declared threshold.

    `key` is what the finding records and what a member argues with. It is
    stable across pack generations, which is what makes a fingerprint stable.
    """

    key: str
    metric_id: str
    comparison: str
    #: The number the comparison is against. Unused by `unavailable`/`stale`.
    threshold: float | None = None
    #: For `outside_band`.
    low: float | None = None
    high: float | None = None
    direction: str = "any"
    severity: str = DEFAULT_SEVERITY
    finding_type: str = "DETERIORATION"
    title: str = ""
    #: The sentence a reader gets when this fires, with {} placeholders filled
    #: from the observation. Left empty, one is composed from the numbers.
    template: str = ""
    #: Where this rule came from — the template that declares it, the policy
    #: document behind it. Printed on the finding.
    basis: str = ""
    active: bool = True

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> Rule:
        """One rule out of a template's `materiality` list, validated.

        Refuses rather than defaults. A rule with an unrecognised comparison
        that silently became "above 0" would fire on everything, and the
        findings list is only useful while people still read it.
        """
        key = str(payload.get("key") or "").strip()
        if not key:
            raise ValueError("A materiality rule needs a key, so the finding "
                             "it raises can say which rule fired.")
        metric_id = str(payload.get("metric_id") or "").strip()
        comparison = str(payload.get("comparison") or "").strip().lower()
        if comparison not in COMPARISONS:
            raise ValueError(
                f"'{comparison}' is not a comparison this engine makes. One "
                f"of: {', '.join(COMPARISONS)}.")
        if comparison != "unavailable" and comparison != "stale" and not metric_id:
            raise ValueError(
                f"Rule '{key}' compares a metric and does not name one.")

        direction = str(payload.get("direction") or "any").strip().lower()
        if direction not in DIRECTIONS:
            raise ValueError(
                f"'{direction}' is not a direction. One of: "
                f"{', '.join(DIRECTIONS)}.")
        severity = str(payload.get("severity") or DEFAULT_SEVERITY).upper()
        if severity not in SEVERITIES:
            raise ValueError(
                f"'{severity}' is not a severity. One of: "
                f"{', '.join(SEVERITIES)}.")

        threshold = payload.get("threshold")
        if comparison in ("absolute_change", "relative_change", "above",
                          "below"):
            if threshold is None:
                raise ValueError(
                    f"Rule '{key}' is a {comparison} test and has no "
                    "threshold to compare against.")
            threshold = float(threshold)
        low = payload.get("low")
        high = payload.get("high")
        if comparison == "outside_band":
            if low is None or high is None:
                raise ValueError(
                    f"Rule '{key}' tests a band and does not give both ends "
                    "of it.")
            low, high = float(low), float(high)
            if low > high:
                raise ValueError(
                    f"Rule '{key}' has a band whose lower end ({low}) is "
                    f"above its upper end ({high}).")

        return Rule(
            key=key, metric_id=metric_id, comparison=comparison,
            threshold=threshold, low=low, high=high, direction=direction,
            severity=severity,
            finding_type=str(payload.get("finding_type")
                             or "DETERIORATION").upper(),
            title=str(payload.get("title") or ""),
            template=str(payload.get("template") or ""),
            basis=str(payload.get("basis") or ""),
            active=bool(payload.get("active", True)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "metric_id": self.metric_id,
            "comparison": self.comparison, "threshold": self.threshold,
            "low": self.low, "high": self.high, "direction": self.direction,
            "severity": self.severity, "finding_type": self.finding_type,
            "title": self.title, "template": self.template,
            "basis": self.basis, "active": self.active,
        }


@dataclass
class Observation:
    """One rule firing on one figure, with everything it fired on.

    This is the thing that becomes a `PlaybookFinding`. It carries the working
    so the finding can show it, which is the whole difference between "the
    default rate deteriorated" and an argument somebody can have.
    """

    rule_key: str
    metric_id: str
    finding_type: str
    severity: str
    title: str
    description: str
    factual_basis: str
    period: str = ""
    snapshot_id: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Stable across regenerations of the same pack.

        Built from the rule and what it is about, NOT from the observed value.
        A finding somebody has already answered must not come back as a new
        one because the number moved a basis point.
        """
        seed = f"{self.rule_key}|{self.metric_id}|{self.period}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_key": self.rule_key, "metric_id": self.metric_id,
            "finding_type": self.finding_type, "severity": self.severity,
            "title": self.title, "description": self.description,
            "factual_basis": self.factual_basis, "period": self.period,
            "snapshot_id": self.snapshot_id, "detail": dict(self.detail),
            "fingerprint": self.fingerprint,
        }


# ------------------------------------------------------------------ testing


def parse(payload: Any) -> list[Rule]:
    """A template's declared rules, with the bad ones named rather than dropped.

    Raises on the first invalid rule. A materiality set that silently loses
    a rule is worse than one that refuses to load: the pack still generates,
    the finding never fires, and nobody finds out until the quarter after.
    """
    rules: list[Rule] = []
    for index, entry in enumerate(list(payload or [])):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Materiality rule {index + 1} is not a rule definition.")
        rules.append(Rule.from_dict(entry))
    return rules


def evaluate(rules: list[Rule], figures: dict[str, snap.Figure],
             *, snapshot_ids: dict[str, int] | None = None
             ) -> list[Observation]:
    """Every rule that fires, over the figures this pack actually holds.

    Deterministic and side-effect free. Given the same figures it produces the
    same observations in the same order, which is what lets a test assert on
    it and a reviewer reproduce it.
    """
    snapshot_ids = dict(snapshot_ids or {})
    out: list[Observation] = []
    for rule in rules:
        if not rule.active:
            continue
        figure = figures.get(rule.metric_id)
        found = _fire(rule, figure)
        if found is None:
            continue
        found.snapshot_id = snapshot_ids.get(rule.metric_id)
        out.append(found)
    # Most serious first. A findings list ordered by rule declaration order
    # buries the critical one under four informational ones.
    return sorted(out, key=lambda o: (-SEVERITY_RANK.get(o.severity, 0),
                                      o.rule_key))


def _fire(rule: Rule, figure: snap.Figure | None) -> Observation | None:
    """Whether this rule fires on this figure, and what it observed."""
    if rule.comparison == "unavailable":
        return _unavailable(rule, figure)
    if figure is None:
        # The metric this rule watches is not in the pack. That is a gap in
        # the pack rather than a finding about the book, and it is the
        # readiness check's business, not this one's.
        return None
    if not figure.available:
        return None

    value = float(figure.value)  # available implies not None
    unit = figure.unit
    places = figure.decimals

    if rule.comparison == "above":
        if value <= rule.threshold:
            return None
        return _make(rule, figure,
                     observed=value, threshold=rule.threshold,
                     basis=f"{snap.display(value, unit, places)} is above the "
                           f"{snap.display(rule.threshold, unit, places)} "
                           "threshold.")

    if rule.comparison == "below":
        if value >= rule.threshold:
            return None
        return _make(rule, figure,
                     observed=value, threshold=rule.threshold,
                     basis=f"{snap.display(value, unit, places)} is below the "
                           f"{snap.display(rule.threshold, unit, places)} "
                           "threshold.")

    if rule.comparison == "outside_band":
        if rule.low <= value <= rule.high:
            return None
        side = "below" if value < rule.low else "above"
        edge = rule.low if value < rule.low else rule.high
        return _make(rule, figure,
                     observed=value, low=rule.low, high=rule.high,
                     basis=f"{snap.display(value, unit, places)} is {side} the "
                           f"{snap.display(rule.low, unit, places)}–"
                           f"{snap.display(rule.high, unit, places)} band, by "
                           f"{snap.display(abs(value - edge), unit, places)}.")

    if rule.comparison in ("absolute_change", "relative_change"):
        return _movement(rule, figure)

    return None


def _movement(rule: Rule, figure: snap.Figure) -> Observation | None:
    """A rule about how far a figure moved.

    Returns nothing when there is nothing to compare against. A movement rule
    that fires on a missing comparison is the most confidently wrong finding a
    pack can carry, because it reads exactly like a real one.
    """
    moved = snap.movement(figure)
    if not moved.get("available"):
        return None

    change = float(moved["change"])
    if rule.comparison == "relative_change":
        relative = moved.get("relative")
        if relative is None:
            # The previous value was zero, so "up 400 per cent" has no
            # meaning. Silent rather than wrong.
            return None
        magnitude = abs(float(relative)) * 100.0
        shown = f"{magnitude:,.1f}%"
        limit_shown = f"{rule.threshold:,.1f}%"
    else:
        magnitude = abs(change)
        shown = snap.display(magnitude, figure.unit, figure.decimals)
        limit_shown = snap.display(rule.threshold, figure.unit,
                                   figure.decimals)

    if magnitude <= rule.threshold:
        return None
    if not _direction_matches(rule.direction, moved):
        return None

    unit, places = figure.unit, figure.decimals
    return _make(
        rule, figure, observed=figure.value, threshold=rule.threshold,
        change=change, direction=moved["direction"], better=moved.get("better"),
        basis=(
            f"{figure.comparison_display} in "
            f"{figure.comparison_period or 'the previous period'} to "
            f"{snap.display(figure.value, unit, places)} in {figure.period}: "
            f"a move of {shown} against a {limit_shown} threshold."))


def _direction_matches(direction: str, moved: dict[str, Any]) -> bool:
    """Whether the movement went the way the rule cares about.

    "worse" and "better" need the metric to declare which way is good. A
    metric that does not say satisfies neither, rather than satisfying both —
    a rule that fires on an improvement because the direction was unknown
    puts a deterioration finding on a pack about good news.
    """
    if direction == "any":
        return True
    if direction in ("up", "down"):
        return moved.get("direction") == direction
    better = moved.get("better")
    if better is None:
        return False
    return better if direction == "better" else not better


def _unavailable(rule: Rule, figure: snap.Figure | None) -> Observation | None:
    """A rule that fires when a figure the pack expects is not there.

    Deliberately does NOT fire on NOT_MATURED. An outcome that has not
    happened yet is not a data quality problem, and raising it as one every
    month trains a committee to skip the data quality section.
    """
    if figure is None:
        return Observation(
            rule_key=rule.key, metric_id=rule.metric_id,
            finding_type=rule.finding_type or "DATA_QUALITY",
            severity=rule.severity,
            title=rule.title or f"{rule.metric_id} is missing from this pack",
            description=(
                f"This pack is expected to carry {rule.metric_id} and does "
                "not."),
            factual_basis="The metric has no calculated figure in this pack.",
            detail={"rule": rule.to_dict(), "availability": "ABSENT"})

    if figure.availability in (snap.OK, snap.NOT_MATURED):
        return None

    return Observation(
        rule_key=rule.key, metric_id=rule.metric_id,
        finding_type=rule.finding_type or "DATA_QUALITY",
        severity=rule.severity,
        title=rule.title or f"{figure.metric_name or rule.metric_id} has no "
                            "value for this period",
        description=figure.unavailable_reason,
        factual_basis=(
            f"{figure.metric_name or rule.metric_id} for "
            f"{figure.period or 'this period'}: {figure.availability}. "
            f"{figure.unavailable_reason}"),
        period=figure.period,
        detail={"rule": rule.to_dict(), "availability": figure.availability})


def _make(rule: Rule, figure: snap.Figure, *, basis: str,
          **detail: Any) -> Observation:
    """One observation, with the rule and its inputs recorded on it."""
    name = figure.metric_name or rule.metric_id
    title = rule.title or _title(rule, name, detail)
    described = rule.template.format(
        metric=name, value=figure.display_value,
        period=figure.period or "this period",
        threshold=rule.threshold) if rule.template else basis
    return Observation(
        rule_key=rule.key, metric_id=rule.metric_id,
        finding_type=rule.finding_type, severity=rule.severity,
        title=title, description=described, factual_basis=basis,
        period=figure.period,
        detail={"rule": rule.to_dict(), **detail,
                "basis": rule.basis, "unit": figure.unit,
                "display_value": figure.display_value})


def _title(rule: Rule, name: str, detail: dict[str, Any]) -> str:
    """A title, when the rule did not give one.

    Composed rather than generated: this is a heading in a governance record
    and it has to say the same thing every time the same rule fires.
    """
    if rule.comparison == "above":
        return f"{name} is above its threshold"
    if rule.comparison == "below":
        return f"{name} is below its threshold"
    if rule.comparison == "outside_band":
        return f"{name} is outside its tolerance band"
    direction = str(detail.get("direction") or "")
    better = detail.get("better")
    if better is False:
        return f"{name} has deteriorated"
    if better is True:
        return f"{name} has improved"
    if direction == "up":
        return f"{name} has risen materially"
    if direction == "down":
        return f"{name} has fallen materially"
    return f"{name} has moved materially"


__all__ = [
    "COMPARISONS", "DEFAULT_SEVERITY", "DIRECTIONS", "Observation", "Rule",
    "evaluate", "parse",
]
