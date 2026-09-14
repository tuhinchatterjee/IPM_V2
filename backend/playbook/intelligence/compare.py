"""Since Last Time: what a document relied on, and what is true now. §6D, §9.

THEN and NOW mean exact things
------------------------------
**THEN** is the frozen snapshot a version actually relied on — written when
that version was written and never touched again. Not "the value we have for
last quarter"; the value THIS PAPER USED. A snapshot that moves when today's
data moves cannot answer "what did the committee see", which is the only
question it exists for.

**NOW** is the latest GOVERNED binding for the same metric identity in the
same context. Governed means confirmed by a person or carried by an authority
— a suggestion is never a NOW, because a comparison built on a guess is worse
than no comparison.

What makes two readings comparable
----------------------------------
The same `metric_id`, and the same unit, currency, population, segment and
scenario. The period is expected to differ — that is the entire point — but
everything else that distinguishes one series from another must match. Two
figures that share a name and differ in population are two different series,
and subtracting one from the other produces a number that looks like insight
and is noise.

Where they do not match, this says **not comparable** and says which dimension
disagreed. A missing comparison is a fact a reader can act on; a misleading
delta is not.

How a change is expressed
-------------------------
A difference between two percentages is percentage POINTS, not per cent —
`calc` has kept that distinction since the beginning and it is honoured here.
A ratio or statistic changes absolutely. Currency changes in its currency, and
only when both sides are in the same one.

Better or worse
---------------
Only where the metric's direction is known. A rising bad rate is worse and a
rising Gini is better; for a metric whose polarity nobody has stated, this
reports the movement and declines to judge it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from backend.models.playbook import PlaybookMetricBinding, PlaybookMetricSnapshot
from backend.playbook import calc
from backend.playbook import repository as repo
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import service as svc

# --------------------------------------------------------------------------
# Direction
# --------------------------------------------------------------------------

UP_IS_BETTER = "up_is_better"
DOWN_IS_BETTER = "down_is_better"
NEUTRAL = "neutral"

#: Which way is good, per governed metric. Stated rather than guessed: a
#: metric nobody has classified reports its movement and no judgement.
POLARITY: dict[str, str] = {
    "retail.default_rate": DOWN_IS_BETTER,
    "retail.dpd30_rate": DOWN_IS_BETTER,
    "retail.dpd90_rate": DOWN_IS_BETTER,
    "application.cohort_bad_rate": DOWN_IS_BETTER,
    "scorecard.gini": UP_IS_BETTER,
    "scorecard.auc": UP_IS_BETTER,
    "scorecard.ks": UP_IS_BETTER,
    "scorecard.brier": DOWN_IS_BETTER,
    "ifrs9.coverage_ratio": NEUTRAL,
    "ifrs9.weighted_ecl": DOWN_IS_BETTER,
}

IMPROVED, WORSE, UNCHANGED, MOVED = "improved", "worse", "unchanged", "moved"

#: The dimensions that make two readings the same series. Period is absent on
#: purpose — comparing two periods is the point of the whole feature.
CONTEXT = ("unit", "currency", "population", "segment", "scenario")


@dataclass
class Comparison:
    """One metric, then and now, with everything a reader needs to check it."""

    metric_id: str
    label: str
    then_value: str = ""
    then_display: str = ""
    then_period: str = ""
    then_version: int = 0
    then_locator: str = ""
    now_value: str = ""
    now_display: str = ""
    now_period: str = ""
    now_locator: str = ""
    unit: str = ""
    currency: str = ""
    population: str = ""
    segment: str = ""
    scenario: str = ""
    change: str = ""
    change_unit: str = ""
    direction: str = ""
    comparable: bool = True
    reason: str = ""
    section_key: str = ""
    lineage: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "metric_id": self.metric_id, "label": self.label,
            "then": {"value": self.then_value, "display": self.then_display,
                     "period": self.then_period, "version": self.then_version,
                     "locator": self.then_locator},
            "now": {"value": self.now_value, "display": self.now_display,
                    "period": self.now_period, "locator": self.now_locator},
            "unit": self.unit, "currency": self.currency,
            "population": self.population, "segment": self.segment,
            "scenario": self.scenario,
            "change": self.change, "change_unit": self.change_unit,
            "direction": self.direction, "comparable": self.comparable,
            "reason": self.reason, "section_key": self.section_key,
            "lineage": dict(self.lineage),
        }


# --------------------------------------------------------------------------
# Freezing THEN
# --------------------------------------------------------------------------


def freeze(session, artifact_id: int, version_id: int, version: int,
           bindings: list[PlaybookMetricBinding]
           ) -> list[PlaybookMetricSnapshot]:
    """Write the values a version relied on, once, and never again.

    Only governed bindings are frozen. A suggestion is not something the
    document relied on — nobody confirmed that it was that metric — and
    freezing it would put a guess into the permanent record as though it were
    a reading.

    Idempotent per (version, metric, section): re-running over the same
    version returns the snapshots already written rather than a second set.
    Existing rows are NOT updated, which is the whole point of a snapshot.
    """
    existing = {
        (s.metric_id, s.section_key): s
        for s in session.query(PlaybookMetricSnapshot)
        .filter(PlaybookMetricSnapshot.version_id == version_id).all()
    }
    written = list(existing.values())
    for binding in bindings:
        if not bind.is_governed(binding):
            continue
        key = (binding.metric_id, binding.section_key)
        if key in existing:
            continue
        row = PlaybookMetricSnapshot(
            artifact_id=artifact_id, version_id=version_id, version=version,
            section_key=binding.section_key, metric_id=binding.metric_id,
            label=binding.label or binding.canonical_name or binding.metric_id,
            value=binding.raw_value or binding.value_in_document,
            display_value=binding.display_value or binding.value_in_document,
            unit=binding.unit, currency=binding.currency,
            population=binding.population, segment=binding.segment,
            scenario=binding.scenario, as_of=binding.as_of,
            reporting_period=binding.reporting_period,
            source_locator=binding.source_locator,
            source_export_revision_id=binding.source_export_revision_id)
        session.add(row)
        existing[key] = row
        written.append(row)
    session.flush()
    return written


def freeze_current(session, workspace_id: int) -> list[PlaybookMetricSnapshot]:
    """Freeze the current version of the workspace's document."""
    artifact = svc._current_artifact(session, workspace_id)
    if artifact is None:
        return []
    versions = repo.versions(session, artifact.id)
    if not versions:
        return []
    current = versions[-1]
    bindings = (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                .all())
    return freeze(session, artifact.id, current.id, current.version, bindings)


# --------------------------------------------------------------------------
# Comparing
# --------------------------------------------------------------------------


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(str(text).replace(",", "").rstrip("%").strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None


def _change_unit(unit: str) -> str:
    """How a difference in this unit is expressed.

    A difference between two percentages is percentage POINTS. `calc` has kept
    `PERCENT` and `PERCENTAGE_POINT` as different units from the start,
    precisely because calling a 0.61pp move "0.61%" is the unit slip that
    survives review and reaches a committee.
    """
    return {
        calc.PERCENT: "pp",
        "percent": "pp",
        calc.PERCENTAGE_POINT: "pp",
        calc.BASIS_POINT: "bps",
        calc.CURRENCY: "currency",
        calc.STATISTIC: "",
        "statistic": "",
        calc.RATIO: "",
        calc.COUNT: "",
    }.get(unit, "")


def _format_change(delta: Decimal, unit: str) -> str:
    change_unit = _change_unit(unit)
    dp = 2
    if unit in ("statistic", calc.STATISTIC):
        dp = 3
    elif unit == calc.RATIO:
        dp = 4
    elif unit in (calc.COUNT, calc.BASIS_POINT):
        dp = 0
    shown = calc.present(delta.copy_abs(), dp)
    sign = "-" if delta < 0 else "+"
    return f"{sign}{shown}{change_unit}" if change_unit not in ("currency",) \
        else f"{sign}{shown}"


def _mismatch(snapshot: PlaybookMetricSnapshot,
              binding: PlaybookMetricBinding) -> str:
    """Which context dimension disagrees, if any. Named, not just flagged."""
    for field_name in CONTEXT:
        then = (getattr(snapshot, field_name, "") or "").strip().lower()
        now = (getattr(binding, field_name, "") or "").strip().lower()
        if then and now and then != now:
            return (f"{field_name} differs: the document used {then!r} and "
                    f"the current value is {now!r}")
    return ""


def compare_one(snapshot: PlaybookMetricSnapshot,
                binding: PlaybookMetricBinding | None) -> Comparison:
    """One THEN against one NOW, or an honest refusal to compare them."""
    result = Comparison(
        metric_id=snapshot.metric_id, label=snapshot.label or snapshot.metric_id,
        then_value=snapshot.value, then_display=snapshot.display_value,
        then_period=snapshot.reporting_period, then_version=snapshot.version,
        then_locator=snapshot.source_locator, unit=snapshot.unit,
        currency=snapshot.currency, population=snapshot.population,
        segment=snapshot.segment, scenario=snapshot.scenario,
        section_key=snapshot.section_key)

    if binding is None:
        result.comparable = False
        result.reason = ("no current governed value for this metric — nothing "
                         "confirmed has replaced it")
        return result

    result.now_value = binding.raw_value or binding.value_in_document
    result.now_display = binding.display_value or binding.value_in_document
    result.now_period = binding.reporting_period
    result.now_locator = binding.source_locator
    result.currency = binding.currency or snapshot.currency
    result.population = binding.population or snapshot.population
    result.segment = binding.segment or snapshot.segment
    result.scenario = binding.scenario or snapshot.scenario
    result.lineage = {
        "then": {"version": snapshot.version, "locator": snapshot.source_locator,
                 "export_revision_id": snapshot.source_export_revision_id,
                 "as_of": snapshot.as_of, "period": snapshot.reporting_period},
        "now": {"locator": binding.source_locator,
                "export_revision_id": binding.source_export_revision_id,
                "source_module": binding.source_module,
                "binding_method": binding.binding_method,
                "as_of": binding.as_of, "period": binding.reporting_period},
    }

    mismatch = _mismatch(snapshot, binding)
    if mismatch:
        result.comparable = False
        result.reason = mismatch
        return result

    then, now = _decimal(snapshot.value), _decimal(result.now_value)
    if then is None or now is None:
        result.comparable = False
        result.reason = "one of the two values is not numeric"
        return result

    delta = now - then
    result.change = _format_change(delta, binding.unit or snapshot.unit)
    result.change_unit = _change_unit(binding.unit or snapshot.unit)

    polarity = POLARITY.get(snapshot.metric_id, NEUTRAL)
    if delta == 0:
        result.direction = UNCHANGED
    elif polarity == UP_IS_BETTER:
        result.direction = IMPROVED if delta > 0 else WORSE
    elif polarity == DOWN_IS_BETTER:
        result.direction = WORSE if delta > 0 else IMPROVED
    else:
        # Nobody has said which way is good for this metric. Reporting the
        # movement is honest; calling it an improvement would not be.
        result.direction = MOVED
    return result


def since_last_time(session, workspace_id: int, *,
                    version: int | None = None) -> dict:
    """§6D's table: every metric the document relied on, then and now."""
    artifact = svc._current_artifact(session, workspace_id)
    if artifact is None:
        return {"available": False, "rows": [], "reason": "no document yet"}

    snapshots = (session.query(PlaybookMetricSnapshot)
                 .filter(PlaybookMetricSnapshot.artifact_id == artifact.id)
                 .order_by(PlaybookMetricSnapshot.version).all())
    if not snapshots:
        return {"available": False, "rows": [],
                "reason": "no version has frozen its metrics yet"}

    # THEN is the most recent snapshot at or before the version asked for —
    # the reading the paper in front of the reader actually used.
    target = version if version is not None else max(s.version
                                                     for s in snapshots)
    chosen: dict[tuple[str, str], PlaybookMetricSnapshot] = {}
    for snapshot in snapshots:
        if snapshot.version <= target:
            chosen[(snapshot.metric_id, snapshot.section_key)] = snapshot

    # NOW is only ever a governed binding. A suggestion cannot be a NOW.
    current: dict[str, PlaybookMetricBinding] = {}
    for binding in (session.query(PlaybookMetricBinding)
                    .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                    .all()):
        if bind.is_governed(binding):
            current[binding.metric_id] = binding

    rows = [compare_one(snapshot, current.get(snapshot.metric_id)).as_dict()
            for snapshot in chosen.values()]
    rows.sort(key=lambda r: (not r["comparable"], r["label"]))
    return {
        "available": True,
        "then_version": target,
        "rows": rows,
        "compared": sum(1 for r in rows if r["comparable"]),
        "not_comparable": sum(1 for r in rows if not r["comparable"]),
        "worse": sum(1 for r in rows if r["direction"] == WORSE),
        "improved": sum(1 for r in rows if r["direction"] == IMPROVED),
    }
