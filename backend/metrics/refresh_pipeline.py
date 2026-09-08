"""One pipeline, three doors. §19 and §23.

    REFRESH REQUEST
      → execute the Lens
      → store the snapshot
      → choose the previous COMPARABLE snapshot
      → compare, deterministically
      → build the package
      → interpret the change
      → verify every number in the interpretation
      → render

Opening a Lens, pressing Refresh and a scheduled run are the same journey
through this function with a different `trigger`. §19 asks for that
explicitly, and the reason is not tidiness: three execution paths would drift,
and the one that drifted would be the one nobody demonstrates.

Why the snapshot is stored BEFORE it is compared
--------------------------------------------------
`store` writes the current refresh, and only then does `comparable` look for
an earlier one. The reverse order has a window in it: two people opening the
same Lens at once would each find the same "previous" refresh and neither
would see the other's, which is a race that produces two histories that each
look complete. Storing first means the second one sees the first.

What happens when there is no database
---------------------------------------
The Lens renders. Everything else in this module reports that it cannot
remember anything and says so in a sentence a reader can act on. A Lens that
refused to open because it could not record history would be a worse product
than one that opens and says its memory is off.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.metrics import refresh as refresh_mod
from backend.metrics import (
    refresh_intelligence,
    refresh_package,
    refresh_store,
)

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "3.0.0"


@dataclass
class Outcome:
    """Everything one pass through the pipeline produced."""

    rendered: dict[str, Any] = field(default_factory=dict)
    refresh: refresh_mod.Refresh | None = None
    delta: refresh_mod.Delta | None = None
    package: dict[str, Any] = field(default_factory=dict)
    reading: refresh_intelligence.ChangeReading | None = None
    history: list[refresh_mod.Refresh] = field(default_factory=list)
    duration_ms: int = 0
    remembered: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "refresh": self.refresh.to_dict() if self.refresh else None,
            "delta": self.delta.to_dict() if self.delta else None,
            "changes": (self.reading.to_dict() if self.reading else None),
            "history": [_summary(r) for r in self.history],
            "duration_ms": self.duration_ms,
            "remembered": self.remembered,
            "note": self.note,
            "version": PIPELINE_VERSION,
        }


def _summary(refresh: refresh_mod.Refresh) -> dict[str, Any]:
    """One row of the history strip: what ran, when, and what kind it was."""
    return {
        "id": refresh.id,
        "refreshed_at": (refresh.refreshed_at.isoformat()
                         if refresh.refreshed_at else ""),
        "reporting_period": refresh.reporting_period,
        "trigger": refresh.trigger,
        "trigger_label": refresh_mod.TRIGGER_LABELS.get(refresh.trigger,
                                                        refresh.trigger),
        "classification": list(refresh.classification),
        "classification_labels": [
            refresh_mod.CLASSIFICATION_LABELS.get(c, c)
            for c in refresh.classification],
        "baseline": refresh.baseline,
        "status": refresh.status,
    }


def run(lens_id: int, *, period: str | None = None,
        trigger: str = refresh_mod.TRIGGER_OPENED, user_id: int | None = None,
        readable: Any = None, mode: str = "standard", budget: Any = None,
        interpret: bool = True, rendered: dict[str, Any] | None = None
        ) -> Outcome:
    """§23's whole flow, for one Lens.

    `rendered` lets a caller that has ALREADY executed the Lens — the render
    route, which has to return the panels anyway — hand the result in rather
    than running every panel twice. §44: one execution per meaningful open.
    """
    from backend.services import lenses as lens_service

    started = time.monotonic()
    outcome = Outcome()

    if rendered is None:
        rendered = lens_service.render(lens_id, period=period,
                                       user_id=user_id)
    outcome.rendered = rendered
    lens = dict(rendered.get("lens") or {})
    lens.setdefault("id", lens_id)

    duration = int((time.monotonic() - started) * 1000)
    current = refresh_mod.capture(lens, rendered, trigger=trigger,
                                  user_id=user_id, duration_ms=duration)
    outcome.refresh = current

    if not refresh_store.available():
        outcome.remembered = False
        outcome.note = (
            "This deployment has no database configured, so the Lens cannot "
            "record what it showed. The figures above are unaffected; change "
            "interpretation needs a stored history and is unavailable.")
        outcome.duration_ms = duration
        return outcome

    if budget is None:
        from backend.agentic.budgets import INTERACTIVE, PROACTIVE, Budget

        budget = Budget(limits=PROACTIVE if mode.lower() == "deep"
                        else INTERACTIVE)

    try:
        # Stored BEFORE the comparison — see the module docstring.
        current = refresh_store.record(current)
        outcome.refresh = current
        history = refresh_store.history(
            lens_id, limit=refresh_mod.HISTORY_LIMIT, user_id=user_id,
            readable=readable)
    except Exception as e:  # noqa: BLE001 - a Lens must open regardless
        logger.warning("could not record lens refresh: %s", e, exc_info=True)
        outcome.remembered = False
        outcome.note = (
            "CreditProbe could not record this refresh, so it cannot say what "
            "changed. The figures above are unaffected.")
        outcome.duration_ms = duration
        return outcome

    outcome.history = history
    earlier = [r for r in history if r.id != current.id]
    comparison = refresh_mod.comparable(current, earlier)
    delta = refresh_mod.compare(current, comparison)
    outcome.delta = delta

    current.classification = list(delta.classification)
    current.compared_with_id = (comparison.refresh.id
                                if comparison.refresh else None)

    permissions = {
        "user_id": user_id,
        "may_read": "the Cockpit and Early Warning domains only",
        "further_inspection": "the stored snapshots of this Lens",
    }
    outcome.package = refresh_package.build(
        lens, rendered, current, delta, earlier, mode=mode, budget=budget,
        permissions=permissions)

    reading = (refresh_intelligence.interpret(
        lens, current, delta, outcome.package, budget=budget)
        if interpret else None)
    outcome.reading = reading
    if reading is not None:
        current.interpretation = reading.to_dict()

    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    try:
        refresh_store.annotate(
            current.id, compared_with_id=current.compared_with_id,
            classification=current.classification,
            interpretation=current.interpretation,
            duration_ms=outcome.duration_ms,
            budget=budget.to_dict() if hasattr(budget, "to_dict") else {})
    except Exception:  # noqa: BLE001 - the refresh is stored either way
        logger.warning("could not annotate lens refresh %s", current.id,
                       exc_info=True)

    _log(lens_id, current, delta, reading, outcome.duration_ms, budget)
    return outcome


def _log(lens_id: int, current: refresh_mod.Refresh, delta: refresh_mod.Delta,
         reading: refresh_intelligence.ChangeReading | None,
         duration_ms: int, budget: Any) -> None:
    """§47's refresh record, as one structured line.

    Everything §47 asks to be logged, and nothing that would put a figure from
    the book into a log file: metric NAMES and counts, never values.
    """
    logger.info(
        "lens refresh: lens=%s refresh=%s trigger=%s previous=%s "
        "classification=%s source_changed=%s definitions_changed=%s "
        "material=%s rejected_claims=%s downgraded=%s latency_ms=%s budget=%s",
        lens_id, current.id, current.trigger, current.compared_with_id,
        ",".join(current.classification) or "-",
        ",".join(delta.source_changed) or "-",
        ",".join(delta.definitions_changed) or "-",
        len(delta.material_changes),
        len(reading.ungrounded) if reading else 0,
        len(reading.downgraded) if reading else 0,
        duration_ms,
        budget.usage_line() if hasattr(budget, "usage_line") else "-")


def changes(lens_id: int, *, period: str | None = None,
            user_id: int | None = None, readable: Any = None,
            mode: str = "standard") -> dict[str, Any]:
    """§31's panel: what changed, and everything the header needs to say it."""
    outcome = run(lens_id, period=period,
                  trigger=refresh_mod.TRIGGER_OPENED, user_id=user_id,
                  readable=readable, mode=mode)
    return present(outcome)


def present(outcome: Outcome) -> dict[str, Any]:
    """One payload for the whole live-Lens header and panel. §31."""
    refresh = outcome.refresh
    delta = outcome.delta
    comparison = delta.comparison if delta else None
    previous = comparison.refresh if comparison else None

    cockpit_changed, ews_changed = _domains_changed(delta)
    return {
        "remembered": outcome.remembered,
        "note": outcome.note,
        "reporting_period": refresh.reporting_period if refresh else "",
        "last_refreshed": (refresh.refreshed_at.isoformat()
                           if refresh and refresh.refreshed_at else ""),
        "refresh_id": refresh.id if refresh else None,
        "trigger": refresh.trigger if refresh else "",
        "compared_with": ({
            "id": previous.id,
            "refreshed_at": (previous.refreshed_at.isoformat()
                             if previous.refreshed_at else ""),
            "reporting_period": previous.reporting_period,
            "exact": comparison.exact if comparison else False,
            "relaxed": list(comparison.relaxed) if comparison else [],
        } if previous is not None else None),
        "why_no_comparison": (comparison.why_none if comparison else ""),
        # §31's "data changes detected", per domain, so a reader can see at a
        # glance whether this is a Cockpit story, an EWS story or both.
        "data_changes": {
            "cockpit": cockpit_changed,
            "ews": ews_changed,
            "datasets": list(delta.source_changed) if delta else [],
        },
        "classification": (delta.to_dict()["classification"] if delta else []),
        "classification_labels": (
            delta.to_dict()["classification_labels"] if delta else []),
        "classification_meaning": (
            delta.to_dict()["classification_meaning"] if delta else []),
        "changes": (outcome.reading.to_dict() if outcome.reading else None),
        "delta": delta.to_dict() if delta else None,
        "history": [_summary(r) for r in outcome.history],
        "duration_ms": outcome.duration_ms,
    }


def _domains_changed(delta: refresh_mod.Delta | None) -> tuple[bool, bool]:
    from backend.metrics import lens_domains as domains

    if delta is None:
        return False, False
    cockpit = any(domains.COCKPIT in c.domains for c in delta.material_changes)
    ews = any(domains.EWS in c.domains for c in delta.material_changes)
    return cockpit, ews


__all__ = ["PIPELINE_VERSION", "Outcome", "changes", "present", "run"]
